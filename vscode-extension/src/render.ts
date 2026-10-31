import { compareFindings } from './severity';
import type {
  ExcludedFile,
  Finding,
  GitCollection,
  LocalReviewResult,
  UnifiedSeverity
} from './types';

export interface DiagnosticViewState {
  shown: Set<string>;
  reasons: Map<string, string>;
}

export type ReportViewState =
  | { kind: 'loading'; message: string }
  | { kind: 'cancelled' }
  | { kind: 'error'; message: string }
  | {
      kind: 'result';
      result: LocalReviewResult;
      collection: GitCollection | null;
      diagnostics: DiagnosticViewState | null;
    };

const REASON_LABELS: Record<string, string> = {
  file_not_in_snapshot: 'file is not part of this snapshot',
  file_deleted: 'file was deleted',
  unsafe_path: 'path is outside the repository',
  stale_snapshot: 'file changed after the snapshot',
  file_unreadable: 'file could not be read',
  line_missing: 'finding has no line number',
  line_outside_diff: 'line is outside the reviewed diff'
};


export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function commandUri(command: string, ...args: unknown[]): string {
  return `command:${command}?${encodeURIComponent(JSON.stringify(args))}`;
}

function inlineMarkdown(escaped: string): string {
  return escaped.replace(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g, (match) => {
    if (match.startsWith('`')) {
      return `<code>${match.slice(1, -1)}</code>`;
    }
    if (match.startsWith('**')) {
      return `<strong>${match.slice(2, -2)}</strong>`;
    }
    return `<em>${match.slice(1, -1)}</em>`;
  });
}

/**
 * Renders the small Markdown subset the review summary uses (headings, lists,
 * bold, italics, inline code). Every input is HTML-escaped before formatting,
 * so untrusted text can never inject markup.
 */
export function renderMarkdown(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const html: string[] = [];
  let paragraph: string[] = [];
  let list: 'ul' | 'ol' | null = null;

  const closeList = (): void => {
    if (list) {
      html.push(`</${list}>`);
      list = null;
    }
  };
  const flushParagraph = (): void => {
    if (paragraph.length > 0) {
      html.push(`<p>${inlineMarkdown(escapeHtml(paragraph.join(' ')))}</p>`);
      paragraph = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushParagraph();
      closeList();
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      closeList();
      const level = Math.min(heading[1]!.length + 2, 5);
      html.push(`<h${level}>${inlineMarkdown(escapeHtml(heading[2]!))}</h${level}>`);
      continue;
    }

    const bullet = /^[-*+]\s+(.*)$/.exec(line);
    if (bullet) {
      flushParagraph();
      if (list !== 'ul') {
        closeList();
        html.push('<ul>');
        list = 'ul';
      }
      html.push(`<li>${inlineMarkdown(escapeHtml(bullet[1]!))}</li>`);
      continue;
    }

    const numbered = /^\d+[.)]\s+(.*)$/.exec(line);
    if (numbered) {
      flushParagraph();
      if (list !== 'ol') {
        closeList();
        html.push('<ol>');
        list = 'ol';
      }
      html.push(`<li>${inlineMarkdown(escapeHtml(numbered[1]!))}</li>`);
      continue;
    }

    closeList();
    paragraph.push(line);
  }

  flushParagraph();
  closeList();
  return html.join('');
}

export function groupFindings(findings: Finding[]): Array<[string, Finding[]]> {
  const groups = new Map<string, Finding[]>();
  for (const finding of [...findings].sort(compareFindings)) {
    const key = finding.filePath || 'General';
    groups.set(key, [...(groups.get(key) ?? []), finding]);
  }
  return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right));
}

function severityClass(severity: UnifiedSeverity): string {
  switch (severity) {
    case 'critical':
    case 'high':
      return 'sev-high';
    case 'medium':
      return 'sev-medium';
    case 'low':
      return 'sev-low';
    default:
      return 'sev-info';
  }
}

