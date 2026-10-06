import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { Observable } from 'rxjs';

import { AuthService } from '../../../core/services/auth.service';
import { OrgInvitationsComponent } from '../org-invitations/org-invitations.component';
import {
  SettingsNavComponent,
  SettingsNavTab
} from '../../../shared/components/settings-nav/settings-nav.component';
import {
  AGENT_DOMAINS,
  CeilingPatch,
  NUMERIC_KEYS,
  OrgSettings,
  OrgSettingsService,
  OrgSummary,
  PlatformSettings,
  POSTING_MODE_VOCAB,
  SEVERITY_VOCAB,
  SETTING_KEYS,
  SettingKey,
  SettingValue,
  SettingsOverrides,
  TRIGGER_VOCAB,
  canManageSettings,
  effectiveRole,
  parseSettingsError
} from '../../../core/services/org-settings.service';

/**
 * Org + platform settings page (Step 5; walkthrough structure Step 8, plan
 * §4.4).
 *
 * Three sections share one field renderer: `org` (the selected org's
 * overrides — grouped into Scanners / AI agents / Limits / Posting / Model),
 * `defaults` and `ceilings` (PLATFORM_ADMIN only). The shared
 * `app-settings-nav` sits on top; `?view=members` swaps the Organization
 * panel for Members & invitations (role explanations + invitations) without a
 * new route. Save semantics follow the backend contract — only dirty fields
 * are sent (absent = keep) and the per-field "Reset to default" button PUTs an
 * explicit `null`. 422 responses render inline next to the offending field.
 * The route guard (ADMIN_ROLES + org-membership elevation) is the gate; the
 * effective role computed here only disables editing — the backend re-checks
 * every request.
 */
type Section = 'org' | 'defaults' | 'ceilings';
type FieldKind = 'number' | 'boolean' | 'multi' | 'enum' | 'text';

const FIELD_KIND: Record<SettingKey, FieldKind> = {
  diffCharCap: 'number',
  maxFindingsPerAgent: 'number',
  maxConcurrentReviews: 'number',
  enabledAgents: 'multi',
  sonarqubeEnabled: 'boolean',
  semgrepEnabled: 'boolean',
  reviewTriggers: 'multi',
  minSeverityToPost: 'enum',
  postingMode: 'enum',
  aiModel: 'text'
};

const FIELD_LABELS: Record<SettingKey, string> = {
  diffCharCap: 'Diff character cap',
  maxFindingsPerAgent: 'Max findings per agent',
  maxConcurrentReviews: 'Max concurrent reviews',
  enabledAgents: 'Agents enabled',
  sonarqubeEnabled: 'SonarQube analysis',
  semgrepEnabled: 'Semgrep analysis',
  reviewTriggers: 'Review triggers',
  minSeverityToPost: 'Min severity to post',
  postingMode: 'Posting mode',
  aiModel: 'AI model'
};

const FIELD_HINTS: Partial<Record<SettingKey, string>> = {
  diffCharCap: 'Max characters of diff forwarded to the LLM.',
  maxFindingsPerAgent: 'Cap on findings each specialist returns.',
  maxConcurrentReviews: 'Reviews running at once for this org.',
  enabledAgents: 'Which of the five specialists run on every review.',
  sonarqubeEnabled: 'Run SonarQube in parallel with Semgrep.',
  semgrepEnabled: 'Run the Semgrep microservice scan.',
  reviewTriggers: 'Events that queue a review.',
  minSeverityToPost: 'Lowest severity that reaches the GitHub comment.',
  postingMode: 'auto posts immediately; staged holds the summary for in-app review.',
  aiModel: 'Leave empty to inherit the default.'
};

const CEILING_HINT = 'Org values above this ceiling are rejected (422).';

const AGENT_LABELS: Record<string, string> = {
  security: 'Security',
  complexity: 'Complexity',
  performance: 'Performance',
  style: 'Style',
  test_coverage: 'Test coverage'
};

const TRIGGER_LABELS: Record<string, string> = {
  pull_request: 'Pull request events',
  manual: 'Manual trigger & retry'
};

const SEVERITY_LABELS: Record<string, string> = {
  info: 'Info',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical'
};

const MODE_LABELS: Record<string, string> = {
  auto: 'auto — post right away',
  staged: 'staged — hold for in-app review'
};

