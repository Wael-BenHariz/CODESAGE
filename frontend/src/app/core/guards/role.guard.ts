import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { KeycloakAuthGuard, KeycloakService } from 'keycloak-angular';

/**
 * Map the roles carried by the Keycloak JWT to the single app role used for
 * route access.
 *
 * Mirrors the backend's `derive_role` (app/security/roles.py) exactly:
 * precedence SUPER_ADMIN > GUEST > DEVELOPER; no recognized role → DEVELOPER
 * (the realm is invite-only — GUEST is an explicit restriction, not the
 * anonymous default). Keeping both sides identical prevents a redirect loop
 * where the frontend allows a user the backend 403s, or vice versa.
 */
export function deriveRole(tokenRoles: readonly string[]): string {
  const roles = new Set(tokenRoles.map(role => String(role).toUpperCase()));
  if (roles.has('SUPER_ADMIN')) {
    return 'SUPER_ADMIN';
  }
  if (roles.has('GUEST')) {
    return 'GUEST';
  }
  return 'DEVELOPER';
}

/**
 * Route guard: requires a Keycloak session and (when the route declares
 * `data.roles`) an effective role among them. Role lists are set per route in
 * app.routes.ts.
 */
@Injectable({ providedIn: 'root' })
export class RoleGuard extends KeycloakAuthGuard {
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
    if (required.length === 0 || required.includes(deriveRole(this.roles))) {
      return true;
    }

    // Authenticated but the effective role is not allowed here (e.g. GUEST
    // hitting /dashboard) — fall back to the read-only home every role can
    // open instead of bouncing between restricted routes.
    return this.router.createUrlTree(['/repositories']);
  }
}
