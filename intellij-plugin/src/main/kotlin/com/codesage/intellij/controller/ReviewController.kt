package com.codesage.intellij.controller

import com.codesage.intellij.api.ApiError
import com.codesage.intellij.api.CodeSageClient
import com.codesage.intellij.auth.DevTokenAuthProvider
import com.codesage.intellij.diagnostics.FindingsCache
import com.codesage.intellij.git.GitCollector
import com.codesage.intellij.git.GitError
import com.codesage.intellij.git.NoChangesError
import com.codesage.intellij.model.Finding
import com.codesage.intellij.model.GitCollection
import com.codesage.intellij.model.LocalReviewResult
import com.codesage.intellij.model.ReviewScope
import com.codesage.intellij.report.ReportPanel
import com.codesage.intellij.settings.CodeSageConfig
import com.codesage.intellij.settings.CodeSageSettings
import com.codesage.intellij.ui.ConsoleHolder
import com.codesage.intellij.ui.Notifications
import com.codesage.intellij.util.ByteFormat
import com.intellij.codeInsight.daemon.DaemonCodeAnalyzer
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.ModalityState
import com.intellij.openapi.components.Service
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.ide.CopyPasteManager
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProcessCanceledException
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.vfs.LocalFileSystem
import java.awt.datatransfer.StringSelection
import java.net.URI
import java.nio.file.Path
import java.util.concurrent.ConcurrentHashMap

/**
 * Port of `vscode-extension/src/controller.ts`.
 *
 * Command IDs, prompts, confirmations, output lines and failure messages are
 * identical to the VS Code extension. The only platform differences are the
 * progress UI (`Task.Backgroundable` instead of a notification progress) and
 * the dialogs used for the confirmation and the development token.
 */
@Service(Service.Level.PROJECT)
class ReviewController(private val project: Project) {

    private val auth = DevTokenAuthProvider()
    private val findingsById = ConcurrentHashMap<String, Finding>()

    @Volatile
    private var running = false

    @Volatile
    private var result: LocalReviewResult? = null

    @Volatile
    private var activeTask: Task.Backgroundable? = null

    /**
     * `Task` has no `cancel()` of its own, so the running indicator is kept to
     * implement `codesage.cancelReview` (VS Code uses `AbortController`).
     */
    @Volatile
    private var activeIndicator: ProgressIndicator? = null

    private val report: ReportPanel
        get() = project.getService(ReportPanel::class.java)

    private val diagnostics: FindingsCache
        get() = project.getService(FindingsCache::class.java)

    private val output: ConsoleHolder
        get() = project.getService(ConsoleHolder::class.java)

    fun run(scope: ReviewScope? = null) {
        if (running) {
            Notifications.info(project, "A CodeSage review is already running.")
            return
        }

        val config = CodeSageSettings.getInstance().config
        val folder = project.basePath?.let { Path.of(it) }
        if (folder == null) {
            Notifications.error(project, "Open a Git repository folder first.")
            return
        }

        val backendUrl = try {
            URI(config.backendUrl)
        } catch (_: Exception) {
            Notifications.error(project, "CodeSage backend URL is invalid.")
            return
        }
        if (backendUrl.scheme != "http" && backendUrl.scheme != "https") {
            Notifications.error(project, "CodeSage backend URL must use http or https.")
            return
        }

        if (!auth.hasToken()) {
            val choice = Messages.showYesNoDialog(
                project,
                "CodeSage needs the development token before it can review local changes.",
                "CodeSage",
                "Set Development Token",
                "Cancel",
                Messages.getWarningIcon(),
            )
            if (choice == Messages.YES) {
                setDevToken()
            }
            if (!auth.hasToken()) {
                return
            }
        }

        running = true
        val selectedScope = scope ?: config.reviewScope
        startTask(folder, selectedScope, config, backendUrl)
    }

    fun cancel() {
        activeIndicator?.cancel()
    }

