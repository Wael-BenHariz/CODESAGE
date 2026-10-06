import { Component, signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { of } from 'rxjs';

import { AppComponent } from './app.component';
import { AuthService } from './core/services/auth.service';
import { OrgSettingsService } from './core/services/org-settings.service';
import { User } from './core/models/user.model';

@Component({
  standalone: true,
  template: 'stub-page'
})
class StubComponent {}

describe('AppComponent', () => {
  let auth: {
    currentUser: WritableSignal<User | null>;
    logout: jasmine.Spy;
    switchAccount: jasmine.Spy;
  };

  const user: User = {
    id: 'u-1',
    login: 'octocat',
    email: 'octo@example.com',
    name: null,
    avatarUrl: 'https://example.com/a.png',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    role: 'DEVELOPER'
  };

  beforeEach(async () => {
    localStorage.removeItem('codesage_active_org');
    auth = {
      currentUser: signal<User | null>(null),
      logout: jasmine.createSpy('logout'),
      switchAccount: jasmine.createSpy('switchAccount')
    };
    const orgSvc = jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', ['listOrgs']);
    orgSvc.listOrgs.and.returnValue(of([]));

    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [
        provideRouter([
          { path: 'login', component: StubComponent, data: { shell: false } },
          { path: 'landing', component: StubComponent, data: { shell: false } },
          { path: 'dashboard', component: StubComponent }
        ]),
        { provide: AuthService, useValue: auth },
        { provide: OrgSettingsService, useValue: orgSvc }
      ]
    }).compileComponents();
  });

  afterEach(() => localStorage.removeItem('codesage_active_org'));

  async function render(path: string): Promise<{
    fixture: import('@angular/core/testing').ComponentFixture<AppComponent>;
    el: HTMLElement;
  }> {
    await TestBed.inject(Router).navigate([path]);
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    return { fixture, el: fixture.nativeElement as HTMLElement };
  }

  it('should create the app', async () => {
    const { fixture } = await render('/dashboard');
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should render the router outlet', async () => {
    const { el } = await render('/dashboard');
    expect(el.querySelector('router-outlet')).not.toBeNull();
  });

  it('omits the shell chrome without a session', async () => {
    const { el } = await render('/dashboard');

    expect(el.querySelector('[data-testid="app-sidebar"]')).toBeNull();
    expect(el.querySelector('[data-testid="site-header"]')).toBeNull();
    expect(el.querySelector('router-outlet')).not.toBeNull();
  });

  it('renders skip link, sidebar and top bar with a session on a shell route', async () => {
    auth.currentUser.set(user);
    const { el } = await render('/dashboard');

    expect(el.querySelector('.skip-link')).not.toBeNull();
    expect(el.querySelector('[data-testid="app-sidebar"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="site-header"]')).not.toBeNull();
    expect(el.querySelector('.backdrop')).toBeNull();
  });

  it('hides the shell on public (shell: false) routes even with a session', async () => {
    auth.currentUser.set(user);
    const { el } = await render('/login');

    expect(el.querySelector('[data-testid="app-sidebar"]')).toBeNull();
    expect(el.querySelector('[data-testid="site-header"]')).toBeNull();
    expect(el.querySelector('router-outlet')).not.toBeNull();
  });

  it('opens the mobile drawer with a backdrop and closes it on Escape', async () => {
    auth.currentUser.set(user);
    const { fixture, el } = await render('/dashboard');

    fixture.componentInstance.toggleNav();
    fixture.detectChanges();
    expect(el.querySelector('.backdrop')).not.toBeNull();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();
    expect(el.querySelector('.backdrop')).toBeNull();
  });
});
