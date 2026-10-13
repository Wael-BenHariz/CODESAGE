import { Component, ElementRef, computed, inject, ViewChild } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

import { AuthContextService } from '../../../core/services/auth-context.service';

/**
 * Application sidebar (plan Step 3): role-aware navigation for the app
 * shell. Visibility goes through `AuthContextService.can()` only —
 * cosmetic, the backend re-authorizes every request. The shell closes the
 * mobile drawer on NavigationEnd, so links need no click plumbing
 * (keyboard activation comes free with routerLink).
 *
 * Shared copy with the retired site-header is kept verbatim
 * (Dashboard / Repositories / Settings / Organization / Platform and the
 * `nav-*` data-testids).
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

  /**
   * Organization Repositories is meaningful only for members of at least
   * one organization (`GET /orgs`) — never derived from a global role
   * alone (a REVIEWER claim without a membership shares nothing, and
   * memberships are exactly what invitations grant). Cosmetic: the page
   * and its data re-authorize server-side.
   */
  readonly hasOrg = computed(() => (this.ctx.orgs() ?? []).length > 0);

  constructor() {
    // Fire-and-forget: the org list is memoized, so this never duplicates
    // a fetch already kicked off by the org-settings guard.
    void this.ctx.ensureOrgs().catch(() => undefined);
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