    fun clear() {
        cancel()
        diagnostics.clear()
        result = null
        findingsById.clear()
        onEdt { report.clear() }
        ApplicationManager.getApplication().invokeLater {
            DaemonCodeAnalyzer.getInstance(project).restart()
        }
    }

    fun openFinding(id: String) {
        val finding = findingsById[id]
        if (finding == null) {
            Notifications.warning(project, "This finding is no longer available.")
            return
        }
        val snapshotFile = result?.snapshot?.files?.firstOrNull { it.path == finding.filePath }
        if (snapshotFile == null) {
            Notifications.warning(project, "This finding is not part of the current snapshot.")
            return
        }
        val repoRoot = diagnostics.repoRoot ?: project.basePath?.let { Path.of(it) }
        if (repoRoot == null) {
            Notifications.error(project, "Open a Git repository folder first.")
            return
        }
        try {
            val absolute = repoRoot.resolve(finding.filePath).normalize()
            if (!absolute.startsWith(repoRoot)) {
                throw IllegalArgumentException("finding path escapes the repository")
            }
            val virtualFile = LocalFileSystem.getInstance()
                .refreshAndFindFileByPath(absolute.toString())
                ?: throw IllegalArgumentException("file not found")
            val line = maxOf(0, (finding.lineStart ?: 1) - 1)
            OpenFileDescriptor(project, virtualFile, line, 0).navigate(true)
        } catch (_: Exception) {
            Notifications.warning(project, "Could not open ${finding.filePath}.")
        }
    }

    fun copySuggestion(id: String) {
        val finding = findingsById[id]
        if (finding?.suggestion.isNullOrEmpty()) {
            Notifications.info(project, "This finding has no suggestion.")
            return
        }
        CopyPasteManager.getInstance().setContents(StringSelection(finding.suggestion))
        Notifications.info(project, "CodeSage suggestion copied.")
    }

    fun showSummary() {
        if (result == null) {
            Notifications.info(project, "Run a CodeSage review first.")
            return
        }
        report.reveal()
    }

    fun setDevToken() {
        val token = Messages.showPasswordDialog(
            project,
            "Must match LOCAL_REVIEW_DEV_TOKEN on the local backend.",
            "CodeSage development token",
            Messages.getQuestionIcon(),
        )
        if (token == null) {
            return
        }
        if (token.isBlank()) {
            auth.storeToken(null)
            Notifications.info(project, "CodeSage development token cleared.")
            return
        }
        auth.storeToken(token.trim())
        Notifications.info(project, "CodeSage development token saved.")
    }

    fun showOutput() {
        output.show()
    }

    // ------------------------------------------------------------------
    // Review task
    // ------------------------------------------------------------------

