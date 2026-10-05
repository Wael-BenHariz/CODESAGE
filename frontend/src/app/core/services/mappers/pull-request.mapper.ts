import {
  PullRequest,
  PullRequestReviewState,
  PullRequestState
} from '../../models/pull-request.model';
import { ReviewDetail } from '../../models/review.model';
import { PaginatedResponse } from '../../models/pagination.model';

/**
 * Pull-request route group (`/pull-requests/*`) mapping layer — the ONE
 * place snake_case PR payloads become the camelCase `PullRequest` model
 * (Step 0 constraint #3). Pure functions, no HTTP.
 *
 * Wire shape: `PullRequestResponse` / `PullRequestListResponse` /
 * `PullRequestWithReviews` in `backend/app/schemas/pull_request.py`.
 * Every field is optional at the DTO level so a partial or older payload
 * degrades to empty values instead of throwing.
 */
export interface PullRequestDto {
  id: string;
  repository_id?: string;
  github_pr_id?: number;
  number: number;
  title?: string;
  body?: string | null;
  state?: string | null;
  author_login?: string | null;
  author_avatar_url?: string | null;
  base_branch?: string | null;
  head_branch?: string | null;
  base_sha?: string | null;
  head_sha?: string | null;
  additions?: number;
  deletions?: number;
  changed_files?: number;
  created_at?: string;
  updated_at?: string;
}

/** Detail response: base PR fields + the latest-review pointer. */
export interface PullRequestWithReviewsDto extends PullRequestDto {
  reviews_count?: number;
  latest_review_id?: string | null;
  latest_review_status?: string | null;
}

export type PullRequestListDto = PaginatedResponse<PullRequestDto>;

const PR_STATES = new Set<PullRequestState>(['open', 'closed', 'merged']);

const PR_REVIEW_STATES = new Set<PullRequestReviewState>([
  'pending',
  'processing',
  'in_progress',
  'ready_to_post',
  'completed',
  'failed'
]);

/** Unknown or missing enum → the safe `unknown` display value, never a guess. */
export function toPullRequestState(value: string | null | undefined): PullRequestState {
  const normalized = (value ?? '').toLowerCase();
  return PR_STATES.has(normalized as PullRequestState)
    ? (normalized as PullRequestState)
    : 'unknown';
}

function toPullRequestReviewState(value: string | null | undefined): PullRequestReviewState {
  const normalized = (value ?? '').toLowerCase();
  return PR_REVIEW_STATES.has(normalized as PullRequestReviewState)
    ? (normalized as PullRequestReviewState)
    : 'unknown';
}

function toPullRequest(dto: PullRequestDto): PullRequest {
  return {
    id: dto.id ?? '',
    repositoryId: dto.repository_id ?? '',
    number: typeof dto.number === 'number' ? dto.number : 0,
    title: dto.title ?? '',
    body: dto.body ?? null,
    state: toPullRequestState(dto.state),
    author: {
      login: dto.author_login ?? '',
      avatarUrl: dto.author_avatar_url ?? ''
    },
    baseBranch: dto.base_branch ?? '',
    headBranch: dto.head_branch ?? '',
    additions: dto.additions ?? 0,
    deletions: dto.deletions ?? 0,
    changedFiles: dto.changed_files ?? 0,
    // List rows carry NO review fields on the wire (`PullRequestResponse`),
    // so the list badge can never render stale or guessed review data.
    reviewStatus: null,
    createdAt: dto.created_at ?? '',
    updatedAt: dto.updated_at ?? ''
  };
}

export function toPullRequestList(dto: PullRequestListDto): PullRequest[] {
  return (dto?.items ?? []).map(toPullRequest);
}

/**
 * Detail mapping: the only place `latest_review_*` becomes the review
 * pointer. Missing `latest_review_id` ⇒ no review (tiles stay hidden and no
 * extra request is made — plan Step 2 constraint #5).
 */
export function toPullRequestDetail(dto: PullRequestWithReviewsDto): PullRequest {
  const base = toPullRequest(dto);
  if (!dto.latest_review_id) {
    return base;
  }
  return {
    ...base,
    reviewStatus: {
      status: toPullRequestReviewState(dto.latest_review_status),
      reviewId: dto.latest_review_id
    }
  };
}

/**
 * Stats-bar numbers for the PR page, derived from `GET /reviews/{id}`
 * (plan Step 2, Q1/Option 1):
 *
 * - **Comments** = the review's `comments_count` exactly as the API returns
 *   it; if that field is missing, fall back to the length of the returned
 *   list only when a list is present.
 * - **Open issues** = comments in the SAME response with `dismissed = false`
 *   — derived in the frontend because the backend has no issue count. The
 *   label in the template is "open issues" so it is not read as a
 *   backend-defined total.
 * - Scan-report findings are NEVER counted here (they are not comments) and
 *   the two sources are never added together.
 * - A `null` means "unavailable" — the caller must render it as such, never
 *   as 0 (a zero must only mean a real zero).
 *
 * List completeness: the backend route returns ALL comments of the review
 * (`comments_count = len(review.comments)`, no pagination), so counting the
 * returned list is safe. If a future backend paginates `comments`, the list
 * branch here must be disabled and "open issues" marked unavailable — see
 * docs/BACKEND_GAPS_FOR_UI.md.
 */
export interface ReviewStats {
  comments: number | null;
  openIssues: number | null;
}

export function deriveReviewStats(detail: ReviewDetail): ReviewStats {
  const list = Array.isArray(detail?.comments) ? detail.comments : null;
  const countFromWire = typeof detail?.comments_count === 'number' ? detail.comments_count : null;
  return {
    comments: countFromWire ?? (list ? list.length : null),
    openIssues: list ? list.filter(comment => comment && !comment.dismissed).length : null
  };
}
