import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiService } from './api.service';
import { AppNotification, NotificationQuery } from '../models/notification.model';

/**
 * In-app notification routes (`/notifications`). Rows are the caller's
 * own (backend filters by user_id); the workspace filter additionally
 * requires membership in that workspace (uniform 404 otherwise).
 */
@Injectable({ providedIn: 'root' })
export class NotificationService {
  private readonly api = inject(ApiService);

  list(query: NotificationQuery = {}): Observable<AppNotification[]> {
    const params: Record<string, string | number> = {};
    if (query.workspaceId) params['workspace_id'] = query.workspaceId;
    if (query.unreadOnly) params['unread_only'] = 'true';
    if (query.limit !== undefined) params['limit'] = query.limit;
    if (query.offset !== undefined) params['offset'] = query.offset;
    return this.api.get<AppNotification[]>('/notifications', params);
  }

  markRead(notificationId: string): Observable<AppNotification> {
    return this.api.patch<AppNotification>(`/notifications/${notificationId}/read`, {});
  }

  markAllRead(): Observable<unknown> {
    return this.api.patch<unknown>('/notifications/read-all', {});
  }

  remove(notificationId: string): Observable<void> {
    return this.api.delete<void>(`/notifications/${notificationId}`);
  }
}
