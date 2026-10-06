import { Component, computed, inject, signal, ViewChild } from '@angular/core';
import { HostListener } from '@angular/core';
import { ActivatedRouteSnapshot, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AuthService } from './core/services/auth.service';
import { SidebarComponent } from './shared/components/sidebar/sidebar.component';
import { TopbarComponent } from './shared/components/topbar/topbar.component';
import { ToastContainerComponent } from './shared/components/toast/toast-container.component';

/**
 * App shell (plan Step 3): skip link + sidebar + top bar + routed content,
 * one single `<router-outlet>` that never moves (chrome toggles around it,
 * so a session change can never orphan the activated route component).
 *
 * The shell renders when the matched route does not opt out
 * (`data: { shell: false }` on public screens) AND a session profile
 * exists. Mobile ≤768 px: the sidebar becomes a drawer driven by the
 * top bar's toggle; Escape or the backdrop closes it.
 */
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, SidebarComponent, TopbarComponent, ToastContainerComponent],
  template: `
    <div class="frame" [class.with-shell]="showShell()">
      @if (showShell()) {
        <a class="skip-link" href="#main-content">Skip to main content</a>
        <app-sidebar #sidebar [class.open]="mobileNavOpen()" />
        @if (mobileNavOpen()) {
          <button
            type="button"
            class="backdrop"
            aria-label="Close navigation"
            (click)="closeNav()"
          ></button>
        }
      }
      <div class="col">
        @if (showShell()) {
          <app-topbar [navOpen]="mobileNavOpen()" (toggleNav)="toggleNav()" />
        }
        <main id="main-content" class="content" [class.bare]="!showShell()" tabindex="-1">
          <router-outlet />
        </main>
      </div>
    </div>
    <app-toast-container />
  `,
  styles: [
    `
      :host {
        display: block;
        min-height: 100vh;
      }
      .frame {
        display: flex;
        min-height: 100vh;
      }
      .col {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
      }
      .content {
        flex: 1;
      }
      .skip-link {
        position: absolute;
        left: -9999px;
        top: 0;
        z-index: var(--z-toast);
        padding: var(--space-2) var(--space-4);
        background: var(--accent);
        color: var(--text-inverse);
        font-family: var(--font-mono);
        font-size: var(--font-size-sm);
        border-radius: 0 0 var(--radius-sm) 0;
      }
      .skip-link:focus {
        left: 0;
      }
      .backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.6);
        z-index: calc(var(--z-drawer) - 1);
      }
    `
  ]
})
export class AppComponent {
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);

  readonly mobileNavOpen = signal(false);

  /** Whether the matched route opts out of the shell (`shell: false`). */
  private readonly shellFlag = signal(true);

  readonly showShell = computed(() => this.shellFlag() && this.auth.currentUser() !== null);

  @ViewChild('sidebar') private sidebar?: SidebarComponent;
  @ViewChild(TopbarComponent) private topbar?: TopbarComponent;

  constructor() {
    this.syncShellFlag();
    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        takeUntilDestroyed()
      )
      .subscribe(() => {
        this.syncShellFlag();
        this.mobileNavOpen.set(false);
      });
  }

  toggleNav(): void {
    const open = !this.mobileNavOpen();
    this.mobileNavOpen.set(open);
    if (open) {
      // Move focus into the drawer so keyboard users land in the nav.
      setTimeout(() => this.sidebar?.focusHost());
    }
  }

  closeNav(): void {
    if (this.mobileNavOpen()) {
      this.mobileNavOpen.set(false);
      this.topbar?.focusMenuButton();
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.closeNav();
  }

  private syncShellFlag(): void {
    let flag = true;
    let route: ActivatedRouteSnapshot | null = this.router.routerState.snapshot.root;
    while (route) {
      if (route.data && 'shell' in route.data) {
        flag = route.data['shell'] !== false;
      }
      route = route.firstChild;
    }
    this.shellFlag.set(flag);
  }
}
