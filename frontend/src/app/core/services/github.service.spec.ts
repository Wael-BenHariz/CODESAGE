import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { GithubService } from './github.service';

describe('GithubService — review routes (plan Steps 7b–10)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: GithubService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post', 'patch']);
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

  // --- staged controls (plan Step 8) ----------------------------------------

  it('saves summary edits via PATCH /reviews/{id}/summary', () => {
    api.patch.and.returnValue(of({}));

    service.updateReviewSummary('rev-9', 'Edited body').subscribe();

    expect(api.patch).toHaveBeenCalledWith('/reviews/rev-9/summary', { summary: 'Edited body' });
  });

  it('dismisses findings via PATCH /reviews/{id}/comments/{cid}/dismiss', () => {
    api.patch.and.returnValue(of({}));

    service.dismissReviewComment('rev-9', 'c-1').subscribe();

    expect(api.patch).toHaveBeenCalledWith('/reviews/rev-9/comments/c-1/dismiss', {});
  });

  it('restores findings via PATCH /reviews/{id}/comments/{cid}/restore', () => {
    api.patch.and.returnValue(of({}));

    service.restoreReviewComment('rev-9', 'c-1').subscribe();

    expect(api.patch).toHaveBeenCalledWith('/reviews/rev-9/comments/c-1/restore', {});
  });

  it('posts staged reviews via POST /reviews/{id}/post', () => {
    api.post.and.returnValue(
      of({
        review_id: 'rev-9',
        github_review_id: 1,
        posted_at: '2026-01-01T00:00:00Z',
        message: 'ok'
      })
    );

    service.postReview('rev-9').subscribe();

    expect(api.post).toHaveBeenCalledWith('/reviews/rev-9/post', {});
  });

  it('upserts reviewer verdicts via PATCH /reviews/{id}/comments/{cid}/validate', () => {
    api.patch.and.returnValue(of({}));

    service.validateReviewFinding('rev-9', 'c-1', { verdict: 'confirmed' }).subscribe();

    expect(api.patch).toHaveBeenCalledWith('/reviews/rev-9/comments/c-1/validate', {
      verdict: 'confirmed'
    });
  });
});
