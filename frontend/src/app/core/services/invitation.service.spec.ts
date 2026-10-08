import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { InvitationService } from './invitation.service';

describe('InvitationService — invitation routes (plan Steps 11–12)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: InvitationService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'post', 'delete']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(InvitationService);
  });

  it('lists invitations from /orgs/{orgId}/invitations', () => {
    api.get.and.returnValue(of([]));

    service.list('org-1').subscribe();

    expect(api.get).toHaveBeenCalledWith('/orgs/org-1/invitations');
  });

  it('creates invitations via POST /orgs/{orgId}/invitations', () => {
    api.post.and.returnValue(of({}));

    service.create('org-1', { email: 'a@example.com', role: 'REVIEWER' }).subscribe();

    expect(api.post).toHaveBeenCalledWith('/orgs/org-1/invitations', {
      email: 'a@example.com',
      role: 'REVIEWER'
    });
  });

  it('forwards the selected repository ids (one role for the whole selection)', () => {
    api.post.and.returnValue(of({}));

    service
      .create('org-1', {
        email: 'a@example.com',
        role: 'DEVELOPER',
        repository_ids: ['repo-1', 'repo-2']
      })
      .subscribe();

    expect(api.post).toHaveBeenCalledWith('/orgs/org-1/invitations', {
      email: 'a@example.com',
      role: 'DEVELOPER',
      repository_ids: ['repo-1', 'repo-2']
    });
  });

  it('revokes via DELETE /orgs/{orgId}/invitations/{invitationId}', () => {
    api.delete.and.returnValue(of(undefined));

    service.revoke('org-1', 'inv-1').subscribe();

    expect(api.delete).toHaveBeenCalledWith('/orgs/org-1/invitations/inv-1');
  });

  it('previews from the public token route /invitations/{token}', () => {
    api.get.and.returnValue(of({}));

    service.preview('tok-1').subscribe();

    expect(api.get).toHaveBeenCalledWith('/invitations/tok-1');
  });

  it('accepts via POST /invitations/{token}/accept with an empty body', () => {
    api.post.and.returnValue(of({}));

    service.accept('tok-1').subscribe();

    expect(api.post).toHaveBeenCalledWith('/invitations/tok-1/accept', {});
  });

  it('URL-encodes token material in the path', () => {
    api.get.and.returnValue(of({}));

    service.preview('a/b+c').subscribe();

    expect(api.get).toHaveBeenCalledWith('/invitations/a%2Fb%2Bc');
  });
});
