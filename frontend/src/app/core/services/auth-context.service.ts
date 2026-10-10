import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AuthService } from './auth.service';
import {
  OrgSettingsService,
  OrgSummary,
  canManageSettings,
  effectiveRole
} from './org-settings.service';

/**
 * App-wide auth context (plan Step 1): current user, effective role,
 * current organization (with a switcher when the user belongs to several)
 * and `can(action)` helpers shared by templates and guards.
 *
 * Role sources, in preference order (rule 4):
 * 1. the effective role returned by the backend (`GET /auth/me` →
 *    `user.role`, derived server-side from the same JWT) — preferred;
 * 2. if the profile has not loaded yet, guards fall back to deriving the
 *    role from the JWT themselves (`deriveRole` in role.guard.ts mirrors
 *    `security/roles.py` exactly, including the NONE sentinel).
 *
 * `can()` is **cosmetic** — it only shapes nav entries and action rows.
 * The backend re-checks every request; a surprise 403 renders the
 * forbidden message from the error interceptor, never a silent success.
 *
 * Capability semantics mirror the backend guards:
 * - `read`        — any authenticated context (NONE included).
 * - `write`       — NONE is unconditionally read-only (first-step check);
 *                   any other role may attempt mutations (membership is
 *                   re-checked per resource server-side).
 * - `validate`    — effective role (max(JWT, active org membership)) must
 *                   reach REVIEWER (validation endpoint guard).
 * - `org:settings`— effective role must reach ORG_ADMIN in at least one
 *                   org (the guard elevates on any membership row).
 * - `platform`    — PLATFORM_ADMIN only (global role, never elevated).
 */
export type AppCapability = 'read' | 'write' | 'validate' | 'org:settings' | 'platform';

/** localStorage key for the selected org — an id, never a token. */
const ACTIVE_ORG_KEY = 'codesage_active_org';

function normalizeRole(role: string | null | undefined): string {
  const upper = String(role ?? '').toUpperCase();
  return ['PLATFORM_ADMIN', 'ORG_ADMIN', 'REVIEWER', 'DEVELOPER', 'NONE'].includes(upper)
    ? upper
    : 'NONE';
}

@Injectable({ providedIn: 'root' })
export class AuthContextService {
  private readonly auth = inject(AuthService);
  private readonly orgsApi = inject(OrgSettingsService);

  private readonly _orgs = signal<OrgSummary[] | null>(null);
  readonly orgs = this._orgs.asReadonly();

  private readonly _activeOrgId = signal<string | null>(readStoredOrg());
  readonly activeOrgId = this._activeOrgId.asReadonly();

  /** Selected org (or the first one) — the context for org-scoped `can()`. */
  readonly activeOrg = computed<OrgSummary | null>(() => {
    const orgs = this._orgs();
    if (!orgs || orgs.length === 0) {
      return null;
    }
    return orgs.find(org => org.id === this._activeOrgId()) ?? orgs[0];
  });

  /** Role as reported by GET /auth/me — null until the profile loads. */
  readonly backendRole = computed<string | null>(() => this.auth.currentUser()?.role ?? null);

  /**
   * Effective role: max(global role from JWT, active org membership) —
   * the org-based elevation only; null while nothing elevates above NONE.
   */
  readonly effectiveRole = computed<string | null>(() => {
    const jwtRole = normalizeRole(this.backendRole());
    const activeOrgRole = this.activeOrg()?.role ?? null;
    const eff = normalizeRole(effectiveRole(jwtRole, activeOrgRole));
    return eff === 'NONE' ? null : eff;
  });

  /**
   * Get the one-release compatibility map for backward compatibility with role guards
   */
  compatMap(): Record<string, string> {
    return {
      SUPER_ADMIN: 'PLATFORM_ADMIN',
      GUEST: 'NONE',
      DEVELOPER: 'DEVELOPER'
    };
  }

  /**
   * Load the caller's orgs once (shared by the guard's admin elevation and
   * the header switcher). Errors reset the cache so the next navigation
   * retries; the promise never resolves with partial data.
   */
  private orgsPromise: Promise<OrgSummary[]> | null = null;

