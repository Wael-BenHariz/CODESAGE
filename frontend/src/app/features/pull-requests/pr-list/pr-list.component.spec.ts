import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { NEVER, of, throwError } from 'rxjs';

import { PrListComponent } from './pr-list.component';
import { PullRequestService } from '../../../core/services/pull-request.service';
import {
  PullRequest,
  PullRequestReviewRef,
  PullRequestState
} from '../../../core/models/pull-request.model';

describe('PrListComponent — four states, filters, pagination (plan Step 6)', () => {
  let fixture: ComponentFixture<PrListComponent>;
  let github: jasmine.SpyObj<PullRequestService>;

  const pr: PullRequest = {
    id: 'pr-1',
    repositoryId: 'repo-1',
    number: 7,
    title: 'Fix the thing',
    body: null,
    state: 'open',
    author: { login: 'octocat', avatarUrl: '' },
    baseBranch: 'main',
    headBranch: 'fix',
    additions: 10,
    deletions: 2,
    changedFiles: 3,
    reviewStatus: null,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-02T00:00:00Z'
  };

  const makePr = (number: number, state: PullRequestState, author = 'octocat'): PullRequest => ({
    ...pr,
    id: `pr-${number}`,
    number,
    state,
    author: { login: author, avatarUrl: '' }
  });

  beforeEach(() => {
    github = jasmine.createSpyObj<PullRequestService>('PullRequestService', ['getPullRequests']);

    TestBed.configureTestingModule({
      imports: [PrListComponent],
      providers: [
        provideRouter([]), // the component template uses RouterLink
        { provide: PullRequestService, useValue: github }
      ]
    });
  });

  function create(): void {
    fixture = TestBed.createComponent(PrListComponent);
    fixture.componentRef.setInput('owner', 'acme');
    fixture.componentRef.setInput('repo', 'demo');
    fixture.detectChanges(); // ngOnInit → getPullRequests (sync of()/throwError)
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function stateChips(): HTMLButtonElement[] {
    return Array.from(el().querySelectorAll('.filter-btn'));
  }

  it('shows an explicit error state on failure, not "No pull requests found"', () => {
    github.getPullRequests.and.returnValue(
      throwError(() => ({ status: 404, message: 'not found' }))
    );
    create();

    expect(el().querySelector('[data-testid="pr-list-load-error"]')).not.toBeNull();
    expect(el().textContent).not.toContain('No pull requests found');
    expect(fixture.componentInstance.loadError()).toBeTrue();
  });

  it('shows the empty state only when the load succeeded with no results', () => {
    github.getPullRequests.and.returnValue(of([]));
    create();

    expect(el().querySelector('[data-testid="pr-list-load-error"]')).toBeNull();
    expect(el().textContent).toContain('No pull requests found');
    expect(fixture.componentInstance.loadError()).toBeFalse();
  });

  it('retries the load from the error state', () => {
    github.getPullRequests.and.returnValue(throwError(() => ({ status: 500, message: 'boom' })));
    create();

    github.getPullRequests.and.returnValue(of([pr]));
    (el().querySelector('[data-testid="pr-list-load-error"] button') as HTMLButtonElement).click();
    fixture.detectChanges(); // the retry is synchronous; refresh the DOM

    expect(fixture.componentInstance.loadError()).toBeFalse();
    expect(el().querySelectorAll('.pr-item').length).toBe(1);
    expect(github.getPullRequests).toHaveBeenCalledTimes(2);
  });

  // --- four-state coverage (plan Step 2) ------------------------------------

  it('shows the loading state while the request is in flight', () => {
    github.getPullRequests.and.returnValue(NEVER);
    create();

    expect(el().querySelector('[data-testid="pr-list-loading"]')).not.toBeNull();
    expect(fixture.componentInstance.isLoading()).toBeTrue();
    expect(el().querySelector('[data-testid="pr-list-load-error"]')).toBeNull();
    expect(el().textContent).not.toContain('No pull requests found');
  });

  it('renders the PR rows from the mapped model on success', () => {
    github.getPullRequests.and.returnValue(of([pr]));
    create();

    expect(el().querySelector('[data-testid="pr-list-loading"]')).toBeNull();
    expect(fixture.componentInstance.isLoading()).toBeFalse();
    expect(el().querySelectorAll('.pr-item').length).toBe(1);
    expect(el().querySelector('.pr-title')?.textContent).toContain('Fix the thing');
    expect(el().textContent).toContain('#7');
    expect(el().textContent).toContain('by octocat');
  });

  it('passes the owner and repo as separate args (phantom combined path removed)', () => {
    github.getPullRequests.and.returnValue(of([pr]));
    create();

    expect(github.getPullRequests).toHaveBeenCalledWith('acme', 'demo');
  });

  // --- Step 6: written state chips, no review badge, embedded --------------

  it('labels the row state with text (never color-only, emoji icons gone)', () => {
    github.getPullRequests.and.returnValue(of([makePr(1, 'open'), makePr(2, 'merged')]));
    create();

    const chips = el().querySelectorAll('.state-chip');
    expect(chips.length).toBe(2);
    expect(chips[0].textContent?.trim()).toBe('open');
    expect(chips[1].textContent?.trim()).toBe('merged');
    expect(el().textContent).not.toContain('🟢');
    expect(el().textContent).not.toContain('🟣');
  });

  it('never renders a review badge on rows — even when the model carries one (gap 7)', () => {
    const review: PullRequestReviewRef = { status: 'completed', reviewId: 'rev-1' };
    github.getPullRequests.and.returnValue(of([{ ...pr, reviewStatus: review }]));
    create();

    expect(el().querySelectorAll('.pr-item').length).toBe(1);
    expect(el().querySelector('.pr-review-status')).toBeNull();
    expect(el().textContent).not.toContain('completed');
  });

  it('hides the standalone page header when embedded in repository-detail', () => {
    github.getPullRequests.and.returnValue(of([pr]));
    create();
    expect(el().querySelector('h1')?.textContent).toContain('Pull Requests');

    fixture.componentRef.setInput('embedded', true);
    fixture.detectChanges();

    expect(el().querySelector('h1')).toBeNull();
    expect(el().querySelectorAll('.pr-item').length).toBe(1); // list unaffected
  });

  // --- Step 6: state + author filters (client-side over the window) --------

  it('filters rows by state, and "closed" counts merged rows too', () => {
    github.getPullRequests.and.returnValue(
      of([makePr(1, 'open'), makePr(2, 'closed'), makePr(3, 'merged')])
    );
    create();

    const chips = stateChips();
    expect(chips.map(c => c.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      'All 3',
      'Open 1',
      'Closed 2'
    ]);

    chips[2].click(); // Closed (includes merged)
    fixture.detectChanges();
    expect(el().querySelectorAll('.pr-item').length).toBe(2);
    expect(fixture.componentInstance.filter()).toBe('closed');

    chips[1].click(); // Open
    fixture.detectChanges();
    expect(el().querySelectorAll('.pr-item').length).toBe(1);
    expect(el().textContent).toContain('Fix the thing');
  });

  it('filters rows by author (case-insensitive substring) with a clear path back', () => {
    github.getPullRequests.and.returnValue(
      of([makePr(1, 'open', 'octocat'), makePr(2, 'open', 'Hubot')])
    );
    create();

    const input = el().querySelector('[data-testid="pr-author-filter"]') as HTMLInputElement;
    input.value = 'hub';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    expect(el().querySelectorAll('.pr-item').length).toBe(1);
    expect(el().textContent).toContain('#2');

    input.value = 'nobody';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    expect(el().querySelectorAll('.pr-item').length).toBe(0);
    expect(el().textContent).toContain('No pull requests match your filters');
    expect(el().textContent).not.toContain('No pull requests found'); // not the empty state

    (el().querySelector('[data-testid="clear-pr-filters"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(el().querySelectorAll('.pr-item').length).toBe(2);
    expect(input.value).toBe('');
  });

  // --- Step 6: pagination (pageSize rows per page) -------------------------

  it('pages the rows 10 at a time with working prev/next controls', () => {
    const rows = Array.from({ length: 11 }, (_, i) => makePr(i + 1, 'open'));
    github.getPullRequests.and.returnValue(of(rows));
    create();

    expect(el().querySelectorAll('.pr-item').length).toBe(10);
    const pager = el().querySelector('[data-testid="pr-pagination"]');
    expect(pager).not.toBeNull();
    expect(pager?.textContent).toContain('Page 1 of 2');
    expect(pager?.textContent).toContain('1–10 of 11');

    const buttons = Array.from(el().querySelectorAll('.page-btn'));
    expect((buttons[0] as HTMLButtonElement).disabled).toBeTrue(); // first page

    (buttons[1] as HTMLButtonElement).click(); // Next
    fixture.detectChanges();

    expect(el().querySelectorAll('.pr-item').length).toBe(1);
    expect(el().textContent).toContain('#11');
    const after = Array.from(el().querySelectorAll('.page-btn')) as HTMLButtonElement[];
    expect(after[1].disabled).toBeTrue(); // last page
    expect(after[0].disabled).toBeFalse();

    after[0].click(); // Previous
    fixture.detectChanges();
    expect(el().querySelectorAll('.pr-item').length).toBe(10);
  });

  it('resets to page 1 when a state filter changes', () => {
    const rows = Array.from({ length: 12 }, (_, i) => makePr(i + 1, 'open'));
    github.getPullRequests.and.returnValue(of(rows));
    create();

    const next = Array.from(el().querySelectorAll('.page-btn'))[1] as HTMLButtonElement;
    next.click();
    fixture.detectChanges();
    expect(fixture.componentInstance.page()).toBe(2);

    stateChips()[1].click(); // Open → re-slice
    fixture.detectChanges();
    expect(fixture.componentInstance.page()).toBe(1);
  });
});
