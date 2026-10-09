import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Observable } from 'rxjs';
import { AuthService } from '../../../core/services/auth.service';
import { AuthContextService } from '../../../core/services/auth-context.service';
import { GithubAppService } from '../../../core/services/github-app.service';
import { GitHubAppRepo } from '../../../core/models/github-app.model';
import { InstallRequestService } from '../../../core/services/install-request.service';
import { InstallRequest } from '../../../core/models/install-request.model';
import { RepositoryService } from '../../../core/services/repository.service';
import { ToastService } from '../../../core/services/toast.service';
import { navVisibility } from '../../../core/guards/role.guard';
import { Repository } from '../../../core/models/repository.model';
import { SpinnerComponent } from '../../../shared/components/spinner/spinner.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { ConfirmDialogComponent } from '../../../shared/components/confirm-dialog/confirm-dialog.component';

@Component({
  selector: 'app-repository-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    SpinnerComponent,
    EmptyStateComponent,
    ConfirmDialogComponent
  ],
  templateUrl: './repository-list.component.html',
  styleUrl: './repository-list.component.scss'
})
export class RepositoryListComponent implements OnInit {
  private readonly github = inject(GithubAppService);
  private readonly repoApi = inject(RepositoryService);
  private readonly auth = inject(AuthService);
  private readonly ctx = inject(AuthContextService);
  private readonly installRequestsApi = inject(InstallRequestService);
  private readonly toast = inject(ToastService);

  /** Cosmetic write gating for header/card actions (backend stays authoritative). */
  readonly nav = computed(() => navVisibility(this.auth.currentUser()?.role));

  /** Active workspace — the install-request flows are workspace-scoped (§2.5). */
  readonly activeWorkspace = computed(() => this.ctx.activeWorkspace());

  /** ORG workspace where the caller is not `repo_admin` → request, not install. */
  readonly canRequestInstall = computed(() => {
    const workspace = this.activeWorkspace();
    return !!workspace && workspace.type === 'ORG' && !workspace.capabilities.repoAdmin;
  });

  readonly canManageInstallRequests = computed(() => {
    const workspace = this.activeWorkspace();
    return !!workspace && workspace.type === 'ORG' && workspace.capabilities.repoAdmin;
  });

  /** Pending install requests in the active workspace (admins resolve these). */
  readonly pendingInstallRequests = signal<InstallRequest[]>([]);
  readonly installRequestLoading = signal(false);
  readonly installRequestError = signal<string | null>(null);
  readonly creatingInstallRequest = signal(false);
  readonly installRequestSent = signal(false);
  /** Request id of an in-flight approve/reject. */
  readonly resolvingRequestId = signal<string | null>(null);

  /** Shared GitHub App install status (refreshed on init and after the App callback). */
  readonly githubInstalled = this.github.githubInstalled;

  repositories = signal<Repository[]>([]);
  isLoading = signal(true);
  filter = signal<'all' | 'enabled' | 'disabled'>('all');
  /** Free-text search over full name + description (client-side). */
  search = signal('');
  /** Card grid vs. table (session-only view preference). */
  viewMode = signal<'cards' | 'table'>('cards');

  /** Pending destructive action — disable/delete always confirm first. */
  pendingConfirm = signal<{ kind: 'disable' | 'delete'; repo: Repository } | null>(null);
  confirmBusy = signal(false);
  confirmError = signal<string | null>(null);

  showConnectModal = signal(false);
  githubRepos = signal<GitHubAppRepo[]>([]);
  isLoadingGitHubRepos = signal(false);
  connectingRepo = signal<string | null>(null);
  /** Load error inside the modal (null when the empty/install branch should show instead). */
  modalError = signal<string | null>(null);
  /** Save error shown inline under the selection list. */
  saveError = signal<string | null>(null);
  /** Selected App repos (from /github/repos) for the pending-selection note. */
  appSelected = signal<GitHubAppRepo[]>([]);

  get openCount() {
    return this.repositories().filter(r => r.enabled).length;
  }

  get disabledCount() {
    return this.repositories().filter(r => !r.enabled).length;
  }

  get filteredRepos(): Repository[] {
    const repos = this.repositories();
    const f = this.filter();
    const term = this.search().trim().toLowerCase();
    return repos.filter(r => {
      const stateOk = f === 'all' || (f === 'enabled' ? r.enabled : !r.enabled);
      if (!stateOk) return false;
      if (!term) return true;
      return (
        r.fullName.toLowerCase().includes(term) ||
        (r.description ?? '').toLowerCase().includes(term)
      );
    });
  }

