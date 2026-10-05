import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiError } from '../../../core/services/api.service';
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

/** Mirrors backend `EDITED_SUMMARY_MAX_CHARS` (app/services/review_posting.py). */
const SUMMARY_MAX_CHARS = 60_000;

/** Human-readable text for a failed staged action (ApiError carries FastAPI detail). */
function actionErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.message) {
    return err.message;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return 'Request failed — please try again.';
}

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

  /** Client-side cap for the summary editor (backend rejects over-cap too). */
  readonly summaryMaxChars = SUMMARY_MAX_CHARS;

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

  // --- Staged posting controls (plan Step 8) --------------------------------
  /** Last API failure (post / summary / dismiss / restore) — surfaced visibly. */
  readonly actionError = signal<string | null>(null);
  readonly postDialogOpen = signal(false);
  readonly posting = signal(false);
  readonly editingSummary = signal(false);
  readonly summaryDraft = signal('');
  readonly savingSummary = signal(false);
  /** Comment id of an in-flight dismiss/restore (disables that button). */
  readonly pendingCommentId = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.state.set('loading');
    this.triggerError.set(false);
    this.actionError.set(null);
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

  /**
   * Whether the viewer may drive the staged flow: effective role >= DEVELOPER
   * (NONE is the only blocked role — it 403s on every write), the review is
   * staged (`ready_to_post`) and nothing has been posted yet.
   */
  readonly canEdit = computed(() => {
    const detail = this.detail();
    if (!detail || detail.viewer_role === 'NONE') {
      return false;
    }
    return detail.status === 'ready_to_post' && detail.posted_at === null;
  });

  /** Findings that go into the posted body (dismissed are excluded). */
  readonly pendingFindings = computed(() =>
    (this.detail()?.comments ?? []).filter(comment => !comment.dismissed)
  );

  readonly dismissedCount = computed(
    () => (this.detail()?.comments ?? []).filter(comment => comment.dismissed).length
  );

  readonly summaryDirty = computed(
    () => this.summaryDraft() !== (this.detail()?.edited_summary ?? this.detail()?.summary ?? '')
  );

  // --- Staged posting (Step 8) ---------------------------------------------

  openPostDialog(): void {
    this.actionError.set(null);
    this.postDialogOpen.set(true);
  }

  closePostDialog(): void {
    if (this.posting()) {
      return; // a post is in flight — wait for the result
    }
    this.postDialogOpen.set(false);
    this.actionError.set(null);
  }

  confirmPost(): void {
    const detail = this.detail();
    if (!detail || this.posting()) {
      return;
    }
    this.posting.set(true);
    this.actionError.set(null);
    this.github.postReview(detail.id).subscribe({
      next: () => {
        this.posting.set(false);
        this.postDialogOpen.set(false);
        this.load(); // re-fetch → read-only posted view (time + GitHub link)
      },
      error: (err: unknown) => {
        // Keep the dialog open so the failure is visible and retryable.
        this.posting.set(false);
        this.actionError.set(actionErrorMessage(err));
      }
    });
  }

  // --- Summary editing -------------------------------------------------------

  startEditSummary(): void {
    const detail = this.detail();
    if (!detail) {
      return;
    }
    this.summaryDraft.set(detail.edited_summary ?? detail.summary ?? '');
    this.editingSummary.set(true);
    this.actionError.set(null);
  }

  cancelEditSummary(): void {
    if (this.summaryDirty() && !window.confirm('Discard unsaved changes to the summary?')) {
      return; // dirty-state warning: keep editing until confirmed or saved
    }
    this.editingSummary.set(false);
    this.summaryDraft.set('');
  }

  onSummaryInput(event: Event): void {
    this.summaryDraft.set((event.target as HTMLTextAreaElement).value);
  }

  saveSummary(): void {
    const detail = this.detail();
    if (!detail || this.savingSummary()) {
      return;
    }
    const draft = this.summaryDraft();
    if (draft.length > this.summaryMaxChars) {
      this.actionError.set(
        `Summary is too long (${draft.length} / ${this.summaryMaxChars} characters).`
      );
      return;
    }
    this.savingSummary.set(true);
    this.actionError.set(null);
    this.github.updateReviewSummary(detail.id, draft).subscribe({
      next: response => {
        this.savingSummary.set(false);
        this.detail.update(current =>
          current ? { ...current, edited_summary: response.edited_summary } : current
        );
        this.editingSummary.set(false);
      },
      error: (err: unknown) => {
        this.savingSummary.set(false);
        this.actionError.set(actionErrorMessage(err));
      }
    });
  }

  // --- Per-finding dismiss / restore ----------------------------------------

  dismissFinding(comment: ReviewComment): void {
    this.setDismissed(comment, true);
  }

  restoreFinding(comment: ReviewComment): void {
    this.setDismissed(comment, false);
  }

  private setDismissed(comment: ReviewComment, dismissed: boolean): void {
    const detail = this.detail();
    if (!detail || this.pendingCommentId()) {
      return;
    }
    this.pendingCommentId.set(comment.id);
    this.actionError.set(null);
    const request = dismissed
      ? this.github.dismissReviewComment(detail.id, comment.id)
      : this.github.restoreReviewComment(detail.id, comment.id);
    request.subscribe({
      next: updated => {
        this.pendingCommentId.set(null);
        this.detail.update(current =>
          current
            ? {
                ...current,
                comments: current.comments.map(existing =>
                  existing.id === updated.id ? updated : existing
                )
              }
            : current
        );
      },
      error: (err: unknown) => {
        this.pendingCommentId.set(null);
        this.actionError.set(actionErrorMessage(err));
      }
    });
  }

  /** `file:line` (or just the file for file-level comments). */
  locationLabel(comment: ReviewComment): string {
    return comment.line_number !== null
      ? `${comment.file_path}:${comment.line_number}`
      : comment.file_path;
  }
}
