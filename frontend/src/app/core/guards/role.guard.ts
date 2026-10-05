import { Injectable, inject } from '@angular/core';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { KeycloakAuthGuard, KeycloakService } from 'keycloak-angular';

import { AuthContextService } from '../services/auth-context.service';

/**
 * Every authenticated role — matches the backend's "reads: any role" rule
 * (the NONE read-only sentinel may open routes guarded by this list).
 */
export const ANY_ROLE = ['DEVELOPER', 'REVIEWER', 'ORG_ADMIN', 'PLATFORM_ADMIN', 'NONE'];

/** Roles allowed to mutate anything — mirrors the backend's require_developer. */
export const WRITE_ROLES = ['DEVELOPER', 'REVIEWER', 'ORG_ADMIN', 'PLATFORM_ADMIN'];

/** Org/platform administration entries (org settings, member management). */
export const ADMIN_ROLES = ['ORG_ADMIN', 'PLATFORM_ADMIN'];

/**
 * True when the route declares exactly the admin role list — those are
 * the routes eligible for the org-membership elevation below (an org
 * members row raises the effective role, plan §2 max(JWT, org_members.role)).
 */
export function isAdminRoute(required: readonly string[]): boolean {
  return (
    required.length === ADMIN_ROLES.length && required.every(role => ADMIN_ROLES.includes(role))
  );
}

/**
 * One-release compatibility map: legacy claim -> new claim. Mirrors the
 * backend's `_COMPAT_MAP` (app/security/roles.py) — remove in v0.4.0
 * together with the old realm roles/groups.
 */
const COMPAT_MAP: Record<string, string> = {
  SUPER_ADMIN: 'PLATFORM_ADMIN',
  GUEST: 'NONE',
  DEVELOPER: 'DEVELOPER'
};

/**
 * Map the roles carried by the Keycloak JWT to the effective global role
 * used for route access.
 *
 * Mirrors the backend's `derive_role` (app/security/roles.py) exactly:
 * 1. claims pass through the one-release compat map (SUPER_ADMIN ->
 *    PLATFORM_ADMIN, GUEST -> NONE); new names pass through unchanged;
 * 2. precedence PLATFORM_ADMIN > NONE > ORG_ADMIN > REVIEWER > DEVELOPER —
 *    an explicit legacy read-only claim (GUEST -> NONE) beats role grants
 *    (fail-closed: an explicit downgrade is honored);
 * 3. no recognized or legacy claim at all: TEMPORARY (F1) DEVELOPER when
 *    the session authenticated through the GitHub broker (`viaGitHub`,
 *    logs a `role_fallback_broker_developer` warning on each use — plan §6
 *    follow-up: remove once every realm user has a group), else NONE
 *    (fail-closed).
 *
 * A token with no role claim at all never gets this far — the backend
 * rejects it with a 401 before the guard's role list is ever consulted.
 * Keeping both sides identical prevents a redirect loop where the
 * frontend allows a user the backend 403s, or vice versa.
 */
export function deriveRole(
  tokenRoles: readonly string[],
  viaGitHub = false,
  subject?: string
): string {
  const roles = new Set(tokenRoles.map(role => String(role).toUpperCase()));
  const mapped = new Set(Array.from(roles, role => COMPAT_MAP[role] ?? role));

  if (mapped.has('PLATFORM_ADMIN')) {
    return 'PLATFORM_ADMIN';
  }
  if (mapped.has('NONE')) {
    return 'NONE';
  }
  for (const role of ['ORG_ADMIN', 'REVIEWER', 'DEVELOPER']) {
    if (mapped.has(role)) {
      return role;
    }
  }

  // TEMPORARY (F1): GitHub-brokered sessions keep deriving DEVELOPER until
  // every realm user has a group — plan §6 follow-up. Mirrors the backend's
  // structured warning (subject + derived role, no secrets).
  if (viaGitHub) {
    console.warn(
      `role_fallback_broker_developer subject=${subject ?? 'unknown'} derived=DEVELOPER claims=${JSON.stringify([...roles].sort())}`
    );
    return 'DEVELOPER';
  }
  return 'NONE';
}

