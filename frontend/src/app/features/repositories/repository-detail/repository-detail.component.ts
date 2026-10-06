import { Component, OnInit, computed, inject, signal, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { RepositoryService } from '../../../core/services/repository.service';
import { ToastService } from '../../../core/services/toast.service';
import { navVisibility } from '../../../core/guards/role.guard';
import { RepositoryDetail } from '../../../core/models/repository.model';
import { TabsComponent, TabDef } from '../../../shared/components/tabs/tabs.component';
import { SpinnerComponent } from '../../../shared/components/spinner/spinner.component';
import { ErrorStateComponent } from '../../../shared/components/error-state/error-state.component';
import { PrListComponent } from '../../pull-requests/pr-list/pr-list.component';

/**
 * Repository detail (plan §4.2): header stats come from
 * `GET /repositories/{id}/detail` (total_prs, total_reviews, default branch,
 * language, visibility, webhook) and two tabs — **Pull requests** (the PR
 * list with state/author filters + pagination, embedded) and **Settings**.
 *
 * Settings edits only what the API really persists: the default branch via
 * `PATCH /repositories/{id}` and enable/disable via the existing routes.
 * The `settings` block has no update route (always schema defaults), so it is
 * rendered read-only with an explicit note — never as toggles that cannot
 * save (docs/BACKEND_GAPS_FOR_UI.md #17).
 */
@Component({
  selector: 'app-repository-detail',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    TabsComponent,
    SpinnerComponent,
    ErrorStateComponent,
    PrListComponent
  ],
  templateUrl: './repository-detail.component.html',
  styleUrl: './repository-detail.component.scss'
})
export class RepositoryDetailComponent implements OnInit {
  private readonly repoApi = inject(RepositoryService);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);

  /** Cosmetic write gating for the enable/disable toggle (backend stays authoritative). */
  readonly nav = computed(() => navVisibility(this.auth.currentUser()?.role));

  owner = input.required<string>();
  repo = input.required<string>();

  repository = signal<RepositoryDetail | null>(null);
  isLoading = signal(true);
  /** True when the load failed (404/5xx/network) — renders the error state. */
  loadError = signal(false);
  /** Toggle in flight — disables the button so it cannot double-submit. */
  toggling = signal(false);

  readonly tabs: TabDef[] = [
    { id: 'prs', label: 'Pull requests' },
    { id: 'settings', label: 'Settings' }
  ];
  activeTab = signal('prs');

  /** Default-branch draft + save state (PATCH /repositories/{id}). */
  branchDraft = signal('');
  branchSaving = signal(false);
  branchSaved = signal(false);
  branchError = signal<string | null>(null);

  ngOnInit(): void {
    this.loadRepository();
  }

  loadRepository(): void {
    this.loadError.set(false);
    this.isLoading.set(true);
    this.repoApi.getRepositoryDetail(this.owner(), this.repo()).subscribe({
      next: detail => {
        this.repository.set(detail);
        this.branchDraft.set(detail.defaultBranch);
        this.branchSaved.set(false);
        this.isLoading.set(false);
      },
      error: () => {
        this.isLoading.set(false);
        this.loadError.set(true);
      }
    });
  }

  toggleEnabled(): void {
    const repo = this.repository();
    if (!repo || this.toggling()) {
      return; // double-submit guard
    }
    this.toggling.set(true);
    const request = repo.enabled
      ? this.repoApi.disableRepository(repo.id)
      : this.repoApi.enableRepository(repo.id);
    request.subscribe({
      next: () => {
        this.toggling.set(false);
        this.toast.success(repo.enabled ? 'Reviews disabled.' : 'Reviews enabled.');
        this.loadRepository();
      },
      error: () => {
        this.toggling.set(false);
        this.toast.error("Couldn't update the repository — please try again.");
      }
    });
  }

  onBranchInput(event: Event): void {
    this.branchDraft.set((event.target as HTMLInputElement).value);
    this.branchSaved.set(false);
    this.branchError.set(null);
  }

  /** Save is only offered when the draft really differs (and isn't empty). */
  canSaveBranch(): boolean {
    const repo = this.repository();
    if (!repo || this.branchSaving()) {
      return false;
    }
    const draft = this.branchDraft().trim();
    return draft !== '' && draft !== repo.defaultBranch;
  }

  saveBranch(): void {
    const repo = this.repository();
    if (!repo || !this.canSaveBranch()) {
      return; // double-submit guard
    }
    this.branchSaving.set(true);
    this.branchError.set(null);
    this.repoApi
      .updateRepository(repo.id, { default_branch: this.branchDraft().trim() })
      .subscribe({
        next: updated => {
          this.branchSaving.set(false);
          this.repository.set({ ...repo, defaultBranch: updated.defaultBranch });
          this.branchDraft.set(updated.defaultBranch);
          this.branchSaved.set(true);
        },
        error: () => {
          this.branchSaving.set(false);
          this.branchError.set("Couldn't save the default branch — please try again.");
        }
      });
  }
}
