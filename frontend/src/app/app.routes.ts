import { Routes } from '@angular/router';
import { ADMIN_ROLES, ANY_ROLE, RoleGuard, WRITE_ROLES } from './core/guards/role.guard';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./features/landing/landing.component').then(m => m.LandingComponent)
  },
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login/login.component').then(m => m.LoginComponent)
  },
  {
    // No guard here: this route is GitHub's post-install redirect target and
    // must render even when the session is still being restored (check-sso).
    path: 'github/callback',
    loadComponent: () =>
      import('./features/auth/github-callback/github-callback.component').then(
        m => m.GithubCallbackComponent
      )
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
    path: '**',
    redirectTo: ''
  }
];
