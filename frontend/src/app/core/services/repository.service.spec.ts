import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { RepositoryService } from './repository.service';
import { Repository } from '../models/repository.model';
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
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post', 'delete']);
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
});
