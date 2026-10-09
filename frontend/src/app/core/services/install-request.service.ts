import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from './api.service';
import {
  InstallRequest,
  InstallRequestQuery,
  InstallRequestResolution
} from '../models/install-request.model';

/**
 * GitHub App install requests (`/install-requests`, §2.5). Creating
 * requires the `trigger` floor (DEVELOPER+) in the target workspace — the
 * flow a non-admin member of an ORG workspace uses to ask an ORG_ADMIN to
 * install the App. Approve/reject are ORG_ADMIN/PLATFORM_ADMIN (`repo_admin`).
 */
@Injectable({ providedIn: 'root' })
export class InstallRequestService {
  private readonly api = inject(ApiService);

  /** `workspace_id` is a required query parameter on POST there. */
  create(workspaceId: string): Observable<InstallRequest> {
    return this.api.post<InstallRequest>(
      `/install-requests?workspace_id=${encodeURIComponent(workspaceId)}`,
      {}
    );
  }

  list(query: InstallRequestQuery = {}): Observable<InstallRequest[]> {
    const params: Record<string, string> = {};
    if (query.workspaceId) params['workspace_id'] = query.workspaceId;
    if (query.statusFilter) params['status_filter'] = query.statusFilter;
    return this.api.get<InstallRequest[]>('/install-requests', params);
  }

  approve(requestId: string): Observable<InstallRequestResolution> {
    return this.api.patch<InstallRequestResolution>(`/install-requests/${requestId}/approve`, {});
  }

  reject(requestId: string): Observable<InstallRequestResolution> {
    return this.api.patch<InstallRequestResolution>(`/install-requests/${requestId}/reject`, {});
  }
}
