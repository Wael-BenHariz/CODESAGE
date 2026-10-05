import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from './api.service';
import { PullRequest } from '../models/pull-request.model';
import { ReviewSummary } from '../models/review.model';

/**
 * `/pull-requests/*` route group (backend `app/api/routes/pull_requests.py`).
 *
 * The list/detail paths below still carry the phantom shapes that Step 2
 * replaces with `GET /pull-requests/repository/{repository_id}` and
 * `GET /pull-requests/{pull_request_id}` (UUID) plus the snake_case →
 * camelCase mapper for their responses.
 */
@Injectable({ providedIn: 'root' })
export class PullRequestService {
  private readonly api = inject(ApiService);

  /** Phantom path (`/repositories/{id}/pulls`) — replaced in Step 2. */
  getPullRequests(repoId: string, state?: string): Observable<PullRequest[]> {
    const params: Record<string, string | number> = {};
    if (state) {
      params['state'] = state;
    }
    return this.api.get<PullRequest[]>(`/repositories/${repoId}/pulls`, params);
  }

  /** Phantom path (`/pulls/{owner}/{repo}/{n}`) — replaced in Step 2. */
  getPullRequest(owner: string, repo: string, number: number): Observable<PullRequest> {
    return this.api.get<PullRequest>(`/pulls/${owner}/${repo}/${number}`);
  }

  /** `POST /pull-requests/{id}/review` — queues a run (status: pending). */
  triggerReview(prId: string): Observable<{ review_id: string; status: string; message: string }> {
    return this.api.post<{ review_id: string; status: string; message: string }>(
      `/pull-requests/${prId}/review`,
      {}
    );
  }

  /** `GET /pull-requests/{id}/reviews` — newest first (review panel input). */
  getPullRequestReviews(prId: string): Observable<ReviewSummary[]> {
    return this.api.get<ReviewSummary[]>(`/pull-requests/${prId}/reviews`);
  }
}
