import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { GithubService } from '../../core/services/github.service';
import { Repository } from '../../core/models/repository.model';
import { User } from '../../core/models/user.model';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss'
})
export class DashboardComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly github = inject(GithubService);

  user = signal<User | null>(null);
  repositories = signal<Repository[]>([]);
  isLoading = signal(true);
  stats = signal({
    totalRepos: 0,
    enabledRepos: 0,
    openPRs: 0,
    pendingReviews: 0
  });

  ngOnInit(): void {
    this.user.set(this.auth.currentUser());
    this.loadDashboard();
    // Re-read GitHub App install status so shared state is never stale.
    this.github.getInstallStatus().subscribe({ error: () => undefined });
  }

  private loadDashboard(): void {
    this.github.getRepositories().subscribe({
      next: (repos: Repository[]) => {
        this.repositories.set(repos);
        this.stats.set({
          totalRepos: repos.length,
          enabledRepos: repos.filter((r: Repository) => r.enabled).length,
          openPRs: 0,
          pendingReviews: 0
        });
        this.isLoading.set(false);
      },
      error: () => {
        this.isLoading.set(false);
      }
    });
  }

  logout(): void {
    this.auth.logout();
  }

  switchAccount(): void {
    this.auth.switchAccount();
  }
}
