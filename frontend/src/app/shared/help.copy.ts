import { SeverityLevel } from './components/severity-badge/severity-badge.component';

/**
 * Shared explanatory copy for the /help page and the contextual "?" popovers
 * (plan §4.5). Single source of truth: the page and every popover render these
 * exact strings, so the wording can never drift between the two.
 *
 * Every claim mirrors shipped backend behaviour documented in AGENTS.md and
 * docs/ROLES_SETTINGS_RELEASE.md — no invented capabilities or numbers.
 */

/** One row of the shipped five-step severity scale (severity-badge levels). */
export interface SeverityHelpRow {
  readonly id: SeverityLevel;
  readonly meaning: string;
  readonly action: string;
}

export const SEVERITY_COPY: readonly SeverityHelpRow[] = [
  {
    id: 'critical',
    meaning: 'Security holes, data loss, or outright breakage.',
    action: 'Fix before merging.'
  },
  {
    id: 'high',
    meaning: 'Serious defects: likely bugs and major performance or reliability problems.',
    action: 'Fix in this pull request.'
  },
  {
    id: 'medium',
    meaning:
      'Real issues worth a change: code smells and moderate correctness or performance risks.',
    action: 'Address before release.'
  },
  {
    id: 'low',
    meaning: 'Minor improvements: naming, style, and small readability nits.',
    action: 'Optional polish; batch with other edits.'
  },
  {
    id: 'info',
    meaning: 'Observations with no implied defect.',
    action: 'Context only — no action required.'
  }
];

/** How the review-comment vocabulary colour-matches the five-step scale. */
export const SEVERITY_SCALE_NOTE =
  'Review findings are labelled error, warning, suggestion or info and colour-match this scale ' +
  '(error = critical, warning = medium, suggestion = low). Static-analysis findings use the five ' +
  'level names directly.';

/** Compact multi-line body for the dashboard's "?" popover. */
export const SEVERITY_HELP_TEXT =
  SEVERITY_COPY.map(row => `${row.id} — ${row.action}`).join('\n') + '\n\n' + SEVERITY_SCALE_NOTE;

/** Role rows — scope mirrors docs/ROLES_SETTINGS_RELEASE.md §1.1. */
export interface RoleHelpRow {
  readonly id: string;
  readonly label: string;
  readonly can: string;
  readonly scope: string;
}

export const ROLE_COPY: readonly RoleHelpRow[] = [
  {
    id: 'platform-admin',
    label: 'PLATFORM_ADMIN',
    can: 'Change platform defaults and numeric ceilings; manage users and organizations.',
    scope: 'Global only — never stored as an organization membership.'
  },
  {
    id: 'org-admin',
    label: 'ORG_ADMIN',
    can: 'Change organization settings and send invitations, plus everything a reviewer can.',
    scope: 'Keycloak admin group or an organization membership.'
  },
  {
    id: 'reviewer',
    label: 'REVIEWER',
    can:
      'Validate findings — confirmed, false positive, or needs investigation, with an optional ' +
      'severity override — plus everything a developer can.',
    scope: 'Keycloak group or an organization membership.'
  },
  {
    id: 'developer',
    label: 'DEVELOPER',
    can:
      'Trigger reviews, post them to GitHub, dismiss and restore findings, and edit the review ' +
      'summary.',
    scope: 'Keycloak group or an organization membership.'
  },
  {
    id: 'none',
    label: 'NONE',
    can: 'Read-only: every write is rejected with 403.',
    scope: 'Sentinel for a token without a usable role.'
  }
];

export const ROLE_NOTE =
  'Your effective role in an organization is the stronger of your token role and your ' +
  'membership — accepting an invitation never downgrades what you already have.';

/** One stage of the review pipeline; `diagram` feeds the SVG boxes. */
export interface PipelineHelpStep {
  readonly id: string;
  readonly title: string;
  readonly body: string;
  /** Two short lines rendered inside this step's box in the pipeline diagram. */
  readonly diagram: readonly [string, string];
}

