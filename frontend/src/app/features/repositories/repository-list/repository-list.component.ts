import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { GithubService, GitHubAppRepo } from '../../../core/services/github.service';
import { Repository } from '../../../core/models/repository.model';

@Component({
  selector: 'app-repository-list',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './repository-list.component.html',
  styleUrl: './repository-list.component.scss'
})
export class RepositoryListComponent implements OnInit {
  private readonly github = inject(GithubService);

  /** Shared GitHub App install status (refreshed on init and after the App callback). */
  readonly githubInstalled = this.github.githubInstalled;

  repositories = signal<Repository[]>([]);
  isLoading = signal(true);
  filter = signal<'all' | 'enabled' | 'disabled'>('all');

  showConnectModal = signal(false);
  githubRepos = signal<GitHubAppRepo[]>([]);
  isLoadingGitHubRepos = signal(false);
  connectingRepo = signal<string | null>(null);

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

  ngOnInit(): void {
    this.loadRepositories();
    this.refreshInstallStatus();
  }

  /** Always re-read install status on init so a stale "not installed" value is never shown. */
  private refreshInstallStatus(): void {
    this.github.getInstallStatus().subscribe({ error: () => undefined });
  }

  private loadRepositories(): void {
    this.github.getRepositories().subscribe({
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
      this.github.disableRepository(repo.id).subscribe(() => this.loadRepositories());
    } else {
      this.github.enableRepository(repo.id).subscribe(() => this.loadRepositories());
    }
  }

  deleteRepo(repo: Repository): void {
    if (confirm(`Are you sure you want to remove ${repo.fullName}?`)) {
      this.github.deleteRepository(repo.id).subscribe(() => this.loadRepositories());
    }
  }

  openConnectModal(): void {
    this.showConnectModal.set(true);
    this.loadGitHubRepos();
  }

  installGitHubApp(): void {
    this.github.getInstallUrl().subscribe(({ url }) => {
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
    this.github.getAppRepos().subscribe({
      next: repos => {
        this.githubRepos.set(repos);
        this.isLoadingGitHubRepos.set(false);
      },
      error: () => {
        this.githubRepos.set([]);
        this.isLoadingGitHubRepos.set(false);
      }
    });
  }

  connectRepo(repo: GitHubAppRepo): void {
    this.connectingRepo.set(repo.name);
    this.github
      .saveRepoSelection([{ id: repo.id, name: repo.name, private: repo.private, enabled: true }])
      .subscribe({
        next: () => {
          this.loadGitHubRepos();
          this.connectingRepo.set(null);
        },
        error: () => {
          this.connectingRepo.set(null);
        }
      });
  }
}
