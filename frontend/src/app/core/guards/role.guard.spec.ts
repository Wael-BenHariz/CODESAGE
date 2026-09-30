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

  it('returns DEVELOPER for an explicit role, for unknown roles, and by default', () => {
    expect(deriveRole(['DEVELOPER'])).toBe('DEVELOPER');
    expect(deriveRole(['some-other-realm-role'])).toBe('DEVELOPER');
    expect(deriveRole([])).toBe('DEVELOPER');
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

  /** Bootstrap the TestBed with a Keycloak session carrying `sessionRoles`. */
  function configure(sessionRoles: string[]): void {
    keycloak = jasmine.createSpyObj<KeycloakService>('KeycloakService', [
      'isLoggedIn',
      'getUserRoles'
    ]);
    keycloak.isLoggedIn.and.returnValue(sessionRoles.length > 0);
    keycloak.getUserRoles.and.returnValue(sessionRoles);

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

  it('mirrors the backend when the token carries no realm roles (default DEVELOPER)', async () => {
    // Authenticated Keycloak session with an empty role list (invite-only
    // realm default): backend derives DEVELOPER, so the write route opens.
    keycloak = jasmine.createSpyObj<KeycloakService>('KeycloakService', [
      'isLoggedIn',
      'getUserRoles'
    ]);
    keycloak.isLoggedIn.and.returnValue(true);
    keycloak.getUserRoles.and.returnValue([]);

    TestBed.configureTestingModule({
      providers: [provideRouter([]), { provide: KeycloakService, useValue: keycloak }]
    });
    guard = TestBed.inject(RoleGuard);

    const writeRoute = route({ roles: ['DEVELOPER', 'SUPER_ADMIN'] });
    expect(await guard.canActivate(writeRoute, state('/dashboard'))).toBeTrue();
  });
});
