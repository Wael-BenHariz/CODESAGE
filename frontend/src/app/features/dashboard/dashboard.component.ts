import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { GithubAppService } from '../../core/services/github-app.service';
import { RepositoryService } from '../../core/services/repository.service';
import { ReviewService } from '../../core/services/review.service';
import { Repository } from '../../core/models/repository.model';
import { ReviewSummary } from '../../core/models/review.model';
import { User } from '../../core/models/user.model';

type SectionState = 'loading' | 'error' | 'ready';

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/**
 * Dashboard (plan Step 10) — every number comes from a real endpoint:
 * - repo counts from `GET /repositories` (total + enabled);
 * - review totals from `GET /reviews` and the pending count from the same
 *   route's `status_filter=pending` (the filter also drives the envelope
 *   `total`, so no client-side scanning);
 * - the Recent Reviews section renders the newest rows verbatim.
 *
 * Per-org breakdowns are impossible client-side (no org attribution on any
 * response) — see docs/BACKEND_GAPS_FOR_UI.md §3; the numbers here are
 * global to everything the caller can see. A failed count shows '—', never
 * a fake 0; each section owns its loading / empty / error+retry states.
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss'
})
export class DashboardComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly github = inject(GithubAppService);
  private readonly repoApi = inject(RepositoryService);
  private readonly reviewApi = inject(ReviewService);

  user = signal<User | null>(null);
  repositories = signal<Repository[]>([]);
  reposState = signal<SectionState>('loading');
  reposError = signal<string | null>(null);
  stats = signal({ totalRepos: 0, enabledRepos: 0 });

  /** null = not loaded yet or failed → the tile renders '—', never 0. */
  totalReviews = signal<number | null>(null);
  pendingReviews = signal<number | null>(null);
  recentReviews = signal<ReviewSummary[]>([]);
  reviewsState = signal<SectionState>('loading');
  reviewsError = signal<string | null>(null);

  ngOnInit(): void {
    this.user.set(this.auth.currentUser());
    this.loadRepositories();
    this.loadReviews();
    // Re-read GitHub App install status so shared state is never stale.
    this.github.getInstallStatus().subscribe({ error: () => undefined });
  }

  loadRepositories(): void {
    this.reposState.set('loading');
    this.reposError.set(null);
    this.repoApi.getRepositories().subscribe({
      next: (repos: Repository[]) => {
        this.repositories.set(repos);
        this.stats.set({
          totalRepos: repos.length,
          enabledRepos: repos.filter((r: Repository) => r.enabled).length
        });
        this.reposState.set('ready');
      },
      error: err => {
        this.reposError.set(errorMessage(err, 'Could not load repositories.'));
        this.reposState.set('error');
      }
    });
  }

  loadReviews(): void {
    this.reviewsState.set('loading');
    this.reviewsError.set(null);
    // Newest rows + the global total in one call (per_page=5).
    this.reviewApi.listReviews(1, 5).subscribe({
      next: list => {
        this.totalReviews.set(list.total);
        this.recentReviews.set(list.items);
        this.reviewsState.set('ready');
      },
      error: err => {
        this.reviewsError.set(errorMessage(err, 'Could not load reviews.'));
        this.reviewsState.set('error');
      }
    });
    // Pending count — independent of the list above: a failure must never
    // blank the section, it only blanks its own tile ('—', not 0).
    this.reviewApi.listReviews(1, 1, 'pending').subscribe({
      next: list => this.pendingReviews.set(list.total),
      error: () => this.pendingReviews.set(null)
    });
  }
}