const CEILING_ERROR_PREFIX = 'ceiling';

interface SectionUi {
  id: Section;
  title: string;
  subtitle: string;
}

/**
 * plan §4.4 — one plain-language group of the Organization section. Every
 * field keeps its exact renderer/testid; grouping only changes where the
 * group's own h3 + description sit above them.
 */
interface FieldGroup {
  readonly id: string;
  /** `null` = untitled (platform defaults/ceilings keep their section h2). */
  readonly title: string | null;
  readonly description: string;
  readonly keys: readonly SettingKey[];
}

/** The five Organization groups (plan §4.4). All ten SETTING_KEYS, once each. */
const ORG_GROUPS: readonly FieldGroup[] = [
  {
    id: 'scanners',
    title: 'Scanners',
    description:
      'SonarQube and Semgrep run in parallel on every review — findings from both engines are merged and de-duplicated.',
    keys: ['sonarqubeEnabled', 'semgrepEnabled']
  },
  {
    id: 'agents',
    title: 'AI agents',
    description:
      'Which of the five specialists run on every review, and how many findings each may return.',
    keys: ['enabledAgents', 'maxFindingsPerAgent']
  },
  {
    id: 'limits',
    title: 'Limits',
    description:
      'Caps that keep review runs predictable — each numeric field shows its ceiling, and a value above it is rejected (422).',
    keys: ['diffCharCap', 'maxConcurrentReviews']
  },
  {
    id: 'posting',
    title: 'Posting',
    description:
      'What queues a review, the lowest severity that reaches the GitHub comment, and whether it posts immediately or waits for approval.',
    keys: ['reviewTriggers', 'minSeverityToPost', 'postingMode']
  },
  {
    id: 'model',
    title: 'Model',
    description:
      'The model name this organization contributes to review runs — empty inherits the platform default (it never changes anyone’s provider or API key).',
    keys: ['aiModel']
  }
];

/** Mutable form state for one section — dirty keys drive partial PUTs. */
class FormScope {
  values: Partial<Record<SettingKey, SettingValue>> = {};
  readonly dirty = new Set<SettingKey>();
  errors: Record<string, string> = {};
  saving = false;
  saved = false;
  error: string | null = null;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

@Component({
  selector: 'app-org-settings',
  standalone: true,
  imports: [CommonModule, FormsModule, OrgInvitationsComponent, SettingsNavComponent],
  templateUrl: './org-settings.component.html',
  styleUrl: './org-settings.component.scss'
})
export class OrgSettingsComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly orgSettings = inject(OrgSettingsService);
  private readonly route = inject(ActivatedRoute);

  // Template constants.
  readonly SETTING_KEYS = SETTING_KEYS;
  readonly NUMERIC_KEYS = NUMERIC_KEYS;
  readonly AGENT_DOMAINS = AGENT_DOMAINS;
  readonly TRIGGER_VOCAB = TRIGGER_VOCAB;
  readonly SEVERITY_VOCAB = SEVERITY_VOCAB;
  readonly POSTING_MODE_VOCAB = POSTING_MODE_VOCAB;

  readonly orgForm = new FormScope();
  readonly defaultsForm = new FormScope();
  readonly ceilingsForm = new FormScope();

  orgs: OrgSummary[] = [];
  selectedOrgId: string | null = null;
  org: OrgSettings | null = null;
  platform: PlatformSettings | null = null;
  isPlatformAdmin = false;

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly platformError = signal<string | null>(null);

  /** plan §4.4 — in-page panel picked by /settings/org?view= (no new routes). */
  readonly view = signal<'organization' | 'members'>('organization');
  readonly navActive = computed<SettingsNavTab>(() =>
    this.view() === 'members' ? 'members' : 'organization'
  );

  ngOnInit(): void {
    this.load();
    // Sub-navigation: the shared nav links carry ?view= — the same component
    // instance is reused across the query change, so subscribe once.
    this.route.queryParamMap.subscribe(params => {
      this.view.set(params.get('view') === 'members' ? 'members' : 'organization');
    });
  }

  // --- loading ---------------------------------------------------------------

  load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.isPlatformAdmin = this.jwtRole === 'PLATFORM_ADMIN';

