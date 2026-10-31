import * as vscode from 'vscode';
import { DevTokenAuthProvider } from './auth';
import { ReviewController } from './controller';
import { DiagnosticsManager } from './diagnostics';
import { ReportPanel } from './reportPanel';
import type { Finding } from './types';

let controller: ReviewController | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel('CodeSage');
  const auth = new DevTokenAuthProvider(context.secrets);
  const diagnostics = new DiagnosticsManager();
  const report = new ReportPanel(context.extensionUri);
  controller = new ReviewController(auth, report, diagnostics, output);

  context.subscriptions.push(
    output,
    diagnostics,
    report,
    vscode.commands.registerCommand('codesage.reviewWorkingTree', () =>
      controller?.run('workingTree')
    ),
    vscode.commands.registerCommand('codesage.reviewStaged', () => controller?.run('staged')),
    vscode.commands.registerCommand('codesage.cancelReview', () => controller?.cancel()),
    vscode.commands.registerCommand('codesage.clearResults', () => controller?.clear()),
    vscode.commands.registerCommand('codesage.showSummary', () => controller?.showSummary()),
    vscode.commands.registerCommand('codesage.openFinding', (target: Finding | string) =>
      controller?.openFinding(target)
    ),
    vscode.commands.registerCommand('codesage.copySuggestion', (target: Finding | string) =>
      controller?.copySuggestion(target)
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
