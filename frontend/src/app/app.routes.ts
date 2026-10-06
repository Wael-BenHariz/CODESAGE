import { Routes } from '@angular/router';
import {
  ADMIN_ROLES,
  ANY_ROLE,
  PLATFORM_ROLES,
  RoleGuard,
  WRITE_ROLES
} from './core/guards/role.guard';
import { confirmUnsavedSummaryGuard } from './features/pull-requests/pr-detail/pr-detail.guard';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./features/landing/landing.component').then(m => m.LandingComponent),
    // Public screen: rendered without the app shell (plan Step 3).
    data: { shell: false }
  },
  {
    path: 'login',
    loadComponent: () =>
      import('./features/auth/login/login.component').then(m => m.LoginComponent),
    data: { shell: false }
  },
  {
    // No guard here: this route is GitHub's post-install redirect target and
    // must render even when the session is still being restored (check-sso).
    path: 'github/callback',
    loadComponent: () =>
      import('./features/auth/github-callback/github-callback.component').then(
        m => m.GithubCallbackComponent
      ),
    data: { shell: false }
  },
  {
    // No guard: the invitee has no session yet (plan Step 12). The page
    // previews the token publicly, then either asks for sign-in (returning
    // here) or shows an explicit Accept button — never auto-accepts.
    path: 'invite/accept',
    loadComponent: () =>
      import('./features/invitations/invite-accept/invite-accept.component').then(
        m => m.InviteAcceptComponent
      ),
    data: { shell: false }
  },
  {
    path: 'dashboard',
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent),
    canActivate: [RoleGuard],
    data: { roles: WRITE_ROLES }
  },
  {
    path: 'repositories',
    loadComponent: () =>
      import('./features/repositories/repository-list/repository-list.component').then(
        m => m.RepositoryListComponent
      ),
    canActivate: [RoleGuard],
    data: { roles: ANY_ROLE }
  },
  {
    path: 'repositories/:owner/:repo',
    loadComponent: () =>
      import('./features/repositories/repository-detail/repository-detail.component').then(
        m => m.RepositoryDetailComponent
      ),
    canActivate: [RoleGuard],
    data: { roles: ANY_ROLE }
  },
  {
    path: 'repositories/:owner/:repo/pulls',
    loadComponent: () =>
      import('./features/pull-requests/pr-list/pr-list.component').then(m => m.PrListComponent),
    canActivate: [RoleGuard],
    data: { roles: ANY_ROLE }
  },
  {
    path: 'repositories/:owner/:repo/pulls/:number',
    loadComponent: () =>
      import('./features/pull-requests/pr-detail/pr-detail.component').then(
        m => m.PrDetailComponent
      ),
    canActivate: [RoleGuard],
    // Plan Step 4: warn before leaving with an unsaved summary edit.
    canDeactivate: [confirmUnsavedSummaryGuard],
    data: { roles: ANY_ROLE }
  },
  {
    path: 'settings',
    loadComponent: () =>
      import('./features/settings/settings.component').then(m => m.SettingsComponent),
    canActivate: [RoleGuard],
    data: { roles: WRITE_ROLES }
  },
  {
    // Org + platform settings (Step 5). ADMIN_ROLES on the JWT, or — same
    // effective role per plan §2 — an org_members ORG_ADMIN row (the guard
    // elevates; the backend re-checks authoritatively).
    path: 'settings/org',
    loadComponent: () =>
      import('./features/settings/org-settings/org-settings.component').then(
        m => m.OrgSettingsComponent
      ),
    canActivate: [RoleGuard],
    data: { roles: ADMIN_ROLES }
  },
  {
    // Platform admin screen (plan Step 9) — PLATFORM_ADMIN only. Not an
    // "admin route" for the guard's org-membership elevation (the role
    // list is not ADMIN_ROLES), so an ORG_ADMIN can never open it; the
    // backend re-authorizes every /users and /orgs read regardless.
    path: 'platform',
    loadComponent: () =>
      import('./features/admin/platform-admin/platform-admin.component').then(
        m => m.PlatformAdminComponent
      ),
    canActivate: [RoleGuard],
    data: { roles: PLATFORM_ROLES }
  },
  {
    // Generic 404 (rule 5) — also the wildcard target below, so an unknown
    // client-side URL renders the page instead of silently bouncing home.
    path: 'not-found',
    loadComponent: () =>
      import('./features/errors/not-found/not-found.component').then(m => m.NotFoundComponent),
    data: { shell: false }
  },
  {
    // Role-guard denial target (rule 5's "forbidden"). Unguarded: a
    // NONE-role user lands here from the guard and must not redirect-loop.
    path: 'forbidden',
    loadComponent: () =>
      import('./features/errors/forbidden/forbidden.component').then(m => m.ForbiddenComponent),
    data: { shell: false }
  },
  {
    path: '**',
    loadComponent: () =>
      import('./features/errors/not-found/not-found.component').then(m => m.NotFoundComponent),
    data: { shell: false }
  }
];
