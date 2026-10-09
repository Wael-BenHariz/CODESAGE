/**
 * In-app notification (`/notifications` routes, workspace RBAC §2.5).
 * Fields mirror the wire payload exactly (snake_case), like the
 * invitation/review models.
 */
export interface AppNotification {
  id: string;
  workspace_id: string | null;
  type: string;
  title: string;
  message: string;
  is_read: boolean;
  related_id: string | null;
  related_type: string | null;
  created_at: string;
  updated_at: string;
}

/** Query options for `GET /notifications`. */
export interface NotificationQuery {
  workspaceId?: string;
  unreadOnly?: boolean;
  limit?: number;
  offset?: number;
}
