import * as vscode from 'vscode';
import { ApiError, CodeSageClient } from './api';
import { DevTokenAuthProvider } from './auth';
import type { DiagnosticsManager } from './diagnostics';
import { buildReviewRequest, collectLocalReview, GitError, NoChangesError } from './git';
import { SummaryDocumentProvider } from './tree';
import type { ReviewTreeProvider } from './tree';
import type { Finding, LocalReviewResult, ReviewScope } from './types';

interface CodeSageConfig {
  backendUrl: string;
  reviewScope: ReviewScope;
  includeUntracked: boolean;
  changedLinesOnly: boolean;
  includeFileLevel: boolean;
  confirmBeforeSend: boolean;
  maxFiles: number;
  maxPayloadBytes: number;
  requestTimeoutMs: number;
  showSuggestions: boolean;
}

function readConfig(): CodeSageConfig {
  const config = vscode.workspace.getConfiguration('codesage');
  const scope = config.get<string>('reviewScope', 'workingTree');
  return {
    backendUrl: config.get<string>('backendUrl', 'http://127.0.0.1:8000'),
    reviewScope: scope === 'staged' ? 'staged' : 'workingTree',
    includeUntracked: config.get<boolean>('includeUntracked', true),
    changedLinesOnly: config.get<boolean>('changedLinesOnly', true),
    includeFileLevel: config.get<boolean>('includeFileLevel', true),
    confirmBeforeSend: config.get<boolean>('confirmBeforeSend', true),
    maxFiles: config.get<number>('maxFiles', 25),
    maxPayloadBytes: config.get<number>('maxPayloadBytes', 4 * 1024 * 1024),
    requestTimeoutMs: config.get<number>('requestTimeoutMs', 240000),
    showSuggestions: config.get<boolean>('showSuggestions', true)
  };
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function isLoopbackUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return ['127.0.0.1', '::1', 'localhost'].includes(url.hostname);
  } catch {
    return false;
  }
}

function summaryMarkdown(result: LocalReviewResult, repoRoot: string): string {
  const lines = [
    '# CodeSage local review',
    '',
    `- Repository: \`${repoRoot}\``,
    `- Branch: \`${result.snapshot.branch ?? 'detached HEAD'}\``,
    `- Snapshot: \`${result.snapshot.id}\``,
    `- Duration: ${result.durationMs} ms`,
    `- Findings: ${result.findings.length}`,
    '',
    '## Summary',
    '',
    result.summary || '_No summary returned._',
    '',
    '## Counts',
    '',
    `- Files reviewed: ${result.statistics.filesReviewed}`,
    `- Issues found: ${result.statistics.issuesFound}`
  ];
  for (const [severity, count] of Object.entries(result.statistics.bySeverity).sort()) {
    lines.push(`- ${severity}: ${count}`);
  }
  if (result.degradedReasons.length > 0) {
    lines.push('', '## Limited coverage', '');
    for (const reason of result.degradedReasons) {
      lines.push(`- ${reason}`);
    }
  }
  if (result.agentFailures.length > 0) {
    lines.push('', '## Agent failures', '');
    for (const failure of result.agentFailures) {
      lines.push(`- ${failure}`);
    }
  }
  if (result.diffTruncated) {
    lines.push('', '_The diff was truncated before it was sent to the LLM._');
  }
  return lines.join('\n');
}

export class ReviewController implements vscode.Disposable {
  private abortController: AbortController | null = null;
  private running = false;

  constructor(
    private readonly auth: DevTokenAuthProvider,
    private readonly tree: ReviewTreeProvider,
    private readonly diagnostics: DiagnosticsManager,
    private readonly summaryProvider: SummaryDocumentProvider,
    private readonly output: vscode.OutputChannel
  ) {}

