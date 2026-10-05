import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import { ApiService, ApiError } from './api.service';

/**
 * Org & platform settings (Step 5) — API mapping + the pure decision
 * helpers the settings UI and the role guard share.
 *
 * Backend contract (docs/PLAN_ROLES_SETTINGS_STAGED.md §2/§3):
 * - `GET /orgs` returns the caller's org context (memberships; every org
 *   for PLATFORM_ADMIN per F2);
 * - PUT bodies are partial: **absent field = keep, explicit null =
 *   reset to default** — never send untouched fields;
 * - numerics above their ceiling / unknown vocabulary → 422 with either a
 *   FastAPI `{loc, msg}` array (body typing) or a single string starting
 *   with the offending field name (route ceiling/vocabulary checks).
 */

/** One organization the caller may act in (GET /orgs). */
export interface OrgSummary {
  id: string;
  name: string;
  account_type: string;
  /** Caller's own org_members role; null for platform admins without a row. */
  role: string | null;
}

/** Camel-case view of the ten settings fields (overrides / patch bodies). */
export interface SettingsOverrides {
  diffCharCap: number | null;
  maxFindingsPerAgent: number | null;
  maxConcurrentReviews: number | null;
  enabledAgents: string[] | null;
  sonarqubeEnabled: boolean | null;
  semgrepEnabled: boolean | null;
  reviewTriggers: string[] | null;
  minSeverityToPost: string | null;
  postingMode: string | null;
  aiModel: string | null;
}

/** Effective (merged) values — every field present, aiModel may be null. */
export interface EffectiveSettings {
  diffCharCap: number;
  maxFindingsPerAgent: number;
  maxConcurrentReviews: number;
  enabledAgents: string[];
  sonarqubeEnabled: boolean;
  semgrepEnabled: boolean;
  reviewTriggers: string[];
  minSeverityToPost: string;
  postingMode: string;
  aiModel: string | null;
}

export interface NumericCeilings {
  diffCharCap: number;
  maxFindingsPerAgent: number;
  maxConcurrentReviews: number;
}

export type SettingKey = keyof SettingsOverrides;
export type SettingValue = SettingsOverrides[SettingKey];
export type CeilingKey = keyof NumericCeilings;
export type CeilingPatch = { [K in CeilingKey]: number | null };

export interface OrgSettings {
  orgId: string;
  overrides: SettingsOverrides;
  effective: EffectiveSettings;
  ceilings: NumericCeilings;
  overridden: Record<SettingKey, boolean>;
}

export interface PlatformSettings {
  defaults: SettingsOverrides;
  effectiveDefaults: EffectiveSettings;
  ceilings: NumericCeilings;
  hardCaps: NumericCeilings;
}

export interface SettingsFieldErrors {
  /** Keyed by camel field name; ceilings as `ceilingDiffCharCap` etc. */
  fields: Record<string, string>;
  /** Form-level message when nothing maps to a field (or as a summary). */
  form: string | null;
}

// --- vocabularies (mirror backend org_settings.py / review_orchestrator.py) --

export const AGENT_DOMAINS = [
  'security',
  'complexity',
  'performance',
  'style',
  'test_coverage'
] as const;

export const TRIGGER_VOCAB = ['pull_request', 'manual'] as const;

export const SEVERITY_VOCAB = ['info', 'low', 'medium', 'high', 'critical'] as const;

export const POSTING_MODE_VOCAB = ['auto', 'staged'] as const;

export const NUMERIC_KEYS: CeilingKey[] = [
  'diffCharCap',
  'maxFindingsPerAgent',
  'maxConcurrentReviews'
];

export const BOOLEAN_KEYS: (keyof SettingsOverrides)[] = ['sonarqubeEnabled', 'semgrepEnabled'];

/** Field order = response/reporting order (mirrors backend SETTINGS_FIELDS). */
export const SETTING_KEYS: SettingKey[] = [
  'diffCharCap',
  'maxFindingsPerAgent',
  'maxConcurrentReviews',
  'enabledAgents',
  'sonarqubeEnabled',
  'semgrepEnabled',
  'reviewTriggers',
  'minSeverityToPost',
  'postingMode',
  'aiModel'
];

const CAMEL_TO_SNAKE: Record<SettingKey, string> = {
  diffCharCap: 'diff_char_cap',
  maxFindingsPerAgent: 'max_findings_per_agent',
  maxConcurrentReviews: 'max_concurrent_reviews',
  enabledAgents: 'enabled_agents',
  sonarqubeEnabled: 'sonarqube_enabled',
  semgrepEnabled: 'semgrep_enabled',
  reviewTriggers: 'review_triggers',
  minSeverityToPost: 'min_severity_to_post',
  postingMode: 'posting_mode',
  aiModel: 'ai_model'
};

const SNAKE_ORG_FIELDS = Object.values(CAMEL_TO_SNAKE);
const SNAKE_CEILINGS = NUMERIC_KEYS.map(key => `ceiling_${CAMEL_TO_SNAKE[key]}`);

