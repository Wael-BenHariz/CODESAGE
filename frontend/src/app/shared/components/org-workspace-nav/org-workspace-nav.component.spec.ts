import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { OrgWorkspaceNavComponent } from './org-workspace-nav.component';

describe('OrgWorkspaceNavComponent — organization workspace navigation (plan Step 5)', () => {
  let fixture: ComponentFixture<OrgWorkspaceNavComponent>;

  function create(): void {
    fixture = TestBed.createComponent(OrgWorkspaceNavComponent);
    fixture.detectChanges();
  }

  function tab(testid: string): HTMLElement | null {
    return (fixture.nativeElement as HTMLElement).querySelector(`[data-testid="${testid}"]`);
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [OrgWorkspaceNavComponent],
      providers: [provideRouter([])]
    });
  });

  it('renders exactly the three org-workspace destinations', () => {
    create();
    expect(tab('org-workspace-nav')).not.toBeNull();
    expect(tab('org-nav-overview')?.getAttribute('href')).toBe('/settings/org?view=overview');
    expect(tab('org-nav-settings')?.getAttribute('href')).toBe('/settings/org?view=organization');
    expect(tab('org-nav-members')?.getAttribute('href')).toBe('/settings/org?view=members');
  });

  it('marks the active destination current and only that one', () => {
    create(); // default input: 'organization'
    expect(tab('org-nav-settings')?.getAttribute('aria-current')).toBe('page');
    expect(tab('org-nav-overview')?.getAttribute('aria-current')).toBeNull();
    expect(tab('org-nav-members')?.getAttribute('aria-current')).toBeNull();

    fixture.componentRef.setInput('active', 'overview');
    fixture.detectChanges();
    expect(tab('org-nav-overview')?.getAttribute('aria-current')).toBe('page');

    fixture.componentRef.setInput('active', 'members');
    fixture.detectChanges();
    expect(tab('org-nav-members')?.getAttribute('aria-current')).toBe('page');
  });

  it('never carries personal settings or platform destinations', () => {
    // The org workspace is its own area: personal settings (profile / AI
    // model) and the platform console have their own navigation.
    create();
    expect(tab('settings-nav-profile')).toBeNull();
    expect(tab('settings-nav-ai')).toBeNull();
    expect(tab('settings-nav-platform')).toBeNull();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).not.toContain('AI model');
    expect(text).not.toContain('Platform');
  });
});
