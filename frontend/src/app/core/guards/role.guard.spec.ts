import { TestBed } from '@angular/core/testing';
import {
  ActivatedRouteSnapshot,
  provideRouter,
  Router,
  RouterStateSnapshot
} from '@angular/router';
import { KeycloakService } from 'keycloak-angular';

import { RoleGuard, deriveRole } from './role.guard';

describe('deriveRole', () => {
  it('gives SUPER_ADMIN precedence over everything', () => {
    expect(deriveRole(['GUEST', 'SUPER_ADMIN', 'DEVELOPER'])).toBe('SUPER_ADMIN');
  });

  it('lets an explicit GUEST downgrade outrank DEVELOPER', () => {
    expect(deriveRole(['DEVELOPER', 'GUEST'])).toBe('GUEST');
    expect(deriveRole(['guest'])).toBe('GUEST');
  });

  it('returns DEVELOPER for an explicit DEVELOPER, GUEST for anything unrecognized', () => {
    expect(deriveRole(['DEVELOPER'])).toBe('DEVELOPER');
    // Fail-closed fallback (mirrors backend derive_role): unknown role names
    // and an empty role list both land on the read-only GUEST role when the
    // session did NOT authenticate through GitHub.
    expect(deriveRole(['some-other-realm-role'])).toBe('GUEST');
    expect(deriveRole(['default-roles-codesage-realm'])).toBe('GUEST');
    expect(deriveRole([])).toBe('GUEST');
  });

  it('falls back to DEVELOPER for a GitHub-brokered session', () => {
    // Mirrors backend derive_role(via_github=True): a token carrying the
    // GitHub identity claims with only default realm roles is a developer.
    expect(deriveRole(['default-roles-codesage-realm'], true)).toBe('DEVELOPER');
    expect(deriveRole([], true)).toBe('DEVELOPER');
    expect(deriveRole(['some-other-realm-role'], true)).toBe('DEVELOPER');
  });

  it('lets explicit roles outrank the GitHub fallback', () => {
    expect(deriveRole(['GUEST'], true)).toBe('GUEST');
    expect(deriveRole(['DEVELOPER', 'GUEST'], true)).toBe('GUEST');
    expect(deriveRole(['SUPER_ADMIN'], true)).toBe('SUPER_ADMIN');
    expect(deriveRole(['DEVELOPER'], true)).toBe('DEVELOPER');
  });

  it('matches the backend derive_role contract case-insensitively', () => {
    expect(deriveRole(['super_admin'])).toBe('SUPER_ADMIN');
    expect(deriveRole(['Super_Admin', 'guest'])).toBe('SUPER_ADMIN');
  });
});

describe('RoleGuard', () => {
  let guard: RoleGuard;
  let router: Router;
  let keycloak: jasmine.SpyObj<KeycloakService>;

  const state = (url: string) => ({ url }) as RouterStateSnapshot;

  function route(data?: Record<string, unknown>): ActivatedRouteSnapshot {
    return { data: data ?? {} } as ActivatedRouteSnapshot;
  }

  /**
   * Bootstrap the TestBed with a Keycloak session carrying `sessionRoles`
   * and an optional parsed-token claim map (`tokenParsed` — used for the
   * GitHub identity claims the guard inspects).
   */
  function configure(sessionRoles: string[], tokenParsed: Record<string, unknown> = {}): void {
    keycloak = jasmine.createSpyObj<KeycloakService>('KeycloakService', [
      'isLoggedIn',
      'getUserRoles',
      'getKeycloakInstance'
    ]);
    keycloak.isLoggedIn.and.returnValue(sessionRoles.length > 0);
    keycloak.getUserRoles.and.returnValue(sessionRoles);
    keycloak.getKeycloakInstance.and.returnValue({
      tokenParsed
    } as unknown as ReturnType<KeycloakService['getKeycloakInstance']>);

    TestBed.configureTestingModule({
      providers: [provideRouter([]), { provide: KeycloakService, useValue: keycloak }]
    });
    router = TestBed.inject(Router);
    guard = TestBed.inject(RoleGuard);
  }

  it('redirects an anonymous visitor to /login with the original returnUrl', async () => {
    configure([]);
    const result = await guard.canActivate(route(), state('/settings'));

    expect(result).toEqual(router.parseUrl('/login?returnUrl=/settings'));
  });

  it('activates a role-less route for any authenticated user', async () => {
    configure(['GUEST']);
    expect(await guard.canActivate(route(), state('/repositories'))).toBeTrue();
  });

  it('allows DEVELOPER on a write-protected route', async () => {
    configure(['DEVELOPER']);
    const writeRoute = route({ roles: ['DEVELOPER', 'SUPER_ADMIN'] });
    expect(await guard.canActivate(writeRoute, state('/dashboard'))).toBeTrue();
  });

  it('allows SUPER_ADMIN everywhere', async () => {
    configure(['SUPER_ADMIN']);
    const writeRoute = route({ roles: ['DEVELOPER', 'SUPER_ADMIN'] });
    expect(await guard.canActivate(writeRoute, state('/settings'))).toBeTrue();
  });

  it('bounces GUEST off a write-protected route to the read-only home', async () => {
    configure(['GUEST', 'DEVELOPER']);
    const writeRoute = route({ roles: ['DEVELOPER', 'SUPER_ADMIN'] });
    const result = await guard.canActivate(writeRoute, state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/repositories'));
  });

  it('mirrors the backend when the token carries no recognized roles (default GUEST)', async () => {
    // Authenticated Keycloak session whose realm roles are only defaults
    // (empty list here) and NO GitHub claims: backend derive_role falls back
    // to GUEST, so the guard must bounce off the write route to the read-only
    // home — exactly like an explicit GUEST, keeping both sides identical.
    configure([]);
    // configure() sets isLoggedIn from sessionRoles.length — force the
    // authenticated-but-roleless state this scenario needs.
    keycloak.isLoggedIn.and.returnValue(true);

    const writeRoute = route({ roles: ['DEVELOPER', 'SUPER_ADMIN'] });
    const result = await guard.canActivate(writeRoute, state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/repositories'));
  });

  it('allows a GitHub-brokered default-roles session on write routes', async () => {
    // Same roleless session as above, but the token carries the GitHub
    // identity claims (githubId/githubLogin): backend derives DEVELOPER, so
    // the guard must let it through — mirrors derive_role(via_github=True).
    configure([], { githubId: 75458407, githubLogin: 'Wael-BenHariz' });
    keycloak.isLoggedIn.and.returnValue(true);

    const writeRoute = route({ roles: ['DEVELOPER', 'SUPER_ADMIN'] });
    expect(await guard.canActivate(writeRoute, state('/dashboard'))).toBeTrue();
  });

  it('still bounces a GitHub session explicitly downgraded to GUEST', async () => {
    // Explicit GUEST role in the token outranks the GitHub fallback.
    configure(['GUEST'], { githubId: 75458407 });
    const writeRoute = route({ roles: ['DEVELOPER', 'SUPER_ADMIN'] });
    const result = await guard.canActivate(writeRoute, state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/repositories'));
  });
});
