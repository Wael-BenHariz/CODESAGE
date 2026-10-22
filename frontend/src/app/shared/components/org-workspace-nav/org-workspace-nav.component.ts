import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';

/** Destination within the organization administration workspace (plan Step 5). */
export type OrgWorkspaceTab = 'overview' | 'organization' | 'members';

/**
 * Organization administration sub-navigation (plan Step 5): **Overview ·
 * Settings · Members & invitations** — the three panels of the org
 * workspace, selected by `/settings/org?view=` (no new routes; the guard
 * and the backend re-authorization stay exactly as they are).
 *
 * Every entry maps to a panel backed by real endpoints (`GET /orgs`,
 * `GET /orgs/{id}/settings`, `GET/POST/DELETE /orgs/{id}/invitations`).
 * Panels the backend cannot support (workspaces — removed in v0.6.0,
 * audit logs, statistics) are deliberately absent rather than stubbed.
 *
 * Like the personal settings nav these are *links*, not ARIA tabs
 * (`aria-current="page"` marks the active destination).
 */
@Component({
  selector: 'app-org-workspace-nav',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <nav
      class="settings-nav"
      aria-label="Organization administration sections"
      data-testid="org-workspace-nav"
    >
      <a
        class="nav-tab"
        routerLink="/settings/org"
        [queryParams]="{ view: 'overview' }"
        data-testid="org-nav-overview"
        [class.active]="active() === 'overview'"
        [attr.aria-current]="active() === 'overview' ? 'page' : null"
      >
        Overview
      </a>
      <a
        class="nav-tab"
        routerLink="/settings/org"
        [queryParams]="{ view: 'organization' }"
        data-testid="org-nav-settings"
        [class.active]="active() === 'organization'"
        [attr.aria-current]="active() === 'organization' ? 'page' : null"
      >
        Settings
      </a>
      <a
        class="nav-tab"
        routerLink="/settings/org"
        [queryParams]="{ view: 'members' }"
        data-testid="org-nav-members"
        [class.active]="active() === 'members'"
        [attr.aria-current]="active() === 'members' ? 'page' : null"
      >
        Members & invitations
      </a>
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
export class OrgWorkspaceNavComponent {
  /** Which organization panel the host screen is on. */
  readonly active = input<OrgWorkspaceTab>('organization');
}
