/**
 * Review-comment dismissal request (`/dismissal-requests` routes, §2.5):
 * a member asks REVIEWER+ to dismiss a finding. Fields mirror the wire
 * payload (snake_case).
 */
export type DismissalRequestStatus = 'PENDING' | 'APPROVED' | 'REJECTED';

export interface DismissalRequest {
  id: string;
  review_comment_id: string;
  requested_by: string;
  reason: string;
  status: DismissalRequestStatus;
  review_id: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
}

/** `PATCH …/approve|reject` response. */
export interface DismissalRequestResolution {
  id: string;
  status: DismissalRequestStatus;
  resolved_by: string | null;
  resolved_at: string | null;
}

/** Query options for `GET /dismissal-requests`. */
export interface DismissalRequestQuery {
  reviewId?: string;
  statusFilter?: DismissalRequestStatus;
}
