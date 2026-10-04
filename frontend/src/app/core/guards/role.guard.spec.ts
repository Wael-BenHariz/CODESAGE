import { TestBed } from '@angular/core/testing';
import {
  ActivatedRouteSnapshot,
  provideRouter,
  Router,
  RouterStateSnapshot
} from '@angular/router';
import { KeycloakService } from 'keycloak-angular';

import {
  ADMIN_ROLES,
  ANY_ROLE,
  RoleGuard,
  WRITE_ROLES,
  deriveRole,
  navVisibility
} from './role.guard';
import { routes } from '../../app.routes';

describe('role lists', () => {
  it('exposes the four-role vocabulary plus the NONE read sentinel', () => {
    expect(ANY_ROLE).toEqual(['DEVELOPER', 'REVIEWER', 'ORG_ADMIN', 'PLATFORM_ADMIN', 'NONE']);
    expect(WRITE_ROLES).toEqual(['DEVELOPER', 'REVIEWER', 'ORG_ADMIN', 'PLATFORM_ADMIN']);
    expect(ADMIN_ROLES).toEqual(['ORG_ADMIN', 'PLATFORM_ADMIN']);
  });

  it('keeps NONE readable but never writable or admin', () => {
    expect(ANY_ROLE).toContain('NONE');
    expect(WRITE_ROLES).not.toContain('NONE');
    expect(ADMIN_ROLES).not.toContain('NONE');
  });

  it('assigns role lists to every guarded route', () => {
    const guarded = routes.filter(route => route.canActivate?.length);
    expect(guarded.length).toBeGreaterThan(0);
    for (const route of guarded) {
      const roles = route.data?.['roles'] as string[] | undefined;
      expect(roles).toBeDefined();
      // Every declared role must exist in the vocabulary the guard derives.
      expect((roles ?? []).every(role => ANY_ROLE.includes(role))).toBeTrue();
    }
    const byPath = (path: string) => routes.find(route => route.path === path);
    expect(byPath('dashboard')?.data?.['roles']).toBe(WRITE_ROLES);
    expect(byPath('settings')?.data?.['roles']).toBe(WRITE_ROLES);
    expect(byPath('repositories')?.data?.['roles']).toBe(ANY_ROLE);
    expect(byPath('repositories/:owner/:repo')?.data?.['roles']).toBe(ANY_ROLE);
    expect(byPath('repositories/:owner/:repo/pulls')?.data?.['roles']).toBe(ANY_ROLE);
    expect(byPath('repositories/:owner/:repo/pulls/:number')?.data?.['roles']).toBe(ANY_ROLE);
  });
});

