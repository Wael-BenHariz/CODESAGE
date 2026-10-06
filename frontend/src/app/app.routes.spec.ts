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
