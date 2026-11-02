package com.codesage.intellij.ui

import com.intellij.execution.filters.TextConsoleBuilderFactory
import com.intellij.execution.ui.ConsoleView
import com.intellij.execution.ui.ConsoleViewContentType
import com.intellij.openapi.Disposable
import com.intellij.openapi.components.Service
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindowManager

/**
 * Port of the `CodeSage` output channel (`vscode.window.createOutputChannel`).
 *
 * The channel becomes the `CodeSage Output` tool window instead of a separate
 * output view, but the lines written to it are the same.
 */
@Service(Service.Level.PROJECT)
class ConsoleHolder(private val project: Project) : Disposable {

    val console: ConsoleView =
        TextConsoleBuilderFactory.getInstance().createBuilder(project).console

    fun append(line: String) {
        console.print(line + "\n", ConsoleViewContentType.NORMAL_OUTPUT)
    }

    fun show() {
        ToolWindowManager.getInstance(project)
            .getToolWindow(TOOL_WINDOW_ID)
            ?.show()
    }

    override fun dispose() {
        console.dispose()
    }

    companion object {
        const val TOOL_WINDOW_ID = "CodeSage Output"
    }
}
