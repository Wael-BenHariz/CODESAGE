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

type NavItemId = 'dashboard' | 'users' | 'settings' | 'system' | 'logs' | 'quotas';

interface ConsoleNavItem {
  readonly id: NavItemId;
  readonly link: string;
  readonly label: string;
  /** The dashboard link is the section root — exact match only. */
  readonly exact: boolean;
}

/**
 * Platform Administration console shell (static PFE prototype) — route
 * `/platform-admin`.
 *
 * Renders its own sidebar + topbar instead of the app shell: the route
 * opts out with `data: { shell: false }` (the global chrome would show
 * navigation this console does not use) while `RoleGuard` + `PLATFORM_ROLES`
 * on the parent route keep it platform-admin-only, exactly like `/platform`.
 *
 * Everything behind it is local mock data — no service in this feature ever
 * performs an HTTP request, so the console works with the backend offline.
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

  readonly navItems: readonly ConsoleNavItem[] = [
    { id: 'dashboard', link: '/platform-admin', label: 'Dashboard', exact: true },
    { id: 'users', link: '/platform-admin/users', label: 'Utilisateurs', exact: false },
    { id: 'settings', link: '/platform-admin/settings', label: 'Paramètres', exact: false },
    { id: 'system', link: '/platform-admin/system', label: 'État du système', exact: false },
    { id: 'logs', link: '/platform-admin/logs', label: 'Journaux', exact: false },
    { id: 'quotas', link: '/platform-admin/quotas', label: 'Quotas & Utilisation', exact: false }
  ];

  readonly login = computed(() => this.auth.currentUser()?.login ?? 'Administrateur');

  readonly avatarUrl = computed(() => this.auth.currentUser()?.avatarUrl || null);

  /** Initials fallback when the session carries no avatar image. */
  readonly initials = computed(() => {
    const login = this.auth.currentUser()?.login ?? 'AD';
    return login.slice(0, 2).toUpperCase();
  });

  @ViewChild('sidebarEl') private sidebarEl?: ElementRef<HTMLElement>;
  @ViewChild('menuButton') private menuBtn?: ElementRef<HTMLButtonElement>;

  constructor() {
    // Close the mobile drawer after any navigation (like the app shell).
    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        takeUntilDestroyed()
      )
      .subscribe(() => this.navOpen.set(false));
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
