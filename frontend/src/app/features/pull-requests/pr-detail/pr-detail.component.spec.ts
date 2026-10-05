import { TestBed, ComponentFixture } from '@angular/core/testing';
import { WritableSignal, signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { PrDetailComponent } from './pr-detail.component';
import { AuthService } from '../../../core/services/auth.service';
import { GithubService } from '../../../core/services/github.service';
import { PullRequest } from '../../../core/models/pull-request.model';

describe('PrDetailComponent — load error state (F3 pre-check b)', () => {
  let fixture: ComponentFixture<PrDetailComponent>;
  let github: jasmine.SpyObj<GithubService>;
  let roleSignal: WritableSignal<{ role: string } | null>;

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

  beforeEach(() => {
    roleSignal = signal({ role: 'DEVELOPER' });
    github = jasmine.createSpyObj<GithubService>('GithubService', [
      'getPullRequest',
      'triggerReview'
    ]);

    TestBed.configureTestingModule({
      imports: [PrDetailComponent],
      providers: [
        provideRouter([]), // the component template uses RouterLink
        { provide: GithubService, useValue: github },
        // The component only reads currentUser()?.role.
        { provide: AuthService, useValue: { currentUser: roleSignal } }
      ]
    });
  });

  function create(): void {
    fixture = TestBed.createComponent(PrDetailComponent);
    fixture.componentRef.setInput('owner', 'acme');
    fixture.componentRef.setInput('repo', 'demo');
    fixture.componentRef.setInput('number', 7);
    fixture.detectChanges(); // ngOnInit → getPullRequest (sync of()/throwError)
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('renders an explicit error state instead of a blank page when the load fails', () => {
    github.getPullRequest.and.returnValue(
      throwError(() => ({ status: 404, message: 'Pull request not found' }))
    );
    create();

    const errorEl = el().querySelector('[data-testid="pr-load-error"]');
    expect(errorEl).not.toBeNull();
    expect(errorEl?.textContent).toContain("Couldn't load this pull request");
    expect(fixture.componentInstance.loadError()).toBeTrue();
    expect(fixture.componentInstance.pullRequest()).toBeNull();
  });

  it('retries the load from the error state and renders the PR on success', () => {
    github.getPullRequest.and.returnValue(
      throwError(() => ({ status: 404, message: 'Pull request not found' }))
    );
    create();

    github.getPullRequest.and.returnValue(of(pr));
    (el().querySelector('[data-testid="pr-load-error"] button') as HTMLButtonElement).click();
    fixture.detectChanges(); // the retry is synchronous; refresh the DOM

    expect(fixture.componentInstance.loadError()).toBeFalse();
    expect(el().querySelector('[data-testid="pr-load-error"]')).toBeNull();
    expect(el().querySelector('h1')?.textContent).toContain('Fix the thing');
    expect(github.getPullRequest).toHaveBeenCalledTimes(2);
  });

  it('renders the PR detail when the load succeeds (no error state)', () => {
    github.getPullRequest.and.returnValue(of(pr));
    create();

    expect(el().querySelector('[data-testid="pr-load-error"]')).toBeNull();
    expect(el().querySelector('h1')?.textContent).toContain('Fix the thing');
    expect(el().textContent).toContain('Start AI Review'); // DEVELOPER + nav().write
  });
});
