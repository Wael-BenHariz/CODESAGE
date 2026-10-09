/**
 * GitHub App install request (`/install-requests` routes, §2.5 request
 * flow: a non-admin member of an ORG workspace asks an ORG_ADMIN to
 * install the App). Fields mirror the wire payload (snake_case).
 */
export type InstallRequestStatus = 'PENDING' | 'APPROVED' | 'REJECTED';

export interface InstallRequest {
  id: string;
  workspace_id: string;
  requested_by: string;
  status: InstallRequestStatus;
  install_url: string | null;
  github_account_login: string | null;
  created_at: string;
  updated_at: string;
}

/** `PATCH …/approve|reject` response — carries the GitHub resolution. */
export interface InstallRequestResolution {
  id: string;
  status: InstallRequestStatus;
  resolved_by: string;
  resolved_at: string;
  github_error: string | null;
}

/** Query options for `GET /install-requests`. */
export interface InstallRequestQuery {
  workspaceId?: string;
  statusFilter?: InstallRequestStatus;
}
