import { CommonModule } from '@angular/common';
import {
  Component,
  computed,
  ElementRef,
  EventEmitter,
  HostListener,
  inject,
  input,
  OnInit,
  Output,
  signal,
  ViewChild
} from '@angular/core';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { filter } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AuthService } from '../../../core/services/auth.service';
import { AuthContextService } from '../../../core/services/auth-context.service';
import { NotificationService } from '../../../core/services/notification.service';
import { AppNotification } from '../../../core/models/notification.model';
import { OrgSummary, effectiveRole } from '../../../core/services/org-settings.service';

interface Crumb {
  label: string;
  link?: string[];
}

/**
 * Application top bar (plan Step 3): mobile nav toggle, breadcrumbs,
 * the org switcher (when the caller belongs to >1 org) and the user menu
 * (login, effective-role badge, Switch Account, Logout).
 *
 * Carries the retired site-header's `data-testid="site-header"` so any
 * caller/test written against it keeps finding the header element.
 * All role checks go through `AuthContextService.can()` — cosmetic only.
 */
@Component({
  selector: 'app-topbar',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './topbar.component.html',
  styleUrl: './topbar.component.scss'
})
export class TopbarComponent implements OnInit {
  readonly auth = inject(AuthService);
  readonly ctx = inject(AuthContextService);
  private readonly router = inject(Router);
  private readonly notificationsApi = inject(NotificationService);

  /** Whether the mobile drawer is currently open (drives aria-expanded). */
  readonly navOpen = input(false);

  @Output() toggleNav = new EventEmitter<void>();

  readonly crumbs = signal<Crumb[]>([]);

  @ViewChild('menuButton') private menuBtn?: ElementRef<HTMLButtonElement>;

  /** Keyboard support: the shell returns focus here when the drawer closes. */
  focusMenuButton(): void {
    this.menuBtn?.nativeElement.focus();
  }

  constructor() {
    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        takeUntilDestroyed()
      )
      .subscribe(() => this.crumbs.set(this.buildCrumbs(this.router.url)));
  }

  ngOnInit(): void {
    this.crumbs.set(this.buildCrumbs(this.router.url));
    // Load orgs for the switcher (shared with the guard's admin elevation).
    // Fire-and-forget: an org-list failure must never break the top bar —
    // nav and user menu still render from the JWT-derived context.
    void this.ctx.ensureOrgs().catch(() => undefined);
    // Same isolation for notifications — the bell simply shows no badge.
    if (this.auth.currentUser()) {
      this.loadNotifications();
    }
  }

  get orgs(): OrgSummary[] {
    return this.ctx.orgs() ?? [];
  }

  get activeOrgId(): string | null {
    return this.ctx.activeOrg()?.id ?? null;
  }

  /** Effective role = max(JWT, active org membership); null without session. */
  readonly roleBadge = computed<string | null>(() => {
    const user = this.auth.currentUser();
    if (!user) return null;
    return effectiveRole(user.role, this.ctx.activeOrg()?.role ?? null);
  });

  /** Get the user's workspaces */
  get workspaces() {
    return this.ctx.workspaces() ?? [];
  }

  /** Get the active workspace ID */
  get activeWorkspaceId(): string | null {
    return this.ctx.activeWorkspaceId() ?? null;
  }

  /** Get the active workspace */
  get activeWorkspace() {
    return this.ctx.activeWorkspace();
  }

  // --- Notifications (bell dropdown) ----------------------------------------

  readonly notifications = signal<AppNotification[]>([]);
  readonly notificationsOpen = signal(false);
  readonly notificationsLoading = signal(false);
  readonly notificationsError = signal<string | null>(null);

  readonly unreadCount = computed(
    () => this.notifications().filter(notification => !notification.is_read).length
  );

  toggleNotifications(): void {
    const open = !this.notificationsOpen();
    this.notificationsOpen.set(open);
    if (open) {
      this.loadNotifications();
    }
  }

  /** Escape closes the panel (the toggle button itself handles focus). */
  @HostListener('document:keydown.escape')
  closeNotifications(): void {
    this.notificationsOpen.set(false);
  }

  loadNotifications(): void {
    this.notificationsLoading.set(true);
    this.notificationsError.set(null);
    this.notificationsApi.list({ limit: 15 }).subscribe({
      next: list => {
        this.notifications.set(list);
        this.notificationsLoading.set(false);
      },
      error: () => {
        this.notificationsLoading.set(false);
        this.notificationsError.set('Could not load notifications.');
      }
    });
  }

  /** Mark one notification read (cosmetic panel — failures stay silent). */
  markNotificationRead(notification: AppNotification): void {
    if (notification.is_read) {
      return;
    }
    this.notificationsApi.markRead(notification.id).subscribe({
      next: updated =>
        this.notifications.update(list =>
          list.map(existing => (existing.id === updated.id ? updated : existing))
        ),
      error: () => undefined
    });
  }

  markAllNotificationsRead(): void {
    this.notificationsApi.markAllRead().subscribe({
      next: () => this.loadNotifications(),
      error: () => undefined
    });
  }

  switchOrg(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    if (value) {
      this.ctx.setActiveOrg(value);
    }
  }

  switchWorkspace(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    if (value) {
      this.ctx.setActiveWorkspace(value);
      // Reload the current page to reflect the new workspace context
      window.location.reload();
    }
  }

  logout(): void {
    this.auth.logout();
  }

  switchAccount(): void {
    this.auth.switchAccount();
  }

  /**
   * Breadcrumbs from the current URL (presentation only — labels mirror
   * the route table; unknown segments render verbatim, never invented).
   */
  private buildCrumbs(url: string): Crumb[] {
    const path = decodeURIComponent(url.split('?')[0]);
    const segs = path.split('/').filter(Boolean);
    if (segs.length === 0) return [];

    if (segs[0] === 'repositories') {
      const crumbs: Crumb[] = [{ label: 'Repositories', link: ['/repositories'] }];
      if (segs.length >= 3) {
        const repoLink = ['/repositories', segs[1], segs[2]];
        crumbs.push({ label: `${segs[1]}/${segs[2]}`, link: repoLink });
        if (segs[3] === 'pulls') {
          const pullsLink = [...repoLink, 'pulls'];
          crumbs.push({ label: 'Pull requests', link: pullsLink });
          if (segs[4]) {
            crumbs.push({ label: `#${segs[4]}` });
          }
        }
      }
      return crumbs;
    }

    if (segs[0] === 'settings') {
      const crumbs: Crumb[] = [{ label: 'Settings', link: ['/settings'] }];
      if (segs[1] === 'org') {
        crumbs.push({ label: 'Organization', link: ['/settings', 'org'] });
      }
      if (segs[1] === 'workspaces') {
        crumbs.push({ label: 'Workspaces', link: ['/settings', 'workspaces'] });
      }
      return crumbs;
    }

    const labels: Record<string, string> = {
      dashboard: 'Dashboard',
      platform: 'Platform',
      help: 'Help'
    };
    return [{ label: labels[segs[0]] ?? segs[0] }];
  }
}
