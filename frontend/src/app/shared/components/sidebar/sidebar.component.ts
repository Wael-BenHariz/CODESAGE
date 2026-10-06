import { Component, ElementRef, inject, ViewChild } from '@angular/core';
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
