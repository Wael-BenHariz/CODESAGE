import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { WorkspaceService } from './workspace.service';

describe('WorkspaceService — /workspaces routes (§2.5)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: WorkspaceService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post', 'patch', 'delete']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(WorkspaceService);
  });

  it('lists workspaces and maps server capability flags (never re-derived)', () => {
    api.get.and.returnValue(
      of([
        {
          id: 'ws-1',
          type: 'ORG',
          name: 'acme',
          role: 'ORG_ADMIN',
          github_account_login: 'acme',
          capabilities: {
            view: true,
            trigger: true,
            request: true,
            review: true,
            repo_config: true,
            repo_admin: true,
            platform: false
          }
        }
      ])
    );

    let result: unknown;
    service.list().subscribe(ws => (result = ws));

    expect(api.get).toHaveBeenCalledWith('/workspaces');
    expect(result).toEqual([
      {
        id: 'ws-1',
        type: 'ORG',
        name: 'acme',
        role: 'ORG_ADMIN',
        isPersonal: false,
        githubAccountLogin: 'acme',
        capabilities: {
          view: true,
          trigger: true,
          request: true,
          review: true,
          repoConfig: true,
          repoAdmin: true,
          platform: false
        }
      }
    ]);
  });

  it('fails closed on missing capability flags (view only)', () => {
    api.get.and.returnValue(of([{ id: 'ws-1', type: 'ORG', name: 'acme', role: 'DEVELOPER' }]));

    let result: { capabilities: Record<string, boolean> }[] | undefined;
    service.list().subscribe(ws => (result = ws as never));

    expect(result?.[0].capabilities['view']).toBeTrue();
    expect(result?.[0].capabilities['repoAdmin']).toBeFalse();
  });

  it('creates an ORG workspace via query-parameter name', () => {
    api.post.and.returnValue(of({ id: 'ws-2' }));

    service.create('acme', 'acme-gh').subscribe();

    expect(api.post).toHaveBeenCalledWith('/workspaces?name=acme&github_account_login=acme-gh', {});
  });

  it('deletes a workspace by id', () => {
    api.delete.and.returnValue(of(void 0));

    service.remove('ws-1').subscribe();

    expect(api.delete).toHaveBeenCalledWith('/workspaces/ws-1');
  });

  it('lists members of a workspace', () => {
    api.get.and.returnValue(of([]));

    service.members('ws-1').subscribe();

    expect(api.get).toHaveBeenCalledWith('/workspaces/ws-1/members');
  });

  it('changes a member role via the ?role= query parameter', () => {
    api.patch.and.returnValue(of({}));

    service.updateMemberRole('ws-1', 'user-1', 'REVIEWER').subscribe();

    expect(api.patch).toHaveBeenCalledWith('/workspaces/ws-1/members/user-1?role=REVIEWER', {});
  });

  it('removes a member', () => {
    api.delete.and.returnValue(of(void 0));

    service.removeMember('ws-1', 'user-1').subscribe();

    expect(api.delete).toHaveBeenCalledWith('/workspaces/ws-1/members/user-1');
  });
});
