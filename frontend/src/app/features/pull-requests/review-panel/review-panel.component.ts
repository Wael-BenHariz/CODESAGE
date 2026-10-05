import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiError } from '../../../core/services/api.service';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { ReviewService } from '../../../core/services/review.service';
import {
  CommentValidation,
  ReviewComment,
  ReviewDetail,
  ValidationSeverity,
  ValidationVerdict
} from '../../../core/models/review.model';

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

/** Login shown on the optimistic verdict row — the client never guesses identity. */
const PENDING_LOGIN = '(you)';

/** Per-comment draft of the Step 10 severity-override + note inputs. */
interface ValidationDraft {
  severity: ValidationSeverity | '';
  note: string;
}

/**
 * Upsert one verdict into a comment's list (plan Step 9: one row per
 * reviewer): the incoming row replaces any row for the same reviewer and
 * any pending placeholder; ordering stays newest-first (`updated_at` desc).
 */
function withValidation(
  validations: CommentValidation[],
  incoming: CommentValidation
): CommentValidation[] {
  const next = validations.filter(
    v => v.reviewer_login !== incoming.reviewer_login && v.reviewer_login !== PENDING_LOGIN
  );
  next.push(incoming);
  return next.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
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
  private readonly pullRequests = inject(PullRequestService);
  private readonly reviewApi = inject(ReviewService);

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

  // --- Reviewer validation (plan Step 10) -----------------------------------
  /** Comment id of the in-flight verdict upsert — one at a time → safe rollback. */
  readonly validatingCommentId = signal<string | null>(null);
  /** Per-comment draft of the severity-override + note inputs (keyed by comment id). */
  readonly validationDrafts = signal<Record<string, ValidationDraft>>({});

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.state.set('loading');
    this.triggerError.set(false);
    this.actionError.set(null);
    this.pullRequests.getPullRequestReviews(this.prId()).subscribe({
      next: reviews => {
        const latest = reviews[0]; // the endpoint orders created_at desc
        if (!latest) {
          this.detail.set(null);
          this.state.set('none');
          return;
        }
        this.reviewApi.getReviewDetail(latest.id).subscribe({
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
    this.pullRequests.triggerReview(this.prId()).subscribe({
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
    this.reviewApi.postReview(detail.id).subscribe({
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
    this.reviewApi.updateReviewSummary(detail.id, draft).subscribe({
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
      ? this.reviewApi.dismissReviewComment(detail.id, comment.id)
      : this.reviewApi.restoreReviewComment(detail.id, comment.id);
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

  // --- Reviewer validation (Step 10) ----------------------------------------

  /**
   * Gate on the verdict controls: effective role >= REVIEWER — exactly the
   * plan's condition (the guarded backend enforces it; this is cosmetic).
   * Existing verdicts stay visible to every viewer regardless.
   */
  readonly canValidate = computed(() => {
    const role = this.detail()?.viewer_role;
    return role === 'REVIEWER' || role === 'ORG_ADMIN' || role === 'PLATFORM_ADMIN';
  });

  validationSeverity(commentId: string): ValidationSeverity | '' {
    return this.validationDrafts()[commentId]?.severity ?? '';
  }

  validationNote(commentId: string): string {
    return this.validationDrafts()[commentId]?.note ?? '';
  }

  onValidationSeverityChange(commentId: string, event: Event): void {
    const severity = (event.target as HTMLSelectElement).value as ValidationSeverity | '';
    this.validationDrafts.update(drafts => ({
      ...drafts,
      [commentId]: { severity, note: this.validationNote(commentId) }
    }));
  }

  onValidationNoteChange(commentId: string, event: Event): void {
    const note = (event.target as HTMLInputElement).value;
    this.validationDrafts.update(drafts => ({
      ...drafts,
      [commentId]: { severity: this.validationSeverity(commentId), note }
    }));
  }

  /** Stored verdict value → display text. */
  verdictLabel(verdict: string): string {
    if (verdict === 'false_positive') {
      return 'false positive';
    }
    if (verdict === 'needs_investigation') {
      return 'needs investigation';
    }
    return verdict;
  }

  /**
   * Submit the caller's verdict for one finding: optimistic pending row
   * first, the server row on success, snapshot rollback + error strip on
   * failure (plan Step 10's optimistic update with rollback).
   */
  submitValidation(comment: ReviewComment, verdict: ValidationVerdict): void {
    const detail = this.detail();
    if (!detail || this.validatingCommentId()) {
      return;
    }
    const draft = this.validationDrafts()[comment.id] ?? { severity: '', note: '' };
    const trimmedNote = draft.note.trim();
    const payload = {
      verdict,
      severity_override: draft.severity === '' ? null : draft.severity,
      note: trimmedNote === '' ? null : trimmedNote
    };

    const snapshot = detail; // rollback point — detail is only ever replaced wholesale
    const now = new Date().toISOString();
    this.validatingCommentId.set(comment.id);
    this.actionError.set(null);
    this.detail.update(current =>
      current
        ? {
            ...current,
            comments: current.comments.map(existing =>
              existing.id === comment.id
                ? {
                    ...existing,
                    validations: withValidation(existing.validations, {
                      verdict: payload.verdict,
                      severity_override: payload.severity_override,
                      note: payload.note,
                      reviewer_login: PENDING_LOGIN,
                      created_at: now,
                      updated_at: now
                    })
                  }
                : existing
            )
          }
        : current
    );

    this.reviewApi.validateReviewFinding(detail.id, comment.id, payload).subscribe({
      next: validation => {
        this.validatingCommentId.set(null);
        // Server row is the truth: it replaces the pending row (and any
        // older verdict of the same reviewer — one row per reviewer).
        this.detail.update(current =>
          current
            ? {
                ...current,
                comments: current.comments.map(existing =>
                  existing.id === comment.id
                    ? {
                        ...existing,
                        validations: withValidation(existing.validations, validation)
                      }
                    : existing
                )
              }
            : current
        );
        this.validationDrafts.update(drafts => {
          const rest = { ...drafts };
          delete rest[comment.id];
          return rest;
        });
      },
      error: (err: unknown) => {
        this.validatingCommentId.set(null);
        this.detail.set(snapshot); // rollback the optimistic row
        this.actionError.set(actionErrorMessage(err));
      }
    });
  }
}
