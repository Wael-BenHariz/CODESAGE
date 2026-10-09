/** Roles assignable to a workspace member (backend `_MEMBER_ROLES`). */
export type WorkspaceRole = 'ORG_ADMIN' | 'REVIEWER' | 'DEVELOPER' | 'NONE';

/**
 * One membership row from `GET /workspaces/{id}/members`. `id` is null
 * when the membership comes from `org_members` only (no `workspace_members`
 * row yet) — the backend merges both tables.
 */
export interface WorkspaceMemberRow {
  id: string | null;
  user_id: string;
  username: string | null;
  role: WorkspaceRole;
  created_at: string | null;
  updated_at: string | null;
}

/** `PATCH /workspaces/{id}/members/{userId}` response (both rows updated). */
export interface WorkspaceMemberUpdate {
  id: string;
  user_id: string;
  role: WorkspaceRole;
  created_at: string;
  updated_at: string;
}
