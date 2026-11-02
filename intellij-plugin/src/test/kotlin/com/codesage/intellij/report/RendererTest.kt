package com.codesage.intellij.report

import com.codesage.intellij.model.ExcludedFile
import com.codesage.intellij.model.Finding
import com.codesage.intellij.model.FindingSource
import com.codesage.intellij.model.GitCollection
import com.codesage.intellij.model.LocalReviewResult
import com.codesage.intellij.model.ReviewSnapshot
import com.codesage.intellij.model.ReviewStatistics
import com.codesage.intellij.model.Severity
import com.codesage.intellij.model.SnapshotFile
import com.codesage.intellij.model.UnifiedSeverity
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Port of the assertions in `vscode-extension/test/render.test.ts`. */
class RendererTest {

    @Test
    fun `renders the loading state`() {
        val html = Renderer.renderReportHtml(ReportViewState.Loading("Running AI code review."))
        assertTrue(html.contains("CodeSage Code Review"))
        assertTrue(html.contains("Reviewing…"))
        assertTrue(html.contains("Running AI code review."))
        assertTrue(html.contains("Waiting for the review to finish…"))
    }

    @Test
    fun `renders the error state`() {
        val html = Renderer.renderReportHtml(ReportViewState.Error("Backend unreachable."))
        assertTrue(html.contains("Review failed"))
        assertTrue(html.contains("Backend unreachable."))
        assertTrue(html.contains("status-error"))
    }

    @Test
    fun `renders summary, findings, severity and command links`() {
        val html = Renderer.renderReportHtml(
            ReportViewState.Result(
                result = makeResult(),
                collection = makeCollection(),
                diagnostics = DiagnosticViewState(setOf("finding-1"), emptyMap()),
            ),
        )
        assertTrue(html.contains("Two problems were found in the changed code."))
        assertTrue(html.contains("Unsanitized input reaches the query builder."))
        assertTrue(html.contains("src/app.ts"))
        assertTrue(html.contains("sev-high"))
        assertTrue(html.contains("Use a parameterized query."))
        assertTrue(html.contains("also detected by sonarqube"))
        assertTrue(html.contains("command:codesage.openFinding"))
        assertTrue(html.contains("command:codesage.copySuggestion"))
        assertTrue(html.contains("command:codesage.openFinding?"))
        assertTrue(html.contains("2 findings · 3 files"))
        assertTrue(html.contains("Excluded files"))
        assertTrue(html.contains("vendor/big.js"))
    }

    @Test
    fun `escapes untrusted content in findings`() {
        val result = makeResult()
        val escaped = result.findings[0].copy(message = "<img src=x onerror=\"alert(1)\">")
        val html = Renderer.renderReportHtml(
            ReportViewState.Result(
                result = result.copy(findings = listOf(escaped, result.findings[1])),
                collection = makeCollection(),
                diagnostics = null,
            ),
        )
        assertFalse(html.contains("<img src=x"))
        assertTrue(html.contains("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"))
    }

    @Test
    fun `shows the empty state when there are no findings`() {
        val html = Renderer.renderReportHtml(
            ReportViewState.Result(
                result = makeResult().copy(findings = emptyList(), degradedReasons = emptyList()),
                collection = null,
                diagnostics = null,
            ),
        )
        assertTrue(html.contains("No specific issues returned."))
        assertTrue(html.contains("0 findings"))
        assertFalse(html.contains("Full Report"))
        assertFalse(html.contains("Limited coverage"))
    }

    @Test
    fun `notes findings that are not shown inline`() {
        val html = Renderer.renderReportHtml(
            ReportViewState.Result(
                result = makeResult().copy(degradedReasons = emptyList()),
                collection = null,
                diagnostics = DiagnosticViewState(
                    shown = emptySet(),
                    reasons = mapOf("finding-1" to "line_outside_diff"),
                ),
            ),
        )
        assertTrue(html.contains("Not shown inline: line is outside the reviewed diff"))
    }

    @Test
    fun `renders headings, lists and inline formatting`() {
        val html = Renderer.renderMarkdown(
            listOf(
                "## Executive Summary",
                "- The scan found **hard-coded credentials** in `test.java`.",
                "",
                "### Findings by File",
                "1. First item",
                "2. Second item with *emphasis*",
            ).joinToString("\n"),
        )
        assertTrue(html.contains("<h4>Executive Summary</h4>"))
        assertTrue(html.contains("<h5>Findings by File</h5>"))
        assertTrue(
            html.contains(
                "<ul><li>The scan found <strong>hard-coded credentials</strong> in " +
                    "<code>test.java</code>.</li></ul>",
            ),
        )
        assertTrue(
            html.contains("<ol><li>First item</li><li>Second item with <em>emphasis</em></li></ol>"),
        )
        assertFalse(html.contains("##"))
    }

