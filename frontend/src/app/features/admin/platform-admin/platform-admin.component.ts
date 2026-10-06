import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';

import { PlatformUser } from '../../../core/models/user.model';
import { OrgSettingsService, OrgSummary } from '../../../core/services/org-settings.service';
import { UserService } from '../../../core/services/user.service';
import { SettingsNavComponent } from '../../../shared/components/settings-nav/settings-nav.component';

type PanelState = 'loading' | 'error' | 'ready';

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/**
 * PLATFORM_ADMIN overview (plan Step 9) — route `/platform`.
 *
 * Strictly read-only, by design:
 * - `GET /users` / `GET /users/{id}` are PLATFORM_ADMIN **reads** — there is
 *   no cross-user update/suspend route (docs/BACKEND_GAPS_FOR_UI.md §2), so
 *   no edit controls exist here (read-only "unless an update endpoint
 *   exists");
 * - the organizations panel uses `GET /orgs`, which for a platform admin
 *   returns *every* org (F2 read bypass); no org-members endpoint exists
 *   (§1) — the members list is omitted, not stubbed.
 *
 * Role names render verbatim from the backend's realm-role vocabulary; the
 * route guard restricts the screen to PLATFORM_ADMIN and the backend
 * re-authorizes every request regardless.
 */
@Component({
  selector: 'app-platform-admin',
  standalone: true,
  imports: [CommonModule, SettingsNavComponent],
  templateUrl: './platform-admin.component.html',
  styleUrl: './platform-admin.component.scss'
})
export class PlatformAdminComponent implements OnInit {
  private readonly usersApi = inject(UserService);
  private readonly orgsApi = inject(OrgSettingsService);

  readonly perPage = 20;

  readonly users = signal<PlatformUser[]>([]);
  readonly page = signal(1);
  readonly pages = signal(1);
  readonly total = signal(0);
  readonly usersState = signal<PanelState>('loading');
  readonly usersError = signal<string | null>(null);

  readonly orgs = signal<OrgSummary[]>([]);
  readonly orgsState = signal<PanelState>('loading');
  readonly orgsError = signal<string | null>(null);

  ngOnInit(): void {
    this.loadUsers();
    this.loadOrgs();
  }

  loadUsers(): void {
    this.usersState.set('loading');
    this.usersError.set(null);
    this.usersApi.listUsers(this.page(), this.perPage).subscribe({
      next: list => {
        this.users.set(list.items);
        this.page.set(list.page);
        this.pages.set(Math.max(list.pages, 1));
        this.total.set(list.total);
        this.usersState.set('ready');
      },
      error: err => {
        this.usersError.set(errorMessage(err, 'Could not load users.'));
        this.usersState.set('error');
      }
    });
  }

  prevPage(): void {
    if (this.page() > 1) {
      this.page.update(p => p - 1);
      this.loadUsers();
    }
  }

  nextPage(): void {
    if (this.page() < this.pages()) {
      this.page.update(p => p + 1);
      this.loadUsers();
    }
  }

  loadOrgs(): void {
    this.orgsState.set('loading');
    this.orgsError.set(null);
    this.orgsApi.listOrgs().subscribe({
      next: orgs => {
        this.orgs.set(orgs);
        this.orgsState.set('ready');
      },
      error: err => {
        this.orgsError.set(errorMessage(err, 'Could not load organizations.'));
        this.orgsState.set('error');
      }
    });
  }
}
