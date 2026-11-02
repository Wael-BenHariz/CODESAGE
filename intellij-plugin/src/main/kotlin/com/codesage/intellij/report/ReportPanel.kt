package com.codesage.intellij.report

import com.codesage.intellij.controller.ReviewController
import com.codesage.intellij.diagnostics.FindingsCache
import com.codesage.intellij.model.GitCollection
import com.codesage.intellij.model.LocalReviewResult
import com.codesage.intellij.ui.ConsoleHolder
import com.codesage.intellij.util.UriEncode
import com.google.gson.Gson
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBScrollPane
import java.awt.BorderLayout
import javax.swing.JComponent
import javax.swing.JEditorPane
import javax.swing.JPanel
import javax.swing.ScrollPaneConstants
import javax.swing.event.HyperlinkEvent

/**
 * Port of `vscode-extension/src/reportPanel.ts`.
 *
 * State machine, strings and reuse semantics match the VS Code webview panel:
 * one report for the project, closing it keeps the results, and
 * "Show Review Report" re-renders from the cached state.
 *
 * The report lives in the **CodeSage tool window** (no editor tab and no
 * external browser). It renders the byte-identical VS Code HTML through JCEF;
 * when JCEF is unavailable the same report is rendered as a simplified HTML 3.2
 * document in a `JEditorPane`, so the result is still shown inside the IDE.
 *
 * This class must never reference a JCEF type: see [JcefReport].
 */
@Service(Service.Level.PROJECT)
class ReportPanel(private val project: Project) : Disposable {

    private var state: ReportViewState? = null

    private val root = object : JPanel(BorderLayout()) {
        override fun addNotify() {
            super.addNotify()
            // JCEF can drop its first loadHtml() if it is called before the
            // browser component is attached to a visible Swing hierarchy. The
            // tool window creates its content lazily, so the initial render in
            // initialise() can happen too early. Re-send the latest state once
            // the panel is actually attached.
            ApplicationManager.getApplication().invokeLater {
                if (!project.isDisposed) {
                    render()
                }
            }
        }
    }
    private var browser: ReportBrowser? = null
    private var fallbackPane: JEditorPane? = null
    private var initialised = false
    private var renderFailed = false

    /**
     * Lazily built content component, created by the tool window factory on the
     * EDT. It never throws: a broken report must not leave the tool window empty
     * (that is how a missing JCEF module used to hide every review result).
     */
    val component: JComponent
        get() {
            try {
                initialise()
            } catch (error: Throwable) {
                initialised = true
                logToOutput(
                    "report panel failed to initialise: " +
                        (error.message ?: error.javaClass.simpleName),
                )
                showFatal(error)
            }
            return root
        }

    private fun initialise() {
        if (initialised) {
            return
        }
        // Any JCEF problem — module missing on this IDE build, JCEF disabled, or
        // the native browser failing to start — must leave a readable report.
        val created = try {
            JcefReport.create(
                onCommand = ::handleCommand,
                onLoadFailure = ::onBrowserLoadFailure,
            )
        } catch (_: Throwable) {
            null
        }
        if (created != null) {
            initialised = true
            browser = created
            root.add(created.component, BorderLayout.CENTER)
            render()
            return
        }
        initialised = true
        val status = try {
            JcefReport.status()
        } catch (_: Throwable) {
            "not installed"
        }
        logToOutput("JCEF is $status — showing the simplified report view")
        useSimplifiedRenderer()
    }

    private fun useSimplifiedRenderer() {
        if (fallbackPane != null) {
            return
        }
        browser?.dispose()
        browser = null
        val pane = JEditorPane()
        pane.isEditable = false
        pane.contentType = "text/html"
        pane.putClientProperty(JEditorPane.HONOR_DISPLAY_PROPERTIES, true)
        pane.addHyperlinkListener { event ->
            if (event.eventType == HyperlinkEvent.EventType.ACTIVATED) {
                // `command:` is not a registered protocol, so `event.url` is null and the
                // raw href only survives in `description`.
                val url = event.url?.toString() ?: event.description
                if (url != null && url.startsWith("command:")) {
                    handleCommand(url)
                }
            }
        }
        val scroll = JBScrollPane(
            pane,
            ScrollPaneConstants.VERTICAL_SCROLLBAR_AS_NEEDED,
            ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER,
        )
        fallbackPane = pane
        root.removeAll()
        root.add(
            JBLabel("The embedded browser (JCEF) is unavailable — showing a simplified report."),
            BorderLayout.NORTH,
        )
        root.add(scroll, BorderLayout.CENTER)
        render()
        root.revalidate()
        root.repaint()
    }

    /** Last-resort view when even the Swing renderer cannot be built. */
    private fun showFatal(error: Throwable) {
        val pane = JEditorPane()
        pane.isEditable = false
        pane.contentType = "text/html"
        pane.text = "<html><body style='font-family: sans-serif; margin: 12px'>" +
            "<h2>CodeSage Code Review</h2>" +
            "<p>The report could not be displayed: " +
            Renderer.escapeHtml(error.message ?: error.javaClass.simpleName) +
            "</p><p>See the <b>CodeSage Output</b> tool window for details.</p>" +
            "</body></html>"
        root.removeAll()
        fallbackPane = pane
        root.add(JBScrollPane(pane), BorderLayout.CENTER)
        root.revalidate()
        root.repaint()
    }

