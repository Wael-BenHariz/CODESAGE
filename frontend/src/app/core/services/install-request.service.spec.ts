import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { InstallRequestService } from './install-request.service';

describe('InstallRequestService — /install-requests routes (§2.5)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: InstallRequestService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post', 'patch']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(InstallRequestService);
  });

  it('creates a request with workspace_id as a query parameter', () => {
    api.post.and.returnValue(of({}));

    service.create('ws-1').subscribe();

    expect(api.post).toHaveBeenCalledWith('/install-requests?workspace_id=ws-1', {});
  });

  it('lists with workspace + status filters', () => {
    api.get.and.returnValue(of([]));

    service.list({ workspaceId: 'ws-1', statusFilter: 'PENDING' }).subscribe();

    expect(api.get).toHaveBeenCalledWith('/install-requests', {
      workspace_id: 'ws-1',
      status_filter: 'PENDING'
    });
  });

  it('approves a request', () => {
    api.patch.and.returnValue(of({}));

    service.approve('req-1').subscribe();

    expect(api.patch).toHaveBeenCalledWith('/install-requests/req-1/approve', {});
  });

  it('rejects a request', () => {
    api.patch.and.returnValue(of({}));

    service.reject('req-1').subscribe();

    expect(api.patch).toHaveBeenCalledWith('/install-requests/req-1/reject', {});
  });
});
