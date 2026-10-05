import { TestBed } from '@angular/core/testing';
import { HTTP_INTERCEPTORS, HttpClient, HttpErrorResponse } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { Router } from '@angular/router';

import { ErrorInterceptor } from './error.interceptor';
import { ToastService } from '../services/toast.service';

/**
 * ErrorInterceptor contract (plan Step 1, rule 5):
 * - 401 passes through untouched (AuthInterceptor owns refresh → re-login),
 * - 403 toasts a forbidden message,
 * - 404 navigates to /not-found, except on the invitation/auth prefixes,
 * - every error is rethrown so outer layers and component handlers still run.
 */
describe('ErrorInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let toast: ToastService;
  let router: jasmine.SpyObj<Router>;

  beforeEach(() => {
    router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    router.navigate.and.returnValue(Promise.resolve(true));

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
        { provide: Router, useValue: router },
        { provide: HTTP_INTERCEPTORS, useClass: ErrorInterceptor, multi: true }
      ]
    });

    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    toast = TestBed.inject(ToastService);
  });

  afterEach(() => {
    httpMock.verify();
  });

  function flushError(status: number, url = '/api/v1/things'): HttpErrorResponse {
    let captured: unknown = null;
    http.get(url).subscribe({ error: (err: unknown) => (captured = err) });
    httpMock.expectOne(url).flush({ message: 'x' }, { status, statusText: 'err' });
    return captured as HttpErrorResponse;
  }

  it('lets a 401 pass through untouched — no toast, no navigation', () => {
    const err = flushError(401);

    expect(err instanceof HttpErrorResponse).toBeTrue();
    expect(err.status).toBe(401);
    expect(toast.toasts().length).toBe(0);
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('shows the forbidden toast on 403 and rethrows the error', () => {
    const err = flushError(403);

    expect(err.status).toBe(403);
    expect(toast.toasts().length).toBe(1);
    expect(toast.toasts()[0].kind).toBe('error');
    expect(toast.toasts()[0].message).toContain('Forbidden');
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('navigates to /not-found on 404 and rethrows the error', () => {
    const err = flushError(404);

    expect(err.status).toBe(404);
    expect(router.navigate).toHaveBeenCalledWith(['/not-found']);
    expect(toast.toasts().length).toBe(0);
  });

  it('keeps invitation-token 404s in place (contextual copy on that page)', () => {
    flushError(404, '/api/v1/invitations/preview?token=secret-token-value');

    // The invite page renders its own invalid/expired/used message — no redirect.
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('keeps auth-bootstrap 404s in place (a redirect would cancel startup)', () => {
    flushError(404, '/api/v1/auth/keycloak/config');

    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('keeps scan-report 404s in place (a review with no scan yet is absence)', () => {
    const err = flushError(404, '/api/v1/reviews/rev-1/scan-report');

    // "No scan report yet" is an expected 404 — the panel renders the review
    // without enrichment; the review detail request guards access instead.
    expect(err.status).toBe(404);
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('passes 2xx responses through untouched', () => {
    let body: unknown = null;
    http.get('/api/v1/ok').subscribe(res => (body = res));
    httpMock.expectOne('/api/v1/ok').flush({ value: 1 });

    expect(body).toEqual({ value: 1 });
    expect(toast.toasts().length).toBe(0);
    expect(router.navigate).not.toHaveBeenCalled();
  });
});
