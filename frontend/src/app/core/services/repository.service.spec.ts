import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { ApiError, ApiService } from './api.service';
import { RepositoryService } from './repository.service';
import { Repository, RepositoryDetail } from '../models/repository.model';
import { RepositoryListDto, toRepository } from './mappers/repository.mapper';

describe('RepositoryService (/repositories group)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: RepositoryService;

  /** Wire fixture shaped like backend RepositoryResponse (schemas/repository.py). */
  const dto = {
    id: 'repo-1',
    installation_id: 'inst-1',
    github_repo_id: 42,
    name: 'api',
    full_name: 'acme/api',
    owner: 'acme',
    description: 'Backend',
    private: false,
    default_branch: 'main',
    language: 'Python',
    stars: 3,
    forks: 1,
    open_issues: 2,
    webhook_enabled: true,
    webhook_id: 99,
    enabled: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z'
  };

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post', 'patch', 'delete']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(RepositoryService);
  });

  it('lists repositories from GET /repositories and maps the envelope', () => {
    const list: RepositoryListDto = { items: [dto], total: 1, page: 1, per_page: 20, pages: 1 };
    api.get.and.returnValue(of(list));

    let repos: Repository[] = [];
    service.getRepositories().subscribe(r => (repos = r));

    expect(api.get).toHaveBeenCalledWith('/repositories');
    expect(repos.length).toBe(1);
    expect(repos[0].fullName).toBe('acme/api');
    expect(repos[0].defaultBranch).toBe('main');
    expect(repos[0].webhookEnabled).toBeTrue();
  });

  it('tends toward defaults when optional fields are null or missing', () => {
    const sparse = { ...dto, description: null, language: null, webhook_id: null, owner: null };
    const mapped = toRepository(sparse);

    expect(mapped.description).toBeNull();
    expect(mapped.language).toBeNull();
    // owner falls back to the full_name prefix.
    expect(mapped.owner).toBe('acme');
  });

  it('maps the connect response through the same layer', () => {
    api.post.and.returnValue(of(dto));

    let repo!: Repository;
    service.connectRepository(42).subscribe(r => (repo = r));

    expect(api.post).toHaveBeenCalledWith('/repositories/connect?github_repo_id=42', {});
    expect(repo.fullName).toBe('acme/api');
  });

  it('enables, disables and deletes by repository UUID', () => {
    api.post.and.returnValue(of(dto));
    api.delete.and.returnValue(of(undefined) as never);

    service.enableRepository('repo-1').subscribe();
    service.disableRepository('repo-1').subscribe();
    service.deleteRepository('repo-1').subscribe();

    expect(api.post).toHaveBeenCalledWith('/repositories/repo-1/enable', {});
    expect(api.post).toHaveBeenCalledWith('/repositories/repo-1/disable', {});
    expect(api.delete).toHaveBeenCalledWith('/repositories/repo-1');
  });

  it('resolves owner/name → UUID via search + exact match, cached case-insensitively', () => {
    const neighbour = { ...dto, id: 'repo-2', full_name: 'acme/api-v2' };
    const list: RepositoryListDto = {
      items: [neighbour, dto],
      total: 2,
      page: 1,
      per_page: 100,
      pages: 1
    };
    api.get.and.returnValue(of(list));

    let id = '';
    service.resolveId('acme', 'api').subscribe(v => (id = v));

    expect(api.get).toHaveBeenCalledWith('/repositories', { search: 'acme/api', per_page: 100 });
    // The fuzzy search also returned acme/api-v2 — the exact match must not.
    expect(id).toBe('repo-1');

    // Session cache, lowercased key: no second search request.
    service.resolveId('Acme', 'API').subscribe();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('owner/name not found → genuine backend 404 via the nil UUID (rule 5)', () => {
    // Order: empty search → nil-UUID request fails with the backend's 404.
    api.get.and.returnValues(
      of({ items: [], total: 0, page: 1, per_page: 100, pages: 0 }),
      throwError(() => new ApiError('Repository not found', 404, 'Repository not found'))
    );

    let caught: unknown;
    service.resolveId('ghost', 'repo').subscribe({ error: err => (caught = err) });

    expect(api.get).toHaveBeenCalledWith('/repositories/00000000-0000-0000-0000-000000000000');
    expect(caught instanceof ApiError).toBeTrue();
    expect((caught as ApiError).status).toBe(404);
  });

  it('getRepository resolves owner/name → GET /repositories/{uuid} (phantom path removed)', () => {
    // Order: owner/name search (hit) → GET /repositories/{uuid}.
    api.get.and.returnValues(
      of({ items: [dto], total: 1, page: 1, per_page: 100, pages: 1 }),
      of(dto)
    );

    let repo!: Repository;
    service.getRepository('acme', 'api').subscribe(r => (repo = r));

    expect(api.get).toHaveBeenCalledWith('/repositories', { search: 'acme/api', per_page: 100 });
    expect(api.get).toHaveBeenCalledWith('/repositories/repo-1');
    expect(repo.fullName).toBe('acme/api');
    // Regression guard: /repositories/{owner}/{repo} never existed on the API.
    expect(api.get).not.toHaveBeenCalledWith('/repositories/acme/api');
  });

  it('getRepositoryDetail resolves owner/name → GET /repositories/{uuid}/detail and maps stats + settings', () => {
    api.get.and.returnValues(
      of({ items: [dto], total: 1, page: 1, per_page: 100, pages: 1 }),
      of({
        ...dto,
        total_prs: 7,
        total_reviews: 3,
        settings: { auto_review: false, max_files_per_review: 25 }
      })
    );

    let detail!: RepositoryDetail;
    service.getRepositoryDetail('acme', 'api').subscribe(d => (detail = d));

    expect(api.get).toHaveBeenCalledWith('/repositories/repo-1/detail');
    expect(detail.totalPrs).toBe(7);
    expect(detail.totalReviews).toBe(3);
    expect(detail.settings.autoReview).toBeFalse(); // wire value wins
    expect(detail.settings.maxFilesPerReview).toBe(25);
    expect(detail.settings.reviewOnPush).toBeFalse(); // schema default when absent
    expect(detail.fullName).toBe('acme/api'); // still a full Repository
  });

  it('updateRepository PATCHes only the writable fields and maps the response', () => {
    api.patch.and.returnValue(of({ ...dto, default_branch: 'develop' }));

    let repo!: Repository;
    service.updateRepository('repo-1', { default_branch: 'develop' }).subscribe(r => (repo = r));

    expect(api.patch).toHaveBeenCalledWith('/repositories/repo-1', {
      default_branch: 'develop'
    });
    expect(repo.defaultBranch).toBe('develop');
  });
});
