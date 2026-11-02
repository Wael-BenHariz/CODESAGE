package com.codesage.intellij.actions

import com.codesage.intellij.controller.ReviewController
import com.codesage.intellij.model.ReviewScope
import com.codesage.intellij.settings.CodeSageConfigurable
import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.options.ShowSettingsUtil
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project

/**
 * The nine commands contributed by `vscode-extension/package.json`
 * (`codesage.reviewWorkingTree` … `codesage.openSettings`).
 *
 * `codesage.openFinding` and `codesage.copySuggestion` are invoked from the
 * report through `command:` links, so they have no menu entry, exactly like
 * the `commandPalette` `when: false` entries in VS Code.
 */
private fun controller(event: AnActionEvent): ReviewController? =
    event.project?.getService(ReviewController::class.java)

class ReviewWorkingTreeAction : AnAction(
    "CodeSage: Review Local Changes",
    "Review local working-tree changes with CodeSage",
    AllIcons.Actions.Execute,
), DumbAware {
    override fun actionPerformed(event: AnActionEvent) {
        controller(event)?.run(ReviewScope.WORKING_TREE)
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT
}

class ReviewStagedAction : AnAction(
    "CodeSage: Review Staged Changes",
    "Review staged changes with CodeSage",
    AllIcons.Actions.Checked,
), DumbAware {
    override fun actionPerformed(event: AnActionEvent) {
        controller(event)?.run(ReviewScope.STAGED)
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT
}

class CancelReviewAction : AnAction(
    "CodeSage: Cancel Review",
    "Cancel the running CodeSage review",
    AllIcons.Actions.Suspend,
), DumbAware {
    override fun actionPerformed(event: AnActionEvent) {
        controller(event)?.cancel()
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT
}

class ClearResultsAction : AnAction(
    "CodeSage: Clear Results",
    "Clear CodeSage findings and the review report",
    AllIcons.Actions.GC,
), DumbAware {
    override fun actionPerformed(event: AnActionEvent) {
        controller(event)?.clear()
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT
}

class ShowReportAction : AnAction(
    "CodeSage: Show Review Report",
    "Show the CodeSage review report",
    AllIcons.Actions.Preview,
), DumbAware {
    override fun actionPerformed(event: AnActionEvent) {
        controller(event)?.showSummary()
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT
}

class SetDevTokenAction : AnAction(
    "CodeSage: Set Development Token",
    "Store the development token used by the local CodeSage backend",
    AllIcons.General.User,
), DumbAware {
    override fun actionPerformed(event: AnActionEvent) {
        controller(event)?.setDevToken()
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT
}

class ShowOutputAction : AnAction(
    "CodeSage: Show Output",
    "Show the CodeSage output",
    AllIcons.Actions.Show,
), DumbAware {
    override fun actionPerformed(event: AnActionEvent) {
        controller(event)?.showOutput()
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT
}

class OpenSettingsAction : AnAction(
    "CodeSage: Open Settings",
    "Open the CodeSage settings page",
    AllIcons.General.Settings,
), DumbAware {
    override fun actionPerformed(event: AnActionEvent) {
        val project: Project = event.project ?: return
        ShowSettingsUtil.getInstance().showSettingsDialog(project, CodeSageConfigurable::class.java)
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT
}
