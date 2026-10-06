import {
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  input,
  numberAttribute,
  signal,
  viewChild
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AuthService } from '../../../core/services/auth.service';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { ReviewService } from '../../../core/services/review.service';
import { ApiError } from '../../../core/services/api.service';
import { navVisibility } from '../../../core/guards/role.guard';
import { PullRequest } from '../../../core/models/pull-request.model';
import { ReviewStats, deriveReviewStats } from '../../../core/services/mappers/pull-request.mapper';
import { ReviewPanelComponent } from '../review-panel/review-panel.component';

/**
 * Stats-bar state for the two review tiles (plan Step 2, Q1/Option 1):
 * - `hidden`: no review exists (or a 404 — the interceptor takes the user to
 *   the generic not-found page) → no tiles, no request.
 * - `loading` / `failed`: tiles render "—" (never 0 — a zero must only mean
 *   a real zero); `failed` adds a retry.
 * - `ready`: real numbers from the shared `GET /reviews/{id}` call.
 */
export type ReviewStatsState =
  | { kind: 'hidden' }
  | { kind: 'loading' }
  | ({ kind: 'ready' } & ReviewStats)
  | { kind: 'failed' };

@Component({
  selector: 'app-pr-detail',
  standalone: true,
  imports: [CommonModule, RouterLink, ReviewPanelComponent],
  templateUrl: './pr-detail.component.html',
  styleUrl: './pr-detail.component.scss'
})
export class PrDetailComponent implements OnInit {
  private readonly github = inject(PullRequestService);
  private readonly auth = inject(AuthService);
  private readonly reviewApi = inject(ReviewService);
  private readonly destroyRef = inject(DestroyRef);

  /** Cosmetic write gating for the review trigger (backend stays authoritative). */
  readonly nav = computed(() => navVisibility(this.auth.currentUser()?.role));

  owner = input.required<string>();
  repo = input.required<string>();
  /** Route param is a string — coerced once at the input boundary. */
  number = input.required<number, string>({ transform: numberAttribute });

  pullRequest = signal<PullRequest | null>(null);
  isLoading = signal(true);
  /** True when the load failed (404/5xx/network) — renders the error state. */
  loadError = signal(false);
  isReviewing = signal(false);

  /** Stats-bar state (see ReviewStatsState). */
  readonly reviewStats = signal<ReviewStatsState>({ kind: 'hidden' });
  /** Latest review id from the PR response — source for the stats tiles. */
  private latestReviewId: string | null = null;

  /** Embedded review panel (absent until a review exists). */
  readonly reviewPanel = viewChild(ReviewPanelComponent);

  /**
   * Plan Step 4: true while the summary editor holds unsaved changes —
   * read by the route's canDeactivate guard to warn before navigation.
   */
  hasUnsavedSummaryEdit(): boolean {
    const panel = this.reviewPanel();
    return !!panel && panel.editingSummary() && panel.summaryDirty();
  }

  ngOnInit(): void {
    this.loadPullRequest();
    // Tiles follow the panel: a successful dismiss/restore/summary/post/
    // validate invalidates the shared review cache → this refetch keeps the
    // tiles and the panel's own numbers moving together.
    this.reviewApi.reviewDetailInvalidated$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(reviewId => {
        if (reviewId === this.latestReviewId && this.reviewStats().kind !== 'hidden') {
          this.loadReviewStats();
        }
      });
  }

  loadPullRequest(): void {
    this.loadError.set(false);
    this.isLoading.set(true);
    this.github.getPullRequest(this.owner(), this.repo(), this.number()).subscribe({
      next: pr => {
        this.pullRequest.set(pr);
        this.isLoading.set(false);
        this.applyStatsSource(pr);
      },
      error: () => {
        this.isLoading.set(false);
        this.loadError.set(true);
        this.latestReviewId = null;
        this.reviewStats.set({ kind: 'hidden' });
      }
    });
  }

  /**
   * Point the stats bar at the PR's latest review. No review ⇒ tiles stay
   * hidden and NO extra request is made (constraint #5).
   */
  private applyStatsSource(pr: PullRequest): void {
    const reviewId = pr.reviewStatus?.reviewId ?? null;
    this.latestReviewId = reviewId;
    if (!reviewId) {
      this.reviewStats.set({ kind: 'hidden' });
      return;
    }
    this.loadReviewStats();
  }

  /** Retry entry point for the failed tiles (also used by initial load). */
  reloadReviewStats(): void {
    this.loadReviewStats();
  }

  private loadReviewStats(): void {
    const reviewId = this.latestReviewId;
    if (!reviewId) {
      return;
    }
    this.reviewStats.set({ kind: 'loading' });
    this.reviewApi.getReviewDetail(reviewId).subscribe({
      next: detail => {
        if (this.latestReviewId !== reviewId) {
          return; // stale response — the PR changed underneath
        }
        this.reviewStats.set({ kind: 'ready', ...deriveReviewStats(detail) });
      },
      error: (err: unknown) => {
        if (this.latestReviewId !== reviewId) {
          return;
        }
        // Rule 5: a 404 renders the generic not-found page (ErrorInterceptor
        // navigates) — no partial stats for it.
        if (err instanceof ApiError && err.status === 404) {
          this.reviewStats.set({ kind: 'hidden' });
          return;
        }
        // Failure isolation: the PR page stays; only the tiles degrade.
        this.reviewStats.set({ kind: 'failed' });
      }
    });
  }

  triggerReview(): void {
    const pr = this.pullRequest();
    if (pr) {
      this.isReviewing.set(true);
      this.github.triggerReview(pr.id).subscribe({
        next: () => {
          this.isReviewing.set(false);
          this.loadPullRequest();
        },
        error: () => {
          this.isReviewing.set(false);
        }
      });
    }
  }

  getStateColor(state: string): string {
    switch (state) {
      case 'open':
        return '#2f855a';
      case 'closed':
        return '#c53030';
      case 'merged':
        return '#805ad5';
      default:
        return '#718096';
    }
  }
}
