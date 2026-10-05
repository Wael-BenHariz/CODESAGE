import { EnvironmentInjector, Injectable, inject } from '@angular/core';
import {
  HttpErrorResponse,
  HttpEvent,
  HttpHandler,
  HttpInterceptor,
  HttpRequest
} from '@angular/common/http';
import { Observable, from, throwError } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { KeycloakService } from 'keycloak-angular';

import { AuthService } from '../services/auth.service';

/**
 * 401 recovery layered ON TOP of KeycloakBearerInterceptor.
 *
 * Registration order in app.config.ts is load-bearing: this interceptor is
 * provided FIRST, and Angular builds the class-interceptor chain with
 * reduceRight, so the first-registered interceptor is the OUTERMOST layer.
 * On a 401 the retry below therefore re-enters the downstream chain, where
 * KeycloakBearerInterceptor re-attaches the Authorization header with the
 * token that updateToken(-1) just refreshed.
 *
 * Recovery is strictly once per request:
 *   401 -> keycloak.updateToken(-1) (forced refresh) -> retry the request once
 *   refresh rejected            -> AuthService.logout(), original 401 propagates
 *   retry answers 401 as well   -> AuthService.logout(), retry error propagates
 *   retry fails non-401 (5xx)   -> propagate untouched; the session itself is
 *                                  fine after a successful refresh, so no logout
 *
 * This interceptor never logs (tokens and headers stay out of the console),
 * and it stores nothing: tokens remain inside keycloak-js, and the only
 * browser-persisted state is the cached profile AuthService already keeps.
 */
@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  private readonly keycloak = inject(KeycloakService);
  private readonly injector = inject(EnvironmentInjector);

  intercept(req: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    return next.handle(req).pipe(
      catchError((error: unknown) => {
        if (!(error instanceof HttpErrorResponse) || error.status !== 401) {
          return throwError(() => error);
        }

        return from(this.keycloak.updateToken(-1)).pipe(
          catchError(() => {
            // Forced refresh failed — recovery is impossible, tear the
            // session down. The refresh error itself is dropped on purpose
            // (never surface or log token-endpoint internals).
            this.logout();
            return throwError(() => error);
          }),
          switchMap(() =>
            next.handle(req).pipe(
              catchError((retryError: unknown) => {
                if (retryError instanceof HttpErrorResponse && retryError.status === 401) {
                  this.logout();
                }
                return throwError(() => retryError);
              })
            )
          )
        );
      })
    );
  }

  /**
   * AuthService is resolved lazily on purpose: the interceptor chain is
   * built during the very first HTTP call — the APP_INITIALIZER config GET —
   * while AuthService must not be constructed before keycloak-js init has
   * completed (its constructor reads isLoggedIn() to validate the cached
   * profile and would drop it). Teardown is best-effort and must never
   * replace the original 401, hence the swallow.
   */
  private logout(): void {
    try {
      this.injector.get(AuthService).logout();
    } catch {
      // Ignore — the request error still propagates to the caller.
    }
  }
}
