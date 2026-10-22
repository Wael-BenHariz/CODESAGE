import { routes } from './app.routes';

describe('app routes (plan Step 9: /help)', () => {
  const help = routes.find(route => route.path === 'help');

  it('ships the /help guide route', () => {
    expect(help).toBeDefined();
    expect(help?.loadComponent).toBeDefined();
  });

  it('is public: no guard, no shell — readable before sign-in', () => {
    expect(help?.canActivate).toBeUndefined();
    expect(help?.canActivateChild).toBeUndefined();
    expect(help?.data?.['shell']).toBe(false);
  });
});

describe('app routes (personal settings family, plan Step 4)', () => {
  const settingsRedirect = routes.find(route => route.path === 'settings');
  const profile = routes.find(route => route.path === 'settings/profile');
  const preferences = routes.find(route => route.path === 'settings/review-preferences');
  const aiModel = routes.find(route => route.path === 'settings/ai-model');

  it('ships the three dedicated personal screens, all lazy', () => {
    for (const route of [profile, preferences, aiModel]) {
      expect(route).toBeDefined();
      expect(route?.loadComponent).toBeDefined();
    }
  });

  it('keeps every personal screen behind the write capability (NONE stays out)', () => {
    for (const route of [profile, preferences, aiModel]) {
      expect(route?.canActivate).toBeDefined();
      expect(route?.data?.['capabilities']).toEqual(['write']);
    }
  });

  it('redirects the legacy /settings to the profile screen (compatibility)', () => {
    expect(settingsRedirect?.redirectTo).toBe('settings/profile');
    expect(settingsRedirect?.pathMatch).toBe('full');
    expect(settingsRedirect?.loadComponent).toBeUndefined();
  });
});

describe('app routes (/reviews — cross-repo review history)', () => {
  const reviewsRoute = routes.find(route => route.path === 'reviews');

  it('ships the lazy review-history component', () => {
    expect(reviewsRoute).toBeDefined();
    expect(reviewsRoute?.loadComponent).toBeDefined();
  });

  it('is guarded for authenticated reads and renders in the app shell', () => {
    expect(reviewsRoute?.canActivate).toBeDefined();
    expect(reviewsRoute?.data?.['capabilities']).toEqual(['read']);
    expect(reviewsRoute?.data?.['shell']).toBeUndefined();
  });
});

describe('app routes (/platform consolidated console)', () => {
  const platformRoute = routes.find(route => route.path === 'platform');
  const children = platformRoute?.children ?? [];
  const childPaths = children.map(child => child.path);

  it('ships the console layout with the real overview + all prototype pages', () => {
    expect(platformRoute).toBeDefined();
    expect(platformRoute?.loadComponent).toBeDefined();
    expect(childPaths).toEqual(['', 'dashboard', 'users', 'settings', 'system', 'logs', 'quotas']);
    for (const child of children) {
      expect(child.loadComponent).toBeDefined();
    }
  });

  it('is platform-only and renders its own shell', () => {
    expect(platformRoute?.canActivate).toBeDefined();
    expect(platformRoute?.data?.['capabilities']).toEqual(['platform']);
    expect(platformRoute?.data?.['shell']).toBe(false);
  });

  it('keeps /platform-admin as a legacy redirect into /platform', () => {
    const legacy = routes.find(route => route.path === 'platform-admin');
    expect(legacy?.redirectTo).toBe('platform');
    expect(legacy?.loadComponent).toBeUndefined();
    expect(legacy?.canActivate).toBeUndefined();
  });
});

describe('app routes (/organization-repositories — repo-scoped invitations)', () => {
  const orgRoute = routes.find(route => route.path === 'organization-repositories');
  const repositoriesRoute = routes.find(route => route.path === 'repositories');

  it('ships the lazy organization-repositories component', () => {
    expect(orgRoute).toBeDefined();
    expect(orgRoute?.loadComponent).toBeDefined();
  });

  it('is guarded for authenticated reads — the same floor as /repositories', () => {
    // No invented role vocabulary (e.g. ORG_REVIEWER): the route asks for
    // the read capability only; the data itself is scoped server-side to
    // the caller's org memberships + explicit grants.
    expect(orgRoute?.canActivate).toBeDefined();
    expect(orgRoute?.data?.['capabilities']).toEqual(['read']);
    expect(orgRoute?.data?.['roles']).toBeUndefined();
    // Renders inside the app shell (only public screens opt out).
    expect(orgRoute?.data?.['shell']).toBeUndefined();
  });

  it('does not weaken the personal /repositories routes', () => {
    expect(repositoriesRoute?.canActivate).toBeDefined();
    expect(repositoriesRoute?.data?.['capabilities']).toEqual(['read']);
    const detail = routes.find(route => route.path === 'repositories/:owner/:repo');
    expect(detail?.data?.['capabilities']).toEqual(['read']);
  });
});
