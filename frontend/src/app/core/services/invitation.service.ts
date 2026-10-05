import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from './api.service';
import {
  InvitableRole,
  InvitationAcceptResult,
  InvitationPreview,
  OrgInvitation
} from '../models/invitation.model';

/**
 * Org invitations (plan Steps 11–12).
 *
 * The org-nested routes carry the org id in the path (the backend
 * authorizes membership + role there); the token routes are the public
 * preview and the authenticated accept. The raw token exists only in the
 * emailed link and in those URL paths — it is never logged or persisted
 * client-side (no analytics exist; keep it out of `console` all the same).
 */
@Injectable({ providedIn: 'root' })
export class InvitationService {
  private readonly api = inject(ApiService);

  list(orgId: string): Observable<OrgInvitation[]> {
    return this.api.get<OrgInvitation[]>(`/orgs/${orgId}/invitations`);
  }

  create(
    orgId: string,
    payload: { email: string; role: InvitableRole }
  ): Observable<OrgInvitation> {
    return this.api.post<OrgInvitation>(`/orgs/${orgId}/invitations`, payload);
  }

  revoke(orgId: string, invitationId: string): Observable<void> {
    return this.api.delete<void>(`/orgs/${orgId}/invitations/${invitationId}`);
  }

  preview(token: string): Observable<InvitationPreview> {
    return this.api.get<InvitationPreview>(`/invitations/${encodeURIComponent(token)}`);
  }

  accept(token: string): Observable<InvitationAcceptResult> {
    return this.api.post<InvitationAcceptResult>(
      `/invitations/${encodeURIComponent(token)}/accept`,
      {}
    );
  }
}
