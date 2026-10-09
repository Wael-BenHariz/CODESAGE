import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { NotificationService } from './notification.service';

describe('NotificationService — /notifications routes', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: NotificationService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'patch', 'delete']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(NotificationService);
  });

  it('lists the caller notifications with no filters by default', () => {
    api.get.and.returnValue(of([]));

    service.list().subscribe();

    expect(api.get).toHaveBeenCalledWith('/notifications', {});
  });

  it('forwards workspace, unread and paging filters as snake_case params', () => {
    api.get.and.returnValue(of([]));

    service.list({ workspaceId: 'ws-1', unreadOnly: true, limit: 20, offset: 40 }).subscribe();

    expect(api.get).toHaveBeenCalledWith('/notifications', {
      workspace_id: 'ws-1',
      unread_only: 'true',
      limit: 20,
      offset: 40
    });
  });

  it('marks one notification read', () => {
    api.patch.and.returnValue(of({}));

    service.markRead('n-1').subscribe();

    expect(api.patch).toHaveBeenCalledWith('/notifications/n-1/read', {});
  });

  it('marks all notifications read', () => {
    api.patch.and.returnValue(of({}));

    service.markAllRead().subscribe();

    expect(api.patch).toHaveBeenCalledWith('/notifications/read-all', {});
  });

  it('deletes a notification', () => {
    api.delete.and.returnValue(of(void 0));

    service.remove('n-1').subscribe();

    expect(api.delete).toHaveBeenCalledWith('/notifications/n-1');
  });
});
