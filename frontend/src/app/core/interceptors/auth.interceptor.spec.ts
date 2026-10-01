import { TestBed } from '@angular/core/testing';
import {
  HTTP_INTERCEPTORS,
  HttpClient,
  HttpErrorResponse,
  provideHttpClient,
  withInterceptorsFromDi
} from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { KeycloakBearerInterceptor, KeycloakService } from 'keycloak-angular';

import { AuthInterceptor } from './auth.interceptor';
import { AuthService } from '../services/auth.service';
import { appConfig } from '../../app.config';

/** Lets pending promise microtasks (updateToken) run before we assert. */
const flushAsync = (): Promise<void> => new Promise(resolve => setTimeout(resolve));

const unauthorized = { status: 401, statusText: 'Unauthorized' };

describe('AuthInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let keycloak: jasmine.SpyObj<KeycloakService>;
  let auth: jasmine.SpyObj<AuthService>;

  beforeEach(() => {
    keycloak = jasmine.createSpyObj<KeycloakService>('KeycloakService', ['updateToken']);
    keycloak.updateToken.and.resolveTo(true);
    auth = jasmine.createSpyObj<AuthService>('AuthService', ['logout']);

    TestBed.configureTestingModule({
      providers: [
        // Same shape as app.config.ts: without withInterceptorsFromDi()
        // Angular's provideHttpClient() silently ignores HTTP_INTERCEPTORS.
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
        { provide: HTTP_INTERCEPTORS, useClass: AuthInterceptor, multi: true },
        { provide: KeycloakService, useValue: keycloak },
        { provide: AuthService, useValue: auth }
      ]
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('recovers from a 401: updateToken(-1) once, then a single retry', async () => {
    let body: unknown;
    http.get('/api/v1/things').subscribe(v => {
      body = v;
    });

    httpMock.expectOne('/api/v1/things').flush(null, unauthorized);
    await flushAsync();

    expect(keycloak.updateToken).toHaveBeenCalledTimes(1);
    expect(keycloak.updateToken).toHaveBeenCalledWith(-1);
    expect(auth.logout).not.toHaveBeenCalled();

    httpMock.expectOne('/api/v1/things').flush({ ok: true });

    expect(body).toEqual({ ok: true });
    expect(auth.logout).not.toHaveBeenCalled();
  });

  it('401 -> refresh fails -> logout, no retry issued, original 401 propagates', async () => {
    keycloak.updateToken.and.rejectWith(new Error('refresh failed'));
    let caught: unknown;
    http.get('/api/v1/things').subscribe({
      error: e => {
        caught = e;
      }
    });

    httpMock.expectOne('/api/v1/things').flush(null, unauthorized);
    await flushAsync();

    expect(auth.logout).toHaveBeenCalledTimes(1);
    expect(caught).toBeInstanceOf(HttpErrorResponse);
    expect((caught as HttpErrorResponse).status).toBe(401);
    httpMock.expectNone('/api/v1/things');
  });

  it('retries exactly once — a second 401 tears the session down', async () => {
    keycloak.updateToken.and.resolveTo(true);
    let caught: unknown;
    http.get('/api/v1/things').subscribe({
      error: e => {
        caught = e;
      }
    });

    httpMock.expectOne('/api/v1/things').flush(null, unauthorized);
    await flushAsync();
    httpMock.expectOne('/api/v1/things').flush(null, unauthorized);

    expect(auth.logout).toHaveBeenCalledTimes(1);
    expect((caught as HttpErrorResponse).status).toBe(401);
    httpMock.expectNone('/api/v1/things');
  });

  it('leaves non-401 failures untouched (no refresh, no logout)', () => {
    let caught: unknown;
    http.get('/api/v1/things').subscribe({
      error: e => {
        caught = e;
      }
    });

    httpMock.expectOne('/api/v1/things').flush(null, { status: 500, statusText: 'Server Error' });

    expect((caught as HttpErrorResponse).status).toBe(500);
    expect(keycloak.updateToken).not.toHaveBeenCalled();
    expect(auth.logout).not.toHaveBeenCalled();
    httpMock.expectNone('/api/v1/things');
  });

  it('never logs tokens or headers during the recovery flow', async () => {
    const consoleSpies = (['log', 'info', 'warn', 'error', 'debug'] as const).map(method =>
      spyOn(console, method)
    );

    let body: unknown;
    http
      .get('/api/v1/things', { headers: { Authorization: 'Bearer super-secret-token' } })
      .subscribe(v => {
        body = v;
      });

    httpMock.expectOne('/api/v1/things').flush(null, unauthorized);
    await flushAsync();
    httpMock.expectOne('/api/v1/things').flush({ ok: true });

    expect(body).toEqual({ ok: true });
    for (const spy of consoleSpies) {
      expect(spy).not.toHaveBeenCalled();
    }
  });

  it('is registered outside KeycloakBearerInterceptor (retry must re-attach the token)', () => {
    const classes = (appConfig.providers as unknown[])
      .map(p => p as Record<string, unknown>)
      .filter(p => p['provide'] === HTTP_INTERCEPTORS && p['multi'] === true)
      .map(p => p['useClass']);

    expect(classes).toContain(AuthInterceptor);
    expect(classes).toContain(KeycloakBearerInterceptor);
    // First-registered class interceptor = outermost in Angular's reduceRight
    // chain; swapping this order would retry without a refreshed token.
    expect(classes.indexOf(AuthInterceptor)).toBeLessThan(
      classes.indexOf(KeycloakBearerInterceptor)
    );
  });
});
