import { ChangeDetectionStrategy, Component, OnInit, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../../core/services/auth.service';
import { OrgSettingsService, canManageSettings } from '../../../core/services/org-settings.service';

/** Destination within the settings family (plan §4.4). */
export type SettingsNavTab = 'ai' | 'organization' | 'members' | 'platform';

/**
 * Settings sub-navigation shared by /settings, /settings/org and /platform
 * (plan §4.4): **AI model · Organization · Members & invitations · Platform**
 * — deliberately no new routes; `/settings/org?view=members` picks the panel.
 *
 * These are *links*, not ARIA tabs: two of the four destinations are separate
 * guarded routes, so `aria-current="page"` marks the active entry. Visibility
 * mirrors the route guards (`ADMIN_ROLES` / `PLATFORM_ROLES`): an entry the
 * caller could never open is omitted instead of rendering a dead end — the
 * same cosmetic-capability rule as the sidebar, and the backend re-checks
 * every request regardless.
 */
@Component({
  selector: 'app-settings-nav',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <nav class="settings-nav" aria-label="Settings sections" data-testid="settings-nav">
      <a
        class="nav-tab"
        routerLink="/settings"
        data-testid="settings-nav-ai"
        [class.active]="active() === 'ai'"
        [attr.aria-current]="active() === 'ai' ? 'page' : null"
      >
        AI model
      </a>
      @if (canOrg()) {
        <a
          class="nav-tab"
          routerLink="/settings/org"
          [queryParams]="{ view: 'organization' }"
          data-testid="settings-nav-organization"
          [class.active]="active() === 'organization'"
          [attr.aria-current]="active() === 'organization' ? 'page' : null"
        >
          Organization
        </a>
        <a
          class="nav-tab"
          routerLink="/settings/org"
          [queryParams]="{ view: 'members' }"
          data-testid="settings-nav-members"
          [class.active]="active() === 'members'"
          [attr.aria-current]="active() === 'members' ? 'page' : null"
        >
          Members &amp; invitations
        </a>
      }
      @if (canPlatform()) {
        <a
          class="nav-tab"
          routerLink="/platform"
          data-testid="settings-nav-platform"
          [class.active]="active() === 'platform'"
          [attr.aria-current]="active() === 'platform' ? 'page' : null"
        >
          Platform
        </a>
      }
    </nav>
  `,
  styles: [
    `
      .settings-nav {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-1);
        margin-bottom: var(--space-5);
        border-bottom: 1px solid var(--border-subtle);
      }
      .nav-tab {
        font-size: var(--font-size-sm);
        font-weight: var(--font-weight-medium);
        color: var(--text-2);
        text-decoration: none;
        padding: var(--space-2) var(--space-3);
        margin-bottom: -1px;
        border-bottom: 2px solid transparent;
        transition: color var(--motion-fast) var(--motion-ease);
      }
      .nav-tab:hover {
        color: var(--text-1);
      }
      .nav-tab.active {
        color: var(--text-1);
        border-bottom-color: var(--accent);
      }
      .nav-tab:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: -2px;
        border-radius: var(--radius-xs);
      }
    `
  ]
})
export class SettingsNavComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly orgsApi = inject(OrgSettingsService);

  /** Which destination the host screen is on. */
  readonly active = input<SettingsNavTab>('ai');

  /** Org entries — JWT ≥ ORG_ADMIN or an admin membership (fail-closed). */
  readonly canOrg = signal(false);
  /** Platform entry — PLATFORM_ADMIN only. */
  readonly canPlatform = signal(false);

  ngOnInit(): void {
    this.recompute();
  }

  /**
   * Mirrors `AuthContextService.can('org:settings')` semantics but against a
   * fresh `listOrgs()` call, so each host screen decides from live data
   * instead of a cached org list. Fail-closed: an error keeps the entries
   * hidden.
   */
  private recompute(): void {
    const jwt = this.auth.currentUser()?.role ?? null;
    this.canPlatform.set(String(jwt ?? '').toUpperCase() === 'PLATFORM_ADMIN');
    if (canManageSettings(jwt, null)) {
      // The JWT alone already reaches ORG_ADMIN (same as ADMIN_ROLES).
      this.canOrg.set(true);
      return;
    }
    this.orgsApi.listOrgs().subscribe({
      next: orgs => this.canOrg.set(orgs.some(org => canManageSettings(jwt, org.role))),
      error: () => this.canOrg.set(false)
    });
  }
}