    @Test
    fun `never lets untrusted summary text inject markup`() {
        val html = Renderer.renderMarkdown("<img src=x onerror=\"alert(1)\">")
        assertFalse(html.contains("<img"))
        assertTrue(html.contains("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"))
    }

    @Test
    fun `keeps identifier underscores literal`() {
        val html = Renderer.renderMarkdown("Fields `SECRET_KEY` and DB_PASS are hard-coded.")
        assertTrue(html.contains("<code>SECRET_KEY</code>"))
        assertTrue(html.contains("DB_PASS"))
        assertFalse(html.contains("<em>"))
    }

    @Test
    fun `idle panel explains how to start a review`() {
        val html = Renderer.renderIdleHtml()
        assertTrue(html.contains("CodeSage Code Review"))
        assertTrue(html.contains("CodeSage: Review Local Changes"))
        assertTrue(html.contains("CodeSage: Review Staged Changes"))
    }

    @Test
    fun `simplified panel shows the same report without css layout`() {
        val html = Renderer.renderFallbackHtml(
            ReportViewState.Result(
                result = makeResult(),
                collection = makeCollection(),
                diagnostics = DiagnosticViewState(
                    shown = setOf("finding-1"),
                    reasons = mapOf("finding-2" to "line_missing"),
                ),
            ),
        )
        assertTrue(html.contains("Unsanitized input reaches the query builder."))
        assertTrue(html.contains("src/app.ts"))
        assertTrue(html.contains("HIGH"))
        assertTrue(html.contains("Use a parameterized query."))
        assertTrue(html.contains("also detected by sonarqube"))
        assertTrue(html.contains("Not shown inline: finding has no line number"))
        assertTrue(html.contains("vendor/big.js"))
        assertTrue(html.contains("2 findings · 3 files"))
        assertFalse(html.contains("sev-high"))
        assertFalse(html.contains("class=\"finding\""))
    }

    private fun makeResult(): LocalReviewResult = LocalReviewResult(
        schemaVersion = 1,
        snapshot = ReviewSnapshot(
            id = "snapshot-1",
            baseRevision = "abc",
            headSha = "def",
            branch = "main",
            capturedAt = "2026-10-24T00:00:00Z",
            files = listOf(
                SnapshotFile(
                    path = "src/app.ts",
                    status = com.codesage.intellij.model.FileStatus.MODIFIED,
                    contentSha256 = "sha",
                    size = 120,
                ),
            ),
        ),
        summary = "Two problems were found in the changed code.",
        overallSeverity = "high",
        statistics = ReviewStatistics(
            filesReviewed = 3,
            issuesFound = 2,
            bySeverity = mapOf("high" to 1, "low" to 1),
            byCategory = emptyMap(),
        ),
        findings = listOf(
            Finding(
                id = "finding-1",
                source = FindingSource.STATIC,
                nativeSeverity = "high",
                severity = UnifiedSeverity.HIGH,
                filePath = "src/app.ts",
                lineStart = 12,
                lineEnd = 12,
                message = "Unsanitized input reaches the query builder.",
                body = "The request value is concatenated into SQL.",
                suggestion = "Use a parameterized query.",
                snippet = "db.query(`... \${req.query.id}`)",
                tool = "semgrep",
                ruleId = "sql-injection",
                category = "security",
                alsoDetectedBy = listOf("sonarqube"),
            ),
            Finding(
                id = "finding-2",
                source = FindingSource.AGENT,
                nativeSeverity = "suggestion",
                severity = Severity.normalize("suggestion", FindingSource.AGENT),
                filePath = "src/util.ts",
                lineStart = null,
                lineEnd = null,
                message = "Consider extracting this helper.",
                body = "Consider extracting this helper.",
                suggestion = null,
                snippet = null,
                tool = null,
                ruleId = null,
                category = "style",
                alsoDetectedBy = emptyList(),
            ),
        ),
        degradedReasons = listOf("semgrep_failed"),
        agentFailures = listOf("PerformanceAgent"),
        diffTruncated = false,
        durationMs = 1234,
    )

    private fun makeCollection(): GitCollection = GitCollection(
        repoRoot = "/repo",
        snapshot = makeResult().snapshot,
        diff = "",
        diffTruncated = false,
        changedRanges = emptyMap(),
        files = emptyList(),
        excluded = listOf(ExcludedFile("vendor/big.js", "larger than 524288 bytes")),
        totalBytes = 0,
    )
}
