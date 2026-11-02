package com.codesage.intellij.ui

import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.content.ContentFactory

/** Hosts the console that replaces the VS Code output channel. */
class CodeSageOutputToolWindowFactory : ToolWindowFactory, DumbAware {

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val holder = project.getService(ConsoleHolder::class.java)
        val content = ContentFactory.getInstance().createContent(holder.console.component, "", false)
        content.isCloseable = false
        toolWindow.contentManager.addContent(content)
    }

    override fun shouldBeAvailable(project: Project): Boolean = true
}
