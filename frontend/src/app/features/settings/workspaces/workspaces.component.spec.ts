import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal, WritableSignal } from '@angular/core';
import { of, throwError } from 'rxjs';

import { WorkspacesComponent } from './workspaces.component';
import { AuthService } from '../../../core/services/auth.service';
import { WorkspaceService } from '../../../core/services/workspace.service';
import { User, Workspace } from '../../../core/models/user.model';
import { WorkspaceMemberRow } from '../../../core/models/workspace-member.model';

describe('WorkspacesComponent — /settings/workspaces (§2.5)', () => {
  let fixture: ComponentFixture<WorkspacesComponent>;
  let auth: { currentUser: WritableSignal<User | null> };
  let workspacesApi: jasmine.SpyObj<WorkspaceService>;

  const capabilities = {
    view: true,
    trigger: true,
    request: true,
    review: true,
    repoConfig: true,
    repoAdmin: true,
    platform: false
  };

  const orgWorkspace = (): Workspace => ({
    id: 'ws-1',
    type: 'ORG',
    name: 'acme',
    role: 'ORG_ADMIN',
    isPersonal: false,
    githubAccountLogin: 'acme-gh',
    capabilities
  });

  const member = (userId: string, role: string): WorkspaceMemberRow => ({
    id: `m-${userId}`,
    user_id: userId,
    username: userId,
    role: role as WorkspaceMemberRow['role'],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z'
  });

  const user = (role: string): User => ({
    id: 'u-1',
    login: 'octocat',
    email: 'octo@example.com',
    name: null,
    avatarUrl: '',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    role
  });

  function render(): void {
    fixture = TestBed.createComponent(WorkspacesComponent);
    fixture.detectChanges();
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  beforeEach(() => {
    auth = { currentUser: signal(user('PLATFORM_ADMIN')) };
    workspacesApi = jasmine.createSpyObj<WorkspaceService>('WorkspaceService', [
      'list',
      'create',
      'remove',
      'members',
      'updateMemberRole',
      'removeMember'
    ]);
    workspacesApi.list.and.returnValue(of([orgWorkspace()]));

    TestBed.configureTestingModule({
      imports: [WorkspacesComponent],
      providers: [
        { provide: AuthService, useValue: auth },
        { provide: WorkspaceService, useValue: workspacesApi }
      ]
    });
  });

  it('renders the workspace list with the server role and capabilities', () => {
    render();

    expect(el().querySelector('[data-testid="workspaces-loading"]')).toBeNull();
    expect(el().querySelector('[data-testid="workspace-name-item"]')?.textContent).toContain(
      'acme'
    );
    expect(el().querySelector('[data-testid="workspace-role"]')?.textContent?.trim()).toBe(
      'ORG_ADMIN'
    );
  });

  it('shows the load error with a retry instead of an empty list', () => {
    workspacesApi.list.and.returnValue(throwError(() => new Error('boom')));
    render();

    expect(el().querySelector('[data-testid="workspaces-error"]')?.textContent).toContain('boom');

    workspacesApi.list.and.returnValue(of([orgWorkspace()]));
    el().querySelector<HTMLButtonElement>('[data-testid="workspaces-error"] button')?.click();
    fixture.detectChanges();

    expect(el().querySelector('[data-testid="workspace-list"]')).not.toBeNull();
  });

  it('offers creation only to a global ORG_ADMIN/PLATFORM_ADMIN', () => {
    render();
    expect(el().querySelector('[data-testid="workspace-create"]')).not.toBeNull();

    auth.currentUser.set(user('REVIEWER'));
    workspacesApi.list.and.returnValue(of([orgWorkspace()]));
    render();
    expect(el().querySelector('[data-testid="workspace-create"]')).toBeNull();
  });

  it('creates a workspace with the trimmed name and clears the form', () => {
    workspacesApi.create.and.returnValue(of({ ...orgWorkspace(), id: 'ws-2', name: 'new-co' }));
    render();

    const nameInput = el().querySelector<HTMLInputElement>(
      '[data-testid="workspace-name"]'
    ) as HTMLInputElement;
    nameInput.value = '  new-co  ';
    nameInput.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    el().querySelector<HTMLButtonElement>('[data-testid="workspace-create"]')?.click();
    fixture.detectChanges();

    expect(workspacesApi.create).toHaveBeenCalledWith('new-co', undefined);
    expect(el().querySelectorAll('[data-testid="workspace-name-item"]').length).toBe(2);
  });

  it('loads members when the workspace card is expanded', () => {
    workspacesApi.members.and.returnValue(of([member('u-2', 'DEVELOPER')]));
    render();

    el().querySelector<HTMLButtonElement>('[data-testid="toggle-members"]')?.click();
    fixture.detectChanges();

    expect(workspacesApi.members).toHaveBeenCalledWith('ws-1');
    expect(el().querySelectorAll('[data-testid="member-row"]').length).toBe(1);
  });

  it('changes a member role through the backend query-parameter route', () => {
    workspacesApi.members.and.returnValue(of([member('u-2', 'DEVELOPER')]));
    workspacesApi.updateMemberRole.and.returnValue(
      of({ id: 'm-u-2', user_id: 'u-2', role: 'REVIEWER', created_at: '', updated_at: '' })
    );
    render();

    el().querySelector<HTMLButtonElement>('[data-testid="toggle-members"]')?.click();
    fixture.detectChanges();

    const select = el().querySelector<HTMLSelectElement>(
      '[data-testid="member-role"]'
    ) as HTMLSelectElement;
    select.value = 'REVIEWER';
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(workspacesApi.updateMemberRole).toHaveBeenCalledWith('ws-1', 'u-2', 'REVIEWER');
  });

  it('surfaces the backend rule violation (last admin) inline without dropping the row', () => {
    workspacesApi.members.and.returnValue(of([member('u-2', 'ORG_ADMIN')]));
    workspacesApi.removeMember.and.returnValue(
      throwError(() => new Error('Cannot remove the last ORG_ADMIN'))
    );
    render();

    el().querySelector<HTMLButtonElement>('[data-testid="toggle-members"]')?.click();
    fixture.detectChanges();

    el().querySelector<HTMLButtonElement>('[data-testid="member-remove"]')?.click();
    fixture.detectChanges();

    expect(el().querySelector('[data-testid="member-error"]')?.textContent).toContain(
      'last ORG_ADMIN'
    );
    expect(el().querySelectorAll('[data-testid="member-row"]').length).toBe(1);
  });
});
