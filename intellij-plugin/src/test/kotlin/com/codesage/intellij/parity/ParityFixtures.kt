package com.codesage.intellij.parity

import com.codesage.intellij.git.ChangedRange
import com.codesage.intellij.model.ExcludedFile
import com.codesage.intellij.model.FileStatus
import com.codesage.intellij.model.Finding
import com.codesage.intellij.model.FindingSource
import com.codesage.intellij.model.GitCollection
import com.codesage.intellij.model.LocalReviewResult
import com.codesage.intellij.model.ReviewSnapshot
import com.codesage.intellij.model.ReviewStatistics
import com.codesage.intellij.model.Severity
import com.codesage.intellij.model.SnapshotFile
import com.codesage.intellij.model.SourceFile
import com.codesage.intellij.report.DiagnosticViewState
import com.codesage.intellij.report.ReportViewState
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.nio.file.Files
import java.nio.file.Path

/**
 * Loads `src/test/resources/parity/fixtures.json`, the same fixtures that
 * `scripts/parity/emit-golden.mjs` feeds to the real VS Code renderer.
 */
object ParityFixtures {
    val directory: Path = Path.of(
        System.getProperty("codesage.parity.dir")
            ?: error("codesage.parity.dir system property is not set"),
    )

    fun fixtures(): List<Pair<String, ReportViewState>> {
        val text = Files.readString(directory.resolve("fixtures.json"))
        val array = JsonParser.parseString(text).asJsonArray
        return array.map { element ->
            val fixture = element.asJsonObject
            fixture["name"].asString to toState(fixture["view"].asJsonObject)
        }
    }

    fun golden(name: String): String =
        Files.readString(directory.resolve("expected").resolve("$name.html"))

    private fun toState(view: JsonObject): ReportViewState = when (view["kind"].asString) {
        "loading" -> ReportViewState.Loading(view["message"].asString)
        "cancelled" -> ReportViewState.Cancelled
        "error" -> ReportViewState.Error(view["message"].asString)
        "result" -> ReportViewState.Result(
            result = toResult(view["result"].asJsonObject),
            collection = view["collection"].nullableObject()?.let { toCollection(it) },
            diagnostics = view["diagnostics"].nullableObject()?.let { toDiagnostics(it) },
        )
        else -> error("unknown fixture kind: ${view["kind"]}")
    }

    private fun toResult(json: JsonObject): LocalReviewResult {
        val statistics = json["statistics"].asJsonObject
        return LocalReviewResult(
            schemaVersion = json["schemaVersion"].asInt,
            snapshot = toSnapshot(json["snapshot"].asJsonObject),
            summary = json["summary"].asString,
            overallSeverity = json["overallSeverity"].asString,
            statistics = ReviewStatistics(
                filesReviewed = statistics["filesReviewed"].asInt,
                issuesFound = statistics["issuesFound"].asInt,
                bySeverity = toIntMap(statistics["bySeverity"]),
                byCategory = toIntMap(statistics["byCategory"]),
            ),
            findings = json["findings"].asJsonArray.map { toFinding(it.asJsonObject) },
            degradedReasons = json["degradedReasons"].stringList(),
            agentFailures = json["agentFailures"].stringList(),
            diffTruncated = json["diffTruncated"].asBoolean,
            durationMs = json["durationMs"].asLong,
        )
    }

    private fun toSnapshot(json: JsonObject): ReviewSnapshot = ReviewSnapshot(
        id = json["id"].asString,
        baseRevision = json["baseRevision"].nullableString(),
        headSha = json["headSha"].asString,
        branch = json["branch"].nullableString(),
        capturedAt = json["capturedAt"].asString,
        files = json["files"].asJsonArray.map { element ->
            val file = element.asJsonObject
            SnapshotFile(
                path = file["path"].asString,
                oldPath = file["oldPath"].nullableString(),
                status = FileStatus.fromWire(file["status"].asString),
                contentSha256 = file["contentSha256"].nullableString(),
                size = file["size"].asInt,
            )
        },
    )

    private fun toFinding(json: JsonObject): Finding {
        val source = FindingSource.fromWire(json["source"].asString)
        return Finding(
            id = json["id"].asString,
            source = source,
            nativeSeverity = json["nativeSeverity"].asString,
            severity = Severity.normalize(json["severity"].asString, source),
            filePath = json["filePath"].asString,
            oldPath = json["oldPath"].nullableString(),
            lineStart = json["lineStart"].nullableInt(),
            lineEnd = json["lineEnd"].nullableInt(),
            message = json["message"].asString,
            body = json["body"].asString,
            suggestion = json["suggestion"].nullableString(),
            snippet = json["snippet"].nullableString(),
            tool = json["tool"].nullableString(),
            ruleId = json["ruleId"].nullableString(),
            category = json["category"].nullableString(),
            alsoDetectedBy = json["alsoDetectedBy"].stringList(),
            reason = json["reason"].nullableString(),
        )
    }

    private fun toCollection(json: JsonObject): GitCollection = GitCollection(
        repoRoot = json["repoRoot"].asString,
        snapshot = toSnapshot(json["snapshot"].asJsonObject),
        diff = json["diff"].asString,
        diffTruncated = json["diffTruncated"].asBoolean,
        changedRanges = toRanges(json["changedRanges"].asJsonObject),
        files = json["files"].asJsonArray.map { element ->
            val file = element.asJsonObject
            SourceFile(
                path = file["path"].asString,
                oldPath = file["oldPath"].nullableString(),
                status = FileStatus.fromWire(file["status"].asString),
                content = file["content"].asString,
                contentSha256 = file["contentSha256"].asString,
            )
        },
        excluded = json["excluded"].asJsonArray.map { element ->
            val file = element.asJsonObject
            ExcludedFile(file["path"].asString, file["reason"].asString)
        },
        totalBytes = json["totalBytes"].asInt,
    )

    private fun toDiagnostics(json: JsonObject): DiagnosticViewState =
        DiagnosticViewState(
            shown = json["shown"].asJsonArray.map { it.asString }.toSet(),
            reasons = json["reasons"].asJsonObject.entrySet()
                .associate { it.key to it.value.asString },
        )

    private fun toRanges(json: JsonObject): Map<String, List<ChangedRange>> =
        json.entrySet().associate { (path, value) ->
            path to value.asJsonArray.map { element ->
                val range = element.asJsonObject
                ChangedRange(range["start"].asInt, range["end"].asInt)
            }
        }

    private fun toIntMap(element: JsonElement): Map<String, Int> {
        if (!element.isJsonObject) {
            return emptyMap()
        }
        return element.asJsonObject.entrySet().associate { it.key to it.value.asInt }
    }

    private fun JsonElement?.stringList(): List<String> =
        if (this == null || isJsonNull) emptyList() else asJsonArray.map { it.asString }

    private fun JsonElement?.nullableString(): String? =
        if (this == null || isJsonNull) null else asString

    private fun JsonElement?.nullableInt(): Int? =
        if (this == null || isJsonNull) null else asInt

    private fun JsonElement?.nullableObject(): JsonObject? =
        if (this == null || isJsonNull) null else asJsonObject
}
