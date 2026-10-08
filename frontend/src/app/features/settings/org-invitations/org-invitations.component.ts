import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiError } from '../../../core/services/api.service';
import { InvitationService } from '../../../core/services/invitation.service';
import { RepositoryService } from '../../../core/services/repository.service';
import { InvitableRole, OrgInvitation } from '../../../core/models/invitation.model';
import { Repository } from '../../../core/models/repository.model';

function messageOf(err: unknown, fallback: string): string {
  return err instanceof ApiError && err.message ? err.message : fallback;
}

/**
 * Invite form + invitation list + revoke (plan Step 12) — the ORG_ADMIN
 * half, embedded on the org settings page (which already carries the
 * ADMIN_ROLES route guard and the org picker).
 *
 * Contract mirrors Step 11: DEVELOPER/REVIEWER only (422 otherwise),
 * 20/hour/org → 429, revoke is 409 on an already-accepted row, and the
 * list NEVER carries token material — the raw link exists only in the
 * email.
 *
 * Repo-scoped extension: ONE role is picked once and applied to the
 * whole repository selection (`repository_ids`); the backend validates
 * each id against the org's GitHub App installation (400 before
 * anything is persisted) and, on accept, adds the invitee as a GitHub
 * collaborator (push for DEVELOPER, triage for REVIEWER). A stored
 * `github_error` is shown as a warning on the row — the invitation is
 * still valid, only the GitHub side failed.
 *
 * Dev note (plan Step 7 — kept here, out of the UI): with the default
 * `MAIL_BACKEND=console` no email is sent; the invite link is the
 * `mail_console to=…` line in the **backend pod log** (`kubectl logs`).
 */
@Component({
  selector: 'app-org-invitations',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './org-invitations.component.html',
  styleUrl: './org-invitations.component.scss'
})
export class OrgInvitationsComponent implements OnInit {
  /** Driven by the parent — a new org id remounts the component (see the
   * `@for … track` wrapper in the org settings template), so `ngOnInit`
   * always loads the right org. */
  readonly orgId = input.required<string>();
  readonly canManage = input(true);

  private readonly invitations = inject(InvitationService);
  private readonly repositoryService = inject(RepositoryService);

  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);
  readonly items = signal<OrgInvitation[]>([]);

  readonly email = signal('');
  readonly role = signal<InvitableRole>('DEVELOPER');
  readonly sending = signal(false);
  readonly formError = signal<string | null>(null);
  readonly sentTo = signal<string | null>(null);

  /** Repo picker (only loaded for managers — nobody else can invite). */
  readonly repos = signal<Repository[]>([]);
  readonly reposLoading = signal(false);
  readonly reposError = signal<string | null>(null);
  /** The ONE role chosen above applies to every id in here. */
  readonly repositoryIds = signal<string[]>([]);

  readonly revokingId = signal<string | null>(null);
  readonly revokeError = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
    if (this.canManage()) {
      this.loadRepos();
    }
  }

  load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.invitations.list(this.orgId()).subscribe({
      next: rows => {
        this.items.set(rows);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.loadError.set(messageOf(err, 'Could not load invitations.'));
      }
    });
  }

  loadRepos(): void {
    this.reposLoading.set(true);
    this.reposError.set(null);
    this.repositoryService.getRepositories({ page: 1, per_page: 100 }).subscribe({
      next: rows => {
        this.repos.set(rows);
        this.reposLoading.set(false);
        // Drop ids whose repository disappeared since the picker was shown.
        this.repositoryIds.update(ids => ids.filter(id => rows.some(r => r.id === id)));
      },
      error: (err: unknown) => {
        this.reposLoading.set(false);
        this.reposError.set(messageOf(err, 'Could not load repositories.'));
      }
    });
  }

  isSelected(repoId: string): boolean {
    return this.repositoryIds().includes(repoId);
  }

  toggleRepo(repoId: string): void {
    this.repositoryIds.update(ids =>
      ids.includes(repoId) ? ids.filter(id => id !== repoId) : [...ids, repoId]
    );
  }

  send(): void {
    const email = this.email().trim();
    if (!email || this.sending()) {
      return;
    }
    this.sending.set(true);
    this.formError.set(null);
    this.sentTo.set(null);
    this.invitations
      .create(this.orgId(), {
        email,
        role: this.role(),
        repository_ids: this.repositoryIds()
      })
      .subscribe({
        next: created => {
          this.sending.set(false);
          this.sentTo.set(created.email);
          this.email.set('');
          this.load(); // reflect the new row (and its expiry) from the server
        },
        error: (err: unknown) => {
          this.sending.set(false);
          this.formError.set(messageOf(err, 'Could not create the invitation.'));
        }
      });
  }

  revoke(invitation: OrgInvitation): void {
    if (this.revokingId()) {
      return;
    }
    this.revokingId.set(invitation.id);
    this.revokeError.set(null);
    this.invitations.revoke(this.orgId(), invitation.id).subscribe({
      next: () => {
        this.revokingId.set(null);
        // 204: flip the row locally instead of a full reload (revoke is
        // idempotent server-side, so this cannot disagree with the API).
        this.items.update(rows =>
          rows.map(row => (row.id === invitation.id ? { ...row, status: 'revoked' } : row))
        );
      },
      error: (err: unknown) => {
        this.revokingId.set(null);
        this.revokeError.set(messageOf(err, 'Could not revoke the invitation.'));
      }
    });
  }
}
