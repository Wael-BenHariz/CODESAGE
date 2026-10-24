import * as vscode from 'vscode';
import { compareFindings } from './severity';
import type { ExcludedFile, Finding, GitCollection, LocalReviewResult } from './types';

export interface TreeDiagnostics {
  shown: Set<string>;
  reasons: Map<string, string>;
}

type Node =
  | StatusNode
  | SummaryNode
  | DegradedNode
  | FileNode
  | FindingNode
  | DetailNode
  | ExcludedNode
  | MessageNode;

interface StatusNode {
  kind: 'status';
}
interface SummaryNode {
  kind: 'summary';
}
interface DegradedNode {
  kind: 'degraded';
  reasons: string[];
}
interface FileNode {
  kind: 'file';
  filePath: string;
  findings: Finding[];
}
interface FindingNode {
  kind: 'finding';
  finding: Finding;
  note?: string;
}
interface DetailNode {
  kind: 'detail';
  detail: 'explanation' | 'suggestion' | 'source';
  finding: Finding;
}
interface ExcludedNode {
  kind: 'excluded';
  file: ExcludedFile;
}
interface MessageNode {
  kind: 'message';
  message: string;
  icon?: string;
}

function truncate(value: string, max = 140): string {
  const singleLine = value.replace(/\s+/g, ' ').trim();
  return singleLine.length > max ? `${singleLine.slice(0, max - 1)}…` : singleLine;
}

function severityIcon(severity: Finding['severity']): string {
  switch (severity) {
    case 'critical':
    case 'high':
      return 'error';
    case 'medium':
      return 'warning';
    case 'low':
      return 'info';
    default:
      return 'lightbulb';
  }
}

function findingTooltip(finding: Finding): vscode.MarkdownString {
  const tooltip = new vscode.MarkdownString();
  tooltip.isTrusted = false;
  tooltip.appendMarkdown(`**${finding.severity.toUpperCase()}** · \`${finding.filePath}\``);
  if (finding.lineStart !== null) {
    tooltip.appendMarkdown(`:${finding.lineStart}`);
  }
  tooltip.appendMarkdown(`\n\n${finding.body || finding.message}`);
  if (finding.suggestion) {
    tooltip.appendMarkdown(`\n\n**Suggestion:** ${finding.suggestion}`);
  }
  if (finding.tool || finding.ruleId) {
    tooltip.appendMarkdown(
      `\n\nSource: ${[finding.tool, finding.ruleId].filter(Boolean).join(' / ')}`
    );
  }
  if (finding.snippet) {
    tooltip.appendMarkdown(`\n\n\`\`\`\n${finding.snippet}\n\`\`\``);
  }
  return tooltip;
}

export class ReviewTreeProvider implements vscode.TreeDataProvider<Node>, vscode.Disposable {
  private readonly emitter = new vscode.EventEmitter<Node | undefined>();
  readonly onDidChangeTreeData = this.emitter.event;

  private result: LocalReviewResult | null = null;
  private collection: GitCollection | null = null;
  private diagnostics: TreeDiagnostics = { shown: new Set(), reasons: new Map() };
  private error: string | null = null;
  private loading = false;

  setLoading(): void {
    this.loading = true;
    this.error = null;
    this.emitter.fire(undefined);
  }

  setResult(result: LocalReviewResult, collection: GitCollection, diagnostics: TreeDiagnostics): void {
    this.result = result;
    this.collection = collection;
    this.diagnostics = diagnostics;
    this.error = null;
    this.loading = false;
    this.emitter.fire(undefined);
  }

  setError(message: string): void {
    this.error = message;
    this.result = null;
    this.collection = null;
    this.loading = false;
    this.emitter.fire(undefined);
  }

  reset(): void {
    this.result = null;
    this.collection = null;
    this.diagnostics = { shown: new Set(), reasons: new Map() };
    this.error = null;
    this.loading = false;
    this.emitter.fire(undefined);
  }

  get currentResult(): LocalReviewResult | null {
    return this.result;
  }

