import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { SidebarComponent } from './sidebar.component';
import { AuthService } from '../../../core/services/auth.service';
import { OrgSettingsService } from '../../../core/services/org-settings.service';
import { User } from '../../../core/models/user.model';

describe('SidebarComponent', () => {
  let fixture: ComponentFixture<SidebarComponent>;
  let auth: {
    currentUser: WritableSignal<User | null>;
    logout: jasmine.Spy;
    switchAccount: jasmine.Spy;
  };

  const user = (role: string): User => ({
    id: 'u-1',
    login: 'octocat',
    email: 'octo@example.com',
    name: null,
    avatarUrl: 'https://example.com/a.png',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    role
  });

  function render(role: string | null): void {
    auth.currentUser.set(role ? user(role) : null);
    fixture = TestBed.createComponent(SidebarComponent);
    fixture.detectChanges();
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function linkTexts(): string[] {
    return Array.from(el().querySelectorAll('.nav-item')).map(a => (a.textContent ?? '').trim());
  }

  beforeEach(() => {
    localStorage.removeItem('codesage_active_org');
    auth = {
      currentUser: signal<User | null>(null),
      logout: jasmine.createSpy('logout'),
      switchAccount: jasmine.createSpy('switchAccount')
    };
    TestBed.configureTestingModule({
      imports: [SidebarComponent],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: auth },
        { provide: OrgSettingsService, useValue: { listOrgs: () => of([]) } }
      ]
    });
  });

  afterEach(() => localStorage.removeItem('codesage_active_org'));

  it('shows read-only navigation to a NONE-role user', () => {
    render('NONE');

    expect(linkTexts()).toEqual(['Repositories']);
    expect(el().querySelector('[data-testid="nav-org-settings"]')).toBeNull();
    expect(el().querySelector('[data-testid="nav-dashboard"]')).toBeNull();
    expect(el().querySelector('[data-testid="nav-settings"]')).toBeNull();
  });

  it('shows Dashboard and AI model to a write role', () => {
    render('DEVELOPER');

    const links = linkTexts();
    expect(links).toContain('Dashboard');
    expect(links).toContain('Repositories');
    expect(links).toContain('AI model');
    expect(links).not.toContain('Organization');
    expect(links).not.toContain('Platform');
  });

  it('adds the Organization entry for an ORG_ADMIN', () => {
    render('ORG_ADMIN');

    expect(el().querySelector('[data-testid="nav-org-settings"]')).not.toBeNull();
  });

  it('adds the Platform entry only for a PLATFORM_ADMIN', () => {
    render('PLATFORM_ADMIN');
    expect(el().querySelector('[data-testid="nav-platform"]')).not.toBeNull();

    render('ORG_ADMIN');
    expect(el().querySelector('[data-testid="nav-platform"]')).toBeNull();

    render('DEVELOPER');
    expect(el().querySelector('[data-testid="nav-platform"]')).toBeNull();
  });

  it('points the brand at the right home per role', () => {
    render('NONE');
    expect(el().querySelector('.brand')?.getAttribute('href')).toBe('/repositories');

    render('DEVELOPER');
    expect(el().querySelector('.brand')?.getAttribute('href')).toBe('/dashboard');
  });

  it('labels the nav landmark for assistive technology', () => {
    render('DEVELOPER');
    expect(el().querySelector('nav[aria-label="Main navigation"]')).not.toBeNull();
    expect(el().querySelector('[data-testid="nav-repositories"]')).not.toBeNull();
  });
});
