package com.codesage.intellij.report

import com.codesage.intellij.api.ApiMapping
import com.codesage.intellij.api.CodeSageGson
import com.codesage.intellij.api.ResultDto
import com.codesage.intellij.model.UnifiedSeverity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Renders a **real** `POST /api/v1/local-reviews/dev` response captured from the
 * local backend (2 files, 8 static findings from SonarQube + Semgrep).
 *
 * The parity goldens are hand-built fixtures; this one guards the path the IDE
 * actually takes: backend JSON -> Gson DTOs -> `ApiMapping` -> renderer.
 */
class BackendSampleTest {

    private val json: String =
        javaClass.getResourceAsStream("/realsample/local-review-result.json")!!
            .bufferedReader()
            .use { it.readText() }

    private fun result(): com.codesage.intellij.model.LocalReviewResult =
        ApiMapping.toModel(CodeSageGson.fromJson(json, ResultDto::class.java))

    private fun state(): ReportViewState.Result {
        val result = result()
        return ReportViewState.Result(result = result, collection = null, diagnostics = null)
    }

    @Test
    fun `maps every finding from the backend response`() {
        val result = result()
        assertEquals(8, result.findings.size)
        assertEquals(2, result.statistics.filesReviewed)
        assertTrue(result.findings.all { it.filePath.isNotEmpty() })
        assertTrue(result.findings.all { it.message.isNotEmpty() })
        assertTrue(result.findings.any { it.severity == UnifiedSeverity.HIGH })
        assertTrue(result.findings.any { it.severity == UnifiedSeverity.MEDIUM })
        assertTrue(result.findings.any { it.lineStart != null })
        assertEquals(emptyList<String>(), result.degradedReasons)
    }

    @Test
    fun `report lists the findings of a real response`() {
        val html = Renderer.renderReportHtml(state())
        val result = result()

        assertTrue(html.contains("8 findings · 2 files"))
        for (finding in result.findings) {
            assertTrue(
                "missing finding ${finding.id} (${finding.message})",
                html.contains(Renderer.escapeHtml(finding.message)),
            )
            // The id only appears inside the URI-encoded `command:` href.
            val href = Renderer.escapeHtml(
                Renderer.commandUri("codesage.openFinding", finding.id),
            )
            assertTrue("missing link for ${finding.id}", html.contains(href))
        }
        assertTrue(html.contains("src/demo.js"))
        assertTrue(html.contains("src/demo.py"))
        assertFalse(html.contains("No specific issues returned."))
    }

    @Test
    fun `simplified report lists the findings of a real response`() {
        val html = Renderer.renderFallbackHtml(state())
        val result = result()

        assertTrue(html.contains("8 findings · 2 files"))
        for (finding in result.findings) {
            assertTrue(
                "missing finding ${finding.id} in the simplified view",
                html.contains(Renderer.escapeHtml(finding.message)),
            )
        }
        assertTrue(html.contains("src/demo.js"))
        assertTrue(html.contains("command:codesage.openFinding"))
        assertFalse(html.contains("No specific issues returned."))
    }
}
