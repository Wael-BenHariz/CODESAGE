import { Component, ElementRef, computed, inject, signal, ViewChild } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AuthContextService } from '../../../core/services/auth-context.service';

/**
 * Application sidebar (plan Step 3 / role-based redesign): grouped,
 * role-aware navigation for the app shell —
 *
 * - **Main** — Dashboard (write), Repositories, Organization Repositories
 *   (≥1 org membership) and Reviews (cross-repo review history).
 * - **Personal** — Profile, Review Preferences, AI Model (write).
 * - **Organization** — Organization Settings + Members & Invitations
 *   (`org:settings`).
 * - **Platform administration** — the Platform console (`platform` only;
 *   the old duplicate `/platform-admin` alias link is gone).
 *
 * Visibility goes through `AuthContextService.can()` only — cosmetic, the
 * backend re-authorizes every request. The shell closes the mobile drawer
 * on NavigationEnd, so links need no click plumbing (keyboard activation
 * comes free with routerLink). The org entries highlight from the live URL
 * (`?view=members` vs the settings panel) because routerLinkActive cannot
 * tell query params apart.
 */
@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss'
})
export class SidebarComponent {
  readonly ctx = inject(AuthContextService);
  private readonly router = inject(Router);

  /**
   * Organization Repositories is meaningful only for members of at least
   * one organization (`GET /orgs`) — never derived from a global role
   * alone (a REVIEWER claim without a membership shares nothing, and
   * memberships are exactly what invitations grant). Cosmetic: the page
   * and its data re-authorize server-side.
   */
  readonly hasOrg = computed(() => (this.ctx.orgs() ?? []).length > 0);

  /** Which `/settings/org?view=` panel is active ('organization' default). */
  readonly orgView = signal<'organization' | 'members'>('organization');

  constructor() {
    // Fire-and-forget: the org list is memoized, so this never duplicates
    // a fetch already kicked off by the org-settings guard.
    void this.ctx.ensureOrgs().catch(() => undefined);

    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationEnd) {
        this.orgView.set(
          event.urlAfterRedirects.includes('view=members') ? 'members' : 'organization'
        );
      }
    });
  }

  @ViewChild('asideEl') private asideEl?: ElementRef<HTMLElement>;

  /** Keyboard support: the shell focuses the drawer when it opens. */
  focusHost(): void {
    this.asideEl?.nativeElement.focus();
  }

  /** Cosmetic capability check — see AuthContextService for semantics. */
  can(action: Parameters<AuthContextService['can']>[0]): boolean {
    return this.ctx.can(action);
  }
}