    this.orgSettings.listOrgs().subscribe({
      next: orgs => {
        this.orgs = orgs;
        this.loading.set(false);
        if (orgs.length > 0) {
          this.selectOrg(orgs[0].id);
        }
        if (this.isPlatformAdmin) {
          this.loadPlatform();
        }
      },
      error: err => {
        this.loadError.set(errorMessage(err, 'Could not load organizations.'));
        this.loading.set(false);
      }
    });
  }

  private loadPlatform(): void {
    this.platformError.set(null);
    this.orgSettings.getPlatformSettings().subscribe({
      next: platform => {
        this.platform = platform;
        this.initSection('defaults');
        this.initSection('ceilings');
      },
      error: err => {
        this.platformError.set(errorMessage(err, 'Could not load platform settings.'));
      }
    });
  }

  selectOrg(id: string): void {
    this.selectedOrgId = id;
    this.orgForm.dirty.clear();
    this.orgForm.errors = {};
    this.orgForm.error = null;
    this.orgForm.saved = false;

    this.orgSettings.getOrgSettings(id).subscribe({
      next: settings => {
        // Last-clicked org wins (responses may arrive out of order).
        if (this.selectedOrgId === id) {
          this.applyOrg(settings, new Set());
        }
      },
      error: err => {
        if (this.selectedOrgId === id) {
          this.org = null;
          this.orgForm.error = errorMessage(err, 'Could not load organization settings.');
        }
      }
    });
  }

  // --- template accessors ----------------------------------------------------

  get jwtRole(): string | null {
    return this.auth.currentUser()?.role ?? null;
  }

  private get selectedOrgRole(): string | null {
    return this.orgs.find(org => org.id === this.selectedOrgId)?.role ?? null;
  }

  /** max(JWT, org_members.role) for the selected org — plan §2. */
  get effectiveRoleLabel(): string {
    return effectiveRole(this.jwtRole, this.selectedOrgRole);
  }

  sections(): SectionUi[] {
    const list: SectionUi[] = [
      {
        id: 'org',
        title: 'Organization',
        subtitle: 'Applies to every review queued for the selected organization.'
      }
    ];
    if (this.isPlatformAdmin) {
      list.push({
        id: 'defaults',
        title: 'Platform defaults',
        subtitle: 'Used by organizations that do not override a field.'
      });
      list.push({
        id: 'ceilings',
        title: 'Numeric ceilings',
        subtitle: 'Upper limits no organization setting can exceed.'
      });
    }
    return list;
  }

  fieldsFor(section: Section): readonly SettingKey[] {
    return section === 'ceilings' ? NUMERIC_KEYS : SETTING_KEYS;
  }

  /** Field groups per section: org → the five plan §4.4 groups, platform → flat. */
  groupsFor(section: Section): readonly FieldGroup[] {
    if (section === 'org') {
      return ORG_GROUPS;
    }
    return [{ id: section, title: null, description: '', keys: this.fieldsFor(section) }];
  }

  formFor(section: Section): FormScope {
    if (section === 'org') {
      return this.orgForm;
    }
    return section === 'defaults' ? this.defaultsForm : this.ceilingsForm;
  }

  sectionReady(section: Section): boolean {
    return section === 'org' ? this.org !== null : this.platform !== null;
  }

  sectionNote(section: Section): string {
    if (section === 'org') {
      return 'Loading organization settings…';
    }
    return this.platformError() ? 'Platform settings failed to load.' : 'Loading…';
  }

  retryPlatform(): void {
    this.loadPlatform();
  }

  canEdit(section: Section): boolean {
    if (section === 'org') {
      return this.org !== null && canManageSettings(this.jwtRole, this.selectedOrgRole);
    }
    return this.isPlatformAdmin && this.platform !== null;
  }

  canSave(section: Section): boolean {
    const form = this.formFor(section);
    return !form.saving && form.dirty.size > 0 && this.canEdit(section);
  }

  fieldId(section: Section, key: SettingKey): string {
    return `${section}-${key}`;
  }

  kindOf(key: SettingKey): FieldKind {
    return FIELD_KIND[key];
  }

  labelOf(key: SettingKey): string {
    return FIELD_LABELS[key];
  }

  hintOf(section: Section, key: SettingKey): string {
    if (section === 'ceilings') {
      return CEILING_HINT;
    }
    return FIELD_HINTS[key] ?? '';
  }

  optionsFor(key: SettingKey): readonly string[] {
    switch (key) {
      case 'enabledAgents':
        return AGENT_DOMAINS;
      case 'reviewTriggers':
        return TRIGGER_VOCAB;
      case 'minSeverityToPost':
        return SEVERITY_VOCAB;
      case 'postingMode':
        return POSTING_MODE_VOCAB;
      default:
        return [];
    }
  }

  optionLabel(key: SettingKey, option: string): string {
    switch (key) {
      case 'enabledAgents':
        return AGENT_LABELS[option] ?? option;
      case 'reviewTriggers':
        return TRIGGER_LABELS[option] ?? option;
      case 'minSeverityToPost':
        return SEVERITY_LABELS[option] ?? option;
      case 'postingMode':
        return MODE_LABELS[option] ?? option;
      default:
        return option;
    }
  }

  valueOf(section: Section, key: SettingKey): SettingValue {
    return this.formFor(section).values[key] ?? null;
  }

  isMultiSelected(section: Section, key: SettingKey, option: string): boolean {
    const value = this.formFor(section).values[key];
    return Array.isArray(value) && value.includes(option);
  }

  isOverridden(section: Section, key: SettingKey): boolean {
    if (section === 'org') {
      return this.org?.overridden[key] ?? false;
    }
    if (section === 'defaults') {
      return this.platform ? this.platform.defaults[key] !== null : false;
    }
    if (this.platform) {
      const asNumbers = (source: unknown): Partial<Record<SettingKey, number>> =>
        source as Partial<Record<SettingKey, number>>;
      const stored = asNumbers(this.platform.ceilings)[key];
      const hardCap = asNumbers(this.platform.hardCaps)[key];
      return stored !== undefined && stored !== hardCap;
    }
    return false;
  }

  /** The number displayed beside a numeric input (ceiling / hard cap). */
  ceilingLabel(section: Section, key: SettingKey): string {
    const asNumbers = (source: unknown): Partial<Record<SettingKey, number>> | undefined =>
      source as Partial<Record<SettingKey, number>> | undefined;
    const value =
      section === 'ceilings'
        ? asNumbers(this.platform?.hardCaps)?.[key]
        : asNumbers(section === 'org' ? this.org?.ceilings : this.platform?.ceilings)?.[key];
    return typeof value === 'number' ? String(value) : '—';
  }

  /** Effective (merged) value — shown as placeholder/inherited hint. */
  effectiveText(section: Section, key: SettingKey): string {
    const value = this.effectiveValue(section, key);
    if (value === null || value === undefined) {
      return 'system default';
    }
    if (typeof value === 'boolean') {
      return value ? 'on' : 'off';
    }
    if (Array.isArray(value)) {
      return value.length > 0 ? value.join(', ') : 'none';
    }
    return String(value);
  }

  inheritText(section: Section, key: SettingKey): string {
    if (section === 'ceilings') {
      return `hard cap ${this.effectiveText(section, key)}`;
    }
    return this.effectiveText(section, key);
  }

  placeholderFor(section: Section, key: SettingKey): string {
    return this.effectiveText(section, key);
  }

  fieldError(section: Section, key: SettingKey): string | null {
    return this.formFor(section).errors[key] ?? null;
  }

  // --- editing ---------------------------------------------------------------

  setField(section: Section, key: SettingKey, raw: unknown): void {
    const kind = FIELD_KIND[key];
    let value: SettingValue;
    if (kind === 'number') {
      value = raw === null || raw === undefined || raw === '' ? null : Number(raw);
    } else if (kind === 'boolean') {
      value = Boolean(raw);
    } else if (kind === 'multi') {
      value = Array.isArray(raw) ? [...raw] : String(raw);
    } else if (kind === 'text') {
      value = raw === null || raw === undefined || String(raw) === '' ? null : String(raw);
    } else {
      value = String(raw);
    }
    this.applyEdit(section, key, value);
  }

  toggleBoolean(section: Section, key: SettingKey, event: Event): void {
    const target = event.target as HTMLInputElement;
    this.applyEdit(section, key, target.checked);
  }

  toggleMulti(section: Section, key: SettingKey, option: string): void {
    const current = this.multiSelection(section, key);
    const next = current.includes(option)
      ? current.filter(item => item !== option)
      : [...current, option];
    this.applyEdit(section, key, next);
  }

  private applyEdit(section: Section, key: SettingKey, value: SettingValue): void {
    const form = this.formFor(section);
    if (!this.canEdit(section) || form.saving) {
      return;
    }
    form.values[key] = value;
    form.dirty.add(key);
    form.saved = false;
    form.error = null;
    delete form.errors[key];
  }

  private multiSelection(section: Section, key: SettingKey): string[] {
    const value = this.formFor(section).values[key];
    if (Array.isArray(value)) {
      return [...value];
    }
    const effective = this.effectiveValue(section, key);
    return Array.isArray(effective) ? [...effective] : [];
  }

  // --- saving ----------------------------------------------------------------

  save(section: Section): void {
    const form = this.formFor(section);
    if (!this.canSave(section)) {
      return;
    }
    if (section === 'org' && !this.selectedOrgId) {
      return;
    }

    form.saving = true;
    form.saved = false;
    form.error = null;
    form.errors = {};

    let request: Observable<OrgSettings | PlatformSettings>;
    if (section === 'org') {
      request = this.orgSettings.saveOrgSettings(this.selectedOrgId ?? '', this.buildPatch(form));
    } else if (section === 'defaults') {
      request = this.orgSettings.savePlatformSettings({ defaults: this.buildPatch(form) });
    } else {
      request = this.orgSettings.savePlatformSettings({
        ceilings: this.buildCeilingPatch(form)
      });
    }

    request.subscribe({
      next: response => {
        form.saving = false;
        form.saved = true;
        form.dirty.clear();
        this.applyResponse(section, response, new Set());
      },
      error: err => this.handleSaveError(section, err)
    });
  }

  resetField(section: Section, key: SettingKey): void {
    const form = this.formFor(section);
    if (!this.canEdit(section) || form.saving) {
      return;
    }
    if (section === 'org' && !this.selectedOrgId) {
      return;
    }

    form.saving = true;
    form.saved = false;
    form.error = null;
    delete form.errors[key];

    // Explicit null = "reset to default" (backend contract).
    let request: Observable<OrgSettings | PlatformSettings>;
    if (section === 'org') {
      request = this.orgSettings.saveOrgSettings(
        this.selectedOrgId ?? '',
        this.singleNullPatch(key)
      );
    } else if (section === 'defaults') {
      request = this.orgSettings.savePlatformSettings({
        defaults: this.singleNullPatch(key)
      });
    } else {
      request = this.orgSettings.savePlatformSettings({
        ceilings: this.singleCeilingNullPatch(key)
      });
    }

    request.subscribe({
      next: response => {
        form.saving = false;
        form.saved = true;
        form.dirty.delete(key);
        // Re-init the reset field from the response; keep other in-flight edits.
        this.applyResponse(section, response, new Set(form.dirty));
      },
      error: err => this.handleSaveError(section, err)
    });
  }

  /** Only the dirty keys — absent fields are kept by the backend. */
  private buildPatch(form: FormScope): Partial<SettingsOverrides> {
    const patch: Partial<SettingsOverrides> = {};
    for (const key of form.dirty) {
      (patch as Record<string, SettingValue>)[key] = this.payloadValue(key, form.values[key]);
    }
    return patch;
  }

  private buildCeilingPatch(form: FormScope): Partial<CeilingPatch> {
    const patch: Partial<CeilingPatch> = {};
    for (const key of NUMERIC_KEYS) {
      if (form.dirty.has(key)) {
        (patch as Record<string, SettingValue>)[key] = form.values[key] ?? null;
      }
    }
    return patch;
  }

  private singleNullPatch(key: SettingKey): Partial<SettingsOverrides> {
    const patch: Partial<SettingsOverrides> = {};
    (patch as Record<string, SettingValue>)[key] = null;
    return patch;
  }

  private singleCeilingNullPatch(key: SettingKey): Partial<CeilingPatch> {
    const patch: Partial<CeilingPatch> = {};
    (patch as Record<string, SettingValue>)[key] = null;
    return patch;
  }

  /** Trim text on the way out (typing must not fight the input). */
  private payloadValue(key: SettingKey, value: SettingValue | undefined): SettingValue {
    if (value === undefined) {
      return null;
    }
    if (FIELD_KIND[key] === 'text') {
      const trimmed = String(value).trim();
      return trimmed === '' ? null : trimmed;
    }
    return value;
  }

  private handleSaveError(section: Section, err: unknown): void {
    const form = this.formFor(section);
    form.saving = false;
    form.saved = false;

    const parsed = parseSettingsError(err);
    const validKeys: readonly string[] = section === 'ceilings' ? NUMERIC_KEYS : SETTING_KEYS;
    const unmapped: string[] = [];

    for (const [rawKey, message] of Object.entries(parsed.fields)) {
      let key = rawKey;
      if (section === 'ceilings' && key.startsWith(CEILING_ERROR_PREFIX)) {
        key = key.slice(CEILING_ERROR_PREFIX.length);
      }
      const normalized = key.charAt(0).toLowerCase() + key.slice(1);
      if (validKeys.includes(normalized)) {
        form.errors[normalized] = message;
      } else {
        unmapped.push(message);
      }
    }

    form.error =
      [parsed.form, ...unmapped].filter(part => part !== null && part !== '').join(' ') || null;
  }

  // --- response application --------------------------------------------------

  private applyResponse(
    section: Section,
    response: OrgSettings | PlatformSettings,
    keep: Set<SettingKey>
  ): void {
    if (section === 'org') {
      this.applyOrg(response as OrgSettings, keep);
      return;
    }
    if (section === 'defaults') {
      this.applyPlatform(response as PlatformSettings, keep, this.ceilingsForm.dirty);
      return;
    }
    this.applyPlatform(response as PlatformSettings, this.defaultsForm.dirty, keep);
  }

  private applyOrg(response: OrgSettings, keep: Set<SettingKey>): void {
    this.org = response;
    for (const key of SETTING_KEYS) {
      if (!keep.has(key)) {
        this.orgForm.values[key] = this.initialValue('org', key);
      }
    }
  }

  private applyPlatform(
    response: PlatformSettings,
    keepDefaults: Set<SettingKey>,
    keepCeilings: Set<SettingKey>
  ): void {
    this.platform = response;
    for (const key of SETTING_KEYS) {
      if (!keepDefaults.has(key)) {
        this.defaultsForm.values[key] = this.initialValue('defaults', key);
      }
    }
    for (const key of NUMERIC_KEYS) {
      if (!keepCeilings.has(key)) {
        this.ceilingsForm.values[key] = this.initialValue('ceilings', key);
      }
    }
  }

  private initSection(section: Section): void {
    const form = this.formFor(section);
    form.values = {};
    form.dirty.clear();
    form.errors = {};
    form.error = null;
    form.saved = false;
    for (const key of this.fieldsFor(section)) {
      form.values[key] = this.initialValue(section, key);
    }
  }

  /**
   * Initial display value: numbers/text show the *override* only (empty
   * input = inherit); toggles/selects show override ?? effective because
   * an inherited checkbox must display its active value. Dirty tracking
   * keeps display-only values out of the PUT.
   */
  private initialValue(section: Section, key: SettingKey): SettingValue {
    const kind = FIELD_KIND[key];
    if (section === 'ceilings') {
      const ceilings = this.platform?.ceilings as Partial<Record<SettingKey, number>> | undefined;
      return ceilings?.[key] ?? null;
    }
    if (section === 'org') {
      if (!this.org) {
        return null;
      }
      const { overrides, effective } = this.org;
      if (kind === 'number' || kind === 'text') {
        return overrides[key];
      }
      return overrides[key] ?? (effective[key] as SettingValue);
    }
    if (!this.platform) {
      return null;
    }
    const { defaults, effectiveDefaults } = this.platform;
    if (kind === 'number' || kind === 'text') {
      return defaults[key];
    }
    return defaults[key] ?? (effectiveDefaults[key] as SettingValue);
  }

  /** Effective (merged) value — always the raw backend value for the section. */
  private effectiveValue(section: Section, key: SettingKey): SettingValue {
    if (section === 'org') {
      return (this.org?.effective[key] as SettingValue) ?? null;
    }
    if (section === 'ceilings') {
      const hardCaps = this.platform?.hardCaps as Partial<Record<SettingKey, number>> | undefined;
      return hardCaps?.[key] ?? null;
    }
    return (this.platform?.effectiveDefaults[key] as SettingValue) ?? null;
  }
}
