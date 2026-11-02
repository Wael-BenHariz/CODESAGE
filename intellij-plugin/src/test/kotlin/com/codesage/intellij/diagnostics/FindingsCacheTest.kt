package com.codesage.intellij.diagnostics

import com.codesage.intellij.git.ChangedRange
import com.codesage.intellij.model.FileStatus
import com.codesage.intellij.model.Finding
import com.codesage.intellij.model.FindingSource
import com.codesage.intellij.model.LocalReviewResult
import com.codesage.intellij.model.ReviewSnapshot
import com.codesage.intellij.model.ReviewStatistics
import com.codesage.intellij.model.SnapshotFile
import com.codesage.intellij.model.UnifiedSeverity
import com.codesage.intellij.util.Sha256
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.nio.file.Files
import java.nio.file.Path

/**
 * Port of the inline-annotation decisions in `vscode-extension/src/diagnostics.ts`.
 *
 * The report always lists every finding; only these decisions put a squiggle in
 * the editor, so a wrong skip reason is invisible in the IDE and must be tested.
 */
class FindingsCacheTest {

    @get:Rule
    val temporary = TemporaryFolder()

    private val content = "import os\n\nPASSWORD = \"hunter2\"\n\ndef run(cmd):\n    os.system(cmd)\n"

    private fun repo(): Path {
        val root = temporary.root.toPath()
        val file = root.resolve("src/demo.py")
        Files.createDirectories(file.parent)
        Files.writeString(file, content)
        return root
    }

    private fun result(
        root: Path,
        findings: List<Finding>,
        shaOverride: String? = Sha256.hex(content.toByteArray()),
        snapshotFiles: List<SnapshotFile> = listOf(
            SnapshotFile(
                path = "src/demo.py",
                oldPath = null,
                status = FileStatus.MODIFIED,
                contentSha256 = shaOverride,
                size = content.toByteArray().size,
            ),
        ),
    ) = LocalReviewResult(
        schemaVersion = 1,
        snapshot = ReviewSnapshot(
            id = "snap",
            baseRevision = null,
            headSha = "",
            branch = "main",
            capturedAt = "2026-11-02T00:00:00Z",
            files = snapshotFiles,
        ),
        summary = "summary",
        overallSeverity = "high",
        statistics = ReviewStatistics(1, findings.size, emptyMap(), emptyMap()),
        findings = findings,
        degradedReasons = emptyList(),
        agentFailures = emptyList(),
        diffTruncated = false,
        durationMs = 1,
    )

    private fun finding(
        id: String,
        lineStart: Int?,
        lineEnd: Int? = lineStart,
        filePath: String = "src/demo.py",
    ) = Finding(
        id = id,
        source = FindingSource.STATIC,
        nativeSeverity = "high",
        severity = UnifiedSeverity.HIGH,
        filePath = filePath,
        oldPath = null,
        lineStart = lineStart,
        lineEnd = lineEnd,
        message = "Issue $id",
        body = "Issue $id",
        suggestion = "fix it",
        snippet = null,
        tool = "semgrep",
        ruleId = "rule-$id",
        category = "security",
        alsoDetectedBy = emptyList(),
        reason = null,
    )

    private val allLines = mapOf("src/demo.py" to listOf(ChangedRange(1, 6)))
    private val defaultSettings = FindingsCache.Settings(
        changedLinesOnly = true,
        includeFileLevel = true,
        showSuggestions = true,
    )

    @Test
    fun `places findings that fall inside the reviewed diff`() {
        val root = repo()
        val cache = FindingsCache()
        val apply = cache.apply(
            result(root, listOf(finding("a", 3), finding("b", 5))),
            root,
            allLines,
            defaultSettings,
        )

        assertEquals(setOf("a", "b"), apply.shown)
        assertTrue(apply.reasons.isEmpty())
        val placements = cache.placementsFor("src/demo.py")
        assertEquals(2, placements.size)
        assertEquals(3, placements[0].startLine)
        assertTrue(placements[0].message.contains("Issue a"))
        assertTrue(placements[0].message.contains("Suggestion: fix it"))
        assertTrue(placements[0].message.contains("Source: semgrep / rule-a"))
        assertFalse(placements[0].fileLevel)
    }