  /** Selected repos whose row hasn't materialized in the grid yet (no PR event). */
  get selectedPending() {
    const names = new Set(this.repositories().map(r => r.fullName));
    return this.appSelected().filter(r => !names.has(r.name));
  }

  ngOnInit(): void {
    this.loadRepositories();
    this.refreshInstallStatus();
    if (!this.githubInstalled() && this.canManageInstallRequests()) {
      this.loadPendingInstallRequests();
    }
  }

  /** Always re-read install status on init so a stale "not installed" value is never shown. */
  private refreshInstallStatus(): void {
    this.github.getInstallStatus().subscribe({
      next: status => {
        if (status.installed) this.fetchAppSelection();
      },
      error: () => undefined
    });
  }

  /** Keeps the pending-selection note in sync (init + after modal toggles). */
  private fetchAppSelection(): void {
    this.github.getAppRepos().subscribe({
      next: repos => this.appSelected.set(repos.filter(r => r.enabled)),
      error: () => undefined
    });
  }

  private loadRepositories(): void {
    this.repoApi.getRepositories().subscribe({
      next: repos => {
        this.repositories.set(repos);
        this.isLoading.set(false);
      },
      error: () => {
        this.isLoading.set(false);
      }
    });
  }

  setFilter(filter: 'all' | 'enabled' | 'disabled'): void {
    this.filter.set(filter);
  }

  onSearchInput(event: Event): void {
    this.search.set((event.target as HTMLInputElement).value);
  }

  clearFilters(): void {
    this.search.set('');
    this.filter.set('all');
  }

  /**
   * Disable and delete are destructive → they open the confirm dialog;
   * enabling is harmless and runs immediately.
   */
  toggleRepo(repo: Repository): void {
    if (repo.enabled) {
      this.confirmError.set(null);
      this.pendingConfirm.set({ kind: 'disable', repo });
    } else {
      this.repoApi.enableRepository(repo.id).subscribe(() => this.loadRepositories());
    }
  }

  deleteRepo(repo: Repository): void {
    this.confirmError.set(null);
    this.pendingConfirm.set({ kind: 'delete', repo });
  }

  /** Runs the confirmed action; failures keep the dialog open with an alert. */
  confirmPending(): void {
    const pending = this.pendingConfirm();
    if (!pending || this.confirmBusy()) {
      return; // double-submit guard
    }
    this.confirmBusy.set(true);
    this.confirmError.set(null);
    const { kind, repo } = pending;
    // disable → Observable<Repository>, delete → Observable<void>: the union
    // needs a common supertype before subscribe() can resolve an overload.
    const request: Observable<unknown> =
      kind === 'disable'
        ? this.repoApi.disableRepository(repo.id)
        : this.repoApi.deleteRepository(repo.id);
    request.subscribe({
      next: () => {
        this.confirmBusy.set(false);
        this.pendingConfirm.set(null);
        this.loadRepositories();
      },
      error: () => {
        this.confirmBusy.set(false);
        this.confirmError.set(
          kind === 'disable'
            ? `Couldn't disable ${repo.fullName} — please try again.`
            : `Couldn't remove ${repo.fullName} — please try again.`
        );
      }
    });
  }

  cancelConfirm(): void {
    if (this.confirmBusy()) {
      return; // never dismiss mid-request
    }
    this.pendingConfirm.set(null);
    this.confirmError.set(null);
  }

  get confirmTitle(): string {
    return this.pendingConfirm()?.kind === 'delete' ? 'Remove repository' : 'Disable reviews';
  }

  get confirmMessage(): string {
    const pending = this.pendingConfirm();
    if (!pending) return '';
    return pending.kind === 'delete'
      ? `Remove ${pending.repo.fullName} from CodeSage?`
      : `Disable reviews for ${pending.repo.fullName}? New pull requests won't be reviewed until you enable them again.`;
  }

  get confirmActionLabel(): string {
    const pending = this.pendingConfirm();
    if (!pending) return '';
    if (pending.kind === 'delete') return this.confirmBusy() ? 'Removing…' : 'Remove';
    return this.confirmBusy() ? 'Disabling…' : 'Disable';
  }

  openConnectModal(): void {
    this.showConnectModal.set(true);
    this.loadGitHubRepos();
  }

  installGitHubApp(): void {
    // Signed URL from GET /auth/github/app/install-url (state = JWT) — the
    // URL is used exactly as returned, never rebuilt by hand. The active
    // workspace id binds the installation to that workspace (§2.5); the
    // backend gates it with repo_admin and signs `wid` into the state.
    const workspaceId = this.activeWorkspace()?.id;
    this.auth.getInstallUrl(workspaceId).subscribe(({ url }) => {
      window.location.href = url;
    });
  }

