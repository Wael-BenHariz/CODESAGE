import { Injectable, inject } from '@angular/core';
import { Observable, map, of, switchMap, tap } from 'rxjs';

import { ApiService } from './api.service';
import { RepositoryService } from './repository.service';
import { PullRequest } from '../models/pull-request.model';
import { ReviewSummary } from '../models/review.model';
import {
  PullRequestListDto,
  PullRequestWithReviewsDto,
  toPullRequestDetail,
  toPullRequestList
} from './mappers/pull-request.mapper';

/**
 * Deterministic "definitely does not exist" UUID — when a lookup finds
 * nothing, asking the backend under this id yields its genuine 404 (rule 5:
 * 404 → generic not-found page) instead of a synthesized client error.
 * Rationale in repository.service.ts.
 */
const NIL_UUID = '00000000-0000-0000-0000-000000000000';

/**
 * Safety cap for the by-number page scan (30 pages × 100 rows = 3000 PRs).
 * Beyond it the nil-UUID 404 applies — recorded in docs/BACKEND_GAPS_FOR_UI.md.
 */
const MAX_PAGE_SCAN = 30;

/**
 * `/pull-requests/*` route group (backend `app/api/routes/pull_requests.py`).
 *
 * The backend keys everything by UUID; the UI's owner/name/number URLs
 * resolve through `RepositoryService.resolveId()` (session-cached) plus a
 * bounded list scan for the PR number (also session-cached). Responses go
 * through the ONE mapping layer in `mappers/pull-request.mapper.ts`.
 * This replaces the phantom `/repositories/{owner}/{repo}/pulls` and
 * `/pulls/{owner}/{repo}/{number}` paths of Step 0.
 */
@Injectable({ providedIn: 'root' })
export class PullRequestService {
  private readonly api = inject(ApiService);
  private readonly repos = inject(RepositoryService);

  /** Session cache: `repositoryId#number` → pull-request UUID. */
  private readonly idCache = new Map<string, string>();

  /**
   * `GET /pull-requests/repository/{repository_id}` — paginated envelope,
   * mapped to `PullRequest[]`. Asks for up to 100 rows; the list page
   * filters client-side. `state` mirrors the backend query param.
   */
  getPullRequests(owner: string, repo: string, state?: string): Observable<PullRequest[]> {
    const params: Record<string, string | number> = { per_page: 100 };
    if (state) {
      params['state'] = state;
    }
    return this.repos.resolveId(owner, repo).pipe(
      switchMap(repoId =>
        this.api.get<PullRequestListDto>(`/pull-requests/repository/${repoId}`, params)
      ),
      map(toPullRequestList)
    );
  }

  /**
   * `GET /pull-requests/{pull_request_id}` — mapped with the detail mapper
   * (adds the latest-review pointer). The backend has no by-number lookup,
   * so the number resolves through the repo's PR list first.
   */
  getPullRequest(owner: string, repo: string, number: number): Observable<PullRequest> {
    const target = Number(number);
    return this.repos.resolveId(owner, repo).pipe(
      switchMap(repoId => this.findPullRequestId(repoId, target)),
      switchMap(prId => this.api.get<PullRequestWithReviewsDto>(`/pull-requests/${prId}`)),
      map(toPullRequestDetail)
    );
  }

  /** Cached by-number id resolution (bounded page scan, see scanPage). */
  private findPullRequestId(repoId: string, number: number): Observable<string> {
    const key = `${repoId}#${number}`;
    const cached = this.idCache.get(key);
    if (cached) {
      return of(cached);
    }
    return this.scanPage(repoId, number, 1).pipe(tap(id => this.idCache.set(key, id)));
  }

  /**
   * Scan the repo's PR list for `number` (open + closed alike — the route
   * returns every state unless filtered). Not found after the last page (or
   * the scan cap): genuine backend 404 via the nil UUID.
   */
  private scanPage(repoId: string, number: number, page: number): Observable<string> {
    return this.api
      .get<PullRequestListDto>(`/pull-requests/repository/${repoId}`, { per_page: 100, page })
      .pipe(
        switchMap(list => {
          const match = (list?.items ?? []).find(pr => pr.number === number);
          if (match) {
            return of(match.id);
          }
          const pages = list?.pages ?? 1;
          if (page < pages && page < MAX_PAGE_SCAN) {
            return this.scanPage(repoId, number, page + 1);
          }
          return this.api.get<PullRequestWithReviewsDto>(`/pull-requests/${NIL_UUID}`).pipe(
            map(() => {
              throw new Error('unreachable: a nonexistent pull request cannot be found');
            })
          );
        })
      );
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
