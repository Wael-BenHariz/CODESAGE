import { TestBed } from '@angular/core/testing';
import { KeycloakService } from 'keycloak-angular';
import { of, throwError } from 'rxjs';

import { AdminLoginError, AdminLoginService } from './admin-login.service';
import { ApiService } from './api.service';
import { AuthContextService } from './auth-context.service';
import { AuthService } from './auth.service';
import { User } from '../models/user.model';

describe('AdminLoginService — platform-admin credential sign-in', () => {
  let service: AdminLoginService;
  let api: jasmine.SpyObj<ApiService>;
  let keycloak: jasmine.SpyObj<KeycloakService>;
  let auth: jasmine.SpyObj<AuthService>;
  let context: jasmine.SpyObj<AuthContextService>;

  const config = {
    url: 'http://keycloak.test/auth',
    realm: 'codesage-realm',
    clientId: 'codesage-angular'
  };

  /** Mint an unsigned JWT carrying the given realm roles. */
  function tokenWithRoles(roles: string[]): string {
    const encode = (payload: unknown): string => btoa(JSON.stringify(payload)).replace(/=+$/, '');
    return [encode({ alg: 'none' }), encode({ realm_access: { roles } }), 'sig'].join('.');
  }

  function tokenResponse(roles: string[]): Record<string, unknown> {
    return {
      access_token: tokenWithRoles(roles),
      refresh_token: 'refresh-token',
      expires_in: 300,
      refresh_expires_in: 1800
    };
  }

  function jsonResponse(body: unknown, status = 200): Response {
    return {
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body)
    } as unknown as Response;
  }

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get']);
    api.get.and.returnValue(of(config));

    keycloak = jasmine.createSpyObj<KeycloakService>('KeycloakService', ['init', 'clearToken']);
    keycloak.init.and.returnValue(Promise.resolve(true));

    auth = jasmine.createSpyObj<AuthService>('AuthService', ['loadUser']);
    auth.loadUser.and.returnValue(of({} as User));

    context = jasmine.createSpyObj<AuthContextService>('AuthContextService', ['resetOrgs']);

    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: api },
        { provide: KeycloakService, useValue: keycloak },
        { provide: AuthService, useValue: auth },
        { provide: AuthContextService, useValue: context }
      ]
    });

    service = TestBed.inject(AdminLoginService);
    spyOn(window, 'fetch');
  });

  function fetchSpy(): jasmine.Spy {
    return window.fetch as jasmine.Spy;
  }

  it('installs the session and loads the profile on a valid admin login', async () => {
    fetchSpy().and.returnValue(Promise.resolve(jsonResponse(tokenResponse(['PLATFORM_ADMIN']))));

    await service.login('platform-admin', 'secret');

    expect(api.get).toHaveBeenCalledWith('/auth/keycloak/config');
    expect(keycloak.init).toHaveBeenCalledTimes(1);

    const options = keycloak.init.calls.mostRecent().args[0] as {
      config: { url: string; realm: string; clientId: string };
      initOptions: Record<string, unknown>;
      bearerExcludedUrls: string[];
    };
    expect(options.config).toEqual(config);
    expect(options.initOptions['token']).toEqual(jasmine.any(String));
    expect(options.initOptions['refreshToken']).toBe('refresh-token');
    expect(options.initOptions['checkLoginIframe']).toBeFalse();
    expect(options.bearerExcludedUrls).toEqual(['/auth/keycloak/config']);

    expect(auth.loadUser).toHaveBeenCalled();
    expect(context.resetOrgs).toHaveBeenCalled();
  });

  it('sends the credentials to Keycloak as a password grant', async () => {
    fetchSpy().and.returnValue(Promise.resolve(jsonResponse(tokenResponse(['PLATFORM_ADMIN']))));

    await service.login('platform-admin', 'secret');

    const [url, init] = fetchSpy().calls.mostRecent().args as [string, RequestInit];
    expect(url).toBe(
      'http://keycloak.test/auth/realms/codesage-realm/protocol/openid-connect/token'
    );
    expect(init.method).toBe('POST');
    const body = new URLSearchParams(String(init.body));
    expect(body.get('grant_type')).toBe('password');
    expect(body.get('client_id')).toBe('codesage-angular');
    expect(body.get('username')).toBe('platform-admin');
    expect(body.get('password')).toBe('secret');
  });

  it('accepts a legacy SUPER_ADMIN claim through the shared compat map', async () => {
    fetchSpy().and.returnValue(Promise.resolve(jsonResponse(tokenResponse(['SUPER_ADMIN']))));

    await service.login('platform-admin', 'secret');

    expect(keycloak.init).toHaveBeenCalled();
  });

  it('rejects wrong credentials before touching the session', async () => {
    fetchSpy().and.returnValue(
      Promise.resolve(
        jsonResponse({ error: 'invalid_grant', error_description: 'Invalid user credentials' }, 401)
      )
    );

    await expectAsync(service.login('platform-admin', 'nope')).toBeRejectedWith(
      jasmine.objectContaining({ message: 'Incorrect username or password.' })
    );
    expect(keycloak.init).not.toHaveBeenCalled();
    expect(auth.loadUser).not.toHaveBeenCalled();
  });

  it('fails closed when the account has no platform-admin role', async () => {
    fetchSpy().and.returnValue(
      Promise.resolve(jsonResponse(tokenResponse(['ORG_ADMIN', 'DEVELOPER'])))
    );

    await expectAsync(service.login('someone', 'secret')).toBeRejectedWith(
      jasmine.objectContaining({ name: 'AdminLoginError' })
    );
    expect(keycloak.init).not.toHaveBeenCalled();
    expect(auth.loadUser).not.toHaveBeenCalled();
  });

  it('reports a locked account instead of a plain credential error', async () => {
    fetchSpy().and.returnValue(
      Promise.resolve(
        jsonResponse(
          { error: 'invalid_grant', error_description: 'Account is temporarily locked' },
          401
        )
      )
    );

    await expectAsync(service.login('platform-admin', 'secret')).toBeRejectedWith(
      jasmine.objectContaining({ message: jasmine.stringContaining('temporarily locked') })
    );
  });

  it('reports a disabled account instead of a plain credential error', async () => {
    fetchSpy().and.returnValue(
      Promise.resolve(
        jsonResponse({ error: 'invalid_grant', error_description: 'User account is disabled' }, 401)
      )
    );

    await expectAsync(service.login('platform-admin', 'secret')).toBeRejectedWith(
      jasmine.objectContaining({ message: 'This account is disabled.' })
    );
  });

  it('surfaces an operator hint when the client forbids password sign-in', async () => {
    fetchSpy().and.returnValue(
      Promise.resolve(jsonResponse({ error: 'unauthorized_client' }, 400))
    );

    await expectAsync(service.login('platform-admin', 'secret')).toBeRejectedWith(
      jasmine.objectContaining({
        message: 'Password sign-in is disabled for this application.'
      })
    );
  });

  it('reports an unreachable sign-in service without leaking transport details', async () => {
    fetchSpy().and.returnValue(Promise.reject(new TypeError('Failed to fetch')));

    await expectAsync(service.login('platform-admin', 'secret')).toBeRejectedWith(
      jasmine.objectContaining({ message: 'Could not reach the sign-in service. Try again.' })
    );
  });

  it('rejects a token payload it cannot read', async () => {
    fetchSpy().and.returnValue(
      Promise.resolve(jsonResponse({ access_token: 'not-a-jwt', refresh_token: 'r' }))
    );

    await expectAsync(service.login('platform-admin', 'secret')).toBeRejectedWith(
      jasmine.objectContaining({
        message: 'The sign-in service returned an unreadable token.'
      })
    );
    expect(keycloak.init).not.toHaveBeenCalled();
  });

  it('clears the session when the API cannot resolve the profile', async () => {
    fetchSpy().and.returnValue(Promise.resolve(jsonResponse(tokenResponse(['PLATFORM_ADMIN']))));
    auth.loadUser.and.returnValue(throwError(() => new Error('boom')));

    await expectAsync(service.login('platform-admin', 'secret')).toBeRejected();
    expect(keycloak.clearToken).toHaveBeenCalled();
    expect(context.resetOrgs).not.toHaveBeenCalled();
  });

  it('fails closed when keycloak-js does not authenticate the injected tokens', async () => {
    fetchSpy().and.returnValue(Promise.resolve(jsonResponse(tokenResponse(['PLATFORM_ADMIN']))));
    keycloak.init.and.returnValue(Promise.resolve(false));

    await expectAsync(service.login('platform-admin', 'secret')).toBeRejectedWith(
      jasmine.objectContaining({ message: 'Sign-in did not establish a session. Try again.' })
    );
    expect(auth.loadUser).not.toHaveBeenCalled();
  });

  it('throws an AdminLoginError type (component relies on it for copy)', async () => {
    fetchSpy().and.returnValue(Promise.resolve(jsonResponse({ error: 'invalid_client' }, 401)));

    const err = await service.login('platform-admin', 'secret').then(
      () => null,
      (e: unknown) => e
    );
    expect(err instanceof AdminLoginError).toBeTrue();
  });
});
