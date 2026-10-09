import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { DismissalRequestService } from './dismissal-request.service';

describe('DismissalRequestService — /dismissal-requests routes (§2.5)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: DismissalRequestService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post', 'patch']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(DismissalRequestService);
  });

  it('creates a request with comment id + reason as query parameters', () => {
    api.post.and.returnValue(of({}));

    service.create('c-1', 'false positive: dead code').subscribe();

    expect(api.post).toHaveBeenCalledWith(
      '/dismissal-requests?review_comment_id=c-1&reason=false%20positive%3A%20dead%20code',
      {}
    );
  });

  it('lists by review and status', () => {
    api.get.and.returnValue(of([]));

    service.list({ reviewId: 'r-1', statusFilter: 'PENDING' }).subscribe();

    expect(api.get).toHaveBeenCalledWith('/dismissal-requests', {
      review_id: 'r-1',
      status_filter: 'PENDING'
    });
  });

  it('approves a request', () => {
    api.patch.and.returnValue(of({}));

    service.approve('dr-1').subscribe();

    expect(api.patch).toHaveBeenCalledWith('/dismissal-requests/dr-1/approve', {});
  });

  it('rejects a request', () => {
    api.patch.and.returnValue(of({}));

    service.reject('dr-1').subscribe();

    expect(api.patch).toHaveBeenCalledWith('/dismissal-requests/dr-1/reject', {});
  });
});
