import { Injectable, inject } from '@angular/core';
import {
  HttpErrorResponse,
  HttpEvent,
  HttpHandler,
  HttpInterceptor,
  HttpRequest
} from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { Router } from '@angular/router';

import { ToastService } from '../services/toast.service';

/**
 * Uniform non-401 error handling (plan Step 1, rule 5):
 *
 * - 401 → NOT handled here: AuthInterceptor (outer layer) owns refresh →
 *   retry → re-login. This interceptor only passes 401s through.
 * - 403 → visible "forbidden" message (toast). The page keeps its own
 *   state — a failed mutation stays on screen with its inline error.
 * - 404 → navigate to the generic /not-found page, except for routes whose
 *   error copy must render in place (the invitation token pages — invalid,
 *   expired and used tokens must all read the same message on that page).
 *
 * Registration order: provided LAST, so it is the innermost layer — it sees
 * the raw error first and rethrows it, letting outer layers (bearer, 401
 * recovery) and component error handlers keep working.
 *
 * The message text is static — server `detail` payloads are untrusted and
 * are never interpolated into global UI from here.
 */
@Injectable()
export class ErrorInterceptor implements HttpInterceptor {
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  /**
   * Prefixes whose 404s are handled by their own screens (they must render
   * contextual copy instead of redirecting away):
   * - `/invitations/…` — public preview + accept page (invalid/expired/used
   *   tokens all answer 404 and share one in-place message).
   * - `/auth/…` — session bootstrap (a redirect during APP_INITIALIZER
   *   would cancel app startup).
   * - `…/scan-report` — a review with no static scan yet legitimately 404s
   *   ("no scan report"); the review panel treats it as an absent report and
   *   renders its comments without enrichment (plan Step 3). Access to the
   *   review itself is still guarded by `GET /reviews/{id}`.
   */
  private static readonly ALLOW_404 = ['/invitations/', '/auth/', '/scan-report'];

  intercept(req: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    return next.handle(req).pipe(
      catchError((err: unknown) => {
        if (err instanceof HttpErrorResponse) {
          if (err.status === 403) {
            this.toast.error('Forbidden — you do not have permission to perform this action.');
          } else if (
            err.status === 404 &&
            !ErrorInterceptor.ALLOW_404.some(prefix => req.urlWithParams.includes(prefix))
          ) {
            void this.router.navigate(['/not-found']);
          }
          // 401 falls through untouched for AuthInterceptor (outer layer).
        }
        return throwError(() => err);
      })
    );
  }
}