    private fun startTask(
        folder: Path,
        scope: ReviewScope,
        config: CodeSageConfig,
        backendUrl: URI,
    ) {
        val task = object : Task.Backgroundable(project, "CodeSage: reviewing local changes", true) {
            override fun run(indicator: ProgressIndicator) {
                activeIndicator = indicator
                try {
                    val collection = GitCollector.collect(
                        folder,
                        GitCollector.Options(
                            scope = scope,
                            includeUntracked = config.includeUntracked,
                            maxFiles = config.maxFiles,
                            maxPayloadBytes = config.maxPayloadBytes,
                        ),
                    )
                    indicator.checkCanceled()

                    if (!confirmSend(collection, backendUrl, scope, config)) {
                        return
                    }

                    onEdt { report.showLoading() }

                    val client = CodeSageClient(config.backendUrl, auth, config.requestTimeoutMs)
                    val request = GitCollector.buildReviewRequest(collection, scope)
                    val reviewed = client.submitDevReview(request, indicator)
                    indicator.checkCanceled()

                    val applyResult = diagnostics.apply(
                        reviewed,
                        Path.of(collection.repoRoot),
                        collection.changedRanges,
                        FindingsCache.Settings(
                            changedLinesOnly = config.changedLinesOnly,
                            includeFileLevel = config.includeFileLevel,
                            showSuggestions = config.showSuggestions,
                        ),
                    )

                    result = reviewed
                    findingsById.clear()
                    for (finding in reviewed.findings) {
                        findingsById[finding.id] = finding
                    }

                    onEdt { report.showResult(reviewed, collection, applyResult) }
                    ApplicationManager.getApplication().invokeLater {
                        DaemonCodeAnalyzer.getInstance(project).restart()
                    }

                    val degraded = reviewed.degradedReasons.joinToString(",").ifEmpty { "none" }
                    output.append(
                        "review completed: files=${collection.files.size} " +
                            "findings=${reviewed.findings.size} degraded=$degraded " +
                            "duration_ms=${reviewed.durationMs}",
                    )
                    Notifications.info(
                        project,
                        "CodeSage found ${reviewed.findings.size} " +
                            "finding${if (reviewed.findings.size == 1) "" else "s"}.",
                    )
                } catch (_: ProcessCanceledException) {
                    throw ProcessCanceledException()
                } catch (_: NoChangesError) {
                    onEdt { report.showError("No reviewable Git changes were found.") }
                    Notifications.info(project, "CodeSage: no reviewable Git changes were found.")
                } catch (error: GitError) {
                    val message = error.message ?: "The CodeSage review failed."
                    onEdt { report.showError(message) }
                    Notifications.error(project, message)
                } catch (error: Throwable) {
                    val message = friendlyError(error)
                    onEdt { report.showError(message) }
                    output.append("review failed: $message")
                    Notifications.error(project, message)
                }
            }

            override fun onCancel() {
                onEdt { report.showCancelled() }
                Notifications.info(project, "CodeSage review cancelled.")
            }

            override fun onFinished() {
                activeTask = null
                activeIndicator = null
                running = false
            }
        }
        activeTask = task
        task.queue()
    }

    private fun confirmSend(
        collection: GitCollection,
        backendUrl: URI,
        scope: ReviewScope,
        config: CodeSageConfig,
    ): Boolean {
        if (!config.confirmBeforeSend) {
            return true
        }
        val excluded = if (collection.excluded.isNotEmpty()) {
            "\nExcluded: ${collection.excluded.size} file(s)."
        } else {
            ""
        }
        val transport = if (backendUrl.scheme == "https") "HTTPS" else "unencrypted HTTP"
        val warning = if (isLoopbackUrl(backendUrl)) {
            ""
        } else {
            "\n\nThis is not a loopback backend. Source code leaves this machine."
        }
        val detail = "Backend: ${config.backendUrl}\n" +
            "Mode: development token (no user/org context)\n" +
            "Scope: ${scope.wire}\n" +
            "Files: ${collection.files.size} (${ByteFormat.format(collection.totalBytes.toLong())})\n" +
            "Transport: $transport$excluded$warning\n\n" +
            "The selected source files and diff will be sent to CodeSage for review."

        var confirmed = false
        onEdt {
            confirmed = Messages.showYesNoDialog(
                project,
                detail,
                "Send local source changes to CodeSage?",
                "Send",
                "Cancel",
                Messages.getWarningIcon(),
            ) == Messages.YES
        }
        return confirmed
    }

    private fun friendlyError(error: Throwable): String {
        if (error is ApiError) {
            return when (error.status) {
                404 -> "CodeSage dev mode is not enabled on this backend (or the URL is wrong)."
                401 -> "The CodeSage development token is invalid. Set it again and retry."
                413 -> "The review payload is too large. Reduce the changed files and retry."
                504 -> "The CodeSage review timed out. Try a smaller set of changes."
                else -> error.message ?: "The CodeSage review failed."
            }
        }
        return error.message ?: "The CodeSage review failed."
    }

    private fun isLoopbackUrl(value: URI): Boolean =
        value.host in setOf("127.0.0.1", "::1", "localhost")

    private fun <T> onEdt(action: () -> T): T? {
        if (ApplicationManager.getApplication().isDispatchThread) {
            return action()
        }
        var outcome: T? = null
        ApplicationManager.getApplication()
            .invokeAndWait({ outcome = action() }, ModalityState.defaultModalityState())
        return outcome
    }
}
