import {
  Component,
  ElementRef,
  HostListener,
  ViewChild,
  computed,
  inject,
  signal
} from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AuthService } from '../../../core/services/auth.service';

type NavItemId = 'overview' | 'dashboard' | 'users' | 'settings' | 'system' | 'logs' | 'quotas';

interface ConsoleNavItem {
  readonly id: NavItemId;
  readonly link: string;
  readonly label: string;
  /** The overview link is the section root — exact match only. */
  readonly exact: boolean;
}

/**
 * Platform Administration console shell — route `/platform`.
 *
 * Renders its own sidebar + topbar instead of the app shell: the route
 * opts out with `data: { shell: false }` (the global chrome would show
 * navigation this console does not use) while `RoleGuard` + the `platform`
 * capability on the parent route keep it platform-admin-only.
 *
 * Two kinds of pages live here, labelled differently on purpose:
 * - **Overview** (`/platform`) — the real, API-backed read-only view
 *   (`GET /users`, `GET /orgs`);
 * - everything else — the static **PFE prototype** screens (local mock
 *   data; no service in this feature ever performs an HTTP request). The
 *   shell shows them an honest "prototype" banner: their controls mutate
 *   local state only and never change the production system.
 *
 * Mobile ≤768 px: the sidebar becomes a drawer driven by the topbar toggle;
 * Escape or the backdrop closes it, and navigation closes it too (the
 * NavigationEnd subscription below, mirroring the app shell).
 */
@Component({
  selector: 'app-platform-admin-console',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './platform-admin-console.component.html'
})
export class PlatformAdminConsoleComponent {
  private readonly router = inject(Router);
  readonly auth = inject(AuthService);

  readonly navOpen = signal(false);

  /** True on the six mock pages (everything except the real overview). */
  readonly prototypePage = signal(false);

  readonly navItems: readonly ConsoleNavItem[] = [
    { id: 'overview', link: '/platform', label: 'Overview', exact: true },
    { id: 'dashboard', link: '/platform/dashboard', label: 'Dashboard', exact: false },
    { id: 'users', link: '/platform/users', label: 'Users', exact: false },
    { id: 'settings', link: '/platform/settings', label: 'Global Settings', exact: false },
    { id: 'system', link: '/platform/system', label: 'System Monitoring', exact: false },
    { id: 'logs', link: '/platform/logs', label: 'System Logs', exact: false },
    { id: 'quotas', link: '/platform/quotas', label: 'Quotas & Configuration', exact: false }
  ];

  readonly login = computed(() => this.auth.currentUser()?.login ?? 'Administrator');

  readonly avatarUrl = computed(() => this.auth.currentUser()?.avatarUrl || null);

  /** Initials fallback when the session carries no avatar image. */
  readonly initials = computed(() => {
    const login = this.auth.currentUser()?.login ?? 'PA';
    return login.slice(0, 2).toUpperCase();
  });

  @ViewChild('sidebarEl') private sidebarEl?: ElementRef<HTMLElement>;
  @ViewChild('menuButton') private menuBtn?: ElementRef<HTMLButtonElement>;

  constructor() {
    // Close the mobile drawer after any navigation (like the app shell) and
    // recompute which page kind is active (real overview vs prototype).
    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        takeUntilDestroyed()
      )
      .subscribe(event => {
        this.navOpen.set(false);
        const path = event.urlAfterRedirects.split('?')[0];
        this.prototypePage.set(path !== '/platform');
      });
  }

  toggleNav(): void {
    const open = !this.navOpen();
    this.navOpen.set(open);
    if (open) {
      // Move focus into the drawer so keyboard users land in the nav.
      setTimeout(() => this.sidebarEl?.nativeElement.focus());
    }
  }

  closeNav(): void {
    if (this.navOpen()) {
      this.navOpen.set(false);
      this.menuBtn?.nativeElement.focus();
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.closeNav();
  }

  logout(): void {
    this.auth.logout();
  }
}
