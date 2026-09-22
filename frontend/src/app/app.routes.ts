import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';

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
    path: 'auth/callback',
    loadComponent: () =>
      import('./features/auth/callback/callback.component').then(m => m.CallbackComponent)
  },
  {
    path: 'github/callback',
    loadComponent: () =>
      import('./features/auth/github-callback/github-callback.component').then(
        m => m.GithubCallbackComponent
      ),
    canActivate: [authGuard]
  },
  {
    path: 'dashboard',
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent),
    canActivate: [authGuard]
  },
  {
    path: 'repositories',
    loadComponent: () =>
      import('./features/repositories/repository-list/repository-list.component').then(
        m => m.RepositoryListComponent
      ),
    canActivate: [authGuard]
  },
  {
    path: 'repositories/:owner/:repo',
    loadComponent: () =>
      import('./features/repositories/repository-detail/repository-detail.component').then(
        m => m.RepositoryDetailComponent
      ),
    canActivate: [authGuard]
  },
  {
    path: 'repositories/:owner/:repo/pulls',
    loadComponent: () =>
      import('./features/pull-requests/pr-list/pr-list.component').then(m => m.PrListComponent),
    canActivate: [authGuard]
  },
  {
    path: 'repositories/:owner/:repo/pulls/:number',
    loadComponent: () =>
      import('./features/pull-requests/pr-detail/pr-detail.component').then(
        m => m.PrDetailComponent
      ),
    canActivate: [authGuard]
  },
  {
    path: 'settings',
    loadComponent: () =>
      import('./features/settings/settings.component').then(m => m.SettingsComponent),
    canActivate: [authGuard]
  },
  {
    path: '**',
    redirectTo: ''
  }
];
