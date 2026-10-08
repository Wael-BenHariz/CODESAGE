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
 * - `platform`    — PLATFORM_ADMIN only.
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

  /** Cosmetic capability check — see the class docstring for semantics. */
  can(action: AppCapability): boolean {
    const jwt = normalizeRole(this.backendRole());
    if (jwt === 'NONE') {
      // NONE-first: an explicit read-only sentinel outranks everything.
      return action === 'read';
    }
    const activeOrgRole = this.activeOrg()?.role ?? null;

    switch (action) {
      case 'read':
        return true;
      case 'write':
        return true; // jwt is a write role (NONE already returned above)
      case 'validate': {
        const eff = normalizeRole(effectiveRole(jwt, activeOrgRole));
        return eff === 'REVIEWER' || eff === 'ORG_ADMIN' || eff === 'PLATFORM_ADMIN';
      }
      case 'org:settings':
        // Admin nav entry mirrors the guard: ANY org membership elevates.
        return (
          canManageSettings(jwt, activeOrgRole) ||
          (this._orgs() ?? []).some(org => canManageSettings(jwt, org.role))
        );
      case 'platform':
        return normalizeRole(jwt) === 'PLATFORM_ADMIN';
    }
  }
}

function readStoredOrg(): string | null {
  try {
    return localStorage.getItem(ACTIVE_ORG_KEY);
  } catch {
    return null;
  }
}
