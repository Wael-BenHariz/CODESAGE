import { TestBed } from '@angular/core/testing';
import {
  ActivatedRouteSnapshot,
  provideRouter,
  Router,
  RouterStateSnapshot
} from '@angular/router';
import { KeycloakService } from 'keycloak-angular';
import { of, throwError } from 'rxjs';

import { RoleGuard, deriveRole, navVisibility } from './role.guard';
import { OrgSettingsService } from '../services/org-settings.service';
import { AuthService } from '../services/auth.service';
import { routes } from '../../app.routes';

/** Every capability a route may declare (AppCapability). */
const CAPABILITIES = ['read', 'write', 'validate', 'org:settings', 'platform'] as const;

describe('route capability declarations', () => {
  it('assigns capability lists to every guarded route', () => {
    const guarded = routes.filter(route => route.canActivate?.length);
    expect(guarded.length).toBeGreaterThan(0);
    for (const route of guarded) {
      const capabilities = route.data?.['capabilities'] as string[] | undefined;
      expect(capabilities).toBeDefined();
      // Every declared capability must be one the guard knows how to check.
      expect((capabilities ?? []).every(cap => CAPABILITIES.includes(cap as never))).toBeTrue();
      expect((capabilities ?? []).length).toBeGreaterThan(0);
    }
    const byPath = (path: string) => routes.find(route => route.path === path);
    expect(byPath('dashboard')?.data?.['capabilities']).toEqual(['write']);
    expect(byPath('settings')?.data?.['capabilities']).toEqual(['write']);
    expect(byPath('settings/org')?.data?.['capabilities']).toEqual(['org:settings']);
    expect(byPath('platform')?.data?.['capabilities']).toEqual(['platform']);
    expect(byPath('repositories')?.data?.['capabilities']).toEqual(['read']);
    expect(byPath('repositories/:owner/:repo')?.data?.['capabilities']).toEqual(['read']);
    expect(byPath('repositories/:owner/:repo/pulls')?.data?.['capabilities']).toEqual(['read']);
    expect(byPath('repositories/:owner/:repo/pulls/:number')?.data?.['capabilities']).toEqual([
      'read'
    ]);
  });

  it('keeps platform routes strictly platform-gated (never org-elevated)', () => {
    const byPath = (path: string) => routes.find(route => route.path === path);
    // /platform is THE gated platform entry (console layout, own shell, no
    // org elevation); /platform-admin is only a legacy redirect into it.
    const platform = byPath('platform');
    expect(platform?.data?.['capabilities']).toEqual(['platform']);
    const legacy = byPath('platform-admin');
    expect(legacy?.redirectTo).toBe('platform');
    expect(legacy?.canActivate).toBeUndefined();
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

  it('applies the ladder ORG_ADMIN > REVIEWER > DEVELOPER > NONE', () => {
    // Precedence fix: NONE is the LOWEST rank — an explicit legacy read-only
    // claim no longer outranks a real role grant (target design §2.2).
    expect(deriveRole(['DEVELOPER', 'REVIEWER', 'ORG_ADMIN'])).toBe('ORG_ADMIN');
    expect(deriveRole(['DEVELOPER', 'REVIEWER'])).toBe('REVIEWER');
    expect(deriveRole(['DEVELOPER'])).toBe('DEVELOPER');
    expect(deriveRole(['DEVELOPER'], true)).toBe('DEVELOPER');
    expect(deriveRole(['ORG_ADMIN', 'REVIEWER', 'DEVELOPER', 'NONE'])).toBe('ORG_ADMIN');
    expect(deriveRole(['DEVELOPER', 'GUEST'])).toBe('DEVELOPER');
    expect(deriveRole(['guest'])).toBe('NONE');
    expect(deriveRole(['GUEST'], true)).toBe('NONE');
  });

  it('falls back to NONE for anything unrecognized (non-brokered)', () => {
    // Fail-closed: unknown role names, default realm roles and an empty list
    // all land on the read-only sentinel for a session WITHOUT GitHub
    // identity claims (the F1 temporary DEVELOPER fallback was removed —
    // roles come from workspace membership only).
    expect(deriveRole(['some-other-realm-role'])).toBe('NONE');
    expect(deriveRole(['default-roles-codesage-realm'])).toBe('NONE');
    expect(deriveRole([])).toBe('NONE');
  });

  it('gives a GitHub-brokered session with no recognized claim ORG_ADMIN (signup default)', () => {
    // Mirrors the backend: viaGitHub + nothing recognized/legacy claimed
    // → ORG_ADMIN (the account-creation default — first login creates the
    // personal workspace where that user holds ORG_ADMIN membership).
    // Any explicit claim outranks the default (GUEST stays NONE).
    expect(deriveRole([], true)).toBe('ORG_ADMIN');
    expect(deriveRole(['default-roles-codesage-realm'], true)).toBe('ORG_ADMIN');
    expect(deriveRole(['some-other-realm-role'], true)).toBe('ORG_ADMIN');
    expect(deriveRole(['GUEST'], true)).toBe('NONE');
    expect(deriveRole(['DEVELOPER'], true)).toBe('DEVELOPER');
  });

  it('never warns — derivation is pure (the backend logs its own fallback)', () => {
    const warn = spyOn(console, 'warn');
    deriveRole([], true, 'octocat');
    deriveRole(['DEVELOPER'], true);
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
  let orgSvc: jasmine.SpyObj<OrgSettingsService>;
  /**
   * Fake GET /auth/me profile — `null` by default (profile not loaded yet,
   * guard falls back to the JWT exactly as before).
   */
  let backendUser: { role: string } | null = null;

  const state = (url: string) => ({ url }) as RouterStateSnapshot;

  function route(data?: Record<string, unknown>): ActivatedRouteSnapshot {
    return { data: data ?? {} } as ActivatedRouteSnapshot;
  }

  /**
   * Bootstrap the TestBed with a Keycloak session carrying `sessionRoles`
   * and an optional parsed-token claim map (`tokenParsed` — used for the
   * GitHub identity claims the guard inspects).
   */
  function configure(
    sessionRoles: string[],
    tokenParsed: Record<string, unknown> = {},
    backendRole: string | null = null
  ): void {
    backendUser = backendRole != null ? { role: backendRole } : null;
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
    orgSvc = jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', ['listOrgs']);
    orgSvc.listOrgs.and.returnValue(of([]));

    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        { provide: KeycloakService, useValue: keycloak },
        { provide: OrgSettingsService, useValue: orgSvc },
        // AuthContextService (injected by the guard) reads the backend role
        // from GET /auth/me — null unless a test passes `backendRole`.
        { provide: AuthService, useValue: { currentUser: () => backendUser } }
      ]
    });
    router = TestBed.inject(Router);
    guard = TestBed.inject(RoleGuard);
  }

  it('redirects an anonymous visitor to /login with the original returnUrl', async () => {
    configure([]);
    const result = await guard.canActivate(route(), state('/settings'));

    expect(result).toEqual(router.parseUrl('/login?returnUrl=/settings'));
  });

  it('activates a capability-less route for any authenticated user', async () => {
    configure(['NONE']);
    expect(await guard.canActivate(route(), state('/repositories'))).toBeTrue();
  });

  it('allows NONE on a read route', async () => {
    configure(['NONE']);
    expect(
      await guard.canActivate(route({ capabilities: ['read'] }), state('/repositories'))
    ).toBeTrue();
  });

  it('allows DEVELOPER on a write-protected route', async () => {
    configure(['DEVELOPER']);
    expect(
      await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'))
    ).toBeTrue();
  });

  it('allows REVIEWER on a write-protected route (require_developer includes it)', async () => {
    configure(['REVIEWER']);
    expect(
      await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'))
    ).toBeTrue();
  });

  it('allows ORG_ADMIN on write and org-settings routes', async () => {
    configure(['ORG_ADMIN']);
    expect(
      await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'))
    ).toBeTrue();
    expect(
      await guard.canActivate(route({ capabilities: ['org:settings'] }), state('/settings'))
    ).toBeTrue();
  });

  it('allows PLATFORM_ADMIN on write, org-settings and platform routes', async () => {
    configure(['PLATFORM_ADMIN']);
    expect(
      await guard.canActivate(route({ capabilities: ['write'] }), state('/settings'))
    ).toBeTrue();
    expect(
      await guard.canActivate(route({ capabilities: ['org:settings'] }), state('/settings'))
    ).toBeTrue();
    expect(
      await guard.canActivate(route({ capabilities: ['platform'] }), state('/platform'))
    ).toBeTrue();
  });

  it('allows a legacy SUPER_ADMIN token everywhere (compat → PLATFORM_ADMIN)', async () => {
    configure(['SUPER_ADMIN']);
    expect(
      await guard.canActivate(route({ capabilities: ['write'] }), state('/settings'))
    ).toBeTrue();
    expect(
      await guard.canActivate(route({ capabilities: ['platform'] }), state('/platform'))
    ).toBeTrue();
  });

  it('bounces NONE off a write-protected route to the forbidden page', async () => {
    configure(['NONE']);
    const result = await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/forbidden'));
  });

  it('lets DEVELOPER win over a legacy GUEST claim (compat → NONE, lowest rank)', async () => {
    // Precedence fix: the compat map turns GUEST into NONE, which is now the
    // LOWEST rank — a real role grant outranks an explicit read-only claim.
    configure(['GUEST', 'DEVELOPER']);
    expect(
      await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'))
    ).toBeTrue();
  });

  it('bounces a session carrying only legacy GUEST (compat → NONE)', async () => {
    configure(['GUEST']);
    const result = await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/forbidden'));
  });

  it('mirrors the backend when the token carries no recognized roles (→ NONE)', async () => {
    // Authenticated Keycloak session whose realm roles are only defaults
    // (empty list here) and NO GitHub claims: backend derive_role falls back
    // to NONE, so the guard must bounce off the write route to /forbidden —
    // exactly like an explicit NONE, keeping both sides identical.
    configure([]);
    // configure() sets isLoggedIn from sessionRoles.length — force the
    // authenticated-but-roleless state this scenario needs.
    keycloak.isLoggedIn.and.returnValue(true);

    const result = await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/forbidden'));
  });

  it('gives a GitHub-brokered default-roles session ORG_ADMIN (signup default)', async () => {
    // The same roleless session as above, but the token carries the GitHub
    // identity claims: backend derive_role returns ORG_ADMIN (the
    // account-creation default for GitHub signups) — so the write route
    // must open, both sides identical.
    configure([], { githubId: 75458407, githubLogin: 'Wael-BenHariz' });
    keycloak.isLoggedIn.and.returnValue(true);

    expect(
      await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'))
    ).toBeTrue();
  });

  it('still bounces a GitHub session explicitly downgraded to GUEST', async () => {
    // Explicit GUEST role in the token maps to NONE — claims outrank the
    // brokered signup default.
    configure(['GUEST'], { githubId: 75458407 });
    const result = await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'));

    expect(result).toEqual(router.parseUrl('/forbidden'));
  });

  // --- org-membership elevation (plan §2: effective = max(JWT, org_members)) --

  it('elevates an org_members ORG_ADMIN row onto the org-settings route', async () => {
    // The Q1 seeding shape: DEVELOPER claim, but the org's only linked
    // user holds ORG_ADMIN in org_members — the backend guard computes
    // the same effective role, so the page must be reachable.
    configure(['DEVELOPER']);
    orgSvc.listOrgs.and.returnValue(
      of([{ id: 'org-1', name: 'acme', account_type: 'Organization', role: 'ORG_ADMIN' }])
    );

    expect(
      await guard.canActivate(route({ capabilities: ['org:settings'] }), state('/settings/org'))
    ).toBeTrue();
  });

  it('does not elevate a plain DEVELOPER membership', async () => {
    configure(['DEVELOPER']);
    orgSvc.listOrgs.and.returnValue(
      of([{ id: 'org-1', name: 'acme', account_type: 'Organization', role: 'DEVELOPER' }])
    );

    const result = await guard.canActivate(
      route({ capabilities: ['org:settings'] }),
      state('/settings/org')
    );
    expect(result).toEqual(router.parseUrl('/forbidden'));
  });

  it('fails closed when the org lookup errors on the org-settings route', async () => {
    configure(['DEVELOPER']);
    orgSvc.listOrgs.and.returnValue(throwError(() => new Error('network down')));

    const result = await guard.canActivate(
      route({ capabilities: ['org:settings'] }),
      state('/settings/org')
    );
    expect(result).toEqual(router.parseUrl('/forbidden'));
  });

  it('consults memberships only for org:settings (deny path of write)', async () => {
    configure(['NONE']);
    orgSvc.listOrgs.and.returnValue(
      of([{ id: 'org-1', name: 'acme', account_type: 'Organization', role: 'ORG_ADMIN' }])
    );

    const result = await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'));
    expect(result).toEqual(router.parseUrl('/forbidden'));
    expect(orgSvc.listOrgs).not.toHaveBeenCalled();
  });

  it('skips the membership lookup when the JWT role already qualifies', async () => {
    configure(['ORG_ADMIN']);
    expect(
      await guard.canActivate(route({ capabilities: ['org:settings'] }), state('/settings/org'))
    ).toBeTrue();
    expect(orgSvc.listOrgs).not.toHaveBeenCalled();
  });

  // --- rule 4: prefer the role reported by GET /auth/me -------------------

  it('prefers the backend /auth/me role over re-deriving from the JWT', async () => {
    // JWT says DEVELOPER (no admin qualification), the backend profile says
    // ORG_ADMIN — the guard must take the backend value without consulting
    // org memberships (the lookup never runs).
    configure(['DEVELOPER'], {}, 'ORG_ADMIN');

    expect(
      await guard.canActivate(route({ capabilities: ['org:settings'] }), state('/settings/org'))
    ).toBeTrue();
    expect(orgSvc.listOrgs).not.toHaveBeenCalled();
  });

  it('honors a backend-reported NONE downgrade even when the JWT has roles', async () => {
    // The backend is the source of truth for the effective role: a profile
    // reporting the read-only sentinel must not reach write routes.
    configure(['DEVELOPER'], {}, 'NONE');

    const result = await guard.canActivate(route({ capabilities: ['write'] }), state('/dashboard'));
    expect(result).toEqual(router.parseUrl('/forbidden'));
  });

  it('falls back to the JWT derivation while the profile has not loaded', async () => {
    // backendRole = null (profile still in flight) — derive from the token,
    // mirroring security/roles.py, exactly like before the profile arrives.
    configure(['ORG_ADMIN']);

    expect(
      await guard.canActivate(route({ capabilities: ['org:settings'] }), state('/settings/org'))
    ).toBeTrue();
  });

  it('never opens the platform route for a non-platform role', async () => {
    // org:settings elevation must not leak into platform routes.
    configure(['DEVELOPER']);
    orgSvc.listOrgs.and.returnValue(
      of([{ id: 'org-1', name: 'acme', account_type: 'Organization', role: 'ORG_ADMIN' }])
    );

    const result = await guard.canActivate(
      route({ capabilities: ['platform'] }),
      state('/platform')
    );
    expect(result).toEqual(router.parseUrl('/forbidden'));
    expect(orgSvc.listOrgs).not.toHaveBeenCalled();
  });
});
