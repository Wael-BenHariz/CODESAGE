import * as vscode from 'vscode';
import type { DiagnosticApplyResult } from './diagnostics';
import { renderReportHtml } from './render';
import type { ReportViewState } from './render';
import type { GitCollection, LocalReviewResult } from './types';

const LOADING_MESSAGE = 'Running AI code review.';

/**
 * Serves the CodeSage review as a single styled webview panel beside the editor.
 * The panel is script-free: findings open through `command:` URIs.
 */
export class ReportPanel implements vscode.Disposable {
  private panel: vscode.WebviewPanel | null = null;
  private state: ReportViewState = { kind: 'loading', message: LOADING_MESSAGE };

  constructor(private readonly extensionUri: vscode.Uri) {}

  get isOpen(): boolean {
    return this.panel !== null;
  }

  showLoading(message = LOADING_MESSAGE): void {
    this.render({ kind: 'loading', message });
  }

  showResult(
    result: LocalReviewResult,
    collection: GitCollection,
    diagnostics: DiagnosticApplyResult
  ): void {
    this.render({ kind: 'result', result, collection, diagnostics });
  }

  showError(message: string): void {
    this.render({ kind: 'error', message });
  }

  showCancelled(): void {
    this.render({ kind: 'cancelled' });
  }

  clear(): void {
    this.state = { kind: 'loading', message: LOADING_MESSAGE };
    this.panel?.dispose();
    this.panel = null;
  }

  reveal(): void {
    const panel = this.ensurePanel();
    panel.reveal(vscode.ViewColumn.Beside);
  }

  dispose(): void {
    this.panel?.dispose();
    this.panel = null;
  }

  private render(state: ReportViewState): void {
    this.state = state;
    const panel = this.ensurePanel();
    panel.webview.html = renderReportHtml(state);
    panel.reveal(vscode.ViewColumn.Beside);
  }

  private ensurePanel(): vscode.WebviewPanel {
    if (this.panel) {
      return this.panel;
    }
    const panel = vscode.window.createWebviewPanel(
      'codesage.report',
      'CodeSage Code Review',
      vscode.ViewColumn.Beside,
      {
        enableScripts: false,
        enableCommandUris: true,
        localResourceRoots: [this.extensionUri]
      }
    );
    panel.onDidDispose(() => {
      this.panel = null;
    });
    panel.webview.html = renderReportHtml(this.state);
    this.panel = panel;
    return panel;
  }
}
