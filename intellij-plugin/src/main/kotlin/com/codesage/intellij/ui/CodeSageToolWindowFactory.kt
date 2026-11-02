package com.codesage.intellij.ui

import com.codesage.intellij.report.ReportPanel
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.content.ContentFactory
import javax.swing.JEditorPane

/**
 * Hosts the review report (the port of the VS Code webview panel).
 *
 * The content is a JCEF browser rendering the VS Code HTML, or a simplified
 * Swing view when JCEF is unavailable — never an external browser window.
 */
class CodeSageToolWindowFactory : ToolWindowFactory, DumbAware {

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        // A throw here leaves the tool window with no content at all, which looks
        // exactly like "the report is empty"; always add something.
        val component = try {
            project.getService(ReportPanel::class.java).component
        } catch (error: Throwable) {
            JEditorPane().apply {
                isEditable = false
                contentType = "text/html"
                text = "<html><body style='font-family: sans-serif; margin: 12px'>" +
                    "<h2>CodeSage Code Review</h2>" +
                    "<p>The report panel could not be created: " +
                    error.message.orEmpty().let { if (it.isEmpty()) error.javaClass.simpleName else it } +
                    "</p><p>See the <b>CodeSage Output</b> tool window.</p></body></html>"
            }
        }
        val content = ContentFactory.getInstance().createContent(component, "", false)
        content.isCloseable = false
        toolWindow.contentManager.addContent(content)
    }

    override fun shouldBeAvailable(project: Project): Boolean = true
}
