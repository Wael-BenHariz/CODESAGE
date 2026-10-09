import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiService } from './api.service';
import { Workspace } from '../models/user.model';
import {
  WorkspaceMemberRow,
  WorkspaceMemberUpdate,
  WorkspaceRole
} from '../models/workspace-member.model';
import { WorkspaceDto, toWorkspace, toWorkspaceList } from './mappers/workspace.mapper';

/**
 * Workspace routes (`/workspaces`, §2.5 management): list, create ORG
 * workspaces (global ORG_ADMIN/PLATFORM_ADMIN), and member administration
 * (`repo_admin` in the workspace — the backend re-checks everything).
 * Reads return the server's capability flags via `toWorkspace` — never
 * re-derived client-side.
 */
@Injectable({ providedIn: 'root' })
export class WorkspaceService {
  private readonly api = inject(ApiService);

  list(): Observable<Workspace[]> {
    return this.api
      .get<WorkspaceDto[]>('/workspaces')
      .pipe(map(workspaces => toWorkspaceList(workspaces)));
  }

  /**
   * Creates an ORG workspace; the creator becomes its ORG_ADMIN. The name
   * travels as a query parameter (backend `Query(...)`) — hence the
   * hand-built query string on a POST with an empty body.
   */
  create(name: string, githubAccountLogin?: string): Observable<Workspace> {
    let endpoint = `/workspaces?name=${encodeURIComponent(name)}`;
    if (githubAccountLogin) {
      endpoint += `&github_account_login=${encodeURIComponent(githubAccountLogin)}`;
    }
    return this.api.post<WorkspaceDto>(endpoint, {}).pipe(map(toWorkspace));
  }

  remove(workspaceId: string): Observable<void> {
    return this.api.delete<void>(`/workspaces/${workspaceId}`);
  }

  members(workspaceId: string): Observable<WorkspaceMemberRow[]> {
    return this.api.get<WorkspaceMemberRow[]>(`/workspaces/${workspaceId}/members`);
  }

  /**
   * Changes a member's role — lands in BOTH membership tables on the
   * backend (authorization reads both, ladder max). `role` is a query
   * parameter there, not a body field.
   */
  updateMemberRole(
    workspaceId: string,
    userId: string,
    role: WorkspaceRole
  ): Observable<WorkspaceMemberUpdate> {
    return this.api.patch<WorkspaceMemberUpdate>(
      `/workspaces/${workspaceId}/members/${userId}?role=${role}`,
      {}
    );
  }

  removeMember(workspaceId: string, userId: string): Observable<void> {
    return this.api.delete<void>(`/workspaces/${workspaceId}/members/${userId}`);
  }
}
