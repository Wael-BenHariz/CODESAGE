package com.codesage.intellij.api

import com.codesage.intellij.model.FileStatus
import com.codesage.intellij.model.FindingSource
import com.codesage.intellij.model.LocalReviewRequest
import com.codesage.intellij.model.ReviewSnapshot
import com.codesage.intellij.model.SnapshotFile
import com.codesage.intellij.model.SourceFile
import com.codesage.intellij.model.UnifiedSeverity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Verifies the JSON contract against `vscode-extension/src/api.ts`. */
class ApiMappingTest {

    private val gson = CodeSageGson

    @Test
    fun `serializes the request with snake_case keys`() {
        val request = LocalReviewRequest(
            schemaVersion = 1,
            snapshot = ReviewSnapshot(
                id = "snapshot-1",
                baseRevision = "abc",
                headSha = "def",
                branch = "main",
                capturedAt = "2026-10-24T00:00:00.000Z",
                files = listOf(
                    SnapshotFile(
                        path = "src/a.ts",
                        oldPath = "src/old.ts",
                        status = FileStatus.RENAMED,
                        contentSha256 = "sha",
                        size = 10,
                    ),
                ),
            ),
            title = "Local changes on main",
            description = "CodeSage local review (workingTree)",
            diff = "diff",
            language = "typescript",
            files = listOf(
                SourceFile(
                    path = "src/a.ts",
                    status = FileStatus.MODIFIED,
                    content = "const a = 1;",
                    contentSha256 = "sha",
                ),
            ),
        )

        val json = gson.toJson(ApiMapping.toDto(request))
        assertTrue(json.contains("\"schema_version\":1"))
        assertTrue(json.contains("\"base_revision\":\"abc\""))
        assertTrue(json.contains("\"head_sha\":\"def\""))
        assertTrue(json.contains("\"captured_at\":\"2026-10-24T00:00:00.000Z\""))
        assertTrue(json.contains("\"old_path\":\"src/old.ts\""))
        assertTrue(json.contains("\"content_sha256\":\"sha\""))
        assertTrue(json.contains("\"status\":\"renamed\""))
    }

    @Test
    fun `keeps null fields and markup like JSON stringify`() {
        val request = LocalReviewRequest(
            schemaVersion = 1,
            snapshot = ReviewSnapshot(
                id = "snapshot-1",
                baseRevision = null,
                headSha = "def",
                branch = null,
                capturedAt = "2026-10-24T00:00:00.000Z",
                files = listOf(
                    SnapshotFile(
                        path = "a&b<c>.ts",
                        oldPath = null,
                        status = FileStatus.ADDED,
                        contentSha256 = "sha",
                        size = 3,
                    ),
                ),
            ),
            title = "Local changes",
            description = "CodeSage local review (workingTree)",
            diff = "diff --git a/a&b<c>.ts",
            language = "typescript",
            files = listOf(
                SourceFile(
                    path = "a&b<c>.ts",
                    oldPath = null,
                    status = FileStatus.ADDED,
                    content = "x < y && z > 1",
                    contentSha256 = "sha",
                ),
            ),
        )

        val json = gson.toJson(ApiMapping.toDto(request))
        // JSON.stringify writes nulls and leaves markup untouched.
        assertTrue(json.contains("\"base_revision\":null"))
        assertTrue(json.contains("\"branch\":null"))
        assertTrue(json.contains("\"old_path\":null"))
        assertTrue(json.contains("a&b<c>.ts"))
        assertTrue(json.contains("x < y && z > 1"))
        assertTrue(!json.contains("\\u003c"))
        assertTrue(!json.contains("\\u0026"))
    }

    @Test
    fun `maps a response and normalizes severities`() {
        val json = """
            {
              "schema_version": 1,
              "snapshot": {
                "id": "s1",
                "base_revision": null,
                "head_sha": "def",
                "branch": "main",
                "captured_at": "2026-10-24T00:00:00Z",
                "files": [
                  {"path": "src/a.ts", "status": "modified", "content_sha256": "sha", "size": 12}
                ]
              },
              "summary": "Summary",
              "overall_severity": "high",
              "statistics": {
                "files_reviewed": 2,
                "issues_found": 2,
                "by_severity": {"high": 1, "medium": 1},
                "by_category": {"security": 1}
              },
              "findings": [
                {
                  "id": "f1",
                  "source": "agent",
                  "native_severity": "warning",
                  "severity": "warning",
                  "file_path": "src/a.ts",
                  "line_start": 3,
                  "line_end": 3,
                  "message": "m",
                  "body": "b",
                  "also_detected_by": ["semgrep"]
                },
                {
                  "id": "f2",
                  "source": "static",
                  "severity": "critical",
                  "file_path": "src/b.ts",
                  "line_start": null,
                  "line_end": null,
                  "message": "m",
                  "body": "b"
                }
              ],
              "degraded_reasons": ["semgrep_failed"],
              "duration_ms": 42
            }
        """.trimIndent()

        val model = ApiMapping.toModel(gson.fromJson(json, ResultDto::class.java))

        assertEquals(1, model.schemaVersion)
        assertEquals("Summary", model.summary)
        assertEquals(2, model.statistics.filesReviewed)
        assertEquals(mapOf("high" to 1, "medium" to 1), model.statistics.bySeverity)
        assertEquals(FileStatus.MODIFIED, model.snapshot.files.first().status)

        val agent = model.findings[0]
        assertEquals(FindingSource.AGENT, agent.source)
        assertEquals(UnifiedSeverity.MEDIUM, agent.severity)
        assertEquals("warning", agent.nativeSeverity)
        assertEquals(listOf("semgrep"), agent.alsoDetectedBy)
        assertEquals(3, agent.lineStart)

        val static = model.findings[1]
        assertEquals(UnifiedSeverity.CRITICAL, static.severity)
        assertEquals("critical", static.nativeSeverity)
        assertEquals(emptyList<String>(), static.alsoDetectedBy)
        assertNull(static.lineStart)
        assertEquals(emptyList<String>(), model.agentFailures)
        assertEquals(false, model.diffTruncated)
    }

    @Test
    fun `falls back to safe values when the response is incomplete`() {
        val model = ApiMapping.toModel(gson.fromJson("{}", ResultDto::class.java))
        assertEquals(0, model.schemaVersion)
        assertEquals("", model.summary)
        assertEquals(emptyList<Any>(), model.findings)
        assertEquals(0L, model.durationMs)
        assertEquals(emptyList<String>(), model.degradedReasons)
    }
}
