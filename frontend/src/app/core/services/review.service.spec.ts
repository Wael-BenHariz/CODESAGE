import { TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';

import { ApiError, ApiService } from './api.service';
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

  // --- shared, cached detail (plan Step 2, Q1) ------------------------------

  it('shares ONE request for the same review id across subscribers', () => {
    api.get.and.returnValue(of({ id: 'rev-9' }));

    let a: unknown;
    let b: unknown;
    service.getReviewDetail('rev-9').subscribe(v => (a = v));
    service.getReviewDetail('rev-9').subscribe(v => (b = v));

    // Stats bar + review panel on the same page → one HTTP call.
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(a).toEqual({ id: 'rev-9' });
    expect(b).toEqual({ id: 'rev-9' });
  });

  it('a failed detail request evicts the cache so the retry refetches', () => {
    api.get.and.returnValues(
      throwError(() => new ApiError('boom', 500, null)),
      of({ id: 'rev-9' })
    );

    let err: unknown;
    service.getReviewDetail('rev-9').subscribe({ error: e => (err = e) });
    expect(err instanceof ApiError).toBeTrue();

    let ok: unknown;
    service.getReviewDetail('rev-9').subscribe(v => (ok = v));
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(ok).toEqual({ id: 'rev-9' });
  });

  const mutations: Array<[string, (svc: ReviewService) => Observable<unknown>]> = [
    ['dismiss', svc => svc.dismissReviewComment('rev-9', 'c-1')],
    ['restore', svc => svc.restoreReviewComment('rev-9', 'c-1')],
    ['summary edit', svc => svc.updateReviewSummary('rev-9', 'Edited body')],
    ['post', svc => svc.postReview('rev-9')],
    ['validate', svc => svc.validateReviewFinding('rev-9', 'c-1', { verdict: 'confirmed' })]
  ];

  mutations.forEach(([name, run]) => {
    it(`${name}: invalidates the cached detail and notifies listeners`, () => {
      api.get.and.returnValue(of({ id: 'rev-9' }));
      api.patch.and.returnValue(of({}));
      api.post.and.returnValue(of({}));

      const invalidated: string[] = [];
      service.reviewDetailInvalidated$.subscribe(id => invalidated.push(id));

      service.getReviewDetail('rev-9').subscribe(); // populate the cache
      run(service).subscribe(); // mutation succeeds

      expect(invalidated).toEqual(['rev-9']);

      service.getReviewDetail('rev-9').subscribe(); // must be a fresh request
      expect(api.get).toHaveBeenCalledTimes(2);
    });
  });

  it('a failed mutation does NOT invalidate (server state unchanged)', () => {
    api.get.and.returnValue(of({ id: 'rev-9' }));
    api.patch.and.returnValue(throwError(() => new ApiError('conflict', 409, 'already posted')));

    service.getReviewDetail('rev-9').subscribe();
    service.dismissReviewComment('rev-9', 'c-1').subscribe({ error: () => undefined });
    service.getReviewDetail('rev-9').subscribe();

    expect(api.get).toHaveBeenCalledTimes(1); // still the cached entry
  });

  it('reading run status drops the cached detail without an invalidation event', () => {
    // Order: detail → status → detail (fresh after the silent eviction).
    api.get.and.returnValues(
      of({ id: 'rev-9' }),
      of({ status: 'processing', progress: 40 }),
      of({ id: 'rev-9' })
    );
    const events: string[] = [];
    service.reviewDetailInvalidated$.subscribe(id => events.push(id));

    service.getReviewDetail('rev-9').subscribe();
    service.getReviewStatus('rev-9').subscribe(); // silently evicts
    service.getReviewDetail('rev-9').subscribe(); // fresh fetch

    expect(api.get).toHaveBeenCalledTimes(3);
    expect(events).toEqual([]); // pollers drive their own refetch
  });
});
