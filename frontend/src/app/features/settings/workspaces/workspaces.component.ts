import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { AuthService } from '../../../core/services/auth.service';
import { WorkspaceService } from '../../../core/services/workspace.service';
import { Workspace } from '../../../core/models/user.model';
import { WorkspaceMemberRow, WorkspaceRole } from '../../../core/models/workspace-member.model';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { SpinnerComponent } from '../../../shared/components/spinner/spinner.component';

type ListState = 'loading' | 'error' | 'ready';

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/**
 * Workspace management (workspace RBAC §2.5) — route `/settings/workspaces`.
 *
 * Lists the caller's workspaces (server capability flags drive every
 * control), lets global ORG_ADMIN/PLATFORM_ADMIN create ORG workspaces,
 * and lets a `repo_admin` member manage roles inside a workspace. The
 * backend re-checks every mutation — this screen only mirrors its rules
 * (last-admin protection renders as the backend's 400 inline).
 */
@Component({
  selector: 'app-workspaces',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, EmptyStateComponent, SpinnerComponent],
  templateUrl: './workspaces.component.html',
  styleUrl: './workspaces.component.scss'
})
export class WorkspacesComponent implements OnInit {
  private readonly workspacesApi = inject(WorkspaceService);
  readonly auth = inject(AuthService);

  /** Assignable member roles (backend `_MEMBER_ROLES`). */
  readonly memberRoles: readonly WorkspaceRole[] = ['ORG_ADMIN', 'REVIEWER', 'DEVELOPER', 'NONE'];

  readonly state = signal<ListState>('loading');
  readonly workspaces = signal<Workspace[]>([]);
  readonly loadError = signal<string | null>(null);

  /** Creating ORG workspaces requires the GLOBAL ORG_ADMIN/PLATFORM_ADMIN role. */
  readonly canCreate = computed(() => {
    const role = this.auth.currentUser()?.role;
    return role === 'ORG_ADMIN' || role === 'PLATFORM_ADMIN';
  });

  // --- Create form -----------------------------------------------------------
  readonly creating = signal(false);
  readonly createError = signal<string | null>(null);
  readonly newName = signal('');
  readonly newGithubLogin = signal('');

  // --- Member management -----------------------------------------------------
  readonly expandedId = signal<string | null>(null);
  readonly membersState = signal<ListState>('loading');
  readonly members = signal<WorkspaceMemberRow[]>([]);
  readonly membersError = signal<string | null>(null);
  /** user_id of the member with an in-flight role change / removal. */
  readonly memberBusyId = signal<string | null>(null);
  readonly memberActionError = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.state.set('loading');
    this.loadError.set(null);
    this.workspacesApi.list().subscribe({
      next: workspaces => {
        this.workspaces.set(workspaces);
        this.state.set('ready');
      },
      error: (err: unknown) => {
        this.loadError.set(errorMessage(err, 'Could not load workspaces.'));
        this.state.set('error');
      }
    });
  }

  // --- Create ----------------------------------------------------------------

  onNameInput(event: Event): void {
    this.newName.set((event.target as HTMLInputElement).value);
  }

  onGithubLoginInput(event: Event): void {
    this.newGithubLogin.set((event.target as HTMLInputElement).value);
  }

  createWorkspace(): void {
    const name = this.newName().trim();
    if (!name || this.creating()) return;
    this.creating.set(true);
    this.createError.set(null);
    this.workspacesApi.create(name, this.newGithubLogin().trim() || undefined).subscribe({
      next: workspace => {
        this.creating.set(false);
        this.newName.set('');
        this.newGithubLogin.set('');
        this.workspaces.update(list => [...list, workspace]);
      },
      error: (err: unknown) => {
        this.creating.set(false);
        this.createError.set(errorMessage(err, 'Could not create the workspace.'));
      }
    });
  }

  // --- Members ---------------------------------------------------------------

  canManage(workspace: Workspace): boolean {
    return workspace.type === 'ORG' && workspace.capabilities.repoAdmin;
  }

  toggleMembers(workspace: Workspace): void {
    if (this.expandedId() === workspace.id) {
      this.expandedId.set(null);
      return;
    }
    this.expandedId.set(workspace.id);
    this.memberActionError.set(null);
    if (!this.canManage(workspace)) {
      return; // viewers never fetch the member list (view floor is per workspace)
    }
    this.membersState.set('loading');
    this.membersError.set(null);
    this.workspacesApi.members(workspace.id).subscribe({
      next: members => {
        this.members.set(members);
        this.membersState.set('ready');
      },
      error: (err: unknown) => {
        this.membersError.set(errorMessage(err, 'Could not load members.'));
        this.membersState.set('error');
      }
    });
  }

  updateRole(workspace: Workspace, member: WorkspaceMemberRow, event: Event): void {
    const role = (event.target as HTMLSelectElement).value as WorkspaceRole;
    if (this.memberBusyId()) return;
    this.memberBusyId.set(member.user_id);
    this.memberActionError.set(null);
    this.workspacesApi.updateMemberRole(workspace.id, member.user_id, role).subscribe({
      next: updated => {
        this.memberBusyId.set(null);
        this.members.update(list =>
          list.map(existing =>
            existing.user_id === updated.user_id ? { ...existing, role: updated.role } : existing
          )
        );
      },
      error: (err: unknown) => {
        this.memberBusyId.set(null);
        // The backend already spells out its rules ("last ORG_ADMIN…").
        this.memberActionError.set(errorMessage(err, 'Could not change the member role.'));
      }
    });
  }

  removeMember(workspace: Workspace, member: WorkspaceMemberRow): void {
    if (this.memberBusyId()) return;
    this.memberBusyId.set(member.user_id);
    this.memberActionError.set(null);
    this.workspacesApi.removeMember(workspace.id, member.user_id).subscribe({
      next: () => {
        this.memberBusyId.set(null);
        this.members.update(list => list.filter(existing => existing.user_id !== member.user_id));
      },
      error: (err: unknown) => {
        this.memberBusyId.set(null);
        this.memberActionError.set(errorMessage(err, 'Could not remove the member.'));
      }
    });
  }
}
