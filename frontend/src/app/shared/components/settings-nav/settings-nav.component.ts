import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';

/** Destination within the personal settings family (plan Step 4). */
export type SettingsNavTab = 'profile' | 'review-preferences' | 'ai';

/**
 * Personal settings sub-navigation (plan Step 4): **Profile · Review
 * preferences · AI model** — the three personal screens share it. It is
 * deliberately free of organization and platform administration links:
 * those are separate workspaces with their own navigation (Organization
 * Settings carries its own workspace nav; the platform console has its own
 * sidebar), so this nav never mixes scopes.
 *
 * These are *links*, not ARIA tabs: the destinations are separate guarded
 * routes, so `aria-current="page"` marks the active entry. All three routes
 * sit behind the same `write` capability as the settings family itself, so
 * no per-entry visibility logic is needed here.
 */
@Component({
  selector: 'app-settings-nav',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <nav class="settings-nav" aria-label="Personal settings sections" data-testid="settings-nav">
      <a
        class="nav-tab"
        routerLink="/settings/profile"
        data-testid="settings-nav-profile"
        [class.active]="active() === 'profile'"
        [attr.aria-current]="active() === 'profile' ? 'page' : null"
      >
        Profile
      </a>
      <a
        class="nav-tab"
        routerLink="/settings/review-preferences"
        data-testid="settings-nav-review-preferences"
        [class.active]="active() === 'review-preferences'"
        [attr.aria-current]="active() === 'review-preferences' ? 'page' : null"
      >
        Review preferences
      </a>
      <a
        class="nav-tab"
        routerLink="/settings/ai-model"
        data-testid="settings-nav-ai"
        [class.active]="active() === 'ai'"
        [attr.aria-current]="active() === 'ai' ? 'page' : null"
      >
        AI model
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
export class SettingsNavComponent {
  /** Which personal settings screen the host is on. */
  readonly active = input<SettingsNavTab>('profile');
}