/** `ceiling_diff_char_cap` -> `ceilingDiffCharCap`, `ai_model` -> `aiModel`. */
export function camelSettingKey(snake: string): string {
  return snake.replace(/_([a-z])/g, (_match, chr: string) => chr.toUpperCase());
}

// --- role helpers (mirror backend app/security/org_access.py) ----------------

// Ladder rank (plan §2). NONE has no ladder position — ranked lowest so
// max(NONE, member role) resolves to the member role; a NONE *JWT* still
// fails every write regardless (step 1).
const RANK: Record<string, number> = {
  NONE: 0,
  DEVELOPER: 1,
  REVIEWER: 2,
  ORG_ADMIN: 3,
  PLATFORM_ADMIN: 4
};

function normalizeRole(role: string | null | undefined): string {
  const upper = String(role ?? '').toUpperCase();
  return upper in RANK ? upper : 'NONE';
}

/** Effective role = max(JWT role, org_members.role), unknowns → NONE. */
export function effectiveRole(
  jwtRole: string | null | undefined,
  orgRole: string | null | undefined
): string {
  const jwt = normalizeRole(jwtRole);
  const org = normalizeRole(orgRole);
  return RANK[jwt] >= RANK[org] ? jwt : org;
}

/**
 * Can the caller edit these settings? Mirrors the backend PUT guard:
 * NONE is unconditionally read-only (§2 step 1) and the *effective* role
 * must reach ORG_ADMIN (§2 step 3). The API stays authoritative — a
 * surprise 403 renders as a read-only error, never a silent write.
 */
export function canManageSettings(
  jwtRole: string | null | undefined,
  orgRole: string | null | undefined
): boolean {
  if (normalizeRole(jwtRole) === 'NONE') {
    return false;
  }
  return RANK[effectiveRole(jwtRole, orgRole)] >= RANK['ORG_ADMIN'];
}

// --- 422 parsing (inline per-field messages) ---------------------------------

/**
 * Map a failed settings PUT to per-field messages.
 *
 * Two 422 shapes exist: FastAPI body validation (`detail: [{loc, msg}]`,
 * loc like `["body", "ceilings", "diff_char_cap"]`) and the route's
 * ceiling/vocabulary rejections (`detail` is a single string that starts
 * with the offending field — except `Unknown agent(s)` / `Unknown
 * trigger(s)`, matched by keyword here).
 */
export function parseSettingsError(err: unknown): SettingsFieldErrors {
  const detail = err instanceof ApiError ? err.detail : undefined;
  const fallback =
    err instanceof Error && err.message ? err.message : 'Request failed. Please try again.';

  if (Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    const others: string[] = [];
    for (const raw of detail) {
      if (!raw || typeof raw !== 'object') {
        continue;
      }
      const record = raw as { loc?: unknown; msg?: unknown };
      const loc = Array.isArray(record.loc) ? record.loc : [];
      const last = String(loc[loc.length - 1] ?? '');
      const msg = String(record.msg ?? 'Invalid value');
      if (loc.includes('ceilings') && SNAKE_ORG_FIELDS.includes(last)) {
        fields[camelSettingKey(`ceiling_${last}`)] = msg;
      } else if (SNAKE_ORG_FIELDS.includes(last)) {
        fields[camelSettingKey(last)] = msg;
      } else {
        others.push(msg);
      }
    }
    if (Object.keys(fields).length > 0 || others.length > 0) {
      return { fields, form: others.length > 0 ? others.join(' ') : null };
    }
  }

  if (typeof detail === 'string') {
    const ceiling = SNAKE_CEILINGS.find(key => detail.startsWith(key));
    if (ceiling) {
      return { fields: { [camelSettingKey(ceiling)]: detail }, form: null };
    }
    const field = SNAKE_ORG_FIELDS.find(key => detail.startsWith(key));
    if (field) {
      return { fields: { [camelSettingKey(field)]: detail }, form: null };
    }
    if (detail.startsWith('Unknown agent')) {
      return { fields: { enabledAgents: detail }, form: null };
    }
    if (detail.startsWith('Unknown trigger')) {
      return { fields: { reviewTriggers: detail }, form: null };
    }
    return { fields: {}, form: detail };
  }

  return { fields: {}, form: fallback };
}

// --- DTO shapes (snake_case on the wire) -------------------------------------

interface SettingsValuesDto {
  diff_char_cap: number | null;
  max_findings_per_agent: number | null;
  max_concurrent_reviews: number | null;
  enabled_agents: string[] | null;
  sonarqube_enabled: boolean | null;
  semgrep_enabled: boolean | null;
  review_triggers: string[] | null;
  min_severity_to_post: string | null;
  posting_mode: string | null;
  ai_model: string | null;
}

interface EffectiveValuesDto extends SettingsValuesDto {
  diff_char_cap: number;
  max_findings_per_agent: number;
  max_concurrent_reviews: number;
  enabled_agents: string[];
  sonarqube_enabled: boolean;
  semgrep_enabled: boolean;
  review_triggers: string[];
  min_severity_to_post: string;
  posting_mode: string;
}

interface CeilingsDto {
  diff_char_cap: number;
  max_findings_per_agent: number;
  max_concurrent_reviews: number;
}