    fun showLoading(message: String = LOADING_MESSAGE) {
        show(ReportViewState.Loading(message))
    }

    fun showResult(
        result: LocalReviewResult,
        collection: GitCollection,
        diagnostics: FindingsCache.ApplyResult,
    ) {
        show(
            ReportViewState.Result(
                result = result,
                collection = collection,
                diagnostics = DiagnosticViewState(diagnostics.shown, diagnostics.reasons),
            ),
        )
    }

    fun showError(message: String) {
        show(ReportViewState.Error(message))
    }

    fun showCancelled() {
        show(ReportViewState.Cancelled)
    }

    fun clear() {
        state = null
        ApplicationManager.getApplication().invokeLater {
            render()
            closeToolWindow()
        }
    }

    /** "Show Review Report": reopen the tool window with the cached state. */
    fun reveal() {
        ApplicationManager.getApplication().invokeLater {
            activate()
            render()
        }
    }

    private fun show(next: ReportViewState) {
        state = next
        ApplicationManager.getApplication().invokeLater {
            // Showing the window lets the platform build the content, and loading
            // the HTML only after the browser is attached avoids a blank page on
            // the first review.
            ensureContentCreated()
            activate()
            render()
        }
    }

    private fun ensureContentCreated() {
        // Touching the component makes the tool window factory build it.
        component
    }

    private fun activate() {
        val toolWindow = ToolWindowManager.getInstance(project)
            .getToolWindow(TOOL_WINDOW_ID) ?: return
        toolWindow.show()
        toolWindow.activate(null, false)
    }

    private fun closeToolWindow() {
        ToolWindowManager.getInstance(project).getToolWindow(TOOL_WINDOW_ID)?.hide()
    }

    private fun render() {
        val current = state
        val html = try {
            when (current) {
                null -> Renderer.renderIdleHtml()
                else -> Renderer.renderReportHtml(current)
            }
        } catch (error: Throwable) {
            logToOutput("report rendering failed: ${error.message ?: error.javaClass.simpleName}")
            useSimplifiedRenderer()
            return
        }
        val created = browser
        if (created != null && !renderFailed) {
            try {
                created.loadHtml(html)
                return
            } catch (error: Throwable) {
                onBrowserLoadFailure(error.message ?: error.javaClass.simpleName)
                return
            }
        }
        val pane = fallbackPane ?: return
        val source = try {
            when (current) {
                null -> Renderer.renderIdleHtml()
                else -> Renderer.renderFallbackHtml(current)
            }
        } catch (error: Throwable) {
            logToOutput("simplified report rendering failed: ${error.message ?: error.javaClass.simpleName}")
            "<html><body><h2>CodeSage Code Review</h2><p>" +
                "The report could not be rendered. See the CodeSage Output tool window.</p></body></html>"
        }
        pane.text = source
        pane.caretPosition = 0
    }

    private fun onBrowserLoadFailure(message: String) {
        ApplicationManager.getApplication().invokeLater {
            if (renderFailed) {
                return@invokeLater
            }
            renderFailed = true
            logToOutput(
                "embedded browser could not load the report ($message) — " +
                    "showing the simplified report view",
            )
            useSimplifiedRenderer()
        }
    }

    /** One line in the output channel: report failures must not be silent. */
    private fun logToOutput(line: String) {
        try {
            project.getService(ConsoleHolder::class.java).append(line)
        } catch (_: Throwable) {
            // Never let logging break the report.
        }
    }

    /** Handles a `command:codesage.*` link coming from the report. */
    fun handleCommand(url: String) {
        val parsed = parseCommand(url) ?: return
        val (command, args) = parsed
        val target = args.firstOrNull()
        val controller = project.getService(ReviewController::class.java)
        when (command) {
            "codesage.openFinding" -> if (target != null) controller.openFinding(target)
            "codesage.copySuggestion" -> if (target != null) controller.copySuggestion(target)
        }
    }

    private fun parseCommand(url: String): Pair<String, List<String>>? {
        if (!url.startsWith("command:")) {
            return null
        }
        val rest = url.removePrefix("command:")
        val queryIndex = rest.indexOf('?')
        val name = if (queryIndex >= 0) rest.substring(0, queryIndex) else rest
        val query = if (queryIndex >= 0) rest.substring(queryIndex + 1) else ""
        val args = if (query.isEmpty()) {
            emptyList()
        } else {
            try {
                val decoded = UriEncode.decode(query)
                Gson().fromJson(decoded, Array<String>::class.java)?.toList() ?: emptyList()
            } catch (_: Exception) {
                emptyList()
            }
        }
        return name to args
    }

    override fun dispose() {
        browser?.dispose()
        browser = null
    }

    companion object {
        const val TOOL_WINDOW_ID = "CodeSage"
        const val LOADING_MESSAGE = "Running AI code review."
    }
}
