package com.codesage.intellij.api

import com.codesage.intellij.model.Finding
import com.codesage.intellij.model.FindingSource
import com.codesage.intellij.model.LocalReviewRequest
import com.codesage.intellij.model.LocalReviewResult
import com.codesage.intellij.model.ReviewSnapshot
import com.codesage.intellij.model.ReviewStatistics
import com.codesage.intellij.model.Severity
import com.codesage.intellij.model.SnapshotFile
import com.codesage.intellij.model.SourceFile
import com.codesage.intellij.model.FileStatus
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.annotations.SerializedName

/**
 * Gson configuration that reproduces `JSON.stringify` from `api.ts`: `null`
 * values are written out and markup characters are not escaped. The request
 * body is therefore byte-identical to the VS Code extension's.
 */
internal val CodeSageGson: Gson = GsonBuilder()
    .serializeNulls()
    .disableHtmlEscaping()
    .create()

/**
 * Wire DTOs. Field names mirror `vscode-extension/src/api.ts`.
 *
 * Response fields are nullable on purpose: Gson bypasses Kotlin constructors,
 * so every value is re-checked while mapping into the model, exactly like the
 * `?? default` fallbacks in the VS Code client.
 */
internal data class SnapshotFileDto(
    val path: String? = null,
    @SerializedName("old_path") val oldPath: String? = null,
    val status: String? = null,
    @SerializedName("content_sha256") val contentSha256: String? = null,
    val size: Int? = null,
)

internal data class SnapshotDto(
    val id: String? = null,
    @SerializedName("base_revision") val baseRevision: String? = null,
    @SerializedName("head_sha") val headSha: String? = null,
    val branch: String? = null,
    @SerializedName("captured_at") val capturedAt: String? = null,
    val files: List<SnapshotFileDto>? = null,
)

internal data class SourceFileDto(
    val path: String? = null,
    @SerializedName("old_path") val oldPath: String? = null,
    val status: String? = null,
    val content: String? = null,
    @SerializedName("content_sha256") val contentSha256: String? = null,
)

internal data class RequestDto(
    @SerializedName("schema_version") val schemaVersion: Int? = 1,
    val snapshot: SnapshotDto? = null,
    val title: String? = null,
    val description: String? = null,
    val diff: String? = null,
    val language: String? = null,
    val files: List<SourceFileDto>? = null,
)

internal data class StatisticsDto(
    @SerializedName("files_reviewed") val filesReviewed: Int? = null,
    @SerializedName("issues_found") val issuesFound: Int? = null,
    @SerializedName("by_severity") val bySeverity: Map<String, Int>? = null,
    @SerializedName("by_category") val byCategory: Map<String, Int>? = null,
)

internal data class FindingDto(
    val id: String? = null,
    val source: String? = null,
    @SerializedName("native_severity") val nativeSeverity: String? = null,
    val severity: String? = null,
    @SerializedName("file_path") val filePath: String? = null,
    @SerializedName("old_path") val oldPath: String? = null,
    @SerializedName("line_start") val lineStart: Int? = null,
    @SerializedName("line_end") val lineEnd: Int? = null,
    val message: String? = null,
    val body: String? = null,
    val suggestion: String? = null,
    val snippet: String? = null,
    val tool: String? = null,
    @SerializedName("rule_id") val ruleId: String? = null,
    val category: String? = null,
    @SerializedName("also_detected_by") val alsoDetectedBy: List<String>? = null,
    val reason: String? = null,
)

internal data class ResultDto(
    @SerializedName("schema_version") val schemaVersion: Int? = null,
    val snapshot: SnapshotDto? = null,
    val summary: String? = null,
    @SerializedName("overall_severity") val overallSeverity: String? = null,
    val statistics: StatisticsDto? = null,
    val findings: List<FindingDto>? = null,
    @SerializedName("degraded_reasons") val degradedReasons: List<String>? = null,
    @SerializedName("agent_failures") val agentFailures: List<String>? = null,
    @SerializedName("diff_truncated") val diffTruncated: Boolean? = null,
    @SerializedName("duration_ms") val durationMs: Long? = null,
)

/** Pure request/response mapping — no platform or HTTP dependencies. */
internal object ApiMapping {    fun toDto(request: LocalReviewRequest): RequestDto = RequestDto(
        schemaVersion = request.schemaVersion,
        snapshot = SnapshotDto(
            id = request.snapshot.id,
            baseRevision = request.snapshot.baseRevision,
            headSha = request.snapshot.headSha,
            branch = request.snapshot.branch,
            capturedAt = request.snapshot.capturedAt,
            files = request.snapshot.files.map { file ->
                SnapshotFileDto(
                    path = file.path,
                    oldPath = file.oldPath,
                    status = file.status.wire,
                    contentSha256 = file.contentSha256,
                    size = file.size,
                )
            },
        ),
        title = request.title,
        description = request.description,
        diff = request.diff,
        language = request.language,
        files = request.files.map { file ->
            SourceFileDto(
                path = file.path,
                oldPath = file.oldPath,
                status = file.status.wire,
                content = file.content,
                contentSha256 = file.contentSha256,
            )
        },
    )

    fun toModel(dto: ResultDto?): LocalReviewResult {
        val result = dto ?: ResultDto()
        val statistics = result.statistics
        return LocalReviewResult(
            schemaVersion = result.schemaVersion ?: 0,
            snapshot = toSnapshot(result.snapshot),
            summary = result.summary ?: "",
            overallSeverity = result.overallSeverity ?: "",
            statistics = ReviewStatistics(
                filesReviewed = statistics?.filesReviewed ?: 0,
                issuesFound = statistics?.issuesFound ?: 0,
                bySeverity = statistics?.bySeverity ?: emptyMap(),
                byCategory = statistics?.byCategory ?: emptyMap(),
            ),
            findings = result.findings?.map { toFinding(it) } ?: emptyList(),
            degradedReasons = result.degradedReasons ?: emptyList(),
            agentFailures = result.agentFailures ?: emptyList(),
            diffTruncated = result.diffTruncated ?: false,
            durationMs = result.durationMs ?: 0L,
        )
    }

    private fun toSnapshot(dto: SnapshotDto?): ReviewSnapshot {
        val snapshot = dto ?: SnapshotDto()
        return ReviewSnapshot(
            id = snapshot.id ?: "",
            baseRevision = snapshot.baseRevision,
            headSha = snapshot.headSha ?: "",
            branch = snapshot.branch,
            capturedAt = snapshot.capturedAt ?: "",
            files = snapshot.files?.map { file ->
                SnapshotFile(
                    path = file.path ?: "",
                    oldPath = file.oldPath,
                    status = FileStatus.fromWire(file.status),
                    contentSha256 = file.contentSha256,
                    size = file.size ?: 0,
                )
            } ?: emptyList(),
        )
    }

    private fun toFinding(dto: FindingDto): Finding {
        val source = FindingSource.fromWire(dto.source)
        return Finding(
            id = dto.id ?: "",
            source = source,
            nativeSeverity = dto.nativeSeverity ?: dto.severity ?: "",
            severity = Severity.normalize(dto.severity, source),
            filePath = dto.filePath ?: "",
            oldPath = dto.oldPath,
            lineStart = dto.lineStart,
            lineEnd = dto.lineEnd,
            message = dto.message ?: "",
            body = dto.body ?: "",
            suggestion = dto.suggestion,
            snippet = dto.snippet,
            tool = dto.tool,
            ruleId = dto.ruleId,
            category = dto.category,
            alsoDetectedBy = dto.alsoDetectedBy ?: emptyList(),
            reason = dto.reason,
        )
    }
}
