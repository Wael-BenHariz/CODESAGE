import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { GithubService } from './github.service';

describe('GithubService — review routes (plan Step 7b)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: GithubService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(GithubService);
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

  it('fetches review detail from /reviews/{id}', () => {
    api.get.and.returnValue(of({}));

    service.getReviewDetail('rev-9').subscribe();

    expect(api.get).toHaveBeenCalledWith('/reviews/rev-9');
  });
});
