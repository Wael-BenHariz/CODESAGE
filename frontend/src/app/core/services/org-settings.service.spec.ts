import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiError, ApiService } from './api.service';
import {
  OrgSettings,
  OrgSettingsService,
  OrgSummary,
  camelSettingKey,
  canManageSettings,
  effectiveRole,
  parseSettingsError
} from './org-settings.service';

describe('role helpers (mirror backend org_access.py)', () => {
  it('computes effective = max(JWT, org role) on the ladder', () => {
    expect(effectiveRole('DEVELOPER', 'ORG_ADMIN')).toBe('ORG_ADMIN');
    expect(effectiveRole('ORG_ADMIN', 'DEVELOPER')).toBe('ORG_ADMIN');
    expect(effectiveRole('REVIEWER', null)).toBe('REVIEWER');
    expect(effectiveRole('NONE', 'REVIEWER')).toBe('REVIEWER');
    expect(effectiveRole('PLATFORM_ADMIN', 'ORG_ADMIN')).toBe('PLATFORM_ADMIN');
    expect(effectiveRole(null, null)).toBe('NONE');
    expect(effectiveRole('bogus-role', null)).toBe('NONE');
  });

  it('mirrors the PUT guard: NONE never writes, else effective >= ORG_ADMIN', () => {
    // §2 step 1: a NONE JWT is unconditionally read-only — membership
    // cannot rescue it, even if org_members says ORG_ADMIN.
    expect(canManageSettings('NONE', 'ORG_ADMIN')).toBeFalse();
    // §2 step 3: effective role decides — DEVELOPER claim + ORG_ADMIN row.
    expect(canManageSettings('DEVELOPER', 'ORG_ADMIN')).toBeTrue();
    expect(canManageSettings('REVIEWER', 'ORG_ADMIN')).toBeTrue();
    expect(canManageSettings('ORG_ADMIN', 'DEVELOPER')).toBeTrue();
    expect(canManageSettings('PLATFORM_ADMIN', null)).toBeTrue();
    expect(canManageSettings('ORG_ADMIN', null)).toBeTrue();
    // Below ORG_ADMIN with no elevation.
    expect(canManageSettings('DEVELOPER', 'DEVELOPER')).toBeFalse();
    expect(canManageSettings('REVIEWER', 'DEVELOPER')).toBeFalse();
    expect(canManageSettings('DEVELOPER', null)).toBeFalse();
    // Missing profile role fails closed until /auth/me lands.
    expect(canManageSettings(null, 'ORG_ADMIN')).toBeFalse();
  });
});

describe('camelSettingKey', () => {
  it('converts backend snake_case keys, including ceiling prefixes', () => {
    expect(camelSettingKey('diff_char_cap')).toBe('diffCharCap');
    expect(camelSettingKey('ai_model')).toBe('aiModel');
    expect(camelSettingKey('ceiling_diff_char_cap')).toBe('ceilingDiffCharCap');
    expect(camelSettingKey('ceiling_max_findings_per_agent')).toBe('ceilingMaxFindingsPerAgent');
  });
});

describe('parseSettingsError (422 → inline per field)', () => {
  it('maps FastAPI body-validation arrays by loc', () => {
    const err = new ApiError('Input should be a valid integer', 422, [
      { loc: ['body', 'diff_char_cap'], msg: 'Input should be a valid integer' }
    ]);
    const parsed = parseSettingsError(err);
    expect(parsed.fields['diffCharCap']).toBe('Input should be a valid integer');
    expect(parsed.form).toBeNull();
  });

  it('prefixes ceiling-block errors with `ceiling`', () => {
    const err = new ApiError('too big', 422, [
      { loc: ['body', 'ceilings', 'diff_char_cap'], msg: 'too big' }
    ]);
    const parsed = parseSettingsError(err);
    expect(parsed.fields['ceilingDiffCharCap']).toBe('too big');
  });

  it('maps route-level string details by field prefix', () => {
    const err = new ApiError('x', 422, 'diff_char_cap exceeds the ceiling: 5 > 3');
    expect(parseSettingsError(err).fields['diffCharCap']).toContain('exceeds the ceiling');

    const ceiling = new ApiError(
      'x',
      422,
      'ceiling_diff_char_cap must be between 1 and 100000 (hard cap)'
    );
    expect(parseSettingsError(ceiling).fields['ceilingDiffCharCap']).toContain('must be between');

    const severity = new ApiError('x', 422, 'min_severity_to_post must be one of');
    expect(parseSettingsError(severity).fields['minSeverityToPost']).toContain('must be one of');
  });

  it('maps the vocabulary messages that do not start with a field name', () => {
    const agents = new ApiError('x', 422, "Unknown agent(s) ['nope']; allowed: [...]");
    expect(parseSettingsError(agents).fields['enabledAgents']).toContain('Unknown agent');

    const triggers = new ApiError('x', 422, "Unknown trigger(s) ['nope']; allowed: [...]");
    expect(parseSettingsError(triggers).fields['reviewTriggers']).toContain('Unknown trigger');
  });

  it('falls back to a form-level message for unrecognized shapes', () => {
    const array = new ApiError('Input should be a valid integer', 422, [
      { loc: ['body'], msg: 'Something odd' }
    ]);
    expect(parseSettingsError(array).fields).toEqual({});
    expect(parseSettingsError(array).form).toBe('Something odd');

    const plain = new Error('network exploded');
    expect(parseSettingsError(plain).form).toBe('network exploded');
    expect(parseSettingsError('weird')).toEqual({
      fields: {},
      form: 'Request failed. Please try again.'
    });
  });
});

