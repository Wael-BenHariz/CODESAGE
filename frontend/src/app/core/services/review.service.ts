import { Injectable, inject } from '@angular/core';
import { Observable, Subject, shareReplay, tap } from 'rxjs';

import { ApiService } from './api.service';
import { PaginatedResponse } from '../models/pagination.model';
import {
  CommentValidation,
  ReviewComment,
  ReviewDetail,
  ReviewSummary,
  ScanReport,
  ValidationSeverity,
  ValidationVerdict
} from '../models/review.model';

/**
 * `/reviews/*` route group (backend `app/api/routes/reviews.py`).
 *
 * Response payloads are rendered through `core/models/review.model.ts`,
 * which mirrors the API's snake_case fields 1:1 (the review group does no
 * renaming — components bind the wire shape directly).
 *
 * Staged + validation routes are org-scoped writes with NO platform-admin
 * bypass on the backend; the review panel gates them cosmetically on
 * `viewer_role` and the API stays authoritative.
 */
@Injectable({ providedIn: 'root' })
export class ReviewService {
  private readonly api = inject(ApiService);

  /**
   * `GET /reviews` — the caller-visible list (org-scoped F3; PLATFORM_ADMIN
   * sees everything), newest first. `statusFilter` maps to the backend's
   * `status_filter` query param, which filters BOTH the items and the
   * envelope `total` (plan Step 10: dashboard review counts).
   */
  listReviews(
    page = 1,
    perPage = 20,
    statusFilter?: string
  ): Observable<PaginatedResponse<ReviewSummary>> {
    const params: Record<string, number | string> = { page, per_page: perPage };
    if (statusFilter) {
      params['status_filter'] = statusFilter;
    }
    return this.api.get<PaginatedResponse<ReviewSummary>>('/reviews', params);
  }

  /** Session cache of `GET /reviews/{id}` observables — see getReviewDetail(). */
  private readonly detailCache = new Map<string, Observable<ReviewDetail>>();
  /** Session cache of `GET /reviews/{id}/scan-report` — see getScanReport(). */
  private readonly scanCache = new Map<string, Observable<ScanReport>>();
  private readonly invalidations = new Subject<string>();

  /**
   * Emits a review id whenever its cached detail may be stale (a mutation
   * succeeded). The PR page's stats bar listens and refetches, so its tiles
   * and the review panel's own numbers update together (plan Step 2, Q1).
   */
  readonly reviewDetailInvalidated$ = this.invalidations.asObservable();

  /**
   * `GET /reviews/{id}` — summary + comments + viewer_role, shared and
   * cached per review id: the PR page's stats bar and the review panel
   * subscribe to the SAME observable, so one page load makes exactly one
   * request per review id. A failed request evicts the entry (the next call
   * refetches), and every mutation below invalidates it so refetched data
   * reflects the change.
   */
  getReviewDetail(reviewId: string): Observable<ReviewDetail> {
    const cached = this.detailCache.get(reviewId);
    if (cached) {
      return cached;
    }
    const shared$ = this.api
      .get<ReviewDetail>(`/reviews/${reviewId}`)
      .pipe(
        tap({ error: () => this.detailCache.delete(reviewId) }),
        shareReplay({ bufferSize: 1, refCount: false })
      );
    this.detailCache.set(reviewId, shared$);
    return shared$;
  }

  /**
   * `GET /reviews/{id}/scan-report` — static-analysis results for one review
   * (tools run/failed + unified findings), cached per review id: a scan
   * report is immutable after creation, so the session cache never
   * invalidates; a failed request evicts the entry (retry refetches).
   *
   * 404 means "this review has no scan report yet" — an EXPECTED absence the
   * ErrorInterceptor must not navigate on (the interceptor lets
   * `…/scan-report` 404s through; the panel treats them as "no report").
   */
  getScanReport(reviewId: string): Observable<ScanReport> {
    const cached = this.scanCache.get(reviewId);
    if (cached) {
      return cached;
    }
    const shared$ = this.api
      .get<ScanReport>(`/reviews/${reviewId}/scan-report`)
      .pipe(
        tap({ error: () => this.scanCache.delete(reviewId) }),
        shareReplay({ bufferSize: 1, refCount: false })
      );
    this.scanCache.set(reviewId, shared$);
    return shared$;
  }

  /** Drop the cached detail and notify listeners (stats bar refetches). */
  private invalidateDetail(reviewId: string): void {
    this.detailCache.delete(reviewId);
    this.invalidations.next(reviewId);
  }

  /**
   * `GET /reviews/{id}/status` — {status, progress} of a running review.
   * Silently drops the cached detail: polling implies the run is evolving,
   * so the next explicit fetch must not replay pre-completion data. No
   * invalidation event — pollers drive their own refetch.
   */
  getReviewStatus(reviewId: string): Observable<{ status: string; progress: number }> {
    this.detailCache.delete(reviewId);
    return this.api.get<{ status: string; progress: number }>(`/reviews/${reviewId}/status`);
  }

  /** `PATCH /reviews/{id}/summary` — edited staged summary (≤60 000 chars). */
  updateReviewSummary(
    reviewId: string,
    summary: string
  ): Observable<{
    review_id: string;
    summary: string | null;
    edited_summary: string | null;
    status: string;
    posted_at: string | null;
  }> {
    return this.api
      .patch<{
        review_id: string;
        summary: string | null;
        edited_summary: string | null;
        status: string;
        posted_at: string | null;
      }>(`/reviews/${reviewId}/summary`, { summary })
      .pipe(tap({ next: () => this.invalidateDetail(reviewId) }));
  }

  /** `PATCH …/dismiss` — excluded from the posted Findings body. */
  dismissReviewComment(reviewId: string, commentId: string): Observable<ReviewComment> {
    return this.api
      .patch<ReviewComment>(`/reviews/${reviewId}/comments/${commentId}/dismiss`, {})
      .pipe(tap({ next: () => this.invalidateDetail(reviewId) }));
  }

  /** `PATCH …/restore` — the finding returns to the staged body. */
  restoreReviewComment(reviewId: string, commentId: string): Observable<ReviewComment> {
    return this.api
      .patch<ReviewComment>(`/reviews/${reviewId}/comments/${commentId}/restore`, {})
      .pipe(tap({ next: () => this.invalidateDetail(reviewId) }));
  }

  /** `POST /reviews/{id}/post` — 409 = already posted / not ready. */
  postReview(reviewId: string): Observable<{
    review_id: string;
    github_review_id: number;
    posted_at: string;
    message: string;
  }> {
    return this.api
      .post<{
        review_id: string;
        github_review_id: number;
        posted_at: string;
        message: string;
      }>(`/reviews/${reviewId}/post`, {})
      .pipe(tap({ next: () => this.invalidateDetail(reviewId) }));
  }

  /**
   * `PATCH …/validate` — upsert the caller's verdict for one finding.
   * Backend: member + effective role >= REVIEWER (no platform-admin bypass).
   */
  validateReviewFinding(
    reviewId: string,
    commentId: string,
    payload: {
      verdict: ValidationVerdict;
      severity_override?: ValidationSeverity | null;
      note?: string | null;
    }
  ): Observable<CommentValidation> {
    return this.api
      .patch<CommentValidation>(`/reviews/${reviewId}/comments/${commentId}/validate`, payload)
      .pipe(tap({ next: () => this.invalidateDetail(reviewId) }));
  }
}
