import { Component, HostListener, OnInit, computed, inject, input, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiError } from '../../../core/services/api.service';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { ReviewService } from '../../../core/services/review.service';
import { ToastService } from '../../../core/services/toast.service';
import {
  CommentValidation,
  ReviewComment,
  ReviewDetail,
  ScanFinding,
  ScanReport,
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

/** Client-side render cap for scan-only findings — huge scans must not flood the panel. */
const SCAN_LIST_CAP = 50;

/**
 * Group key joining a review comment back to its source static-analysis
 * finding: tool + rule_id + file_path (the columns migration 015 copies onto
 * comments). `\x1f` separators so concatenated fields can never collide —
 * same convention as the backend fingerprint().
 */
function scanGroupKey(tool: string, ruleId: string, filePath: string): string {
  return `${tool}\x1f${ruleId}\x1f${filePath}`;
}

/**
 * Index scan findings by their source rule (tool + rule_id + file_path),
 * several findings per key (same rule hit at different lines).
 */
export function indexScanFindings(findings: ScanFinding[]): Map<string, ScanFinding[]> {
  const index = new Map<string, ScanFinding[]>();
  for (const finding of findings) {
    const key = scanGroupKey(finding.tool, finding.rule_id, finding.file_path);
    const bucket = index.get(key);
    if (bucket) {
      bucket.push(finding);
    } else {
      index.set(key, [finding]);
    }
  }
  return index;
}

/**
 * The scan finding a comment came from — line-first (same rule at the same
 * line), then a line-less finding; a file-level comment (line null) matches
 * any finding of its rule. `null` = the comment carries no source-rule
 * columns (LLM-only comment) or the scan no longer has it (the scan report
 * is a snapshot — a rule deleted upstream must not break rendering).
 */
export function matchScanFinding(
  comment: ReviewComment,
  index: Map<string, ScanFinding[]>
): ScanFinding | null {
  if (!comment.tool || !comment.rule_id) {
    return null;
  }
  const bucket = index.get(scanGroupKey(comment.tool, comment.rule_id, comment.file_path));
  if (!bucket || bucket.length === 0) {
    return null;
  }
  if (comment.line_number !== null) {
    const exact = bucket.find(finding => finding.line_start === comment.line_number);
    if (exact) {
      return exact;
    }
  }
  return (
    bucket.find(finding => finding.line_start === null) ??
    (comment.line_number === null ? bucket[0] : null)
  );
}

/**
 * Findings of the scan that NO review comment covers (plan Step 3: they are
 * listed separately — never merged into the comments or the stats tiles).
 * A finding is covered when a comment shares its source rule and their lines
 * are compatible (equal, or one side line-less).
 */
export function uncoveredScanFindings(
  comments: ReviewComment[],
  findings: ScanFinding[]
): ScanFinding[] {
  const commentGroups = new Map<string, ReviewComment[]>();
  for (const comment of comments) {
    if (!comment.tool || !comment.rule_id) {
      continue;
    }
    const key = scanGroupKey(comment.tool, comment.rule_id, comment.file_path);
    const bucket = commentGroups.get(key);
    if (bucket) {
      bucket.push(comment);
    } else {
      commentGroups.set(key, [comment]);
    }
  }
  return findings.filter(finding => {
    const bucket = commentGroups.get(
      scanGroupKey(finding.tool, finding.rule_id, finding.file_path)
    );
    if (!bucket) {
      return true;
    }
    return !bucket.some(
      comment =>
        comment.line_number === null ||
        finding.line_start === null ||
        comment.line_number === finding.line_start
    );
  });
}

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
  private readonly toast = inject(ToastService);

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

  // --- Static-analysis report (plan Step 3) ---------------------------------
  /** The review's scan report; null while loading, absent (404) or failed. */
  readonly scanReport = signal<ScanReport | null>(null);
  /** Transient scan-report failure (non-404) — muted note; comments unaffected. */
  readonly scanLoadFailed = signal(false);

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
    this.scanReport.set(null);
    this.scanLoadFailed.set(false);
    // A (re)load supersedes any in-progress edit — the posted/staged view
    // below is read-only, an orphaned textarea must not survive a refresh.
    this.editingSummary.set(false);
    this.summaryDraft.set('');
    this.pullRequests.getPullRequestReviews(this.prId()).subscribe({
      next: reviews => {
        const latest = reviews[0]; // the endpoint orders created_at desc
        if (!latest) {
          this.detail.set(null);
          this.state.set('none');
          return;
        }
        const reviewId = latest.id;
        this.reviewApi.getReviewDetail(reviewId).subscribe({
          next: detail => {
            this.detail.set(detail);
            this.state.set('detail');
          },
          error: () => this.state.set('error')
        });
        // Parallel, failure-isolated: the scan report only enriches — its
        // absence or failure must never take the comments down with it.
        this.loadScanReport(reviewId);
      },
      error: () => this.state.set('error')
    });
  }

  /**
   * Fetch the scan report for enrichment. 404 = "no scan report yet" —
   * expected, silent (the interceptor lets it through, no navigation);
   * any other failure only flips the muted `scanLoadFailed` note.
   */
  private loadScanReport(reviewId: string): void {
    this.reviewApi.getScanReport(reviewId).subscribe({
      next: report => {
        if (report.review_id !== reviewId) {
          return; // stale response — a newer load() supersedes it
        }
        this.scanReport.set(report);
      },
      error: (err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          return; // absence, not a failure — no note, no navigation
        }
        this.scanLoadFailed.set(true);
      }
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

  // --- Scan-report enrichment (plan Step 3) ---------------------------------

  /** Findings grouped by source rule (tool + rule + file) — null before load. */
  readonly scanIndex = computed(() => {
    const report = this.scanReport();
    return report ? indexScanFindings(report.findings) : null;
  });

  /** Scan findings no review comment covers — listed separately, never merged. */
  readonly uncoveredFindings = computed(() => {
    const report = this.scanReport();
    if (!report) {
      return [];
    }
    return uncoveredScanFindings(this.detail()?.comments ?? [], report.findings);
  });

  /** Render slice of `uncoveredFindings` (client-side cap; counts stay exact). */
  readonly visibleUncovered = computed(() => this.uncoveredFindings().slice(0, SCAN_LIST_CAP));

  /** The comment's source finding (OWASP / fix suggestion), or null. */
  scanFindingFor(comment: ReviewComment): ScanFinding | null {
    const index = this.scanIndex();
    return index ? matchScanFinding(comment, index) : null;
  }

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
        // 409 = the review's state changed elsewhere (already posted / not
        // staged / not ready). The dialog's premise is stale: close it,
        // surface the backend's reason (a toast survives the re-fetch), and
        // reload the truth — plan Step 4.
        if (err instanceof ApiError && err.status === 409) {
          this.posting.set(false);
          this.postDialogOpen.set(false);
          this.actionError.set(null);
          this.toast.error(actionErrorMessage(err));
          this.load();
          return;
        }
        // Keep the dialog open so the failure is visible and retryable
        // (a GitHub failure answers 502 — nothing was posted).
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

  /**
   * Dirty-state warning when leaving the page (plan Step 4): a reload or tab
   * close while the summary editor holds unsaved changes is intercepted here;
   * in-app navigation is intercepted by the route's canDeactivate guard
   * (pr-detail.guard.ts), which reads the same two signals.
   */
  @HostListener('window:beforeunload', ['$event'])
  onBeforeUnload(event: Event): void {
    if (this.editingSummary() && this.summaryDirty()) {
      event.preventDefault();
      event.returnValue = false; // legacy browsers require the assignment
    }
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
    // Optimistic (plan Step 4): flip the row immediately — the pending lock
    // keeps the toggle unusable until the server answers with its truth.
    const snapshot = detail.comments;
    this.detail.update(current =>
      current
        ? {
            ...current,
            comments: current.comments.map(existing =>
              existing.id === comment.id ? { ...existing, dismissed } : existing
            )
          }
        : current
    );
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
        // Roll back the optimistic flip to the pre-click snapshot.
        this.pendingCommentId.set(null);
        this.detail.update(current => (current ? { ...current, comments: snapshot } : current));
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
