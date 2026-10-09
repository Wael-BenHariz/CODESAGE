import { Injectable, inject } from '@angular/core';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { KeycloakAuthGuard, KeycloakService } from 'keycloak-angular';

import { AppCapability, AuthContextService } from '../services/auth-context.service';

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
 * Map the roles carried by the Keycloak JWT to the effective global role.
 *
 * Mirrors the backend's `derive_role` (app/security/roles.py) exactly:
 * 1. claims pass through the one-release compat map (SUPER_ADMIN ->
 *    PLATFORM_ADMIN, GUEST -> NONE); new names pass through unchanged;
 * 2. precedence PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER > NONE —
 *    an explicit legacy read-only claim (GUEST -> NONE) is treated as the
 *    lowest rank (fail-closed: an explicit downgrade is honored but still
 *    below DEVELOPER);
 * 3. no recognized or legacy claim at all -> the GitHub-brokered signup
 *    default ORG_ADMIN (a GitHub session starts as admin of the personal
 *    workspace first login creates), otherwise NONE (fail-closed) — an
 *    explicit claim always outranks the default.
 *
 * A token with no role claim at all never gets this far — the backend
 * rejects it with a 401 before any role list is consulted. Keeping both
 * sides identical prevents a redirect loop where the frontend allows a
 * user the backend 403s, or vice versa.
 *
 * `viaGitHub` / `subject` are kept for call-site parity with the backend
 * signature (the brokered default exists on both sides; the F1 DEVELOPER
 * fallback stays removed).
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
  for (const role of ['ORG_ADMIN', 'REVIEWER', 'DEVELOPER']) {
    if (mapped.has(role)) {
      return role;
    }
  }
  if (mapped.has('NONE')) {
    return 'NONE';
  }

  // No recognized or legacy claim at all: the GitHub-brokered signup
  // default is ORG_ADMIN (mirrors the backend); every other session
  // fails closed to NONE. An explicit claim above outranks the default
  // — the GUEST/NONE branch already returned. (The historical F1
  // DEVELOPER broker fallback stays removed.)
  if (viaGitHub) {
    void subject;
    return 'ORG_ADMIN';
  }
  void viaGitHub;
  void subject;
  return 'NONE';
}

/**
 * Cosmetic capability flags for header/nav entries, derived from the
 * effective role (the backend stays authoritative). Roles are normalized
 * through the same compat map as `deriveRole`; an unknown or missing role
 * fails closed (NONE -> no write/admin entries visible). The two booleans
 * mirror the backend permission lists `TRIGGER_ROLES` (write) and
 * `REPO_ADMIN_ROLES` (admin).
 */
export function navVisibility(role: string | null | undefined): {
  write: boolean;
  admin: boolean;
} {
  const upper = (role ?? '').toUpperCase();
  const effective = COMPAT_MAP[upper] ?? upper;
  const known = ['PLATFORM_ADMIN', 'ORG_ADMIN', 'REVIEWER', 'DEVELOPER', 'NONE'].includes(
    effective
  );
  const normalized = known ? effective : 'NONE';
  return {
    write: normalized !== 'NONE',
    admin: normalized === 'ORG_ADMIN' || normalized === 'PLATFORM_ADMIN'
  };
}

/**
 * Route guard: requires a Keycloak session and (when the route declares
 * `data.capabilities`) every listed capability of the caller's effective
 * role — checked against `AuthContextService.canCapability`, which
 * evaluates the backend's permission floors (view/trigger/request/review/
 * repo_config/repo_admin/platform, §2.3). Capability lists replace the
 * old role lists (ANY_ROLE / WRITE_ROLES / ADMIN_ROLES): routes name what
 * they need, never which roles may see them.
 *
 * Role source (plan Step 1, rule 4): the effective role the backend
 * reports for the caller (`GET /auth/me` → `user.role`) when the profile
 * has loaded; otherwise the role derived from the JWT by `deriveRole`,
 * which mirrors `security/roles.py` exactly. No await on the profile
 * fetch — a cold-start navigation must never block on a second request,
 * and both sources compute the same value for the same token.
 *
 * `org:settings` gets one extra step: when the role alone does not
 * qualify, the guard awaits `GET /orgs` (membership elevation, plan §2
 * effective role = max(JWT, org_members.role)) so a DEVELOPER-claim org
 * owner reaches the org settings page. The lookup fails closed, and the
 * backend re-runs the identical check on every request.
 *
 * Denial target: `/forbidden` (rule 5's UI-level 403) — a page that
 * explains the dead end and offers a route every role can open, instead
 * of silently bouncing to /repositories.
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

    const required = (route.data?.['capabilities'] as AppCapability[] | undefined) ?? [];
    if (required.length === 0) {
      return true;
    }

    const parsed = this.keycloakAngular.getKeycloakInstance()?.tokenParsed;
    const viaGitHub =
      parsed != null &&
      (parsed['githubId'] != null ||
        parsed['githubLogin'] != null ||
        // Realm export renamed the mapper to snake_case (see
        // docs/keycloak-changes.md) — accept both spellings.
        parsed['github_login'] != null);
    const subject =
      parsed != null
        ? ((parsed['preferred_username'] ?? parsed['sub']) as string | undefined)
        : undefined;

    // Rule 4: prefer the role the backend reports (GET /auth/me); fall back
    // to deriving it from the JWT with the exact backend vocabulary. The
    // backend role goes through the same one-release compat map so a stale
    // legacy value can't widen or shrink the capability check unexpectedly.
    const backendRole = this.context.backendRole();
    const effective =
      backendRole != null && backendRole !== ''
        ? this.context.compatMap()[backendRole.toUpperCase()] ?? backendRole.toUpperCase()
        : deriveRole(this.roles, viaGitHub, subject);

    for (const capability of required) {
      if (this.context.canCapability(capability, effective)) {
        continue;
      }
      // Membership elevation for org settings (first miss only): the org
      // list may simply not be loaded yet — fetch it, then re-check once.
      if (capability === 'org:settings') {
        try {
          await this.context.ensureOrgs();
        } catch {
          /* fail closed */
        }
        if (this.context.canCapability(capability, effective)) {
          continue;
        }
      }
      return this.router.createUrlTree(['/forbidden']);
    }

    return true;
  }
}
