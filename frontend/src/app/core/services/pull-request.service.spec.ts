import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { PullRequestService } from './pull-request.service';

describe('PullRequestService (/pull-requests group)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: PullRequestService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(PullRequestService);
  });

  it('triggers reviews on the backend mount point /pull-requests/{id}/review', () => {
    api.post.and.returnValue(of({ review_id: 'r1', status: 'pending', message: 'ok' }));

    service.triggerReview('pr-9').subscribe();

    // Regression guard: the old path was /pulls/…, which the API never served.
    expect(api.post).toHaveBeenCalledWith('/pull-requests/pr-9/review', {});
  });

  it('lists PR reviews from /pull-requests/{id}/reviews', () => {
    api.get.and.returnValue(of([]));

    service.getPullRequestReviews('pr-9').subscribe();

    expect(api.get).toHaveBeenCalledWith('/pull-requests/pr-9/reviews');
  });

  it('passes the state filter as a query param on the PR list', () => {
    api.get.and.returnValue(of([]));

    service.getPullRequests('acme/api', 'open').subscribe();

    expect(api.get).toHaveBeenCalledWith('/repositories/acme/api/pulls', { state: 'open' });
  });

  it('omits the state param when none is requested', () => {
    api.get.and.returnValue(of([]));

    service.getPullRequests('acme/api').subscribe();

    expect(api.get).toHaveBeenCalledWith('/repositories/acme/api/pulls', {});
  });
});
