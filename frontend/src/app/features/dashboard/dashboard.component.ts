import { Component, OnInit, WritableSignal, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { AuthContextService } from '../../core/services/auth-context.service';
import { GithubAppService } from '../../core/services/github-app.service';
import { LlmSettingsService } from '../../core/services/llm-settings.service';
import { OrgSettingsService } from '../../core/services/org-settings.service';
import { RepositoryService } from '../../core/services/repository.service';
import { ReviewService } from '../../core/services/review.service';
import { Repository } from '../../core/models/repository.model';
import { ReviewSummary } from '../../core/models/review.model';
import { User } from '../../core/models/user.model';
import {
  SeverityBadgeComponent,
  SeverityLevel
} from '../../shared/components/severity-badge/severity-badge.component';
import { EmptyStateComponent } from '../../shared/components/empty-state/empty-state.component';
import { ErrorStateComponent } from '../../shared/components/error-state/error-state.component';
import { HelpPopoverComponent } from '../../shared/components/help-popover/help-popover.component';
import { SpinnerComponent } from '../../shared/components/spinner/spinner.component';
import { SEVERITY_HELP_TEXT } from '../../shared/help.copy';
import { TimeAgoPipe } from '../../shared/pipes/time-ago.pipe';

type SectionState = 'loading' | 'error' | 'ready';

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/**
 * Review-level `overall_severity` is written by the orchestrator in the
 * comment vocabulary (`info|warning|error` — see backend
 * `orchestrator_agent.py`), which the redesign maps onto the shipped
 * 5-step severity scale (plan §8/Q1): error→critical, warning→medium,
 * suggestion→low, info→info. Scan-style values are accepted defensively
 * so stored data from either family charts correctly.
 */
const SEVERITY_MAP: Record<string, SeverityLevel> = {
  error: 'critical',
  warning: 'medium',
  suggestion: 'low',
  info: 'info',
  critical: 'critical',
  high: 'high',
  medium: 'medium',
  low: 'low'
};

/** Chart order — the shipped severity scale, strongest first. */
const SEVERITY_ORDER: SeverityLevel[] = ['critical', 'high', 'medium', 'low', 'info'];

interface ChecklistItem {
  key: 'github' | 'repos' | 'llm' | 'posting';
  title: string;
  hint: string;
  link: string;
  action: string;
  done: boolean;
}

interface SeverityBar {
  level: SeverityLevel;
  count: number;
  percent: number;
}

/**
 * Dashboard (plan §4.1) — every number comes from a real endpoint:
 * - repo counts from `GET /repositories` (total + enabled);
 * - review totals from `GET /reviews` and the per-status counts from the
 *   same route's `status_filter` (the filter also drives the envelope
 *   `total`, so no client-side scanning);
 * - the setup checklist from `GET /github/status`, `GET /settings/llm`
 *   and (admins) `GET /orgs/{id}/settings`;
 * - the severity distribution from the most recent ≤100 rows (proposal
 *   #16 — no server aggregation exists; the window size is shown in the
 *   UI, never implied to be "all reviews").
 *
 * Per-org breakdowns are impossible client-side (no org attribution on any
 * response) — see docs/BACKEND_GAPS_FOR_UI.md §3; the numbers here are
 * global to everything the caller can see. A failed count shows '—', never
 * a fake 0; each section owns its loading / empty / error+retry states.
 * Checklist rows whose source failed to load are omitted (unknown is not
 * the same as incomplete) so a transient error never nags the user.
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    SpinnerComponent,
    EmptyStateComponent,
    ErrorStateComponent,
    HelpPopoverComponent,
    SeverityBadgeComponent,
    TimeAgoPipe
  ],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss'
})
export class DashboardComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly ctx = inject(AuthContextService);
  private readonly github = inject(GithubAppService);
  private readonly llm = inject(LlmSettingsService);
  private readonly orgApi = inject(OrgSettingsService);
  private readonly repoApi = inject(RepositoryService);
  private readonly reviewApi = inject(ReviewService);

  /** Body of the severity "?" popover — shared copy, same strings as /help. */
  readonly severityHelpText = SEVERITY_HELP_TEXT;

  user = signal<User | null>(null);
  repositories = signal<Repository[]>([]);
  reposState = signal<SectionState>('loading');
  reposError = signal<string | null>(null);
  stats = signal({ totalRepos: 0, enabledRepos: 0 });

  /** null = not loaded yet or failed → the tile renders '—', never 0. */
  totalReviews = signal<number | null>(null);
  pendingReviews = signal<number | null>(null);
  completedReviews = signal<number | null>(null);
  failedReviews = signal<number | null>(null);
  readyToPost = signal<number | null>(null);
  recentReviews = signal<ReviewSummary[]>([]);
  reviewsState = signal<SectionState>('loading');
  reviewsError = signal<string | null>(null);

  /** Severity window (most recent ≤100 rows) — its own state + retry. */
  severityRows = signal<ReviewSummary[]>([]);
  severityState = signal<SectionState>('loading');
  severityError = signal<string | null>(null);

  /** Setup checklist — null = unknown (not loaded / failed) → row omitted. */
  githubInstalled = signal<boolean | null>(null);
  llmHasKey = signal<boolean | null>(null);
  llmUsingDefault = signal<boolean | null>(null);
  postingMode = signal<string | null>(null);

  ngOnInit(): void {
    this.user.set(this.auth.currentUser());
    this.loadRepositories();
    this.loadReviews();
    this.loadSeverity();
    this.loadSetupState();
    // Org posting mode (admins only) resolves after the org list.
    void this.ctx
      .ensureOrgs()
      .then(() => this.loadPostingMode())
      .catch(() => undefined);
  }

  loadRepositories(): void {
    this.reposState.set('loading');
    this.reposError.set(null);
    this.repoApi.getRepositories().subscribe({
      next: (repos: Repository[]) => {
        this.repositories.set(repos);
        this.stats.set({
          totalRepos: repos.length,
          enabledRepos: repos.filter((r: Repository) => r.enabled).length
        });
        this.reposState.set('ready');
      },
      error: err => {
        this.reposError.set(errorMessage(err, 'Could not load repositories.'));
        this.reposState.set('error');
      }
    });
  }

  loadReviews(): void {
    this.reviewsState.set('loading');
    this.reviewsError.set(null);
    // Newest rows + the global total in one call (per_page=5).
    this.reviewApi.listReviews(1, 5).subscribe({
      next: list => {
        this.totalReviews.set(list.total);
        this.recentReviews.set(list.items);
        this.reviewsState.set('ready');
      },
      error: err => {
        this.reviewsError.set(errorMessage(err, 'Could not load reviews.'));
        this.reviewsState.set('error');
      }
    });
    // Per-status counts — envelope totals via status_filter. Each call is
    // independent: a failure blanks only its own tile ('—', not 0).
    this.countReviews('pending', this.pendingReviews);
    this.countReviews('completed', this.completedReviews);
    this.countReviews('failed', this.failedReviews);
    this.countReviews('ready_to_post', this.readyToPost);
  }

  /** Severity distribution window — isolated state so its retry is local. */
  loadSeverity(): void {
    this.severityState.set('loading');
    this.severityError.set(null);
    this.reviewApi.listReviews(1, 100).subscribe({
      next: list => {
        this.severityRows.set(list.items);
        this.severityState.set('ready');
      },
      error: err => {
        this.severityError.set(errorMessage(err, 'Could not load the severity distribution.'));
        this.severityState.set('error');
      }
    });
  }

  /** `overall_severity` (comment vocab) → shipped severity scale, or null. */
  sevLevel(value: string | null): SeverityLevel | null {
    return value ? SEVERITY_MAP[value] ?? null : null;
  }

  readonly checklist = computed<ChecklistItem[]>(() => {
    const items: ChecklistItem[] = [];

    const installed = this.githubInstalled();
    if (installed !== null) {
      items.push({
        key: 'github',
        title: installed ? 'GitHub App installed' : 'Install the GitHub App',
        hint: 'Pull request reviews are triggered by the GitHub App.',
        link: '/repositories',
        action: installed ? 'Manage' : 'Set up',
        done: installed
      });
    }

    if (this.reposState() === 'ready') {
      const enabled = this.stats().enabledRepos;
      items.push({
        key: 'repos',
        title:
          enabled > 0
            ? `${enabled} ${enabled === 1 ? 'repository' : 'repositories'} enabled`
            : 'Connect a repository',
        hint: 'Reviews run on enabled repositories only.',
        link: '/repositories',
        action: enabled > 0 ? 'Manage' : 'Connect',
        done: enabled > 0
      });
    }

    const hasKey = this.llmHasKey();
    if (hasKey !== null) {
      items.push({
        key: 'llm',
        title: hasKey ? 'Personal AI key saved' : 'Add your AI model key',
        hint: hasKey
          ? 'Your provider key is stored encrypted at rest.'
          : this.llmUsingDefault()
            ? 'No personal key yet — the platform default model is used.'
            : 'Add an API key for your preferred provider.',
        link: '/settings',
        action: 'Open',
        done: hasKey
      });
    }

    const mode = this.postingMode();
    if (mode !== null && this.ctx.can('org:settings')) {
      items.push({
        key: 'posting',
        title: `Posting mode: ${mode}`,
        hint:
          mode === 'staged'
            ? 'Staged reviews wait for your approval before they post.'
            : mode === 'auto'
              ? 'Completed reviews post to GitHub automatically.'
              : 'Managed in Organization settings.',
        link: '/settings/org',
        action: 'Change',
        // Informational row — the mode is always configured to something.
        done: true
      });
    }

    return items;
  });

  /** The checklist hides itself once every known row is complete. */
  readonly checklistVisible = computed(() => this.checklist().some(item => !item.done));

  readonly severityDistribution = computed<SeverityBar[]>(() => {
    const counts: Record<SeverityLevel, number> = {
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      info: 0
    };
    for (const row of this.severityRows()) {
      const level = this.sevLevel(row.overall_severity);
      if (level) {
        counts[level] += 1;
      }
    }
    const known = counts.critical + counts.high + counts.medium + counts.low + counts.info;
    return SEVERITY_ORDER.map(level => ({
      level,
      count: counts[level],
      percent: known > 0 ? Math.round((counts[level] / known) * 100) : 0
    }));
  });

  /** Rows in the window that carry a recognised severity. */
  readonly severityKnown = computed(() =>
    this.severityDistribution().reduce((sum, row) => sum + row.count, 0)
  );

  private countReviews(status: string, target: WritableSignal<number | null>): void {
    this.reviewApi.listReviews(1, 1, status).subscribe({
      next: list => target.set(list.total),
      error: () => target.set(null)
    });
  }

  private loadSetupState(): void {
    this.github.getInstallStatus().subscribe({
      next: status => this.githubInstalled.set(status.installed === true),
      error: () => this.githubInstalled.set(null)
    });
    this.llm.getLLMSettings().subscribe({
      next: settings => {
        this.llmHasKey.set(settings.hasApiKey);
        this.llmUsingDefault.set(settings.isUsingDefault);
      },
      error: () => {
        this.llmHasKey.set(null);
        this.llmUsingDefault.set(null);
      }
    });
  }

  private loadPostingMode(): void {
    if (!this.ctx.can('org:settings')) {
      return;
    }
    const org = this.ctx.activeOrg();
    if (!org) {
      return;
    }
    this.orgApi.getOrgSettings(org.id).subscribe({
      next: settings => this.postingMode.set(settings.effective.postingMode),
      error: () => this.postingMode.set(null)
    });
  }
}
