import { createHash } from 'node:crypto';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import * as vscode from 'vscode';
import { lineIsChanged } from './diff';
import type { ChangedRange } from './diff';
import type { Finding, LocalReviewResult, ReviewSnapshot } from './types';

export interface DiagnosticSettings {
  changedLinesOnly: boolean;
  includeFileLevel: boolean;
  showSuggestions: boolean;
}

export interface DiagnosticApplyResult {
  shown: Set<string>;
  reasons: Map<string, string>;
}

function sha256(data: Buffer): string {
  return createHash('sha256').update(data).digest('hex');
}

function vsSeverity(severity: Finding['severity']): vscode.DiagnosticSeverity {
  switch (severity) {
    case 'critical':
    case 'high':
      return vscode.DiagnosticSeverity.Error;
    case 'medium':
      return vscode.DiagnosticSeverity.Warning;
    case 'low':
      return vscode.DiagnosticSeverity.Information;
    default:
      return vscode.DiagnosticSeverity.Information;
  }
}

function diagnosticMessage(finding: Finding, settings: DiagnosticSettings): string {
  const parts = [finding.message];
  if (settings.showSuggestions && finding.suggestion) {
    parts.push('', `Suggestion: ${finding.suggestion}`);
  }
  if (finding.tool && finding.ruleId) {
    parts.push('', `Source: ${finding.tool} / ${finding.ruleId}`);
  }
  return parts.join('\n');
}

export class DiagnosticsManager implements vscode.Disposable {
  private readonly collection = vscode.languages.createDiagnosticCollection('codesage');

  async apply(
    result: LocalReviewResult,
    repoRoot: string,
    changedRanges: Record<string, ChangedRange[]>,
    settings: DiagnosticSettings
  ): Promise<DiagnosticApplyResult> {
    this.collection.clear();
    const shown = new Set<string>();
    const reasons = new Map<string, string>();
    const byFile = new Map<string, vscode.Diagnostic[]>();
    const snapshotByPath = new Map<string, ReviewSnapshot['files'][number]>(
      result.snapshot.files.map((file) => [file.path, file])
    );

    for (const finding of result.findings) {
      const snapshotFile = snapshotByPath.get(finding.filePath);
      if (!snapshotFile) {
        reasons.set(finding.id, 'file_not_in_snapshot');
        continue;
      }
      if (snapshotFile.status === 'deleted') {
        reasons.set(finding.id, 'file_deleted');
        continue;
      }

      const absolute = path.resolve(repoRoot, finding.filePath);
      const relative = path.relative(repoRoot, absolute);
      if (relative.startsWith('..') || path.isAbsolute(relative)) {
        reasons.set(finding.id, 'unsafe_path');
        continue;
      }

      let content: string;
      try {
        const buffer = await fs.readFile(absolute);
        if (snapshotFile.contentSha256 && sha256(buffer) !== snapshotFile.contentSha256) {
          reasons.set(finding.id, 'stale_snapshot');
          continue;
        }
        content = buffer.toString('utf8');
      } catch {
        reasons.set(finding.id, 'file_unreadable');
        continue;
      }

      if (finding.lineStart === null) {
        if (!settings.includeFileLevel) {
          reasons.set(finding.id, 'line_missing');
          continue;
        }
        const diagnostic = new vscode.Diagnostic(
          new vscode.Range(0, 0, 0, 0),
          diagnosticMessage(finding, settings),
          vsSeverity(finding.severity)
        );
        diagnostic.source = 'CodeSage';
        diagnostic.code = finding.id;
        byFile.set(finding.filePath, [...(byFile.get(finding.filePath) ?? []), diagnostic]);
        shown.add(finding.id);
        continue;
      }

      if (settings.changedLinesOnly && !lineIsChanged(finding.lineStart, finding.lineEnd, changedRanges[finding.filePath] ?? [])) {
        reasons.set(finding.id, 'line_outside_diff');
        continue;
      }

      const lines = content.split(/\r?\n/);
      const startLine = Math.min(Math.max(1, finding.lineStart), lines.length);
      const endLine = Math.min(
        Math.max(startLine, finding.lineEnd ?? startLine),
        lines.length
      );
      const start = new vscode.Position(startLine - 1, 0);
      const end = new vscode.Position(endLine - 1, lines[endLine - 1]?.length ?? 0);
      const diagnostic = new vscode.Diagnostic(
        new vscode.Range(start, end),
        diagnosticMessage(finding, settings),
        vsSeverity(finding.severity)
      );
      diagnostic.source = 'CodeSage';
      diagnostic.code = finding.id;

      if (finding.tool || finding.ruleId) {
        diagnostic.relatedInformation = [
          new vscode.DiagnosticRelatedInformation(
            new vscode.Location(vscode.Uri.file(absolute), new vscode.Range(start, start)),
            [finding.tool, finding.ruleId].filter(Boolean).join(' / ')
          )
        ];
      }

      byFile.set(finding.filePath, [...(byFile.get(finding.filePath) ?? []), diagnostic]);
      shown.add(finding.id);
    }

    for (const [filePath, diagnostics] of byFile) {
      this.collection.set(vscode.Uri.file(path.resolve(repoRoot, filePath)), diagnostics);
    }

    return { shown, reasons };
  }

  clear(): void {
    this.collection.clear();
  }

  dispose(): void {
    this.collection.dispose();
  }
}
