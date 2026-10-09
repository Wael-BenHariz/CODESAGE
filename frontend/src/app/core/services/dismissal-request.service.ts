import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from './api.service';
import {
  DismissalRequest,
  DismissalRequestQuery,
  DismissalRequestResolution
} from '../models/dismissal-request.model';

/**
 * Review-comment dismissal requests (`/dismissal-requests`, §2.5): any
 * write-role member may request; approve/reject are REVIEWER+ on the
 * review route (`review` floor there). Both route params travel as query
 * parameters on the backend.
 */
@Injectable({ providedIn: 'root' })
export class DismissalRequestService {
  private readonly api = inject(ApiService);

  create(reviewCommentId: string, reason: string): Observable<DismissalRequest> {
    return this.api.post<DismissalRequest>(
      `/dismissal-requests?review_comment_id=${encodeURIComponent(reviewCommentId)}` +
        `&reason=${encodeURIComponent(reason)}`,
      {}
    );
  }

  list(query: DismissalRequestQuery = {}): Observable<DismissalRequest[]> {
    const params: Record<string, string> = {};
    if (query.reviewId) params['review_id'] = query.reviewId;
    if (query.statusFilter) params['status_filter'] = query.statusFilter;
    return this.api.get<DismissalRequest[]>('/dismissal-requests', params);
  }

  approve(requestId: string): Observable<DismissalRequestResolution> {
    return this.api.patch<DismissalRequestResolution>(
      `/dismissal-requests/${requestId}/approve`,
      {}
    );
  }

  reject(requestId: string): Observable<DismissalRequestResolution> {
    return this.api.patch<DismissalRequestResolution>(
      `/dismissal-requests/${requestId}/reject`,
      {}
    );
  }
}
