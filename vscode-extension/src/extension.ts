import * as vscode from 'vscode';
import { DevTokenAuthProvider } from './auth';
import { ReviewController } from './controller';
import { DiagnosticsManager } from './diagnostics';
import { ReviewTreeProvider, SummaryDocumentProvider } from './tree';
import type { Finding } from './types';

let controller: ReviewController | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel('CodeSage');
  const auth = new DevTokenAuthProvider(context.secrets);
  const diagnostics = new DiagnosticsManager();
  const tree = new ReviewTreeProvider();
  const summaryProvider = new SummaryDocumentProvider();
  controller = new ReviewController(auth, tree, diagnostics, summaryProvider, output);

  context.subscriptions.push(
    output,
    diagnostics,
    tree,
    summaryProvider,
    vscode.window.registerTreeDataProvider('codesage.review', tree),
    vscode.workspace.registerTextDocumentContentProvider(
      'codesage-review',
      summaryProvider
    ),
    vscode.commands.registerCommand('codesage.reviewWorkingTree', () =>
      controller?.run('workingTree')
    ),
    vscode.commands.registerCommand('codesage.reviewStaged', () => controller?.run('staged')),
    vscode.commands.registerCommand('codesage.cancelReview', () => controller?.cancel()),
    vscode.commands.registerCommand('codesage.clearResults', () => controller?.clear()),
    vscode.commands.registerCommand('codesage.showSummary', () => controller?.showSummary()),
    vscode.commands.registerCommand('codesage.openFinding', (finding: Finding) =>
      controller?.openFinding(finding)
    ),
    vscode.commands.registerCommand('codesage.copySuggestion', (finding: Finding) =>
      controller?.copySuggestion(finding)
    ),
    vscode.commands.registerCommand('codesage.setDevToken', () => controller?.setDevToken()),
    vscode.commands.registerCommand('codesage.showOutput', () => controller?.showOutput()),
    vscode.commands.registerCommand('codesage.openSettings', () =>
      vscode.commands.executeCommand(
        'workbench.action.openSettings',
        '@ext:codesage.codesage-vscode'
      )
    ),
    controller
  );
}

export function deactivate(): void {
  controller = undefined;
}
