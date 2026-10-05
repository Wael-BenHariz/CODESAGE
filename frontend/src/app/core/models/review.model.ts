/**
 * Review payloads for the PR-detail review panel (plan Step 7b).
 *
 * Field names mirror the backend JSON exactly (`ReviewResponse`,
 * `ReviewWithComments` and `ReviewCommentResponse` in
 * `backend/app/schemas/review.py`) — the API returns snake_case.
 */

export type ReviewRunStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'ready_to_post';

/** Verdict a reviewer gives on one finding (plan Step 9 / migration 016). */
export type ValidationVerdict = 'confirmed' | 'false_positive' | 'needs_investigation';

/** Severity a reviewer may assign instead of the finding's original. */
export type ValidationSeverity = 'info' | 'warning' | 'error' | 'suggestion';

/** One row from `GET /pull-requests/{id}/reviews` (newest first, no comments). */
export interface ReviewSummary {
  id: string;
  pull_request_id: string;
  user_id: string | null;
  status: ReviewRunStatus;
  error_message: string | null;
  summary: string | null;
  posting_mode: string;
  posted_at: string | null;
  edited_summary: string | null;
  github_review_id: number | null;
  overall_severity: string | null;
  created_at: string;
  completed_at: string | null;
}

/**
 * One reviewer's verdict on one finding (plan Step 9 — `CommentValidation`
 * in `backend/app/schemas/review.py`). One row per reviewer, newest first.
 */
export interface CommentValidation {
  verdict: ValidationVerdict;
  /** Null keeps the finding's original severity. */
  severity_override: ValidationSeverity | null;
  /** Plain text, stored as-is — rendered through interpolation only. */
  note: string | null;
  reviewer_login: string;
  created_at: string;
  updated_at: string;
}

/** A comment on a review, incl. the Step 7b source-finding enrichment. */
export interface ReviewComment {
  id: string;
  review_id: string;
  file_path: string;
  line_number: number | null;
  body: string;
  severity: string;
  category: string;
  resolved: boolean;
  /** Excluded from the staged Findings section when true — muted, not hidden. */
  dismissed: boolean;
  created_at: string;
  /** Enrichment (migration 015): null when unmatched or pre-015. */
  tool: string | null;
  rule_id: string | null;
  cwe: string[] | null;
  line_start: number | null;
  line_end: number | null;
  snippet: string | null;
  also_detected_by: string[] | null;
  /** Reviewer verdicts (Step 9): newest first; empty until judged. */
  validations: CommentValidation[];
}

/** Full detail from `GET /reviews/{id}` — summary + comments + viewer role. */
export interface ReviewDetail extends ReviewSummary {
  comments_count: number;
  comments: ReviewComment[];
  /** Caller's effective org role — cosmetic; the backend stays authoritative. */
  viewer_role: string;
}