export const PIPELINE_STEPS: readonly PipelineHelpStep[] = [
  {
    id: 'event',
    title: 'Pull request event',
    diagram: ['Pull request', 'event'],
    body:
      'GitHub sends a webhook — pull request opened, reopened, or synchronized — and if the ' +
      'repository is enabled, the review is queued. A failed run can be retried from the pull ' +
      'request.'
  },
  {
    id: 'analysis',
    title: 'Static analysis',
    diagram: ['Static', 'analysis'],
    body:
      'SonarQube and Semgrep scan the changes in parallel. If a tool fails, the review still ' +
      'runs and records which analysis was unavailable.'
  },
  {
    id: 'agents',
    title: 'Five specialist agents',
    diagram: ['Five', 'specialists'],
    body:
      'Security, complexity, performance, style, and test-coverage agents each refine the ' +
      'findings for their own domain, in parallel.'
  },
  {
    id: 'summary',
    title: 'One summary',
    diagram: ['One', 'summary'],
    body:
      'The orchestrator merges everything — deduplicating overlapping findings and keeping ' +
      'the strongest severity — into a single summary for the pull request.'
  },
  {
    id: 'posting',
    title: 'Post or stage',
    diagram: ['Post or', 'stage'],
    body:
      'Automatic mode posts the summary to GitHub immediately; staged mode parks it in the ' +
      'app until someone approves it.'
  }
];

/** The two per-organization `posting_mode` values (settings merge, v0.3.0). */
export interface PostingHelpRow {
  readonly id: string;
  readonly label: string;
  readonly body: string;
}

export const POSTING_COPY: readonly PostingHelpRow[] = [
  {
    id: 'auto',
    label: 'Automatic',
    body:
      'When a review finishes, its summary is posted to the pull request immediately — one ' +
      'summary comment, no inline threads.'
  },
  {
    id: 'staged',
    label: 'Staged (awaiting approval)',
    body:
      'The finished review waits in the app as ready to post. Read it, edit the summary if ' +
      'you like, then press Post to GitHub. A review that has already posted is never posted ' +
      'twice.'
  }
];

export const INVITE_STEPS: readonly string[] = [
  'Open Settings → Organization → Members & invitations (organization admins only).',
  'Enter the teammate’s email address and choose Developer or Reviewer — invitations cannot ' +
    'grant admin roles.',
  'Send the invitation. The invitee gets a link; where it is delivered depends on the mail ' +
    'backend (local development prints it to the backend log).',
  'The link previews the invitation — accepting adds the person with the invited role, and ' +
    'existing higher roles are never downgraded.'
];

/** One glossary entry — shared by /help and the contextual popovers. */
export interface GlossaryHelpEntry {
  readonly id: string;
  readonly term: string;
  readonly definition: string;
}

const DISMISSED_VS_VALIDATED =
  'Dismissing hides a finding you judge not worth acting on — it can be restored at any time. ' +
  'Validating records a reviewer verdict (confirmed, false positive, or needs investigation) ' +
  'with an optional severity override, shown on the finding with the reviewer’s login, time, ' +
  'and note. The Status filter on the Findings tab switches between open, dismissed, and ' +
  'validated.';

export const GLOSSARY_COPY: readonly GlossaryHelpEntry[] = [
  {
    id: 'cwe',
    term: 'CWE (Common Weakness Enumeration)',
    definition:
      'A catalogue of software weakness types — CWE-89 is SQL injection, for example. ' +
      'Scan findings that carry CWE ids link straight to the catalogue entry.'
  },
  {
    id: 'owasp',
    term: 'OWASP',
    definition:
      'The Open Worldwide Application Security Project. Its Top Ten is the standard ' +
      'list of critical web-application risks; security findings may carry OWASP category tags.'
  },
  {
    id: 'false-positive',
    term: 'False positive',
    definition:
      'A finding that reports a problem the code does not actually have — the ' +
      'reviewer verdict “false positive” records that judgment on the finding.'
  },
  {
    id: 'dismissed-validated',
    term: 'Dismissed vs validated',
    definition: DISMISSED_VS_VALIDATED
  }
];

/** Popover body for the review panel's Findings status help. */
export const DISMISSED_VS_VALIDATED_TEXT = DISMISSED_VS_VALIDATED;
