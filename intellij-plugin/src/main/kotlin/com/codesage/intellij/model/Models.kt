package com.codesage.intellij.model

/** Review scope. Wire values match the VS Code extension and the backend schema. */
enum class ReviewScope(val wire: String) {
    WORKING_TREE("workingTree"),
    STAGED("staged");

    companion object {
        fun fromWire(value: String?): ReviewScope = if (value == "staged") STAGED else WORKING_TREE
    }
}

enum class FileStatus(val wire: String) {
    ADDED("added"),
    MODIFIED("modified"),
    DELETED("deleted"),
    RENAMED("renamed");

    companion object {
        fun fromWire(value: String?): FileStatus =
            entries.firstOrNull { it.wire == value } ?: MODIFIED
    }
}

enum class UnifiedSeverity(val wire: String) {
    INFO("info"),
    LOW("low"),
    MEDIUM("medium"),
    HIGH("high"),
    CRITICAL("critical");

    companion object {
        fun fromWire(value: String?): UnifiedSeverity =
            entries.firstOrNull { it.wire == value } ?: INFO
    }
}

enum class FindingSource(val wire: String) {
    STATIC("static"),
    AGENT("agent"),
    COMMENT("comment");

    companion object {
        fun fromWire(value: String?): FindingSource =
            entries.firstOrNull { it.wire == value } ?: STATIC
    }
}

data class SnapshotFile(
    val path: String,
    val oldPath: String? = null,
    val status: FileStatus,
    val contentSha256: String?,
    val size: Int,
)

data class ReviewSnapshot(
    val id: String,
    val baseRevision: String?,
    val headSha: String,
    val branch: String?,
    val capturedAt: String,
    val files: List<SnapshotFile>,
)

data class SourceFile(
    val path: String,
    val oldPath: String? = null,
    val status: FileStatus,
    val content: String,
    val contentSha256: String,
)

data class ExcludedFile(val path: String, val reason: String)

data class GitCollection(
    val repoRoot: String,
    val snapshot: ReviewSnapshot,
    val diff: String,
    val diffTruncated: Boolean,
    val changedRanges: Map<String, List<com.codesage.intellij.git.ChangedRange>>,
    val files: List<SourceFile>,
    val excluded: List<ExcludedFile>,
    val totalBytes: Int,
)

data class LocalReviewRequest(
    val schemaVersion: Int,
    val snapshot: ReviewSnapshot,
    val title: String,
    val description: String?,
    val diff: String,
    val language: String,
    val files: List<SourceFile>,
)

data class Finding(
    val id: String,
    val source: FindingSource,
    val nativeSeverity: String,
    val severity: UnifiedSeverity,
    val filePath: String,
    val oldPath: String? = null,
    val lineStart: Int?,
    val lineEnd: Int?,
    val message: String,
    val body: String,
    val suggestion: String?,
    val snippet: String?,
    val tool: String?,
    val ruleId: String?,
    val category: String?,
    val alsoDetectedBy: List<String> = emptyList(),
    val reason: String? = null,
)

data class ReviewStatistics(
    val filesReviewed: Int,
    val issuesFound: Int,
    val bySeverity: Map<String, Int>,
    val byCategory: Map<String, Int>,
)

data class LocalReviewResult(
    val schemaVersion: Int,
    val snapshot: ReviewSnapshot,
    val summary: String,
    val overallSeverity: String,
    val statistics: ReviewStatistics,
    val findings: List<Finding>,
    val degradedReasons: List<String>,
    val agentFailures: List<String>,
    val diffTruncated: Boolean,
    val durationMs: Long,
)
