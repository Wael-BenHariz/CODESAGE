import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { GithubAppService } from './github-app.service';

describe('GithubAppService (/github group)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: GithubAppService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(GithubAppService);
  });

  it('reads install status from GET /github/status and syncs the shared signal', () => {
    api.get.and.returnValue(of({ installed: true, installation_id: 7 }));

    service.getInstallStatus().subscribe();

    expect(api.get).toHaveBeenCalledWith('/github/status');
    expect(service.githubInstalled()).toBeTrue();
  });

  it('lists App repositories from GET /github/repos', () => {
    api.get.and.returnValue(of([]));

    service.getAppRepos().subscribe();

    expect(api.get).toHaveBeenCalledWith('/github/repos');
  });

  it('saves the selection with sync: true so deselection propagates', () => {
    api.post.and.returnValue(of({ saved: true }));
    const repos = [{ id: 1, name: 'acme/api', private: false, enabled: true }];

    service.saveRepoSelection(repos).subscribe();

    expect(api.post).toHaveBeenCalledWith('/github/repos/selection', { repos, sync: true });
  });
});
