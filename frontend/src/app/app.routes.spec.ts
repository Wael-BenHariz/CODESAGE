import { routes } from './app.routes';
import { PLATFORM_ROLES } from './core/guards/role.guard';

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

describe('app routes (/platform-admin static console)', () => {
  const consoleRoute = routes.find(route => route.path === 'platform-admin');
  const children = consoleRoute?.children ?? [];
  const childPaths = children.map(child => child.path);

  it('ships the console layout with all six pages', () => {
    expect(consoleRoute).toBeDefined();
    expect(consoleRoute?.loadComponent).toBeDefined();
    expect(childPaths).toEqual(['', 'users', 'settings', 'system', 'logs', 'quotas']);
    for (const child of children) {
      expect(child.loadComponent).toBeDefined();
    }
  });

  it('is platform-admin-only and renders its own shell', () => {
    expect(consoleRoute?.canActivate).toBeDefined();
    expect(consoleRoute?.data?.['roles']).toEqual(PLATFORM_ROLES);
    expect(consoleRoute?.data?.['shell']).toBe(false);
  });
});
