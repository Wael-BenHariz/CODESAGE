import { TestBed, ComponentFixture } from '@angular/core/testing';
import { WritableSignal, signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { OrgSettingsComponent } from './org-settings.component';
import { AuthService } from '../../../core/services/auth.service';
import { ApiError } from '../../../core/services/api.service';
import { InvitationService } from '../../../core/services/invitation.service';
import {
  OrgSettings,
  OrgSettingsService,
  OrgSummary,
  PlatformSettings
} from '../../../core/services/org-settings.service';

describe('OrgSettingsComponent — org + platform settings (Step 5)', () => {
  let fixture: ComponentFixture<OrgSettingsComponent>;
  let component: OrgSettingsComponent;
  let orgSvc: jasmine.SpyObj<OrgSettingsService>;
  let invitations: jasmine.SpyObj<InvitationService>;
  let roleSignal: WritableSignal<{ role: string } | null>;

  const orgSettings: OrgSettings = {
    orgId: 'org-1',
    overrides: {
      diffCharCap: 20000,
      maxFindingsPerAgent: null,
      maxConcurrentReviews: null,
      enabledAgents: null,
      sonarqubeEnabled: null,
      semgrepEnabled: null,
      reviewTriggers: null,
      minSeverityToPost: null,
      postingMode: null,
      aiModel: null
    },
    effective: {
      diffCharCap: 20000,
      maxFindingsPerAgent: 15,
      maxConcurrentReviews: 5,
      enabledAgents: ['security', 'complexity', 'performance', 'style', 'test_coverage'],
      sonarqubeEnabled: true,
      semgrepEnabled: true,
      reviewTriggers: ['pull_request', 'manual'],
      minSeverityToPost: 'info',
      postingMode: 'auto',
      aiModel: 'openai/gpt-oss-120b'
    },
    ceilings: { diffCharCap: 100000, maxFindingsPerAgent: 50, maxConcurrentReviews: 10 },
    overridden: {
      diffCharCap: true,
      maxFindingsPerAgent: false,
      maxConcurrentReviews: false,
      enabledAgents: false,
      sonarqubeEnabled: false,
      semgrepEnabled: false,
      reviewTriggers: false,
      minSeverityToPost: false,
      postingMode: false,
      aiModel: false
    }
  };

  const platformSettings: PlatformSettings = {
    defaults: { ...orgSettings.overrides, postingMode: 'staged' },
    effectiveDefaults: { ...orgSettings.effective, postingMode: 'staged' },
    ceilings: { diffCharCap: 80000, maxFindingsPerAgent: 50, maxConcurrentReviews: 10 },
    hardCaps: { diffCharCap: 100000, maxFindingsPerAgent: 100, maxConcurrentReviews: 50 }
  };

  beforeEach(() => {
    roleSignal = signal<{ role: string } | null>({ role: 'ORG_ADMIN' });

    orgSvc = jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', [
      'listOrgs',
      'getOrgSettings',
      'saveOrgSettings',
      'getPlatformSettings',
      'savePlatformSettings'
    ]);
    orgSvc.getOrgSettings.and.returnValue(of(orgSettings));
    orgSvc.saveOrgSettings.and.returnValue(of(orgSettings));
    orgSvc.getPlatformSettings.and.returnValue(of(platformSettings));
    orgSvc.savePlatformSettings.and.returnValue(of(platformSettings));

    // Embedded child (Step 12) — stubbed so the org settings tests never
    // need HttpClient (it only reads InvitationService).
    invitations = jasmine.createSpyObj<InvitationService>('InvitationService', ['list']);
    invitations.list.and.returnValue(of([]));

    TestBed.configureTestingModule({
      imports: [OrgSettingsComponent],
      providers: [
        // <app-site-header> carries routerLink directives → the router's
        // ActivatedRoute must exist in the test injector.
        provideRouter([]),
        { provide: OrgSettingsService, useValue: orgSvc },
        { provide: InvitationService, useValue: invitations },
        // The component only reads currentUser()?.role.
        { provide: AuthService, useValue: { currentUser: roleSignal } }
      ]
    });
  });

  function create(
    role: string,
    orgRole: string | null = 'ORG_ADMIN',
    orgs: OrgSummary[] | null = null
  ): void {
    roleSignal.set({ role });
    const list: OrgSummary[] =
      orgs ??
      (orgRole === null
        ? []
        : [{ id: 'org-1', name: 'acme', account_type: 'Organization', role: orgRole }]);
    orgSvc.listOrgs.and.returnValue(of(list));
    fixture = TestBed.createComponent(OrgSettingsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges(); // ngOnInit → listOrgs → getOrgSettings (sync of())
  }

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('loads the org context and shows the effective role', () => {
    create('ORG_ADMIN');
    expect(orgSvc.listOrgs).toHaveBeenCalled();
    expect(orgSvc.getOrgSettings).toHaveBeenCalledWith('org-1');
    expect(el().querySelector('[data-testid="effective-role"]')?.textContent).toContain(
      'ORG_ADMIN'
    );
    expect(orgSvc.getPlatformSettings).not.toHaveBeenCalled();
  });

  it('shows each numeric ceiling beside its field', () => {
    create('ORG_ADMIN');
    const hints = el().querySelectorAll('[data-testid="ceiling-hint"]');
    expect(hints.length).toBe(3); // the three numeric fields
    const text = el().textContent ?? '';
    expect(text).toContain('max 100000');
    expect(text).toContain('max 50');
    expect(text).toContain('max 10');
  });

  it('PUTs only dirty fields — absent fields are kept by the backend', () => {
    create('ORG_ADMIN');
    component.setField('org', 'maxFindingsPerAgent', '20');
    component.save('org');

    expect(orgSvc.saveOrgSettings).toHaveBeenCalledWith('org-1', {
      maxFindingsPerAgent: 20
    });
    expect(component.orgForm.dirty.size).toBe(0);
    expect(component.orgForm.saved).toBeTrue();
  });

  it('does not PUT fields the user did not touch (display-only values)', () => {
    create('ORG_ADMIN');
    // Inherited toggles render their effective value but stay out of the payload.
    expect(component.valueOf('org', 'postingMode')).toBe('auto');
    component.setField('org', 'aiModel', '   ');
    component.save('org');
    // Blank text = explicit reset (null), nothing else included.
    expect(orgSvc.saveOrgSettings).toHaveBeenCalledWith('org-1', { aiModel: null });
  });

  it('offers "Reset to default" only for overridden fields and PUTs an explicit null', () => {
    create('ORG_ADMIN');
    const reset = el().querySelector(
      '[data-testid="reset-org-diffCharCap"]'
    ) as HTMLButtonElement | null;
    expect(reset).not.toBeNull();
    expect(el().querySelector('[data-testid="reset-org-postingMode"]')).toBeNull();

    reset?.click();
    expect(orgSvc.saveOrgSettings).toHaveBeenCalledWith('org-1', { diffCharCap: null });
  });

  it('renders a route-level 422 string inline next to the offending field', () => {
    create('ORG_ADMIN');
    orgSvc.saveOrgSettings.and.returnValue(
      throwError(
        () =>
          new ApiError(
            'diff_char_cap exceeds the ceiling: 999999 > 100000',
            422,
            'diff_char_cap exceeds the ceiling: 999999 > 100000'
          )
      )
    );

    component.setField('org', 'diffCharCap', 999999);
    component.save('org');
    fixture.detectChanges();

    expect(component.orgForm.errors['diffCharCap']).toContain('exceeds the ceiling');
    expect(el().querySelector('[data-testid="error-org-diffCharCap"]')?.textContent).toContain(
      'exceeds the ceiling'
    );
    expect(component.orgForm.saving).toBeFalse();
  });

  it('renders FastAPI body-validation 422 arrays inline too', () => {
    create('ORG_ADMIN');
    orgSvc.saveOrgSettings.and.returnValue(
      throwError(
        () =>
          new ApiError('Input should be a valid integer', 422, [
            { loc: ['body', 'max_concurrent_reviews'], msg: 'Input should be a valid integer' }
          ])
      )
    );

    component.setField('org', 'maxConcurrentReviews', 'not-a-number');
    component.save('org');
    fixture.detectChanges();

    expect(
      el().querySelector('[data-testid="error-org-maxConcurrentReviews"]')?.textContent
    ).toContain('Input should be a valid integer');
  });

  it('shows an unmapped 422 as a section-level error', () => {
    create('ORG_ADMIN');
    orgSvc.saveOrgSettings.and.returnValue(
      throwError(() => new ApiError('Something exploded', 422, 'Something exploded'))
    );

    component.setField('org', 'postingMode', 'staged');
    component.save('org');
    fixture.detectChanges();

    // Unknown shape → form-level; the field message itself is generic.
    expect(component.orgForm.error ?? component.orgForm.errors['postingMode']).toContain(
      'Something exploded'
    );
  });

  it('renders read-only for a lower effective role (backend stays authoritative)', async () => {
    create('DEVELOPER', 'DEVELOPER');

    expect(component.canEdit('org')).toBeFalse();
    expect(el().querySelector('[data-testid="read-only-banner"]')).not.toBeNull();
    // NgModel applies its `disabled` input to the DOM in a microtask.
    await fixture.whenStable();
    const input = el().querySelector('[data-testid="org-maxFindingsPerAgent"]') as HTMLInputElement;
    expect(input.disabled).toBeTrue();
    expect(component.canSave('org')).toBeFalse();
  });

  it('keeps editing enabled through the ORG_ADMIN membership elevation', () => {
    // DEVELOPER claim, ORG_ADMIN org_members row → effective ORG_ADMIN.
    create('DEVELOPER', 'ORG_ADMIN');
    expect(component.canEdit('org')).toBeTrue();
    expect(el().querySelector('[data-testid="read-only-banner"]')).toBeNull();
    const input = el().querySelector('[data-testid="org-maxFindingsPerAgent"]') as HTMLInputElement;
    expect(input.disabled).toBeFalse();
  });

  it('hides the platform sections from non-platform admins', () => {
    create('ORG_ADMIN');
    const text = el().textContent ?? '';
    expect(text).not.toContain('Platform defaults');
    expect(text).not.toContain('Numeric ceilings');
    expect(orgSvc.getPlatformSettings).not.toHaveBeenCalled();
  });

  it('renders the platform defaults + ceilings sections for PLATFORM_ADMIN', () => {
    create('PLATFORM_ADMIN', null);
    expect(orgSvc.getPlatformSettings).toHaveBeenCalled();
    const text = el().textContent ?? '';
    expect(text).toContain('Platform defaults');
    expect(text).toContain('Numeric ceilings');
    // Ceilings show their hard cap beside the input.
    expect(text).toContain('max 100000'); // hard cap for diff_char_cap
    expect(component.sections().map(s => s.id)).toEqual(['org', 'defaults', 'ceilings']);
  });

  it('saves platform ceilings as their own block', () => {
    create('PLATFORM_ADMIN', null);
    component.setField('ceilings', 'diffCharCap', 12345);
    component.save('ceilings');
    expect(orgSvc.savePlatformSettings).toHaveBeenCalledWith({
      ceilings: { diffCharCap: 12345 }
    });
    expect(component.ceilingsForm.saved).toBeTrue();
  });

  it('maps platform ceiling 422s onto the ceilings fields', () => {
    create('PLATFORM_ADMIN', null);
    orgSvc.savePlatformSettings.and.returnValue(
      throwError(
        () =>
          new ApiError(
            'ceiling_diff_char_cap must be between 1 and 100000 (hard cap)',
            422,
            'ceiling_diff_char_cap must be between 1 and 100000 (hard cap)'
          )
      )
    );

    component.setField('ceilings', 'diffCharCap', 999999);
    component.save('ceilings');
    fixture.detectChanges();

    expect(component.ceilingsForm.errors['diffCharCap']).toContain('must be between');
    expect(el().querySelector('[data-testid="error-ceilings-diffCharCap"]')?.textContent).toContain(
      'must be between'
    );
  });

  it('shows an empty state when the caller has no organization', () => {
    create('DEVELOPER', null);
    const text = el().textContent ?? '';
    expect(text).toContain('No organization is linked');
    expect(orgSvc.getOrgSettings).not.toHaveBeenCalled();
    expect(component.sections().length).toBe(1);
  });

  it('surfaces a failed org-settings load with the backend message', () => {
    roleSignal.set({ role: 'ORG_ADMIN' });
    orgSvc.listOrgs.and.returnValue(
      of([{ id: 'org-1', name: 'acme', account_type: 'Organization', role: 'ORG_ADMIN' }])
    );
    orgSvc.getOrgSettings.and.returnValue(throwError(() => new Error('nope')));
    fixture = TestBed.createComponent(OrgSettingsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();

    expect(component.orgForm.error).toContain('nope');
    expect(component.sectionReady('org')).toBeFalse();
  });
});