interface OrgSettingsResponseDto {
  org_id: string;
  overrides: SettingsValuesDto;
  effective: EffectiveValuesDto;
  ceilings: CeilingsDto;
  overridden: Record<string, boolean>;
}

interface PlatformSettingsResponseDto {
  defaults: SettingsValuesDto;
  effective_defaults: EffectiveValuesDto;
  ceilings: CeilingsDto;
  hard_caps: CeilingsDto;
}

function overridesFromDto(dto: SettingsValuesDto): SettingsOverrides {
  return {
    diffCharCap: dto.diff_char_cap,
    maxFindingsPerAgent: dto.max_findings_per_agent,
    maxConcurrentReviews: dto.max_concurrent_reviews,
    enabledAgents: dto.enabled_agents,
    sonarqubeEnabled: dto.sonarqube_enabled,
    semgrepEnabled: dto.semgrep_enabled,
    reviewTriggers: dto.review_triggers,
    minSeverityToPost: dto.min_severity_to_post,
    postingMode: dto.posting_mode,
    aiModel: dto.ai_model
  };
}

function effectiveFromDto(dto: EffectiveValuesDto): EffectiveSettings {
  return {
    diffCharCap: dto.diff_char_cap,
    maxFindingsPerAgent: dto.max_findings_per_agent,
    maxConcurrentReviews: dto.max_concurrent_reviews,
    enabledAgents: dto.enabled_agents,
    sonarqubeEnabled: dto.sonarqube_enabled,
    semgrepEnabled: dto.semgrep_enabled,
    reviewTriggers: dto.review_triggers,
    minSeverityToPost: dto.min_severity_to_post,
    postingMode: dto.posting_mode,
    aiModel: dto.ai_model
  };
}

function ceilingsFromDto(dto: CeilingsDto): NumericCeilings {
  return {
    diffCharCap: dto.diff_char_cap,
    maxFindingsPerAgent: dto.max_findings_per_agent,
    maxConcurrentReviews: dto.max_concurrent_reviews
  };
}

/** camel patch -> snake payload (only the keys actually present). */
function patchToDto<K extends keyof SettingsOverrides>(
  patch: Partial<Pick<SettingsOverrides, K>>,
  keys: readonly K[]
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(patch, key)) {
      body[CAMEL_TO_SNAKE[key]] = patch[key];
    }
  }
  return body;
}

@Injectable({ providedIn: 'root' })
export class OrgSettingsService {
  private readonly api = inject(ApiService);

  /** The caller's org context (empty for users without memberships). */
  listOrgs(): Observable<OrgSummary[]> {
    return this.api.get<OrgSummary[]>('/orgs');
  }

  getOrgSettings(orgId: string): Observable<OrgSettings> {
    return this.api
      .get<OrgSettingsResponseDto>(`/orgs/${orgId}/settings`)
      .pipe(map(dto => this.mapOrgResponse(dto)));
  }

  /**
   * Partial save: absent keys are kept by the backend — the component
   * must send only dirty fields (and explicit nulls for resets).
   */
  saveOrgSettings(orgId: string, patch: Partial<SettingsOverrides>): Observable<OrgSettings> {
    return this.api
      .put<OrgSettingsResponseDto>(`/orgs/${orgId}/settings`, patchToDto(patch, SETTING_KEYS))
      .pipe(map(dto => this.mapOrgResponse(dto)));
  }

  getPlatformSettings(): Observable<PlatformSettings> {
    return this.api
      .get<PlatformSettingsResponseDto>('/platform/settings')
      .pipe(map(dto => this.mapPlatformResponse(dto)));
  }

  savePlatformSettings(patch: {
    defaults?: Partial<SettingsOverrides>;
    ceilings?: Partial<CeilingPatch>;
  }): Observable<PlatformSettings> {
    const body: Record<string, unknown> = {};
    if (patch.defaults) {
      body['defaults'] = patchToDto(patch.defaults, SETTING_KEYS);
    }
    if (patch.ceilings) {
      body['ceilings'] = patchToDto(patch.ceilings, NUMERIC_KEYS);
    }
    return this.api
      .put<PlatformSettingsResponseDto>('/platform/settings', body)
      .pipe(map(dto => this.mapPlatformResponse(dto)));
  }

  private mapOrgResponse(dto: OrgSettingsResponseDto): OrgSettings {
    const overridden: Record<SettingKey, boolean> = {} as Record<SettingKey, boolean>;
    for (const key of SETTING_KEYS) {
      overridden[key] = Boolean(dto.overridden[CAMEL_TO_SNAKE[key]]);
    }
    return {
      orgId: dto.org_id,
      overrides: overridesFromDto(dto.overrides),
      effective: effectiveFromDto(dto.effective),
      ceilings: ceilingsFromDto(dto.ceilings),
      overridden
    };
  }

  private mapPlatformResponse(dto: PlatformSettingsResponseDto): PlatformSettings {
    return {
      defaults: overridesFromDto(dto.defaults),
      effectiveDefaults: effectiveFromDto(dto.effective_defaults),
      ceilings: ceilingsFromDto(dto.ceilings),
      hardCaps: ceilingsFromDto(dto.hard_caps)
    };
  }
}
