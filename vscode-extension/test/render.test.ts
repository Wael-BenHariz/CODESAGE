import { describe, expect, it } from 'vitest';
import { commandUri, escapeHtml, renderMarkdown, renderReportHtml } from '../src/render';
import type { GitCollection, LocalReviewResult } from '../src/types';

function makeResult(overrides: Partial<LocalReviewResult> = {}): LocalReviewResult {
  return {
    schemaVersion: 1,
    snapshot: {
      id: 'snapshot-1',
      baseRevision: 'abc',
      headSha: 'def',
      branch: 'main',
      capturedAt: '2026-10-24T00:00:00Z',
      files: [
        {
          path: 'src/app.ts',
          status: 'modified',
          contentSha256: 'sha',
          size: 120
        }
      ]
    },
    summary: 'Two problems were found in the changed code.',
    overallSeverity: 'high',
    statistics: {
      filesReviewed: 3,
      issuesFound: 2,
      bySeverity: { high: 1, low: 1 },
      byCategory: {}
    },
    findings: [
      {
        id: 'finding-1',
        source: 'static',
        nativeSeverity: 'high',
        severity: 'high',
        filePath: 'src/app.ts',
        lineStart: 12,
        lineEnd: 12,
        message: 'Unsanitized input reaches the query builder.',
        body: 'The request value is concatenated into SQL.',
        suggestion: 'Use a parameterized query.',
        snippet: 'db.query(`... ${req.query.id}`)',
        tool: 'semgrep',
        ruleId: 'sql-injection',
        category: 'security',
        alsoDetectedBy: ['sonarqube'],
        reason: undefined
      },
      {
        id: 'finding-2',
        source: 'agent',
        nativeSeverity: 'suggestion',
        severity: 'low',
        filePath: 'src/util.ts',
        lineStart: null,
        lineEnd: null,
        message: 'Consider extracting this helper.',
        body: 'Consider extracting this helper.',
        suggestion: null,
        snippet: null,
        tool: null,
        ruleId: null,
        category: 'style',
        alsoDetectedBy: []
      }
    ],
    degradedReasons: ['semgrep_failed'],
    agentFailures: ['PerformanceAgent'],
    diffTruncated: false,
    durationMs: 1234,
    ...overrides
  };
}

function makeCollection(): GitCollection {
  return {
    repoRoot: '/repo',
    snapshot: makeResult().snapshot,
    diff: '',
    diffTruncated: false,
    changedRanges: {},
    files: [],
    excluded: [{ path: 'vendor/big.js', reason: 'larger than 524288 bytes' }],
    totalBytes: 0
  };
}

describe('escapeHtml', () => {
  it('escapes markup and quotes', () => {
    expect(escapeHtml('<a href="x">&\'</a>')).toBe(
      '&lt;a href=&quot;x&quot;&gt;&amp;&#039;&lt;/a&gt;'
    );
  });
});

describe('commandUri', () => {
  it('encodes arguments as a JSON array', () => {
    expect(commandUri('codesage.openFinding', 'finding-1')).toBe(
      'command:codesage.openFinding?%5B%22finding-1%22%5D'
    );
  });
});

describe('renderReportHtml', () => {
  it('renders the loading state', () => {
    const html = renderReportHtml({ kind: 'loading', message: 'Running AI code review.' });

    expect(html).toContain('CodeSage Code Review');
    expect(html).toContain('Reviewing…');
    expect(html).toContain('Running AI code review.');
    expect(html).toContain('Waiting for the review to finish…');
  });

  it('renders the error state', () => {
    const html = renderReportHtml({ kind: 'error', message: 'Backend unreachable.' });

    expect(html).toContain('Review failed');
    expect(html).toContain('Backend unreachable.');
    expect(html).toContain('status-error');
  });

  it('renders summary, findings, severity and command links', () => {
    const html = renderReportHtml({
      kind: 'result',
      result: makeResult(),
      collection: makeCollection(),
      diagnostics: { shown: new Set(['finding-1']), reasons: new Map() }
    });

    expect(html).toContain('Two problems were found in the changed code.');
    expect(html).toContain('Unsanitized input reaches the query builder.');
    expect(html).toContain('src/app.ts');
    expect(html).toContain('sev-high');
    expect(html).toContain('Use a parameterized query.');
    expect(html).toContain('also detected by sonarqube');
    expect(html).toContain('command:codesage.openFinding?');
    expect(html).toContain('2 findings · 3 files');
    expect(html).toContain('Excluded files');
    expect(html).toContain('vendor/big.js');
  });

  it('escapes untrusted content in findings', () => {
    const result = makeResult();
    result.findings[0]!.message = '<img src=x onerror="alert(1)">';
    const html = renderReportHtml({
      kind: 'result',
      result,
      collection: makeCollection(),
      diagnostics: null
    });

    expect(html).not.toContain('<img src=x');
    expect(html).toContain('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  });

  it('shows the empty state when there are no findings', () => {
    const html = renderReportHtml({
      kind: 'result',
      result: makeResult({ findings: [], degradedReasons: [], agentFailures: [] }),
      collection: null,
      diagnostics: null
    });

    expect(html).toContain('No specific issues returned.');
    expect(html).toContain('0 findings');
    expect(html).not.toContain('Full Report');
    expect(html).not.toContain('Limited coverage');
  });

  it('notes findings that are not shown inline', () => {
    const html = renderReportHtml({
      kind: 'result',
      result: makeResult({ degradedReasons: [], agentFailures: [] }),
      collection: null,
      diagnostics: {
        shown: new Set(),
        reasons: new Map([['finding-1', 'line_outside_diff']])
      }
    });

    expect(html).toContain('Not shown inline: line is outside the reviewed diff');
  });
});

describe('renderMarkdown', () => {
  it('renders headings, lists and inline formatting', () => {
    const html = renderMarkdown(
      [
        '## Executive Summary',
        '- The scan found **hard-coded credentials** in `test.java`.',
        '',
        '### Findings by File',
        '1. First item',
        '2. Second item with *emphasis*'
      ].join('\n')
    );

    expect(html).toContain('<h4>Executive Summary</h4>');
    expect(html).toContain('<h5>Findings by File</h5>');
    expect(html).toContain('<ul><li>The scan found <strong>hard-coded credentials</strong> in <code>test.java</code>.</li></ul>');
    expect(html).toContain('<ol><li>First item</li><li>Second item with <em>emphasis</em></li></ol>');
    expect(html).not.toContain('##');
  });

  it('never lets untrusted summary text inject markup', () => {
    const html = renderMarkdown('<img src=x onerror="alert(1)">');

    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  });

  it('keeps identifier underscores literal', () => {
    const html = renderMarkdown('Fields `SECRET_KEY` and DB_PASS are hard-coded.');

    expect(html).toContain('<code>SECRET_KEY</code>');
    expect(html).toContain('DB_PASS');
    expect(html).not.toContain('<em>');
  });
});