/**
 * Cosmetic capability flags for header/nav entries, derived from the
 * effective role (the backend stays authoritative). Roles are normalized
 * through the same compat map as `deriveRole`; an unknown or missing role
 * fails closed (NONE -> no write/admin entries visible).
 */
export function navVisibility(role: string | null | undefined): {
  write: boolean;
  admin: boolean;
} {
  const upper = (role ?? '').toUpperCase();
  const effective = COMPAT_MAP[upper] ?? upper;
  return {
    write: WRITE_ROLES.includes(effective),
    admin: ADMIN_ROLES.includes(effective)
  };
}

/**
 * Route guard: requires a Keycloak session and (when the route declares
 * `data.roles`) an effective role among them. Role lists (ANY_ROLE,
 * WRITE_ROLES, ADMIN_ROLES) are exported from this file and set per route
 * in app.routes.ts.
 *
 * When the JWT role alone does not qualify for an **admin** route, the
 * guard consults `GET /orgs`: an `org_members` row with `ORG_ADMIN`
 * elevates the caller (plan §2 effective role = max(JWT, org_members.role)).
 * This is what lets a DEVELOPER-claim user who is the seeded admin of
 * their org reach the org settings page. The lookup fails closed, and the
 * backend re-runs the identical effective-role check on every request.
 *
 * Role source preference (plan Step 1, rule 4): the effective role the
 * backend reports for the caller (`GET /auth/me` → `user.role`, derived
 * server-side from the same JWT) is used when the profile has already
 * loaded; otherwise the guard derives the role itself from the JWT via
 * `deriveRole`, which mirrors `security/roles.py` exactly. No await on the
 * profile fetch — a cold-start navigation must never block on a second
 * request, and both sources compute the same value for the same token.
 *
 * Denial target: `/forbidden` (rule 5's UI-level 403) — a page that explains
 * the dead end and offers a route every role can open, instead of silently
 * bouncing to /repositories.
 */
@Injectable({ providedIn: 'root' })
export class RoleGuard extends KeycloakAuthGuard {
  private readonly context = inject(AuthContextService);

  constructor(router: Router, keycloakAngular: KeycloakService) {
    super(router, keycloakAngular);
  }

  async isAccessAllowed(
    route: ActivatedRouteSnapshot,
    state: RouterStateSnapshot
  ): Promise<boolean | UrlTree> {
    if (!this.authenticated) {
      return this.router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
    }

    const required = (route.data?.['roles'] as string[] | undefined) ?? [];
    const parsed = this.keycloakAngular.getKeycloakInstance()?.tokenParsed;
    const viaGitHub =
      parsed != null && (parsed['githubId'] != null || parsed['githubLogin'] != null);
    const subject =
      parsed != null
        ? ((parsed['preferred_username'] ?? parsed['sub']) as string | undefined)
        : undefined;

    // Rule 4: prefer the role the backend reports (GET /auth/me); fall back
    // to deriving it from the JWT with the exact backend vocabulary. The
    // backend role goes through the same one-release compat map so a stale
    // legacy value can't widen or shrink the route list unexpectedly.
    const backendRole = this.context.backendRole();
    const effective =
      backendRole != null && backendRole !== ''
        ? COMPAT_MAP[backendRole.toUpperCase()] ?? backendRole.toUpperCase()
        : deriveRole(this.roles, viaGitHub, subject);

    if (required.length === 0 || required.includes(effective)) {
      return true;
    }

    if (isAdminRoute(required) && (await this.hasOrgAdminMembership())) {
      return true;
    }

    // Authenticated but the effective role is not allowed here (e.g. NONE
    // hitting /dashboard) — rule 5: render the forbidden page with a way
    // back, rather than silently bouncing between routes.
    return this.router.createUrlTree(['/forbidden']);
  }

  /**
   * Membership elevation (admin routes only) — any error denies access.
   * Shares AuthContext's cached `GET /orgs` result with the header org
   * switcher (first denial fetches, later navigations reuse it; an error
   * resets the cache so the next attempt retries).
   */
  private async hasOrgAdminMembership(): Promise<boolean> {
    try {
      const orgs = await this.context.ensureOrgs();
      return orgs.some(org => org.role === 'ORG_ADMIN');
    } catch {
      return false;
    }
  }
}
