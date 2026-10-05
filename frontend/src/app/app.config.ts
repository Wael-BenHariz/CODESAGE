import { ApplicationConfig, APP_INITIALIZER, provideZoneChangeDetection } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import {
  HttpClient,
  HTTP_INTERCEPTORS,
  provideHttpClient,
  withInterceptorsFromDi
} from '@angular/common/http';
import { provideAnimations } from '@angular/platform-browser/animations';
import { KeycloakBearerInterceptor, KeycloakService } from 'keycloak-angular';
import { firstValueFrom } from 'rxjs';

import { routes } from './app.routes';
import { environment } from '@env/environment';
import { AuthInterceptor } from './core/interceptors/auth.interceptor';
import { ErrorInterceptor } from './core/interceptors/error.interceptor';

/** Shape returned by GET /api/v1/auth/keycloak/config. */
export interface KeycloakAppConfig {
  url: string;
  realm: string;
  clientId: string;
}

/**
 * Application-wide KeycloakService instance. Provided as a value (see below)
 * so the APP_INITIALIZER, the bearer interceptor and the route guard all
 * share the exact same object.
 */
export const keycloakService = new KeycloakService();

/**
 * Factory for APP_INITIALIZER: fetch the Keycloak connection config from the
 * backend, then initialize keycloak-js (check-sso + PKCE S256). The router
 * only starts after this resolves, so guards and the HTTP interceptor always
 * see a ready Keycloak instance.
 *
 * Note: the config GET itself runs before init — the bearer interceptor
 * short-circuits while `enableBearerInterceptor` is still undefined, and the
 * endpoint is excluded anyway.
 */
export function initializeKeycloak(http: HttpClient): () => Promise<boolean> {
  return async () => {
    const config = await firstValueFrom(
      http.get<KeycloakAppConfig>(`${environment.apiUrl}/auth/keycloak/config`)
    );
    return keycloakService.init({
      config,
      initOptions: {
        onLoad: 'check-sso',
        pkceMethod: 'S256',
        silentCheckSsoRedirectUri: `${window.location.origin}/assets/silent-check-sso.html`
      },
      bearerExcludedUrls: ['/auth/keycloak/config']
    });
  };
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(withInterceptorsFromDi()),
    { provide: KeycloakService, useValue: keycloakService },
    {
      provide: APP_INITIALIZER,
      useFactory: initializeKeycloak,
      multi: true,
      deps: [HttpClient]
    },
    // 401 recovery: forced token refresh (updateToken(-1)) + one retry, then
    // logout if recovery fails. MUST be provided BEFORE
    // KeycloakBearerInterceptor — first-registered = outermost in Angular's
    // reduceRight chain, so the retry re-enters the bearer interceptor below
    // and gets the refreshed token re-attached (see auth.interceptor.ts).
    {
      provide: HTTP_INTERCEPTORS,
      useClass: AuthInterceptor,
      multi: true
    },
    // Attaches the Keycloak bearer token to outgoing API calls (replaces the
    // retired custom auth interceptor; refresh is handled by keycloak-js).
    {
      provide: HTTP_INTERCEPTORS,
      useClass: KeycloakBearerInterceptor,
      multi: true
    },
    // Global 403/404 handling — MUST be provided LAST: Angular's reduceRight
    // chain makes the last-registered interceptor the INNERMOST one, so it
    // sees the raw error first and rethrows it outward (401 still reaches
    // AuthInterceptor, component error handlers still run). See
    // error.interceptor.ts.
    {
      provide: HTTP_INTERCEPTORS,
      useClass: ErrorInterceptor,
      multi: true
    },
    provideAnimations()
  ]
};