    @Test
    fun `skips findings outside the changed lines but keeps the report complete`() {
        val root = repo()
        val apply = FindingsCache().apply(
            result(root, listOf(finding("in", 3), finding("out", 5))),
            root,
            mapOf("src/demo.py" to listOf(ChangedRange(1, 3))),
            defaultSettings,
        )

        assertEquals(setOf("in"), apply.shown)
        assertEquals("line_outside_diff", apply.reasons["out"])
    }

    @Test
    fun `annotates every line when changed-lines-only is off`() {
        val root = repo()
        val apply = FindingsCache().apply(
            result(root, listOf(finding("out", 9))),
            root,
            emptyMap(),
            defaultSettings.copy(changedLinesOnly = false),
        )

        assertEquals(setOf("out"), apply.shown)
    }

    @Test
    fun `skips files that changed after the snapshot`() {
        val root = repo()
        val apply = FindingsCache().apply(
            result(root, listOf(finding("a", 3)), shaOverride = "0".repeat(64)),
            root,
            allLines,
            defaultSettings,
        )

        assertTrue(apply.shown.isEmpty())
        assertEquals("stale_snapshot", apply.reasons["a"])
    }

    @Test
    fun `skips files missing from the snapshot and unsafe paths`() {
        val root = repo()
        val apply = FindingsCache().apply(
            result(
                root,
                listOf(finding("missing", 3, filePath = "src/other.py")),
            ),
            root,
            allLines,
            defaultSettings,
        )
        assertEquals("file_not_in_snapshot", apply.reasons["missing"])
        assertTrue(apply.shown.isEmpty())

        // A snapshot entry that escapes the repo (the backend rejects these, but the
        // cache must stay fail-closed if one ever reaches it).
        val unsafe = FindingsCache().apply(
            result(
                root,
                listOf(finding("unsafe", 3, filePath = "../escape.py")),
                snapshotFiles = listOf(
                    SnapshotFile("../escape.py", null, FileStatus.MODIFIED, null, 1),
                ),
            ),
            root,
            allLines,
            defaultSettings,
        )
        assertEquals("unsafe_path", unsafe.reasons["unsafe"])
        assertTrue(unsafe.shown.isEmpty())
    }

    @Test
    fun `file-level findings are annotatable unless the setting is off`() {
        val root = repo()
        val on = FindingsCache().apply(
            result(root, listOf(finding("file", null))),
            root,
            allLines,
            defaultSettings,
        )
        assertEquals(setOf("file"), on.shown)
        assertTrue(FindingsCache().apply(
            result(root, listOf(finding("file", null))),
            root,
            allLines,
            defaultSettings.copy(includeFileLevel = false),
        ).reasons["file"] == "line_missing")
    }

    @Test
    fun `clamps line numbers to the file length`() {
        val root = repo()
        val cache = FindingsCache()
        val apply = cache.apply(
            result(root, listOf(finding("beyond", 99))),
            root,
            allLines,
            defaultSettings.copy(changedLinesOnly = false),
        )

        assertEquals(setOf("beyond"), apply.shown)
        val placement = cache.placementsFor("src/demo.py").single()
        // The content ends with a newline, so the document has a 7th (empty) line —
        // the same line count the editor reports.
        assertEquals(7, placement.startLine)
        assertEquals(7, placement.endLine)
    }

    @Test
    fun `clear removes every placement`() {
        val root = repo()
        val cache = FindingsCache()
        cache.apply(result(root, listOf(finding("a", 3))), root, allLines, defaultSettings)
        cache.clear()

        assertTrue(cache.placementsFor("src/demo.py").isEmpty())
        assertEquals(null, cache.repoRoot)
    }

    @Test
    fun `hashes match the backend content_sha256 format`() {
        // Python: hashlib.sha256(b"abc").hexdigest()
        assertEquals(
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            Sha256.hex("abc".toByteArray()),
        )
    }
}