describe('OrgSettingsService payload mapping', () => {
  const orgDto = {
    org_id: 'org-1',
    overrides: {
      diff_char_cap: 20000,
      max_findings_per_agent: null,
      max_concurrent_reviews: null,
      enabled_agents: null,
      sonarqube_enabled: null,
      semgrep_enabled: null,
      review_triggers: null,
      min_severity_to_post: null,
      posting_mode: null,
      ai_model: null
    },
    effective: {
      diff_char_cap: 20000,
      max_findings_per_agent: 15,
      max_concurrent_reviews: 5,
      enabled_agents: ['security'],
      sonarqube_enabled: true,
      semgrep_enabled: true,
      review_triggers: ['pull_request'],
      min_severity_to_post: 'info',
      posting_mode: 'auto',
      ai_model: 'openai/gpt-oss-120b'
    },
    ceilings: {
      diff_char_cap: 100000,
      max_findings_per_agent: 50,
      max_concurrent_reviews: 10
    },
    overridden: {
      diff_char_cap: true,
      max_findings_per_agent: false,
      max_concurrent_reviews: false,
      enabled_agents: false,
      sonarqube_enabled: false,
      semgrep_enabled: false,
      review_triggers: false,
      min_severity_to_post: false,
      posting_mode: false,
      ai_model: false
    }
  };

  const platformDto = {
    defaults: orgDto.overrides,
    effective_defaults: orgDto.effective,
    ceilings: orgDto.ceilings,
    hard_caps: {
      diff_char_cap: 100000,
      max_findings_per_agent: 100,
      max_concurrent_reviews: 50
    }
  };

  let api: jasmine.SpyObj<ApiService>;
  let service: OrgSettingsService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'put']);
    TestBed.configureTestingModule({ providers: [{ provide: ApiService, useValue: api }] });
    service = TestBed.inject(OrgSettingsService);
  });

  it('PUTs only the provided keys, snake_cased (absent = keep, null = reset)', () => {
    api.put.and.returnValue(of(orgDto));

    service.saveOrgSettings('org-1', { diffCharCap: null, postingMode: 'staged' }).subscribe();

    expect(api.put).toHaveBeenCalledWith('/orgs/org-1/settings', {
      diff_char_cap: null,
      posting_mode: 'staged'
    });
  });

  it('maps GET /orgs/{id}/settings to the camel-case view', () => {
    api.get.and.returnValue(of(orgDto));

    let view: OrgSettings | undefined;
    service.getOrgSettings('org-1').subscribe(v => (view = v));

    expect(view?.effective.diffCharCap).toBe(20000);
    expect(view?.ceilings.maxFindingsPerAgent).toBe(50);
    expect(view?.overridden.diffCharCap).toBeTrue();
    expect(view?.overridden.aiModel).toBeFalse();
    expect(api.get).toHaveBeenCalledWith('/orgs/org-1/settings');
  });

  it('nests platform saves into defaults/ceilings blocks', () => {
    api.put.and.returnValue(of(platformDto));

    service
      .savePlatformSettings({
        defaults: { minSeverityToPost: 'high' },
        ceilings: { diffCharCap: 50000 }
      })
      .subscribe();

    expect(api.put).toHaveBeenCalledWith('/platform/settings', {
      defaults: { min_severity_to_post: 'high' },
      ceilings: { diff_char_cap: 50000 }
    });
  });

  it('lists the caller org context from GET /orgs', () => {
    api.get.and.returnValue(
      of([{ id: 'org-1', name: 'acme', account_type: 'Organization', role: 'ORG_ADMIN' }])
    );
    let orgs: OrgSummary[] = [];
    service.listOrgs().subscribe(v => (orgs = v));
    expect(api.get).toHaveBeenCalledWith('/orgs');
    expect(orgs[0].role).toBe('ORG_ADMIN');
  });
});
