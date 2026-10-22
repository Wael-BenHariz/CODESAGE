import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { WritableSignal, signal } from '@angular/core';

import { PlatformAdminConsoleComponent } from './platform-admin-console.component';
import { AuthService } from '../../../core/services/auth.service';
import { User } from '../../../core/models/user.model';

describe('PlatformAdminConsoleComponent', () => {
  let fixture: ComponentFixture<PlatformAdminConsoleComponent>;
  let auth: {
    currentUser: WritableSignal<User | null>;
    logout: jasmine.Spy;
    switchAccount: jasmine.Spy;
  };

  const user: User = {
    id: 'u-1',
    login: 'nour',
    email: 'nour@example.com',
    name: null,
    avatarUrl: '',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    role: 'PLATFORM_ADMIN'
  };

  beforeEach(() => {
    auth = {
      currentUser: signal<User | null>(user),
      logout: jasmine.createSpy('logout'),
      switchAccount: jasmine.createSpy('switchAccount')
    };
    TestBed.configureTestingModule({
      imports: [PlatformAdminConsoleComponent],
      providers: [provideRouter([]), { provide: AuthService, useValue: auth }]
    });
    fixture = TestBed.createComponent(PlatformAdminConsoleComponent);
    fixture.detectChanges();
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('renders the seven console navigation entries (overview + prototype pages)', () => {
    const labels = Array.from(el().querySelectorAll('.pa-nav-item')).map(
      item => item.textContent?.trim() ?? ''
    );
    expect(labels).toEqual([
      'Overview',
      'Dashboard',
      'Users',
      'Global Settings',
      'System Monitoring',
      'System Logs',
      'Quotas & Configuration'
    ]);
  });

  it('shows the console header with the admin identity', () => {
    expect(el().querySelector('.pa-topbar-title')?.textContent).toContain(
      'Platform Administration'
    );
    expect(el().textContent).toContain('Administrator');
    expect(el().querySelector('.pa-avatar-fallback')?.textContent).toContain('NO');
  });

  it('links back into the main app from the shell-less console', () => {
    const back = el().querySelector<HTMLAnchorElement>('[data-testid="pa-back-to-app"]');
    expect(back).not.toBeNull();
    expect(back?.getAttribute('href')).toBe('/dashboard');
  });

  it('routes the logout entry through AuthService', () => {
    const logout = el().querySelector('[data-testid="pa-logout"]') as HTMLButtonElement;
    logout.click();
    expect(auth.logout).toHaveBeenCalled();
  });

  it('opens and closes the mobile drawer from the burger toggle', () => {
    const burger = el().querySelector('[data-testid="pa-burger"]') as HTMLButtonElement;
    burger.click();
    fixture.detectChanges();
    expect(el().querySelector('.pa-sidebar')?.classList.contains('open')).toBe(true);
    expect(el().querySelector('.pa-backdrop')).not.toBeNull();

    burger.click();
    fixture.detectChanges();
    expect(el().querySelector('.pa-sidebar')?.classList.contains('open')).toBe(false);
    expect(el().querySelector('.pa-backdrop')).toBeNull();
  });

  it('labels the mock pages as a prototype and keeps the overview banner-free', () => {
    // Before any navigation the signal defaults to the prototype branch
    // only when the URL says so; the overview must never carry the banner.
    fixture.componentRef.instance.prototypePage.set(false);
    fixture.detectChanges();
    expect(el().querySelector('[data-testid="pa-prototype-banner"]')).toBeNull();

    fixture.componentRef.instance.prototypePage.set(true);
    fixture.detectChanges();
    const banner = el().querySelector('[data-testid="pa-prototype-banner"]');
    expect(banner).not.toBeNull();
    expect(banner?.textContent).toContain('Prototype');
    expect(banner?.textContent).toContain('local sample data');
  });
});
