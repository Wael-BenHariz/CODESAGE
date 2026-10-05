import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { GithubService } from '../../../core/services/github.service';
import { ReviewComment, ReviewDetail } from '../../../core/models/review.model';

/** Comments of one file after the plan's ordering: severity → file → line. */
export interface ReviewFileGroup {
  file: string;
  comments: ReviewComment[];
}

type PanelState = 'loading' | 'error' | 'none' | 'detail';

/**
 * Plan §3 ordering: error > warning > suggestion > info. Unknown severities
 * sink to the floor — same convention as the worker's severity gate.
 */
const SEVERITY_RANK: Record<string, number> = {
  error: 3,
  warning: 2,
  suggestion: 1,
  info: 0
};

const RUNNING_STATUSES = ['pending', 'processing', 'in_progress'];

/**
 * Read-only AI review panel on the PR detail page (plan Step 7b).
 *
 * Fetches the PR's reviews (newest first) and renders the latest one:
 * summary (edited_summary wins), status states, and the findings grouped
 * by file. All text is interpolated — never `innerHTML` — so LLM and
 * scanner output can't inject markup.
 */
@Component({
  selector: 'app-review-panel',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './review-panel.component.html',
  styleUrl: './review-panel.component.scss'
})
export class ReviewPanelComponent implements OnInit {
  private readonly github = inject(GithubService);

  readonly prId = input.required<string>();
  readonly owner = input.required<string>();
  readonly repo = input.required<string>();
  readonly number = input.required<number>();
  /** Show the "run a review" CTA (write-capable viewers; backend authoritative). */
  readonly canTrigger = input(false);

  readonly state = signal<PanelState>('loading');
  readonly detail = signal<ReviewDetail | null>(null);
  readonly isTriggering = signal(false);
  readonly triggerError = signal(false);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.state.set('loading');
    this.triggerError.set(false);
    this.github.getPullRequestReviews(this.prId()).subscribe({
      next: reviews => {
        const latest = reviews[0]; // the endpoint orders created_at desc
        if (!latest) {
          this.detail.set(null);
          this.state.set('none');
          return;
        }
        this.github.getReviewDetail(latest.id).subscribe({
          next: detail => {
            this.detail.set(detail);
            this.state.set('detail');
          },
          error: () => this.state.set('error')
        });
      },
      error: () => this.state.set('error')
    });
  }

  retry(): void {
    this.load();
  }

  /** CTA in the empty state — triggers a review, then reloads to show it. */
  runReview(): void {
    if (this.isTriggering()) {
      return;
    }
    this.isTriggering.set(true);
    this.github.triggerReview(this.prId()).subscribe({
      next: () => {
        this.isTriggering.set(false);
        this.load(); // the pending review now exists → spinner state
      },
      error: () => {
        this.isTriggering.set(false);
        this.triggerError.set(true);
      }
    });
  }

  readonly runStatus = computed(() => this.detail()?.status ?? null);

  readonly isRunning = computed(() => {
    const status = this.runStatus();
    return status !== null && RUNNING_STATUSES.includes(status);
  });

  readonly isFailed = computed(() => this.runStatus() === 'failed');

  readonly isPosted = computed(() => {
    const detail = this.detail();
    return Boolean(detail?.posted_at && detail?.github_review_id);
  });

  /** edited_summary wins over summary when set (plan Q3). */
  readonly summaryText = computed(() => {
    const detail = this.detail();
    return detail?.edited_summary ?? detail?.summary ?? '';
  });

  readonly githubReviewUrl = computed(() => {
    const detail = this.detail();
    if (!detail?.github_review_id) {
      return null;
    }
    return (
      `https://github.com/${this.owner()}/${this.repo()}/pulls/` +
      `${this.number()}#pullrequestreview-${detail.github_review_id}`
    );
  });

  /** Comments grouped by file; ordered severity desc → file → line asc. */
  readonly fileGroups = computed<ReviewFileGroup[]>(() => {
    const comments = this.detail()?.comments ?? [];
    const sorted = [...comments].sort(
      (a, b) =>
        (SEVERITY_RANK[b.severity.toLowerCase()] ?? 0) -
          (SEVERITY_RANK[a.severity.toLowerCase()] ?? 0) ||
        a.file_path.localeCompare(b.file_path) ||
        (a.line_number ?? Number.MAX_SAFE_INTEGER) - (b.line_number ?? Number.MAX_SAFE_INTEGER)
    );
    const groups: ReviewFileGroup[] = [];
    const byFile = new Map<string, ReviewFileGroup>();
    for (const comment of sorted) {
      let group = byFile.get(comment.file_path);
      if (!group) {
        group = { file: comment.file_path, comments: [] };
        byFile.set(comment.file_path, group);
        groups.push(group);
      }
      group.comments.push(comment);
    }
    return groups;
  });

  /** `file:line` (or just the file for file-level comments). */
  locationLabel(comment: ReviewComment): string {
    return comment.line_number !== null
      ? `${comment.file_path}:${comment.line_number}`
      : comment.file_path;
  }
}