describe('deriveRole', () => {
  it('gives PLATFORM_ADMIN precedence over everything', () => {
    expect(deriveRole(['ORG_ADMIN', 'PLATFORM_ADMIN', 'REVIEWER'])).toBe('PLATFORM_ADMIN');
    expect(deriveRole(['NONE', 'DEVELOPER', 'PLATFORM_ADMIN'])).toBe('PLATFORM_ADMIN');
  });

  it('maps legacy SUPER_ADMIN to PLATFORM_ADMIN through the compat map', () => {
    expect(deriveRole(['SUPER_ADMIN'])).toBe('PLATFORM_ADMIN');
    expect(deriveRole(['super_admin'])).toBe('PLATFORM_ADMIN');
    expect(deriveRole(['GUEST', 'SUPER_ADMIN', 'DEVELOPER'])).toBe('PLATFORM_ADMIN');
  });

  it('lets the explicit NONE sentinel (or legacy GUEST) outrank role grants', () => {
    // Precedence: PLATFORM_ADMIN > NONE > ORG_ADMIN > REVIEWER > DEVELOPER —
    // an explicit legacy read-only downgrade is honored (fail-closed).
    expect(deriveRole(['ORG_ADMIN', 'REVIEWER', 'DEVELOPER', 'NONE'])).toBe('NONE');
    expect(deriveRole(['DEVELOPER', 'GUEST'])).toBe('NONE');
    expect(deriveRole(['guest'])).toBe('NONE');
    expect(deriveRole(['GUEST'], true)).toBe('NONE');
  });

  it('applies the ladder ORG_ADMIN > REVIEWER > DEVELOPER', () => {
    expect(deriveRole(['DEVELOPER', 'REVIEWER', 'ORG_ADMIN'])).toBe('ORG_ADMIN');
    expect(deriveRole(['DEVELOPER', 'REVIEWER'])).toBe('REVIEWER');
    expect(deriveRole(['DEVELOPER'])).toBe('DEVELOPER');
    expect(deriveRole(['DEVELOPER'], true)).toBe('DEVELOPER');
  });

  it('falls back to NONE for anything unrecognized when not GitHub-brokered', () => {
    // Fail-closed: unknown role names, default realm roles and an empty list
    // all land on the read-only sentinel when the session did NOT go through
    // the GitHub broker.
    expect(deriveRole(['some-other-realm-role'])).toBe('NONE');
    expect(deriveRole(['default-roles-codesage-realm'])).toBe('NONE');
    expect(deriveRole([])).toBe('NONE');
  });

  it('falls back to DEVELOPER for a GitHub-brokered session and warns (F1)', () => {
    // TEMPORARY (F1): mirrors backend derive_role(via_github=True) — a token
    // carrying the GitHub identity claims with only default realm roles is a
    // developer, and every use logs the structured fallback warning.
    const warn = spyOn(console, 'warn');
    expect(deriveRole(['default-roles-codesage-realm'], true)).toBe('DEVELOPER');
    expect(deriveRole([], true)).toBe('DEVELOPER');
    expect(deriveRole(['some-other-realm-role'], true)).toBe('DEVELOPER');
    expect(warn).toHaveBeenCalledTimes(3);
    const message = warn.calls.mostRecent().args[0] as string;
    expect(message).toContain('role_fallback_broker_developer');
    expect(message).toContain('subject=unknown');
    expect(message).toContain('derived=DEVELOPER');
  });

  it('reports the subject in the fallback warning when one is provided', () => {
    const warn = spyOn(console, 'warn');
    deriveRole([], true, 'octocat');
    expect(warn.calls.mostRecent().args[0]).toContain('subject=octocat');
  });

  it('never warns when an explicit role matched', () => {
    const warn = spyOn(console, 'warn');
    deriveRole(['DEVELOPER'], true);
    deriveRole(['GUEST'], true);
    deriveRole(['PLATFORM_ADMIN']);
    expect(warn).not.toHaveBeenCalled();
  });
});

