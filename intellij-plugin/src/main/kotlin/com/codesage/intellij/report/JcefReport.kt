package com.codesage.intellij.report

import com.intellij.openapi.application.ApplicationManager
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import org.cef.browser.CefBrowser
import org.cef.browser.CefFrame
import org.cef.handler.CefLoadHandler
import org.cef.handler.CefLoadHandlerAdapter
import org.cef.handler.CefRequestHandlerAdapter
import org.cef.network.CefRequest
import javax.swing.JComponent

/** The embedded report view, without exposing JCEF types to [ReportPanel]. */
interface ReportBrowser {
    val component: JComponent

    fun loadHtml(html: String)

    fun dispose()
}

/**
 * The single place that touches JCEF classes.
 *
 * Until build 261 the JCEF UI lived in the platform; from build 262 (IntelliJ
 * 2026.2) it is a separate bundled plugin, `com.intellij.modules.jcef`. The
 * plugin dependency on it is **optional**, so an IDE without the module (or
 * with JCEF disabled) must degrade to the Swing view instead of failing to
 * build the tool window — see `PARITY.md` D17.
 *
 * Keeping every JCEF reference in this file means a missing module surfaces
 * here as a caught `LinkageError`, not as a `NoClassDefFoundError` thrown from
 * `ReportPanel.initialise` while the platform is creating the tool window
 * content (which leaves the panel permanently empty).
 */
object JcefReport {

    /** Human-readable JCEF state for the output channel. */
    fun status(): String = try {
        if (JBCefApp.isSupported()) "available" else "disabled"
    } catch (_: Throwable) {
        "not installed"
    }

    /**
     * @param onCommand invoked with a `command:` URL clicked in the report.
     * @param onLoadFailure invoked with a description when a page fails to load.
     * @return the browser, or null when JCEF cannot be used.
     */
    fun create(
        onCommand: (String) -> Unit,
        onLoadFailure: (String) -> Unit,
    ): ReportBrowser? {
        val browser = try {
            if (!JBCefApp.isSupported()) {
                return null
            }
            JBCefBrowser()
        } catch (_: Throwable) {
            return null
        }

        try {
            browser.jbCefClient.addRequestHandler(
                CommandLinkHandler(onCommand),
                browser.cefBrowser,
            )
        } catch (_: Throwable) {
            // Older CEF builds may reject the handler; the report still renders.
        }
        try {
            browser.jbCefClient.addLoadHandler(
                object : CefLoadHandlerAdapter() {
                    override fun onLoadError(
                        ignored: CefBrowser,
                        frame: CefFrame,
                        errorCode: CefLoadHandler.ErrorCode,
                        errorText: String,
                        failedUrl: String,
                    ) {
                        if (frame.isMain) {
                            onLoadFailure("$errorText ($errorCode)")
                        }
                    }
                },
                browser.cefBrowser,
            )
        } catch (_: Throwable) {
            // Load diagnostics are optional.
        }

        return object : ReportBrowser {
            override val component: JComponent get() = browser.component

            override fun loadHtml(html: String) {
                browser.loadHTML(html)
            }

            override fun dispose() {
                browser.dispose()
            }
        }
    }

    /** CEF intercepts `command:` navigations, keeping the HTML and CSP unchanged. */
    private class CommandLinkHandler(private val onCommand: (String) -> Unit) :
        CefRequestHandlerAdapter() {

        override fun onBeforeBrowse(
            browser: CefBrowser,
            frame: CefFrame,
            request: CefRequest,
            userGesture: Boolean,
            isRedirect: Boolean,
        ): Boolean {
            val url = request.url
            if (url != null && url.startsWith("command:")) {
                ApplicationManager.getApplication().invokeLater { onCommand(url) }
                return true
            }
            return false
        }
    }
}