function renderFinding(finding: Finding, diagnostics: DiagnosticViewState | null): string {
  const openHref = commandUri('codesage.openFinding', finding.id);
  const location = finding.lineStart === null ? finding.filePath : `${finding.filePath}:${finding.lineStart}`;
  const note = diagnostics && !diagnostics.shown.has(finding.id)
    ? diagnostics.reasons.get(finding.id)
    : undefined;
  const parts: string[] = [
    `<li class="finding">`,
    `<a class="finding-title" href="${escapeHtml(openHref)}" title="Open finding">`,
    `<span class="sev ${severityClass(finding.severity)}">${escapeHtml(finding.severity)}</span>`,
    `<span class="loc">${escapeHtml(location)}</span>`,
    `<span class="msg">${escapeHtml(finding.message)}</span>`,
    `</a>`
  ];
  if (finding.body && finding.body !== finding.message) {
    parts.push(`<p class="body">${escapeHtml(finding.body)}</p>`);
  }
  if (finding.suggestion) {
    const copyHref = commandUri('codesage.copySuggestion', finding.id);
    parts.push(
      `<p class="suggestion"><span>Suggestion:</span> ${escapeHtml(finding.suggestion)} ` +
        `<a href="${escapeHtml(copyHref)}" title="Copy suggestion">Copy</a></p>`
    );
  }
  const source = [finding.tool, finding.ruleId].filter(Boolean).join(' / ');
  if (source) {
    const also = finding.alsoDetectedBy.length
      ? ` · also detected by ${finding.alsoDetectedBy.join(', ')}`
      : '';
    parts.push(`<p class="source">Source: ${escapeHtml(source)}${escapeHtml(also)}</p>`);
  }
  if (note) {
    parts.push(`<p class="note">Not shown inline: ${escapeHtml(REASON_LABELS[note] ?? note)}</p>`);
  }
  if (finding.snippet) {
    parts.push(`<pre class="snippet">${escapeHtml(finding.snippet)}</pre>`);
  }
  parts.push('</li>');
  return parts.join('');
}

function renderIssues(
  findings: Finding[],
  diagnostics: DiagnosticViewState | null,
  emptyText: string
): string {
  if (findings.length === 0) {
    return `<div class="issues"><ul><li>${escapeHtml(emptyText)}</li></ul></div>`;
  }
  const groups = groupFindings(findings)
    .map(([filePath, group]) => {
      const items = group.map((finding) => renderFinding(finding, diagnostics)).join('');
      return (
        `<div class="file-group">` +
        `<div class="file-head"><span class="file-path">${escapeHtml(filePath)}</span>` +
        `<span class="file-count">${group.length}</span></div>` +
        `<ul>${items}</ul></div>`
      );
    })
    .join('');
  return `<div class="issues">${groups}</div>`;
}

function renderExcluded(excluded: ExcludedFile[]): string {
  if (excluded.length === 0) {
    return '';
  }
  const items = excluded
    .map((file) => `<li><code>${escapeHtml(file.path)}</code> — ${escapeHtml(file.reason)}</li>`)
    .join('');
  return `<section><h2>Excluded files</h2><div class="excluded"><ul>${items}</ul></div></section>`;
}

interface PanelView {
  status: string;
  statusClass: string;
  analysis: string;
  issues: string;
  excluded: string;
}

function buildView(state: ReportViewState): PanelView {
  switch (state.kind) {
    case 'loading':
      return {
        status: 'Reviewing…',
        statusClass: '',
        analysis: renderMarkdown(state.message),
        issues: renderIssues([], null, 'Waiting for the review to finish…'),
        excluded: ''
      };
    case 'cancelled':
      return {
        status: 'Review cancelled',
        statusClass: 'status-muted',
        analysis: renderMarkdown('The review was cancelled before it completed.'),
        issues: renderIssues([], null, 'No specific issues returned.'),
        excluded: ''
      };
    case 'error':
      return {
        status: 'Review failed',
        statusClass: 'status-error',
        analysis: renderMarkdown(state.message),
        issues: renderIssues([], null, 'No specific issues returned.'),
        excluded: ''
      };
    case 'result': {
      const { result, collection, diagnostics } = state;
      const count = result.findings.length;
      const files = result.statistics.filesReviewed;
      return {
        status: `${count} finding${count === 1 ? '' : 's'} · ${files} file${files === 1 ? '' : 's'}`,
        statusClass: '',
        analysis: renderMarkdown(result.summary || 'No summary returned.'),
        issues: renderIssues(result.findings, diagnostics, 'No specific issues returned.'),
        excluded: renderExcluded(collection?.excluded ?? [])
      };
    }
  }
}

