import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { SettingsNavComponent } from './settings-nav.component';

describe('SettingsNavComponent — personal settings sub-navigation (plan Step 4)', () => {
  let fixture: ComponentFixture<SettingsNavComponent>;

  function create(): void {
    fixture = TestBed.createComponent(SettingsNavComponent);
    fixture.detectChanges();
  }

  function tab(testid: string): HTMLElement | null {
    return (fixture.nativeElement as HTMLElement).querySelector(`[data-testid="${testid}"]`);
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [SettingsNavComponent],
      providers: [provideRouter([])]
    });
  });

  it('renders exactly the three personal destinations', () => {
    create();
    expect(tab('settings-nav')).not.toBeNull();
    const profile = tab('settings-nav-profile');
    expect(profile).not.toBeNull();
    expect(profile?.getAttribute('href')).toBe('/settings/profile');
    expect(tab('settings-nav-review-preferences')?.getAttribute('href')).toBe(
      '/settings/review-preferences'
    );
    expect(tab('settings-nav-ai')?.getAttribute('href')).toBe('/settings/ai-model');
  });

  it('marks the active destination current and only that one', () => {
    create(); // default input: 'profile'
    expect(tab('settings-nav-profile')?.getAttribute('aria-current')).toBe('page');
    expect(tab('settings-nav-ai')?.getAttribute('aria-current')).toBeNull();
    expect(tab('settings-nav-review-preferences')?.getAttribute('aria-current')).toBeNull();

    fixture.componentRef.setInput('active', 'ai');
    fixture.detectChanges();
    expect(tab('settings-nav-ai')?.getAttribute('aria-current')).toBe('page');
    expect(tab('settings-nav-profile')?.getAttribute('aria-current')).toBeNull();

    fixture.componentRef.setInput('active', 'review-preferences');
    fixture.detectChanges();
    expect(tab('settings-nav-review-preferences')?.getAttribute('aria-current')).toBe('page');
  });

  it('never links organization or platform administration', () => {
    // The personal settings navigation must stay personal: org settings and
    // the platform console are separate workspaces with their own navs
    // (plan Step 4 rule: no org/platform links in the personal settings nav).
    create();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).not.toContain('Organization');
    expect(text).not.toContain('Platform');
    expect(text).not.toContain('Members');
    expect(tab('settings-nav-organization')).toBeNull();
    expect(tab('settings-nav-members')).toBeNull();
    expect(tab('settings-nav-platform')).toBeNull();
  });
});
