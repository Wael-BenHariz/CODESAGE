import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { ReviewPreferencesComponent } from './review-preferences.component';

describe('ReviewPreferencesComponent — honest unavailable state (plan Step 4)', () => {
  let fixture: ComponentFixture<ReviewPreferencesComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ReviewPreferencesComponent],
      providers: [provideRouter([])]
    }).compileComponents();

    fixture = TestBed.createComponent(ReviewPreferencesComponent);
    fixture.detectChanges();
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('renders every preference control disabled with the not-available label', () => {
    const autoReview = el().querySelector('#settings-auto-review') as HTMLInputElement;
    expect(autoReview.disabled).toBeTrue();
    expect(autoReview.checked).toBeFalse();
    expect(
      (el().querySelector('#settings-security-scans') as HTMLInputElement).disabled
    ).toBeTrue();
    expect(
      (el().querySelector('#settings-review-frequency') as HTMLSelectElement).disabled
    ).toBeTrue();
    expect(
      (el().querySelector('#settings-performance-checks') as HTMLInputElement).disabled
    ).toBeTrue();

    const prefsNote = el().querySelector('[data-testid="prefs-unavailable"]')?.textContent ?? '';
    expect(prefsNote).toContain('Not available yet');
    expect(prefsNote).toContain('nothing here is saved');
  });

  it('keeps the email-notification toggles disabled and honestly labelled too', () => {
    const emailToggle = el().querySelector(
      '.notifications-card input[type="checkbox"]'
    ) as HTMLInputElement;
    expect(emailToggle.disabled).toBeTrue();
    expect(emailToggle.checked).toBeFalse();
    expect(el().querySelector('[data-testid="notifications-unavailable"]')?.textContent).toContain(
      'Not available yet'
    );
  });

  it('points to the organization workspace for what IS configurable — never saves here', () => {
    const pointer = el().querySelector('[data-testid="org-policy-pointer"]');
    expect(pointer?.textContent).toContain('organization-wide policy');
    const link = pointer?.querySelector<HTMLAnchorElement>('a[href="/settings/org"]');
    expect(link).not.toBeNull();
  });
});