  getTreeItem(element: Node): vscode.TreeItem {
    switch (element.kind) {
      case 'status': {
        const item = new vscode.TreeItem(
          this.loading ? 'Reviewing…' : this.error ? 'Review failed' : 'CodeSage'
        );
        item.iconPath = new vscode.ThemeIcon(
          this.loading ? 'loading~spin' : this.error ? 'error' : 'pass'
        );
        if (this.result) {
          item.description = `${this.result.findings.length} findings · ${this.result.statistics.filesReviewed} files`;
          item.tooltip = `${this.result.durationMs} ms`;
        } else if (this.error) {
          item.description = truncate(this.error);
        }
        return item;
      }
      case 'summary': {
        const item = new vscode.TreeItem('Review summary');
        item.iconPath = new vscode.ThemeIcon('markdown');
        item.command = {
          command: 'codesage.showSummary',
          title: 'Show review summary'
        };
        return item;
      }
      case 'degraded': {
        const item = new vscode.TreeItem('Limited coverage');
        item.iconPath = new vscode.ThemeIcon('warning');
        item.description = element.reasons.join(', ');
        item.collapsibleState = vscode.TreeItemCollapsibleState.Collapsed;
        return item;
      }
      case 'file': {
        const item = new vscode.TreeItem(element.filePath);
        item.iconPath = new vscode.ThemeIcon('file-code');
        item.description = `${element.findings.length}`;
        item.collapsibleState = vscode.TreeItemCollapsibleState.Collapsed;
        item.tooltip = element.filePath;
        return item;
      }
      case 'finding': {
        const item = new vscode.TreeItem(element.finding.message);
        item.iconPath = new vscode.ThemeIcon(severityIcon(element.finding.severity));
        item.description = [
          element.finding.lineStart === null ? 'file' : `line ${element.finding.lineStart}`,
          element.note
        ]
          .filter(Boolean)
          .join(' · ');
        item.tooltip = findingTooltip(element.finding);
        item.command = {
          command: 'codesage.openFinding',
          title: 'Open finding',
          arguments: [element.finding]
        };
        item.collapsibleState =
          element.finding.body || element.finding.suggestion || element.finding.tool
            ? vscode.TreeItemCollapsibleState.Collapsed
            : vscode.TreeItemCollapsibleState.None;
        return item;
      }
      case 'detail': {
        const label =
          element.detail === 'explanation'
            ? 'Explanation'
            : element.detail === 'suggestion'
              ? 'Suggestion'
              : 'Source';
        const item = new vscode.TreeItem(label);
        item.iconPath = new vscode.ThemeIcon(
          element.detail === 'explanation'
            ? 'comment'
            : element.detail === 'suggestion'
              ? 'lightbulb'
              : 'tag'
        );
        const value =
          element.detail === 'explanation'
            ? element.finding.body || element.finding.message
            : element.detail === 'suggestion'
              ? element.finding.suggestion ?? ''
              : [element.finding.tool, element.finding.ruleId].filter(Boolean).join(' / ');
        item.description = truncate(value);
        item.tooltip = value;
        item.command = {
          command:
            element.detail === 'suggestion' ? 'codesage.copySuggestion' : 'codesage.openFinding',
          title: element.detail === 'suggestion' ? 'Copy suggestion' : 'Open finding',
          arguments: [element.finding]
        };
        return item;
      }
      case 'excluded': {
        const item = new vscode.TreeItem(element.file.path);
        item.iconPath = new vscode.ThemeIcon('circle-slash');
        item.description = element.file.reason;
        return item;
      }
      case 'message': {
        const item = new vscode.TreeItem(element.message);
        item.iconPath = new vscode.ThemeIcon(element.icon ?? 'info');
        return item;
      }
    }
  }

  getChildren(element?: Node): Node[] {
    if (!element) {
      if (this.loading) {
        return [{ kind: 'status' }];
      }
      if (this.error) {
        return [{ kind: 'status' }, { kind: 'message', message: this.error, icon: 'error' }];
      }
      if (!this.result) {
        return [];
      }
      const nodes: Node[] = [{ kind: 'status' }, { kind: 'summary' }];
      if (this.result.degradedReasons.length > 0) {
        nodes.push({ kind: 'degraded', reasons: this.result.degradedReasons });
      }
      const grouped = new Map<string, Finding[]>();
      for (const finding of [...this.result.findings].sort(compareFindings)) {
        const key = finding.filePath || 'General';
        grouped.set(key, [...(grouped.get(key) ?? []), finding]);
      }
      for (const [filePath, findings] of [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b))) {
        nodes.push({ kind: 'file', filePath, findings });
      }
      if (grouped.size === 0) {
        nodes.push({ kind: 'message', message: 'No findings reported', icon: 'pass' });
      }
      if (this.collection?.excluded.length) {
        for (const file of this.collection.excluded) {
          nodes.push({ kind: 'excluded', file });
        }
      }
      return nodes;
    }

    if (element.kind === 'file') {
      return element.findings.map((finding) => ({
        kind: 'finding',
        finding,
        note: this.diagnostics.shown.has(finding.id)
          ? undefined
          : this.diagnostics.reasons.get(finding.id)
      }));
    }

    if (element.kind === 'finding') {
      const details: Node[] = [];
      if (element.finding.body || element.finding.message) {
        details.push({ kind: 'detail', detail: 'explanation', finding: element.finding });
      }
      if (element.finding.suggestion) {
        details.push({ kind: 'detail', detail: 'suggestion', finding: element.finding });
      }
      if (element.finding.tool || element.finding.ruleId) {
        details.push({ kind: 'detail', detail: 'source', finding: element.finding });
      }
      return details;
    }

    if (element.kind === 'degraded') {
      return element.reasons.map((reason) => ({ kind: 'message', message: reason, icon: 'warning' }));
    }

    return [];
  }

  dispose(): void {
    this.emitter.dispose();
  }
}

export class SummaryDocumentProvider implements vscode.TextDocumentContentProvider, vscode.Disposable {
  static readonly URI = vscode.Uri.parse('codesage-review:/summary.md');

  private readonly emitter = new vscode.EventEmitter<vscode.Uri>();
  readonly onDidChange = this.emitter.event;
  private content = '';

  update(content: string): void {
    this.content = content;
    this.emitter.fire(SummaryDocumentProvider.URI);
  }

  provideTextDocumentContent(): string {
    return this.content;
  }

  dispose(): void {
    this.emitter.dispose();
  }
}