  /** Direct install is only completable by an admin of the GitHub account. */
  canDirectInstall(): boolean {
    const workspace = this.activeWorkspace();
    return !workspace || workspace.type !== 'ORG' || workspace.capabilities.repoAdmin;
  }

  // --- Install requests (§2.5: member request → admin approve/reject) --------

  private loadPendingInstallRequests(): void {
    const workspace = this.activeWorkspace();
    if (!workspace) return;
    this.installRequestLoading.set(true);
    this.installRequestError.set(null);
    this.installRequestsApi.list({ workspaceId: workspace.id, statusFilter: 'PENDING' }).subscribe({
      next: requests => {
        this.pendingInstallRequests.set(requests);
        this.installRequestLoading.set(false);
      },
      error: () => {
        this.installRequestLoading.set(false);
        this.installRequestError.set('Could not load install requests.');
      }
    });
  }

  /** Member without repo_admin asks an ORG_ADMIN to install the App. */
  requestGitHubAppInstall(): void {
    const workspace = this.activeWorkspace();
    if (!workspace || this.creatingInstallRequest()) return;
    this.creatingInstallRequest.set(true);
    this.installRequestsApi.create(workspace.id).subscribe({
      next: () => {
        this.creatingInstallRequest.set(false);
        this.installRequestSent.set(true);
        this.toast.success('Install request sent to the workspace admins.');
      },
      error: () => {
        this.creatingInstallRequest.set(false);
        this.installRequestError.set('Could not send the install request.');
      }
    });
  }

  approveInstallRequest(request: InstallRequest): void {
    this.resolveInstallRequest(request, true);
  }

  rejectInstallRequest(request: InstallRequest): void {
    this.resolveInstallRequest(request, false);
  }

  private resolveInstallRequest(request: InstallRequest, approve: boolean): void {
    if (this.resolvingRequestId()) return;
    this.resolvingRequestId.set(request.id);
    const answer = approve
      ? this.installRequestsApi.approve(request.id)
      : this.installRequestsApi.reject(request.id);
    answer.subscribe({
      next: resolution => {
        this.resolvingRequestId.set(null);
        this.pendingInstallRequests.update(list =>
          list
            .map(existing =>
              existing.id === resolution.id ? { ...existing, status: resolution.status } : existing
            )
            .filter(existing => existing.status === 'PENDING')
        );
        this.toast.success(approve ? 'Install request approved.' : 'Install request rejected.');
      },
      error: () => {
        this.resolvingRequestId.set(null);
        this.installRequestError.set('Could not resolve the install request.');
      }
    });
  }

  closeConnectModal(): void {
    this.showConnectModal.set(false);
  }

  /** Closes the modal only when the overlay backdrop itself was clicked. */
  onOverlayClick(event: Event): void {
    if (event.target === event.currentTarget) {
      this.closeConnectModal();
    }
  }

  private loadGitHubRepos(): void {
    this.isLoadingGitHubRepos.set(true);
    this.modalError.set(null);
    this.saveError.set(null);
    this.github.getAppRepos().subscribe({
      next: repos => {
        this.githubRepos.set(repos);
        this.appSelected.set(repos.filter(r => r.enabled));
        this.isLoadingGitHubRepos.set(false);
      },
      error: (err: { status?: number }) => {
        this.githubRepos.set([]);
        this.isLoadingGitHubRepos.set(false);
        // 400 = App not installed → leave modalError null so the install CTA
        // (empty branch) renders; anything else is a real load failure.
        this.modalError.set(
          err?.status === 400 ? null : 'Could not load repositories. Please try again.'
        );
      }
    });
  }

  retryLoad(): void {
    this.loadGitHubRepos();
  }

  /** Two-way selection: flips this repo and saves the FULL list (sync payload). */
  toggleSelection(repo: GitHubAppRepo): void {
    const updated: GitHubAppRepo[] = this.githubRepos().map(r =>
      r.id === repo.id ? { ...r, enabled: !r.enabled } : r
    );
    this.connectingRepo.set(repo.name);
    this.saveError.set(null);
    this.github.saveRepoSelection(updated).subscribe({
      next: () => {
        this.loadGitHubRepos();
        this.connectingRepo.set(null);
      },
      error: () => {
        this.connectingRepo.set(null);
        this.saveError.set('Could not save your selection. Please try again.');
      }
    });
  }
}
