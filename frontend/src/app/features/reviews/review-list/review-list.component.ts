import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink } from '@angular/router';

import { PullRequestService } from '../../../core/services/pull-request.service';
import { RepositoryService } from '../../../core/services/repository.service';
import { ReviewService } from '../../../core/services/review.service';
import { ApiError } from '../../../core/services/api.service';
import { ReviewSummary } from '../../../core/models/review.model';
import { Repository } from '../../../core/models/repository.model';
import { PullRequest } from '../../../core/models/pull-request.model';
import {
  SeverityBadgeComponent,
  SeverityLevel
} from '../../../shared/components/severity-badge/severity-badge.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { ErrorStateComponent } from '../../../shared/components/error-state/error-state.component';
import { SpinnerComponent } from '../../../shared/components/spinner/spinner.component';

type PageState = 'loading' | 'error' | 'ready';

/**
 * Review-history page (plan Step 4 / reviewer experience) — route `/reviews`.
 *
 * The cross-repo review history `GET /reviews` already provides (org-scoped
 * F3, newest first, `status_filter` + pagination). Every column comes from
 * that endpoint — no aggregation, no invented org attribution (the response
 * carries none; see docs/BACKEND_GAPS_FOR_UI.md §3).
 *
 * Per-row navigation: "Open pull request" resolves the review's PR id →
 * repository through the two existing by-id reads (`GET /pull-requests/{id}`,
 * `GET /repositories/{id}`) and navigates to the PR detail page — two
 * requests per click, never a batch of guesses. Resolution failures surface
 * on the row (the app-wide 404 handling stays untouched).
 */
@Component({
  selector: 'app-review-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    SeverityBadgeComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    SpinnerComponent
  ],
  templateUrl: './review-list.component.html',
  styleUrl: './review-list.component.scss'
})
export class ReviewListComponent implements OnInit {
  private readonly reviewApi = inject(ReviewService);
  private readonly pullRequests = inject(PullRequestService);
  private readonly repositories = inject(RepositoryService);
  private readonly router = inject(Router);

  readonly perPage = 20;

  readonly state = signal<PageState>('loading');
  readonly error = signal<string | null>(null);
  readonly reviews = signal<ReviewSummary[]>([]);
  readonly total = signal(0);
  readonly page = signal(1);
  /** Backend status_filter vocabulary — exactly the statuses that exist. */
  readonly statusFilters = [
    { value: '', label: 'All statuses' },
    { value: 'pending', label: 'Pending' },
    { value: 'processing', label: 'Processing' },
    { value: 'completed', label: 'Completed' },
    { value: 'ready_to_post', label: 'Ready to post' },
    { value: 'failed', label: 'Failed' }
  ];
  readonly statusFilter = signal('');

  /** Review id whose "Open pull request" resolution is in flight. */
  readonly openingId = signal<string | null>(null);
  readonly openErrorId = signal<string | null>(null);

  /** Expanded rows (summary + error message reveal). */
  readonly expanded = signal<ReadonlySet<string>>(new Set());

  readonly pages = computed(() => Math.max(1, Math.ceil(this.total() / this.perPage)));

  /**
   * Review-level `overall_severity` is written in the comment vocabulary
   * (info|warning|error|suggestion) — the same mapping the dashboard uses.
   */
  private static readonly SEVERITY_MAP: Record<string, SeverityLevel> = {
    error: 'critical',
    warning: 'medium',
    suggestion: 'low',
    info: 'info',
    critical: 'critical',
    high: 'high',
    medium: 'medium',
    low: 'low'
  };

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.state.set('loading');
    this.error.set(null);
    this.reviewApi
      .listReviews(this.page(), this.perPage, this.statusFilter() || undefined)
      .subscribe({
        next: list => {
          this.reviews.set(list.items);
          this.total.set(list.total);
          this.page.set(list.page);
          this.state.set('ready');
        },
        error: err => {
          this.error.set(this.messageOf(err, 'Could not load reviews.'));
          this.state.set('error');
        }
      });
  }

  onFilterChange(event: Event): void {
    this.statusFilter.set((event.target as HTMLSelectElement).value);
    this.page.set(1);
    this.load();
  }

  prevPage(): void {
    if (this.page() > 1) {
      this.page.update(p => p - 1);
      this.load();
    }
  }

  nextPage(): void {
    if (this.page() < this.pages()) {
      this.page.update(p => p + 1);
      this.load();
    }
  }

  sevLevel(value: string | null): SeverityLevel | null {
    if (!value) {
      return null;
    }
    return ReviewListComponent.SEVERITY_MAP[value] ?? null;
  }

  isExpanded(id: string): boolean {
    return this.expanded().has(id);
  }

  toggle(id: string): void {
    this.expanded.update(current => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  /** Whether a staged review is still awaiting its GitHub post. */
  isAwaitingPost(review: ReviewSummary): boolean {
    return review.status === 'ready_to_post' && review.posted_at === null;
  }

  /**
   * Resolve review → PR → repository and navigate to the PR detail page.
   * In-flight and failed states stay on the row; the app-wide 404 flow is
   * untouched (a deleted PR resolves to the honest not-found page).
   */
  openPullRequest(review: ReviewSummary): void {
    if (this.openingId()) {
      return; // one resolution at a time
    }
    this.openingId.set(review.id);
    this.openErrorId.set(null);

    this.pullRequests.getPullRequestById(review.pull_request_id).subscribe({
      next: (pr: PullRequest) => {
        this.repositories.getRepositoryById(pr.repositoryId).subscribe({
          next: (repo: Repository) => {
            this.openingId.set(null);
            void this.router.navigate(['/repositories', repo.owner, repo.name, 'pulls', pr.number]);
          },
          error: err => {
            this.openingId.set(null);
            // A 404 already navigated to the app-wide not-found page; any
            // other failure stays visible on the row.
            if (!(err instanceof ApiError && err.status === 404)) {
              this.openErrorId.set(review.id);
            }
          }
        });
      },
      error: err => {
        this.openingId.set(null);
        // A 404 already navigated to the app-wide not-found page; any other
        // failure stays visible on the row.
        if (!(err instanceof ApiError && err.status === 404)) {
          this.openErrorId.set(review.id);
        }
      }
    });
  }

  private messageOf(err: unknown, fallback: string): string {
    if (err instanceof ApiError && err.message) {
      return err.message;
    }
    if (err instanceof Error && err.message) {
      return err.message;
    }
    return fallback;
  }
}
