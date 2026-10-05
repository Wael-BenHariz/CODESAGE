import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from './api.service';
import {
  CommentValidation,
  ReviewComment,
  ReviewDetail,
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

  /** `GET /reviews/{id}` — summary + comments + viewer_role. */
  getReviewDetail(reviewId: string): Observable<ReviewDetail> {
    return this.api.get<ReviewDetail>(`/reviews/${reviewId}`);
  }

  /** `GET /reviews/{id}/status` — {status, progress} of a running review. */
  getReviewStatus(reviewId: string): Observable<{ status: string; progress: number }> {
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
    return this.api.patch(`/reviews/${reviewId}/summary`, { summary });
  }

  /** `PATCH …/dismiss` — excluded from the posted Findings body. */
  dismissReviewComment(reviewId: string, commentId: string): Observable<ReviewComment> {
    return this.api.patch(`/reviews/${reviewId}/comments/${commentId}/dismiss`, {});
  }

  /** `PATCH …/restore` — the finding returns to the staged body. */
  restoreReviewComment(reviewId: string, commentId: string): Observable<ReviewComment> {
    return this.api.patch(`/reviews/${reviewId}/comments/${commentId}/restore`, {});
  }

  /** `POST /reviews/{id}/post` — 409 = already posted / not ready. */
  postReview(reviewId: string): Observable<{
    review_id: string;
    github_review_id: number;
    posted_at: string;
    message: string;
  }> {
    return this.api.post(`/reviews/${reviewId}/post`, {});
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
    return this.api.patch(`/reviews/${reviewId}/comments/${commentId}/validate`, payload);
  }
}