export function renderReportHtml(state: ReportViewState): string {
  const view = buildView(state);
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
  <style>
    :root {
      --bg: #171717;
      --panel: #202020;
      --line: #3a332b;
      --text: #f3eee5;
      --muted: #b8ada0;
      --accent: #e0a84b;
      --accent-2: #6bb6a8;
      --danger: #ee6f68;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      color: var(--text);
      background:
        linear-gradient(135deg, rgba(224, 168, 75, 0.08), transparent 32%),
        linear-gradient(315deg, rgba(107, 182, 168, 0.07), transparent 28%),
        var(--bg);
      font-family: "Aptos", "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.55;
    }

    main {
      max-width: 860px;
      margin: 0 auto;
      padding: 22px;
    }

    header {
      border-bottom: 1px solid var(--line);
      margin-bottom: 18px;
      padding-bottom: 16px;
    }

    h1 {
      margin: 0;
      font-family: "Georgia", serif;
      font-size: 28px;
      font-weight: 600;
      letter-spacing: 0;
    }

    .subtitle {
      color: var(--muted);
      margin: 6px 0 0;
    }

    section {
      margin: 18px 0;
    }

    h2 {
      color: var(--accent);
      font-size: 13px;
      letter-spacing: 0;
      margin: 0 0 8px;
      text-transform: uppercase;
    }

    .summary,
    .issues,
    .excluded {
      background: rgba(32, 32, 32, 0.86);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
    }

    .summary .md p {
      margin: 8px 0;
    }

    .summary .md > :first-child {
      margin-top: 0;
    }

    .summary .md > :last-child {
      margin-bottom: 0;
    }

    .summary .md h3,
    .summary .md h4,
    .summary .md h5 {
      color: var(--accent);
      font-size: 12px;
      letter-spacing: 0.06em;
      margin: 16px 0 6px;
      text-transform: uppercase;
    }

    .summary .md ul,
    .summary .md ol {
      padding-left: 20px;
    }

    .summary .md li {
      margin: 4px 0;
    }

    .summary .md strong {
      color: var(--text);
      font-weight: 600;
    }

    .summary .md em {
      color: var(--muted);
    }

    .summary .md code {
      background: rgba(0, 0, 0, 0.28);
      border-radius: 4px;
      padding: 1px 4px;
    }

    ul {
      margin: 0;
      padding-left: 20px;
    }

    li {
      margin: 7px 0;
    }

    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 13px;
    }

    code {
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 13px;
    }

    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--accent-2);
      font-size: 12px;
      margin-top: 12px;
    }

    .status::before {
      background: var(--accent-2);
      border-radius: 50%;
      content: "";
      height: 8px;
      width: 8px;
    }

    .status-muted {
      color: var(--muted);
    }

    .status-muted::before {
      background: var(--muted);
    }

    .status-error {
      color: var(--danger);
    }

    .status-error::before {
      background: var(--danger);
    }

    .file-group {
      border-top: 1px solid var(--line);
      margin-top: 14px;
      padding-top: 14px;
    }

    .file-group:first-child {
      border-top: 0;
      margin-top: 0;
      padding-top: 0;
    }

    .file-head {
      align-items: baseline;
      display: flex;
      gap: 12px;
      justify-content: space-between;
      margin-bottom: 6px;
    }

    .file-path {
      color: var(--accent-2);
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 13px;
      word-break: break-word;
    }

    .file-count {
      color: var(--muted);
      font-size: 12px;
    }

    .finding {
      margin: 10px 0;
    }

    .finding-title {
      color: inherit;
      display: block;
      text-decoration: none;
    }

    .finding-title:hover .msg,
    .finding-title:focus .msg {
      text-decoration: underline;
    }

    .sev {
      font-size: 11px;
      letter-spacing: 0.08em;
      margin-right: 8px;
      text-transform: uppercase;
    }

    .sev-high {
      color: var(--danger);
    }

    .sev-medium {
      color: var(--accent);
    }

    .sev-low {
      color: var(--accent-2);
    }

    .sev-info {
      color: var(--muted);
    }

    .loc {
      color: var(--muted);
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 12px;
      margin-right: 8px;
    }

    .body,
    .suggestion {
      margin: 4px 0 0;
      white-space: pre-wrap;
    }

    .body {
      color: var(--muted);
    }

    .suggestion {
      color: var(--accent);
    }

    .suggestion a {
      color: var(--accent-2);
    }

    .source,
    .note {
      color: var(--muted);
      font-size: 12px;
      margin: 4px 0 0;
    }

    .note {
      font-style: italic;
    }

    .snippet {
      background: rgba(0, 0, 0, 0.25);
      border: 1px solid var(--line);
      border-radius: 6px;
      margin: 8px 0 0;
      padding: 8px 10px;
    }
  </style>
  <title>CodeSage Code Review</title>
</head>
<body>
  <main>
    <header>
      <h1>CodeSage Code Review</h1>
      <p class="subtitle">AI review from the local backend.</p>
      <span class="status ${view.statusClass}">${escapeHtml(view.status)}</span>
    </header>

    <section>
      <h2>Analysis</h2>
      <div class="summary md">${view.analysis}</div>
    </section>

    <section>
      <h2>Issues</h2>
      ${view.issues}
    </section>

    ${view.excluded}
  </main>
</body>
</html>`;
}
