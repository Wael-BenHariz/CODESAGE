import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { GithubAppService } from '../../../core/services/github-app.service';
import { GitHubAppRepo } from '../../../core/models/github-app.model';
import { RepositoryService } from '../../../core/services/repository.service';
import { navVisibility } from '../../../core/guards/role.guard';
import { Repository } from '../../../core/models/repository.model';
import { SiteHeaderComponent } from '../../../shared/components/site-header/site-header.component';

@Component({
  selector: 'app-repository-list',
  standalone: true,
  imports: [SiteHeaderComponent, CommonModule, RouterLink],
  templateUrl: './repository-list.component.html',
  styleUrl: './repository-list.component.scss'
})
export class RepositoryListComponent implements OnInit {
  private readonly github = inject(GithubAppService);
  private readonly repoApi = inject(RepositoryService);
  private readonly auth = inject(AuthService);

  /** Cosmetic write gating for header/card actions (backend stays authoritative). */
  readonly nav = computed(() => navVisibility(this.auth.currentUser()?.role));

  /** Shared GitHub App install status (refreshed on init and after the App callback). */
  readonly githubInstalled = this.github.githubInstalled;

  repositories = signal<Repository[]>([]);
  isLoading = signal(true);
  filter = signal<'all' | 'enabled' | 'disabled'>('all');

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

  get filteredRepos() {
    const repos = this.repositories();
    const f = this.filter();
    if (f === 'all') return repos;
    return repos.filter(r => (f === 'enabled' ? r.enabled : !r.enabled));
  }

  /** Selected repos whose row hasn't materialized in the grid yet (no PR event). */
  get selectedPending() {
    const names = new Set(this.repositories().map(r => r.fullName));
    return this.appSelected().filter(r => !names.has(r.name));
  }

  ngOnInit(): void {
    this.loadRepositories();
    this.refreshInstallStatus();
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

  toggleRepo(repo: Repository): void {
    if (repo.enabled) {
      this.repoApi.disableRepository(repo.id).subscribe(() => this.loadRepositories());
    } else {
      this.repoApi.enableRepository(repo.id).subscribe(() => this.loadRepositories());
    }
  }

  deleteRepo(repo: Repository): void {
    if (confirm(`Are you sure you want to remove ${repo.fullName}?`)) {
      this.repoApi.deleteRepository(repo.id).subscribe(() => this.loadRepositories());
    }
  }

  openConnectModal(): void {
    this.showConnectModal.set(true);
    this.loadGitHubRepos();
  }

  installGitHubApp(): void {
    // Signed URL from GET /auth/github/app/install-url (state = JWT) — the
    // URL is used exactly as returned, never rebuilt by hand.
    this.auth.getInstallUrl().subscribe(({ url }) => {
      window.location.href = url;
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
