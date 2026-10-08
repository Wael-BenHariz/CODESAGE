/**
 * Org invitation shapes (plan Step 12 + repo-scoped grants) — mirrors of
 * the backend schemas, snake_case exactly as the API returns them.
 */

/** The only roles an invitation may grant (backend Literal + migration 017 CHECK). */
export type InvitableRole = 'DEVELOPER' | 'REVIEWER';

export type InvitationStatus = 'pending' | 'accepted' | 'revoked' | 'expired';

/** One row of GET /orgs/{orgId}/invitations — never carries token material. */
export interface OrgInvitation {
  id: string;
  email: string;
  role: InvitableRole;
  status: InvitationStatus;
  expires_at: string;
  created_at: string;
  invited_by: string | null;
  /** `repositories.id` rows granted with `role` — empty = org-only invite. */
  repository_ids: string[];
  /** The same ids resolved to `owner/repo` for display (backend joins them). */
  repositories: string[];
  /**
   * Joined GitHub-collaborator failures from the accept pass, null when
   * everything succeeded (or the invite was never accepted). Presence here
   * is a warning, never an error — the invite itself is valid.
   */
  github_error: string | null;
}

/** Public GET /invitations/{token} — masked address, no inviter identity. */
export interface InvitationPreview {
  org_name: string;
  role: InvitableRole;
  email_masked: string;
  /** What the link grants: `owner/repo` names (ids are never exposed). */
  repositories: string[];
}

/** POST /invitations/{token}/accept. */
export interface InvitationAcceptResult {
  org_id: string;
  org_name: string;
  role: string;
  /** Authoritative server-side verdict (both addresses present and different). */
  email_mismatch: boolean;
  /** GitHub collaborator failures for the granted repos (null = all good). */
  github_error: string | null;
}

/** POST /orgs/{orgId}/invitations body — one role for the whole selection. */
export interface InvitationCreatePayload {
  email: string;
  role: InvitableRole;
  /** `repositories.id` rows; omitted/empty keeps the org-only behaviour. */
  repository_ids?: string[];
}

/**
 * The backend's masking shape (`local[:2] + "***" + @domain`) as a pure
 * function — lets the accept page compare a preview against the signed-in
 * account's email locally, without sending the address anywhere.
 */
export function maskEmail(email: string): string {
  const at = email.indexOf('@');
  if (at < 0) {
    return '***';
  }
  return `${email.slice(0, 2)}***${email.slice(at)}`;
}
