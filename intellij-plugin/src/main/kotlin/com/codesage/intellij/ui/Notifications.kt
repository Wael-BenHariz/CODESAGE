package com.codesage.intellij.ui

import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.project.Project

/**
 * Port of the `vscode.window.show{Information,Warning,Error}Message` calls in
 * `vscode-extension/src/controller.ts`.
 *
 * Notifications use the `CodeSage` group declared in `plugin.xml`; the text is
 * identical to the VS Code strings so users see the same wording in both IDEs.
 */
object Notifications {
    private const val GROUP_ID = "CodeSage"

    fun info(project: Project?, content: String) {
        notify(project, content, NotificationType.INFORMATION)
    }

    fun warning(project: Project?, content: String) {
        notify(project, content, NotificationType.WARNING)
    }

    fun error(project: Project?, content: String) {
        notify(project, content, NotificationType.ERROR)
    }

    private fun notify(project: Project?, content: String, type: NotificationType) {
        NotificationGroupManager.getInstance()
            .getNotificationGroup(GROUP_ID)
            .createNotification("CodeSage", content, type)
            .notify(project)
    }
}