  async run(scope?: ReviewScope): Promise<void> {
    if (this.running) {
      void vscode.window.showInformationMessage('A CodeSage review is already running.');
      return;
    }

    const config = readConfig();
    const folder = await this.pickFolder();
    if (!folder) {
      return;
    }

    let backendUrl: URL;
    try {
      backendUrl = new URL(config.backendUrl);
    } catch {
      void vscode.window.showErrorMessage('CodeSage backend URL is invalid.');
      return;
    }
    if (!['http:', 'https:'].includes(backendUrl.protocol)) {
      void vscode.window.showErrorMessage('CodeSage backend URL must use http or https.');
      return;
    }

    if (!(await this.auth.hasToken())) {
      const action = await vscode.window.showWarningMessage(
        'CodeSage needs the development token before it can review local changes.',
        'Set Development Token'
      );
      if (action === 'Set Development Token') {
        await this.setDevToken();
      }
      if (!(await this.auth.hasToken())) {
        return;
      }
    }

    this.running = true;
    this.tree.setLoading();
    const selectedScope = scope ?? config.reviewScope;

    try {
      const collection = await collectLocalReview(folder.uri.fsPath, {
        scope: selectedScope,
        includeUntracked: config.includeUntracked,
        maxFiles: config.maxFiles,
        maxPayloadBytes: config.maxPayloadBytes
      });

      const confirmed = await this.confirmSend(collection, backendUrl, selectedScope, config);
      if (!confirmed) {
        this.tree.reset();
        return;
      }

      const controller = new AbortController();
      this.abortController = controller;
      const client = new CodeSageClient({
        baseUrl: config.backendUrl,
        auth: this.auth,
        timeoutMs: config.requestTimeoutMs
      });
      const request = buildReviewRequest(collection, selectedScope);

      const result = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: 'CodeSage: reviewing local changes',
          cancellable: true
        },
        async (_progress, token) => {
          token.onCancellationRequested(() => controller.abort());
          return client.submitDevReview(request, controller.signal);
        }
      );

