import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal, WritableSignal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { SettingsNavComponent } from './settings-nav.component';
import { AuthService } from '../../../core/services/auth.service';
import { OrgSettingsService, OrgSummary } from '../../../core/services/org-settings.service';

describe('SettingsNavComponent — settings sub-navigation (Step 8)', () => {
  let fixture: ComponentFixture<SettingsNavComponent>;
  let auth: WritableSignal<{ role: string } | null>;
  let listOrgs: jasmine.Spy;

  function create(): void {
    fixture = TestBed.createComponent(SettingsNavComponent);
    fixture.detectChanges();
  }

  function tab(testid: string): HTMLElement | null {
    return (fixture.nativeElement as HTMLElement).querySelector(`[data-testid="${testid}"]`);
  }

  const membership = (role: string): OrgSummary[] => [
    { id: 'org-1', name: 'acme', account_type: 'Organization', role }
  ];

  beforeEach(() => {
    auth = signal<{ role: string } | null>(null);
    listOrgs = jasmine.createSpy('listOrgs').and.returnValue(of([]));
    TestBed.configureTestingModule({
      imports: [SettingsNavComponent],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: { currentUser: auth } },
        { provide: OrgSettingsService, useValue: { listOrgs } }
      ]
    });
  });

  it('renders the AI entry for everyone and marks it current', () => {
    auth.set({ role: 'DEVELOPER' });
    create();
    expect(tab('settings-nav')).not.toBeNull();
    const ai = tab('settings-nav-ai');
    expect(ai).not.toBeNull();
    expect(ai?.getAttribute('aria-current')).toBe('page');
    expect(tab('settings-nav-organization')).toBeNull();
    expect(tab('settings-nav-members')).toBeNull();
    expect(tab('settings-nav-platform')).toBeNull();
  });

  it('adds Organization + Members for an admin membership (effective role)', () => {
    auth.set({ role: 'DEVELOPER' });
    listOrgs.and.returnValue(of(membership('ORG_ADMIN')));
    create();
    const org = tab('settings-nav-organization');
    expect(org).not.toBeNull();
    expect(org?.getAttribute('href')).toBe('/settings/org?view=organization');
    const members = tab('settings-nav-members');
    expect(members).not.toBeNull();
    expect(members?.getAttribute('href')).toBe('/settings/org?view=members');
    expect(tab('settings-nav-platform')).toBeNull();
  });

  it('opens the org entries from the JWT alone without asking for orgs', () => {
    auth.set({ role: 'ORG_ADMIN' });
    create();
    expect(tab('settings-nav-organization')).not.toBeNull();
    expect(tab('settings-nav-members')).not.toBeNull();
    expect(listOrgs).not.toHaveBeenCalled();
  });

  it('adds the Platform entry only for PLATFORM_ADMIN and can mark it current', () => {
    auth.set({ role: 'PLATFORM_ADMIN' });
    create();
    expect(tab('settings-nav-platform')).not.toBeNull();
    expect(tab('settings-nav-ai')?.getAttribute('aria-current')).toBe('page');

    fixture.componentRef.setInput('active', 'platform');
    fixture.detectChanges();
    expect(tab('settings-nav-platform')?.getAttribute('aria-current')).toBe('page');
    expect(tab('settings-nav-ai')?.getAttribute('aria-current')).toBeNull();
  });

  it('fails closed when listing orgs errors', () => {
    auth.set({ role: 'DEVELOPER' });
    listOrgs.and.returnValue(throwError(() => new Error('nope')));
    create();
    expect(tab('settings-nav-ai')).not.toBeNull();
    expect(tab('settings-nav-organization')).toBeNull();
    expect(tab('settings-nav-members')).toBeNull();
    expect(tab('settings-nav-platform')).toBeNull();
  });
});
