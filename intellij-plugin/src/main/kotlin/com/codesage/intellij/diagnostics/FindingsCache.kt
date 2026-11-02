package com.codesage.intellij.diagnostics

import com.codesage.intellij.git.ChangedRange
import com.codesage.intellij.git.DiffRanges
import com.codesage.intellij.model.Finding
import com.codesage.intellij.model.LocalReviewResult
import com.codesage.intellij.model.UnifiedSeverity
import com.codesage.intellij.util.Sha256
import com.intellij.openapi.components.Service
import java.nio.file.Files
import java.nio.file.Path

/**
 * Port of `vscode-extension/src/diagnostics.ts`.
 *
 * Decisions (show inline, or skip with a reason) are computed once per review,
 * off the EDT, exactly like the VS Code `DiagnosticsManager.apply` call. The
 * external annotator then only renders the stored placements for a file.
 */
@Service(Service.Level.PROJECT)
class FindingsCache {

    data class Placement(
        val findingId: String,
        val startLine: Int,
        val endLine: Int,
        val message: String,
        val severity: UnifiedSeverity,
        val fileLevel: Boolean,
    )

    data class ApplyResult(val shown: Set<String>, val reasons: Map<String, String>)

    data class Settings(
        val changedLinesOnly: Boolean,
        val includeFileLevel: Boolean,
        val showSuggestions: Boolean,
    )

    private data class Snapshot(
        val repoRoot: Path?,
        val byFile: Map<String, List<Placement>>,
        val shown: Set<String>,
        val reasons: Map<String, String>,
        val hasResult: Boolean,
    )

    @Volatile
    private var snapshot = Snapshot(null, emptyMap(), emptySet(), emptyMap(), false)

    val repoRoot: Path?
        get() = snapshot.repoRoot

    fun placementsFor(relativePath: String): List<Placement> = snapshot.byFile[relativePath] ?: emptyList()

    fun clear() {
        snapshot = Snapshot(null, emptyMap(), emptySet(), emptyMap(), false)
    }

    fun apply(
        result: LocalReviewResult,
        repoRoot: Path,
        changedRanges: Map<String, List<ChangedRange>>,
        settings: Settings,
    ): ApplyResult {
        val shown = LinkedHashSet<String>()
        val reasons = LinkedHashMap<String, String>()
        val byFile = LinkedHashMap<String, MutableList<Placement>>()
        val snapshotByPath = result.snapshot.files.associateBy { it.path }

        for (finding in result.findings) {
            val snapshotFile = snapshotByPath[finding.filePath]
            if (snapshotFile == null) {
                reasons[finding.id] = "file_not_in_snapshot"
                continue
            }
            if (snapshotFile.status == com.codesage.intellij.model.FileStatus.DELETED) {
                reasons[finding.id] = "file_deleted"
                continue
            }

            val absolute = safeResolve(repoRoot, finding.filePath)
            if (absolute == null) {
                reasons[finding.id] = "unsafe_path"
                continue
            }

            val content: String
            try {
                val bytes = Files.readAllBytes(absolute)
                if (snapshotFile.contentSha256 != null && Sha256.hex(bytes) != snapshotFile.contentSha256) {
                    reasons[finding.id] = "stale_snapshot"
                    continue
                }
                content = bytes.toString(Charsets.UTF_8)
            } catch (_: Exception) {
                reasons[finding.id] = "file_unreadable"
                continue
            }

            if (finding.lineStart == null) {
                if (!settings.includeFileLevel) {
                    reasons[finding.id] = "line_missing"
                    continue
                }
                byFile.getOrPut(finding.filePath) { mutableListOf() }.add(
                    Placement(
                        findingId = finding.id,
                        startLine = 1,
                        endLine = 1,
                        message = diagnosticMessage(finding, settings),
                        severity = finding.severity,
                        fileLevel = true,
                    ),
                )
                shown.add(finding.id)
                continue
            }

            if (settings.changedLinesOnly &&
                !DiffRanges.lineIsChanged(finding.lineStart, finding.lineEnd, changedRanges[finding.filePath] ?: emptyList())
            ) {
                reasons[finding.id] = "line_outside_diff"
                continue
            }

            val lines = content.split(Regex("\r?\n"))
            val startLine = minOf(maxOf(1, finding.lineStart), lines.size)
            val endLine = minOf(maxOf(startLine, finding.lineEnd ?: startLine), lines.size)

            byFile.getOrPut(finding.filePath) { mutableListOf() }.add(
                Placement(
                    findingId = finding.id,
                    startLine = startLine,
                    endLine = endLine,
                    message = diagnosticMessage(finding, settings),
                    severity = finding.severity,
                    fileLevel = false,
                ),
            )
            shown.add(finding.id)
        }

        snapshot = Snapshot(
            repoRoot = repoRoot,
            byFile = byFile.mapValues { it.value.toList() },
            shown = shown,
            reasons = reasons,
            hasResult = true,
        )
        return ApplyResult(shown, reasons)
    }

    private fun diagnosticMessage(finding: Finding, settings: Settings): String {
        val parts = mutableListOf(finding.message)
        if (settings.showSuggestions && !finding.suggestion.isNullOrEmpty()) {
            parts.add("")
            parts.add("Suggestion: ${finding.suggestion}")
        }
        if (!finding.tool.isNullOrEmpty() && !finding.ruleId.isNullOrEmpty()) {
            parts.add("")
            parts.add("Source: ${finding.tool} / ${finding.ruleId}")
        }
        return parts.joinToString("\n")
    }

    private fun safeResolve(repoRoot: Path, filePath: String): Path? {
        val absolute = try {
            repoRoot.resolve(filePath).normalize()
        } catch (_: Exception) {
            return null
        }
        if (!absolute.startsWith(repoRoot)) {
            return null
        }
        return absolute
    }
}