      const diagnosticState = await this.diagnostics.apply(
        result,
        collection.repoRoot,
        collection.changedRanges,
        {
          changedLinesOnly: config.changedLinesOnly,
          includeFileLevel: config.includeFileLevel,
          showSuggestions: config.showSuggestions
        }
      );
      this.tree.setResult(result, collection, diagnosticState);
      this.summaryProvider.update(summaryMarkdown(result, collection.repoRoot));
      this.output.appendLine(
        `review completed: files=${collection.files.length} findings=${result.findings.length} ` +
          `degraded=${result.degradedReasons.join(',') || 'none'} duration_ms=${result.durationMs}`
      );
      void vscode.window.showInformationMessage(
        `CodeSage found ${result.findings.length} finding${result.findings.length === 1 ? '' : 's'}.`
      );
    } catch (error) {
      if (error instanceof NoChangesError) {
        this.tree.setError('No reviewable Git changes were found.');
        void vscode.window.showInformationMessage('CodeSage: no reviewable Git changes were found.');
        return;
      }
      if (error instanceof GitError) {
        this.tree.setError(error.message);
        void vscode.window.showErrorMessage(error.message);
        return;
      }
      const message = this.friendlyError(error);
      this.tree.setError(message);
      this.output.appendLine(`review failed: ${message}`);
      void vscode.window.showErrorMessage(message);
    } finally {
      this.abortController = null;
      this.running = false;
    }
  }

  cancel(): void {
    this.abortController?.abort();
  }

  clear(): void {
    this.cancel();
    this.diagnostics.clear();
    this.tree.reset();
    this.summaryProvider.update('');
  }

  async openFinding(finding: Finding): Promise<void> {
    const result = this.tree.currentResult;
    const snapshotFile = result?.snapshot.files.find((file) => file.path === finding.filePath);
    if (!snapshotFile) {
      void vscode.window.showWarningMessage('This finding is not part of the current snapshot.');
      return;
    }
    const folder = await this.pickFolder();
    if (!folder) {
      return;
    }
    const uri = vscode.Uri.joinPath(folder.uri, ...finding.filePath.split('/'));
    try {
      const document = await vscode.workspace.openTextDocument(uri);
      const editor = await vscode.window.showTextDocument(document, { preview: true });
      if (finding.lineStart !== null) {
        const position = new vscode.Position(Math.max(0, finding.lineStart - 1), 0);
        editor.selection = new vscode.Selection(position, position);
        editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
      }
    } catch {
      void vscode.window.showWarningMessage(`Could not open ${finding.filePath}.`);
    }
  }

  async copySuggestion(finding: Finding): Promise<void> {
    if (!finding.suggestion) {
      void vscode.window.showInformationMessage('This finding has no suggestion.');
      return;
    }
    await vscode.env.clipboard.writeText(finding.suggestion);
    void vscode.window.showInformationMessage('CodeSage suggestion copied.');
  }

  async showSummary(): Promise<void> {
    if (!this.tree.currentResult) {
      void vscode.window.showInformationMessage('Run a CodeSage review first.');
      return;
    }
    const document = await vscode.workspace.openTextDocument(SummaryDocumentProvider.URI);
    await vscode.window.showTextDocument(document, { preview: true });
  }

  async setDevToken(): Promise<void> {
    const token = await vscode.window.showInputBox({
      title: 'CodeSage development token',
      prompt: 'Must match LOCAL_REVIEW_DEV_TOKEN on the local backend.',
      password: true,
      ignoreFocusOut: true
    });
    if (token === undefined) {
      return;
    }
    if (!token.trim()) {
      await this.auth.clearToken();
      void vscode.window.showInformationMessage('CodeSage development token cleared.');
      return;
    }
    await this.auth.setToken(token.trim());
    void vscode.window.showInformationMessage('CodeSage development token saved.');
  }

  showOutput(): void {
    this.output.show(true);
  }

  dispose(): void {
    this.abortController?.abort();
  }

  private async pickFolder(): Promise<vscode.WorkspaceFolder | undefined> {
    const folders = vscode.workspace.workspaceFolders ?? [];
    if (folders.length === 0) {
      void vscode.window.showErrorMessage('Open a Git repository folder first.');
      return undefined;
    }
    if (folders.length === 1) {
      return folders[0];
    }
    const active = vscode.window.activeTextEditor
      ? vscode.workspace.getWorkspaceFolder(vscode.window.activeTextEditor.document.uri)
      : undefined;
    if (active) {
      return active;
    }
    const picked = await vscode.window.showQuickPick(
      folders.map((folder) => ({ label: folder.name, description: folder.uri.fsPath, folder })),
      { title: 'Select the repository to review' }
    );
    return picked?.folder;
  }

  private async confirmSend(
    collection: Awaited<ReturnType<typeof collectLocalReview>>,
    backendUrl: URL,
    scope: ReviewScope,
    config: CodeSageConfig
  ): Promise<boolean> {
    if (!config.confirmBeforeSend) {
      return true;
    }
    const excluded = collection.excluded.length
      ? `\nExcluded: ${collection.excluded.length} file(s).`
      : '';
    const transport = backendUrl.protocol === 'https:' ? 'HTTPS' : 'unencrypted HTTP';
    const warning = isLoopbackUrl(backendUrl.toString())
      ? ''
      : '\n\nThis is not a loopback backend. Source code leaves this machine.';
    const detail =
      `Backend: ${backendUrl.toString()}\n` +
      `Mode: development token (no user/org context)\n` +
      `Scope: ${scope}\n` +
      `Files: ${collection.files.length} (${formatBytes(collection.totalBytes)})\n` +
      `Transport: ${transport}${excluded}${warning}\n\n` +
      'The selected source files and diff will be sent to CodeSage for review.';
    const choice = await vscode.window.showWarningMessage(
      'Send local source changes to CodeSage?',
      { modal: true, detail },
      'Send'
    );
    return choice === 'Send';
  }

  private friendlyError(error: unknown): string {
    if (error instanceof ApiError) {
      if (error.status === 404) {
        return 'CodeSage dev mode is not enabled on this backend (or the URL is wrong).';
      }
      if (error.status === 401) {
        return 'The CodeSage development token is invalid. Set it again and retry.';
      }
      if (error.status === 413) {
        return 'The review payload is too large. Reduce the changed files and retry.';
      }
      if (error.status === 504) {
        return 'The CodeSage review timed out. Try a smaller set of changes.';
      }
      return error.message;
    }
    if (error instanceof Error) {
      return error.message;
    }
    return 'The CodeSage review failed.';
  }
}
