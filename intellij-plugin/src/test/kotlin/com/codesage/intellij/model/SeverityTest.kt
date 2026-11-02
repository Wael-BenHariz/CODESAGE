package com.codesage.intellij.model

import org.junit.Assert.assertEquals
import org.junit.Test

/** Port of `vscode-extension/test/severity.test.ts`. */
class SeverityTest {

    @Test
    fun `keeps the static five-level scale`() {
        assertEquals(UnifiedSeverity.CRITICAL, Severity.normalize("critical", FindingSource.STATIC))
        assertEquals(UnifiedSeverity.HIGH, Severity.normalize("high", FindingSource.STATIC))
        assertEquals(UnifiedSeverity.MEDIUM, Severity.normalize("medium", FindingSource.STATIC))
        assertEquals(UnifiedSeverity.LOW, Severity.normalize("low", FindingSource.STATIC))
        assertEquals(UnifiedSeverity.INFO, Severity.normalize("info", FindingSource.STATIC))
    }

    @Test
    fun `maps the agent vocabulary honestly`() {
        assertEquals(UnifiedSeverity.LOW, Severity.normalize("suggestion", FindingSource.AGENT))
        assertEquals(UnifiedSeverity.INFO, Severity.normalize("info", FindingSource.AGENT))
        assertEquals(UnifiedSeverity.MEDIUM, Severity.normalize("warning", FindingSource.AGENT))
        assertEquals(UnifiedSeverity.HIGH, Severity.normalize("error", FindingSource.AGENT))
    }

    @Test
    fun `falls back to info for unknown values`() {
        assertEquals(UnifiedSeverity.INFO, Severity.normalize("unknown", FindingSource.STATIC))
        assertEquals(UnifiedSeverity.INFO, Severity.normalize(null, FindingSource.AGENT))
    }

    @Test
    fun `overall severity matches the frontend review badge mapping`() {
        assertEquals(UnifiedSeverity.CRITICAL, Severity.overall("error"))
        assertEquals(UnifiedSeverity.MEDIUM, Severity.overall("warning"))
        assertEquals(UnifiedSeverity.LOW, Severity.overall("suggestion"))
        assertEquals(UnifiedSeverity.INFO, Severity.overall("info"))
    }

    @Test
    fun `sorts by severity, file, then line`() {
        val findings = listOf(
            finding("low", "b.ts", 1),
            finding("critical", "z.ts", 9),
            finding("high", "a.ts", 3),
            finding("high", "a.ts", 1),
        ).sortedWith { left, right -> Severity.compareFindings(left, right) }

        assertEquals(
            listOf("critical:z.ts:9", "high:a.ts:1", "high:a.ts:3", "low:b.ts:1"),
            findings.map { "${it.severity.wire}:${it.filePath}:${it.lineStart}" },
        )
    }

    private fun finding(severity: String, path: String, line: Int): Finding = Finding(
        id = "$path:$line",
        source = FindingSource.STATIC,
        nativeSeverity = severity,
        severity = Severity.normalize(severity, FindingSource.STATIC),
        filePath = path,
        lineStart = line,
        lineEnd = line,
        message = "message",
        body = "message",
        suggestion = null,
        snippet = null,
        tool = null,
        ruleId = null,
        category = null,
    )
}
