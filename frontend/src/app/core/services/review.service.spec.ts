import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { ReviewService } from './review.service';

describe('ReviewService — /reviews group (plan Steps 7b–10)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: ReviewService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post', 'patch']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(ReviewService);
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
    api.post.and.returnValue(of({ github_review_id: 1, posted_at: 'now' }));

    service.postReview('rev-9').subscribe();

    expect(api.post).toHaveBeenCalledWith('/reviews/rev-9/post', {});
  });

  // --- reviewer validation (plan Step 9) ------------------------------------

  it('upserts verdicts via PATCH /reviews/{id}/comments/{cid}/validate', () => {
    api.patch.and.returnValue(of({}));

    service
      .validateReviewFinding('rev-9', 'c-1', {
        verdict: 'false_positive',
        note: 'not reachable'
      })
      .subscribe();

    expect(api.patch).toHaveBeenCalledWith('/reviews/rev-9/comments/c-1/validate', {
      verdict: 'false_positive',
      note: 'not reachable'
    });
  });

  it('reads run progress from GET /reviews/{id}/status', () => {
    api.get.and.returnValue(of({ status: 'processing', progress: 40 }));

    service.getReviewStatus('rev-9').subscribe();

    expect(api.get).toHaveBeenCalledWith('/reviews/rev-9/status');
  });
});