describe('navVisibility', () => {
  it('reveals write entries to every write role and admin entries to admins', () => {
    expect(navVisibility('DEVELOPER')).toEqual({ write: true, admin: false });
    expect(navVisibility('REVIEWER')).toEqual({ write: true, admin: false });
    expect(navVisibility('ORG_ADMIN')).toEqual({ write: true, admin: true });
    expect(navVisibility('PLATFORM_ADMIN')).toEqual({ write: true, admin: true });
  });

  it('hides everything from NONE', () => {
    expect(navVisibility('NONE')).toEqual({ write: false, admin: false });
  });

  it('normalizes legacy cached roles through the compat map', () => {
    expect(navVisibility('GUEST')).toEqual({ write: false, admin: false });
    expect(navVisibility('guest')).toEqual({ write: false, admin: false });
    expect(navVisibility('SUPER_ADMIN')).toEqual({ write: true, admin: true });
  });

  it('fails closed on a missing or unknown role', () => {
    expect(navVisibility(null)).toEqual({ write: false, admin: false });
    expect(navVisibility(undefined)).toEqual({ write: false, admin: false });
    expect(navVisibility('')).toEqual({ write: false, admin: false });
    expect(navVisibility('some-other-realm-role')).toEqual({ write: false, admin: false });
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
    configure(['NONE']);
    expect(await guard.canActivate(route(), state('/repositories'))).toBeTrue();
  });

  it('allows NONE on a read route (ANY_ROLE)', async () => {
    configure(['NONE']);
    expect(await guard.canActivate(route({ roles: ANY_ROLE }), state('/repositories'))).toBeTrue();
  });

  it('allows DEVELOPER on a write-protected route', async () => {
    configure(['DEVELOPER']);
    expect(await guard.canActivate(route({ roles: WRITE_ROLES }), state('/dashboard'))).toBeTrue();
  });

  it('allows REVIEWER on a write-protected route (require_developer includes it)', async () => {
    configure(['REVIEWER']);
    expect(await guard.canActivate(route({ roles: WRITE_ROLES }), state('/dashboard'))).toBeTrue();
  });

  it('allows ORG_ADMIN on write and admin routes', async () => {
    configure(['ORG_ADMIN']);
    expect(await guard.canActivate(route({ roles: WRITE_ROLES }), state('/dashboard'))).toBeTrue();
    expect(await guard.canActivate(route({ roles: ADMIN_ROLES }), state('/settings'))).toBeTrue();
  });

  it('allows PLATFORM_ADMIN on write and admin routes', async () => {
    configure(['PLATFORM_ADMIN']);
    expect(await guard.canActivate(route({ roles: WRITE_ROLES }), state('/settings'))).toBeTrue();
    expect(await guard.canActivate(route({ roles: ADMIN_ROLES }), state('/settings'))).toBeTrue();
  });

  it('allows a legacy SUPER_ADMIN token everywhere (compat → PLATFORM_ADMIN)', async () => {
    configure(['SUPER_ADMIN']);
    expect(await guard.canActivate(route({ roles: WRITE_ROLES }), state('/settings'))).toBeTrue();
    expect(await guard.canActivate(route({ roles: ADMIN_ROLES }), state('/settings'))).toBeTrue();
  });

  it('bounces NONE off a write-protected route to the read-only home', async () => {
    configure(['NONE']);
    const result = await guard.canActivate(route({ roles: WRITE_ROLES }), state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/repositories'));
  });

  it('bounces a session carrying only legacy GUEST + DEVELOPER (compat → NONE)', async () => {
    // The compat map turns GUEST into NONE, which outranks DEVELOPER — an
    // explicit read-only downgrade always wins.
    configure(['GUEST', 'DEVELOPER']);
    const result = await guard.canActivate(route({ roles: WRITE_ROLES }), state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/repositories'));
  });

  it('mirrors the backend when the token carries no recognized roles (→ NONE)', async () => {
    // Authenticated Keycloak session whose realm roles are only defaults
    // (empty list here) and NO GitHub claims: backend derive_role falls back
    // to NONE, so the guard must bounce off the write route — exactly like an
    // explicit NONE, keeping both sides identical.
    configure([]);
    // configure() sets isLoggedIn from sessionRoles.length — force the
    // authenticated-but-roleless state this scenario needs.
    keycloak.isLoggedIn.and.returnValue(true);

    const result = await guard.canActivate(route({ roles: WRITE_ROLES }), state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/repositories'));
  });

  it('allows a GitHub-brokered default-roles session on write routes (F1)', async () => {
    // Same roleless session as above, but the token carries the GitHub
    // identity claims (githubId/githubLogin): backend derives DEVELOPER, so
    // the guard must let it through — and warn, mirroring the backend log.
    const warn = spyOn(console, 'warn');
    configure([], { githubId: 75458407, githubLogin: 'Wael-BenHariz' });
    keycloak.isLoggedIn.and.returnValue(true);

    expect(await guard.canActivate(route({ roles: WRITE_ROLES }), state('/dashboard'))).toBeTrue();
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.calls.mostRecent().args[0]).toContain('role_fallback_broker_developer');
  });

  it('still bounces a GitHub session explicitly downgraded to GUEST', async () => {
    // Explicit GUEST role in the token outranks the GitHub fallback.
    configure(['GUEST'], { githubId: 75458407 });
    const result = await guard.canActivate(route({ roles: WRITE_ROLES }), state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/repositories'));
  });
});
