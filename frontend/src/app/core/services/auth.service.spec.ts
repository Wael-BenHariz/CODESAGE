import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { KeycloakService } from 'keycloak-angular';

import { AuthService } from './auth.service';
import { User } from '../models/user.model';
import { environment } from '@env/environment';

const fakeUser: User = {
  id: 'u-1',
  login: 'octocat',
  email: 'octo@example.com',
  name: 'Octo Cat',
  avatarUrl: 'https://example.com/avatar.png',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  role: 'DEVELOPER'
};

/**
 * The same profile in its REAL wire shape (`UserResponse`, snake_case —
 * what `GET /auth/me` actually returns). HTTP responses flush this DTO;
 * `toUser` maps it onto the camelCase `fakeUser` above.
 */
const fakeUserDto = {
  id: 'u-1',
  login: 'octocat',
  email: 'octo@example.com',
  name: 'Octo Cat',
  avatar_url: 'https://example.com/avatar.png',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  role: 'DEVELOPER'
};

function clearAuthStorage(): void {
  localStorage.removeItem(environment.userKey);
  sessionStorage.clear();
}

describe('AuthService (Keycloak-backed)', () => {
  let httpMock: HttpTestingController;
  let keycloak: jasmine.SpyObj<KeycloakService>;
  let navigateSpy: jasmine.Spy;

  beforeEach(() => {
    clearAuthStorage();
    keycloak = jasmine.createSpyObj<KeycloakService>('KeycloakService', [
      'isLoggedIn',
      'login',
      'logout'
    ]);
    keycloak.isLoggedIn.and.returnValue(false);
    keycloak.login.and.resolveTo(undefined);
    keycloak.logout.and.resolveTo(undefined);

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: KeycloakService, useValue: keycloak }
      ]
    });
    httpMock = TestBed.inject(HttpTestingController);
    const router = TestBed.inject(Router);
    navigateSpy = spyOn(router, 'navigate').and.returnValue(Promise.resolve(true));
  });

  afterEach(() => {
    httpMock.verify();
    clearAuthStorage();
  });

  describe('construction', () => {
    it('stays idle (no HTTP) when there is neither a session nor a cached profile', () => {
      const auth = TestBed.inject(AuthService);

      expect(auth.isAuthenticated()).toBeFalse();
      expect(auth.currentUser()).toBeNull();
      httpMock.expectNone(req => req.url === `${environment.apiUrl}/auth/me`);
    });

    it('drops a stale cached profile when no Keycloak session exists', () => {
      localStorage.setItem(environment.userKey, JSON.stringify(fakeUser));

      const auth = TestBed.inject(AuthService);

      expect(auth.currentUser()).toBeNull();
      expect(localStorage.getItem(environment.userKey)).toBeNull();
      httpMock.expectNone(req => req.url === `${environment.apiUrl}/auth/me`);
    });

    it('shows the cached profile instantly, then refreshes it from /auth/me when logged in', () => {
      localStorage.setItem(environment.userKey, JSON.stringify(fakeUser));
      keycloak.isLoggedIn.and.returnValue(true);

      const auth = TestBed.inject(AuthService);

      // Synchronous: first render has a user without waiting for the network.
      expect(auth.currentUser()?.login).toBe('octocat');

      // The background refresh carries the role derived from the current JWT.
      const fresh = { ...fakeUserDto, role: 'REVIEWER' };
      const req = httpMock.expectOne(`${environment.apiUrl}/auth/me`);
      req.flush(fresh);
      expect(auth.currentUser()?.role).toBe('REVIEWER');
      expect(JSON.parse(localStorage.getItem(environment.userKey) ?? '{}').role).toBe('REVIEWER');
    });
  });

  describe('login()', () => {
    it('starts the GitHub social login with idpHint github and a dashboard redirect', () => {
      const auth = TestBed.inject(AuthService);
      auth.login();

      expect(keycloak.login).toHaveBeenCalledTimes(1);
      const options = keycloak.login.calls.mostRecent().args[0];
      expect(options?.idpHint).toBe('github');
      expect(options?.redirectUri).toBe(`${window.location.origin}/dashboard`);
    });

    it('honors a guard-captured returnUrl', () => {
      const auth = TestBed.inject(AuthService);
      auth.login('/settings');

      const options = keycloak.login.calls.mostRecent().args[0];
      expect(options?.redirectUri).toBe(`${window.location.origin}/settings`);
    });

    it('rejects non-relative and protocol-relative returnUrls (open-redirect guard)', () => {
      const auth = TestBed.inject(AuthService);
      auth.login('//evil.example/phish');
      expect(keycloak.login.calls.mostRecent().args[0]?.redirectUri).toBe(
        `${window.location.origin}/dashboard`
      );

      auth.login('https://evil.example/phish');
      expect(keycloak.login.calls.mostRecent().args[0]?.redirectUri).toBe(
        `${window.location.origin}/dashboard`
      );
    });

    it('surfaces an error signal when Keycloak cannot start the login', async () => {
      keycloak.login.and.rejectWith(new Error('popup blocked'));
      const auth = TestBed.inject(AuthService);

      auth.login();
      await Promise.resolve(); // let the rejection reach the .catch handler

      expect(auth.error()).toBe('Failed to start GitHub login. Please try again.');
    });
  });

  describe('logout()', () => {
    it('POSTs /auth/logout, ends the Keycloak session and clears local state — idempotently', () => {
      localStorage.setItem(environment.userKey, JSON.stringify(fakeUser));
      keycloak.isLoggedIn.and.returnValue(true);
      const auth = TestBed.inject(AuthService);
      httpMock.expectOne(`${environment.apiUrl}/auth/me`).flush(fakeUserDto); // constructor refresh

      auth.logout();

      const req = httpMock.expectOne(`${environment.apiUrl}/auth/logout`);
      expect(req.request.method).toBe('POST');
      req.flush({ status: 'ok' });

      expect(keycloak.logout).toHaveBeenCalledTimes(1);
      expect(keycloak.logout.calls.mostRecent().args[0]).toBe(`${window.location.origin}/`);
      expect(auth.currentUser()).toBeNull();
      expect(localStorage.getItem(environment.userKey)).toBeNull();

      // Second call is a no-op: no duplicate POST, no duplicate redirect.
      auth.logout();
      httpMock.expectNone(r => r.url === `${environment.apiUrl}/auth/logout`);
      expect(keycloak.logout).toHaveBeenCalledTimes(1);
    });

    it('clears local state and navigates to /login even when the server call errors', () => {
      keycloak.isLoggedIn.and.returnValue(true);
      const auth = TestBed.inject(AuthService);
      httpMock.expectOne(`${environment.apiUrl}/auth/me`).flush(fakeUserDto); // constructor refresh

      auth.logout();

      const req = httpMock.expectOne(`${environment.apiUrl}/auth/logout`);
      req.error(new ProgressEvent('network failure'), { status: 0, statusText: 'offline' });

      expect(auth.currentUser()).toBeNull();
      expect(keycloak.logout).toHaveBeenCalledTimes(1);
    });

    it('without a session: no POST, plain navigation to /login', () => {
      const auth = TestBed.inject(AuthService);

      auth.logout();

      httpMock.expectNone(r => r.url === `${environment.apiUrl}/auth/logout`);
      expect(keycloak.logout).not.toHaveBeenCalled();
      expect(navigateSpy).toHaveBeenCalledWith(['/login']);
    });
  });

  describe('switchAccount()', () => {
    it('ends the SSO session and lands on the login page — idempotently', () => {
      localStorage.setItem(environment.userKey, JSON.stringify(fakeUser));
      keycloak.isLoggedIn.and.returnValue(true);
      const auth = TestBed.inject(AuthService);
      httpMock.expectOne(`${environment.apiUrl}/auth/me`).flush(fakeUserDto); // constructor refresh

      auth.switchAccount();

      expect(keycloak.logout).toHaveBeenCalledTimes(1);
      expect(keycloak.logout.calls.mostRecent().args[0]).toBe(`${window.location.origin}/login`);
      expect(auth.currentUser()).toBeNull();

      auth.switchAccount();
      expect(keycloak.logout).toHaveBeenCalledTimes(1);
    });

    it('honors a custom returnUrl — the invite page comes back signed out', () => {
      localStorage.setItem(environment.userKey, JSON.stringify(fakeUser));
      keycloak.isLoggedIn.and.returnValue(true);
      const auth = TestBed.inject(AuthService);
      httpMock.expectOne(`${environment.apiUrl}/auth/me`).flush(fakeUserDto);

      auth.switchAccount('/invite/accept?token=abc');

      expect(keycloak.logout.calls.mostRecent().args[0]).toBe(
        `${window.location.origin}/invite/accept?token=abc`
      );
    });
  });

  describe('loadUser()', () => {
    it('stores the profile (incl. role) in the signal and the cache', () => {
      const auth = TestBed.inject(AuthService);
      let loaded: User | undefined;
      auth.loadUser().subscribe(u => (loaded = u));

      httpMock.expectOne(`${environment.apiUrl}/auth/me`).flush(fakeUserDto);

      expect(loaded?.login).toBe('octocat');
      expect(auth.currentUser()?.role).toBe('DEVELOPER');
      // Regression: GET /auth/me returns snake_case `avatar_url` — the
      // mapper must surface it as camelCase `avatarUrl`.
      expect(auth.currentUser()?.avatarUrl).toBe('https://example.com/avatar.png');
      expect(localStorage.getItem(environment.userKey)).not.toBeNull();
    });

    it('propagates errors and records the backend message', () => {
      const auth = TestBed.inject(AuthService);
      let caught: unknown;
      auth.loadUser().subscribe({ error: e => (caught = e) });

      httpMock
        .expectOne(`${environment.apiUrl}/auth/me`)
        .flush({ detail: 'nope' }, { status: 401, statusText: 'Unauthorized' });

      expect(caught).toBeTruthy();
      expect(auth.error()).toBe('nope');
      expect(auth.isLoading()).toBeFalse();
    });
  });
});