  ensureOrgs(): Promise<OrgSummary[]> {
    if (!this.orgsPromise) {
      this.orgsPromise = firstValueFrom(this.orgsApi.listOrgs())
        .then(orgs => {
          this._orgs.set(orgs);
          // Drop a stored selection that no longer applies (org left/renumbered).
          const stored = this._activeOrgId();
          if (orgs.length > 0 && !orgs.some(org => org.id === stored)) {
            this.setActiveOrg(orgs[0].id);
          } else if (orgs.length === 0) {
            this._activeOrgId.set(null);
          }
          return orgs;
        })
        .catch((err: unknown) => {
          this.orgsPromise = null;
          throw err;
        });
    }
    return this.orgsPromise;
  }

  setActiveOrg(orgId: string): void {
    this._activeOrgId.set(orgId);
    try {
      localStorage.setItem(ACTIVE_ORG_KEY, orgId);
    } catch {
      // Storage unavailable (private mode) — the selection just won't persist.
    }
  }

  /**
   * Drop the cached org list and the stored selection — called when the
   * signed-in account changes (`AdminLoginService.login`) so a platform
   * admin never sees the orgs/roles of whoever was signed in before.
   * The next `ensureOrgs()` refetches for the new account.
   */
  resetOrgs(): void {
    this.orgsPromise = null;
    this._orgs.set(null);
    this._activeOrgId.set(null);
    try {
      localStorage.removeItem(ACTIVE_ORG_KEY);
    } catch {
      // Storage unavailable — nothing was persisted either.
    }
  }

  /**
   * Route-level capability check with an explicit role fallback.
   *
   * The guard calls this with the effective role it resolved *itself*
   * (backend `GET /auth/me` role when the profile has loaded, otherwise
   * the role derived from the JWT) — a cold-start navigation must never
   * bounce to /forbidden just because the profile request has not
   * answered yet. Routes are not resource-scoped, so this evaluates the
   * *global* effective role against the backend's permission floors.
   * Cosmetic either way — the backend re-authorizes every request.
   */
  canCapability(action: AppCapability, role: string): boolean {
    const effective = normalizeRole(role);
    // NONE-first: an explicit read-only sentinel is never elevated by
    // membership rows — fail closed, mirroring the backend's org-access
    // rules (NONE + write → 403 no matter what org_members says).
    if (effective === 'NONE' && action !== 'read') {
      return false;
    }
    switch (action) {
      case 'read':
        return true;
      case 'write':
        // Mirrors the backend `require_developer` floor (NONE is read-only).
        return effective !== 'NONE';
      case 'validate': {
        const reaches = (role: string) =>
          role === 'REVIEWER' || role === 'ORG_ADMIN' || role === 'PLATFORM_ADMIN';
        if (reaches(effective)) {
          return true;
        }
        // Membership elevation: effective = max(JWT, active org membership)
        // (plan §2) — a DEVELOPER who is ORG_ADMIN in the active org validates.
        const orgRole = this.activeOrg()?.role ?? null;
        return orgRole != null && reaches(normalizeRole(effectiveRole(effective, orgRole)));
      }
      case 'org:settings':
        return this.canOrgSettings(effective);
      case 'platform':
        // Global-only: never derived from a membership row.
        return effective === 'PLATFORM_ADMIN';
      default:
        return false;
    }
  }

  /**
   * Org settings (route `settings/org`): ORG_ADMIN/PLATFORM_ADMIN by role,
   * or — same effective role per plan §2 — an `org_members` ORG_ADMIN row.
   * The membership list is only consulted when it has been loaded
   * (`ensureOrgs`); the guard awaits it on the deny path so a
   * DEVELOPER-JWT org owner still gets in.
   */
  canOrgSettings(effectiveRole: string): boolean {
    const role = normalizeRole(effectiveRole);
    if (role === 'ORG_ADMIN' || role === 'PLATFORM_ADMIN') {
      return true;
    }
    return (this._orgs() ?? []).some(org => canManageSettings(role, org.role));
  }

  /**
   * Cosmetic capability check for templates — the global role's server
   * flags/floors. See the class docstring for semantics.
   */
  can(action: AppCapability): boolean {
    return this.canCapability(action, this.backendRole() ?? 'NONE');
  }
}

function readStoredOrg(): string | null {
  try {
    return localStorage.getItem(ACTIVE_ORG_KEY);
  } catch {
    return null;
  }
}
