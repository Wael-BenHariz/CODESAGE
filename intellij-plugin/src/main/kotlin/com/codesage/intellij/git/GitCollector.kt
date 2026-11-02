package com.codesage.intellij.git

import com.codesage.intellij.model.ExcludedFile
import com.codesage.intellij.model.FileStatus
import com.codesage.intellij.model.GitCollection
import com.codesage.intellij.model.LocalReviewRequest
import com.codesage.intellij.model.ReviewScope
import com.codesage.intellij.model.ReviewSnapshot
import com.codesage.intellij.model.SnapshotFile
import com.codesage.intellij.model.SourceFile
import com.codesage.intellij.util.Sha256
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.attribute.BasicFileAttributes
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale
import java.util.UUID

/**
 * Port of `vscode-extension/src/git.ts`.
 *
 * The git invocations, inclusion rules, exclusion reasons, size caps and the
 * snapshot shape are identical so the backend receives the same payload.
 */
object GitCollector {
    private const val MAX_FILE_BYTES = 512 * 1024
    private const val MAX_DIFF_BYTES = 1024 * 1024

    private val ISO_MILLIS: DateTimeFormatter =
        DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.ROOT).withZone(ZoneOffset.UTC)

    data class Options(
        val scope: ReviewScope,
        val includeUntracked: Boolean,
        val maxFiles: Int,
        val maxPayloadBytes: Long,
    )

    private data class RawStatus(
        val path: String,
        val oldPath: String?,
        val index: String,
        val workTree: String,
        val submodule: String,
        val untracked: Boolean,
        val renamed: Boolean,
    )

    private class Candidate(
        val raw: RawStatus,
        val path: String,
        val oldPath: String?,
        val status: FileStatus,
        val content: ByteArray?,
        val contentSha256: String?,
        val size: Int,
    )

    private class ReadResult(val content: ByteArray?, val reason: String? = null)

    fun findRepositoryRoot(folder: Path): Path {
        val root = GitRunner.text(folder, listOf("rev-parse", "--show-toplevel")).trim()
        if (root.isEmpty()) {
            throw GitError("Not inside a Git repository.")
        }
        return Path.of(root).toAbsolutePath().normalize()
    }

    fun collect(folder: Path, options: Options): GitCollection {
        val repoRoot = findRepositoryRoot(folder)
        val statusText = GitRunner.text(
            repoRoot,
            listOf(
                "status",
                "--porcelain=v2",
                "-z",
                "--branch",
                "--untracked-files=all",
                "--find-renames",
            ),
        )
        val parsed = parseStatus(statusText)
        val hasHead = parsed.head != null

        val included = parsed.entries.filter { isIncluded(it, options.scope, options.includeUntracked) }
        val candidates = mutableListOf<Candidate>()
        val excluded = mutableListOf<ExcludedFile>()

        for (raw in included) {
            if (isUnsafePath(raw.path)) {
                excluded.add(ExcludedFile(raw.path, "unsafe path"))
                continue
            }
            if (raw.submodule.startsWith("S")) {
                excluded.add(ExcludedFile(raw.path, "submodule"))
                continue
            }
            if (raw.path.endsWith("/")) {
                excluded.add(ExcludedFile(raw.path, "directory"))
                continue
            }
            val fileStatus = statusFor(raw, options.scope)
            val read = readFileForScope(repoRoot, raw.path, options.scope, fileStatus)
            if (read.reason != null) {
                excluded.add(ExcludedFile(raw.path, read.reason))
                continue
            }
            if (candidates.size >= options.maxFiles) {
                excluded.add(ExcludedFile(raw.path, "more than ${options.maxFiles} files"))
                continue
            }
            val content = read.content
            val size = content?.size ?: 0
            val selectedBytes = candidates.sumOf { it.size }
            if (selectedBytes + size > options.maxPayloadBytes) {
                excluded.add(
                    ExcludedFile(raw.path, "payload would exceed ${options.maxPayloadBytes} bytes"),
                )
                continue
            }
            candidates.add(
                Candidate(
                    raw = raw,
                    path = raw.path,
                    oldPath = raw.oldPath,
                    status = fileStatus,
                    content = content,
                    contentSha256 = content?.let { Sha256.hex(it) },
                    size = size,
                ),
            )
        }

        if (candidates.isEmpty()) {
            throw NoChangesError()
        }

        val snapshotFiles = mutableListOf<SnapshotFile>()
        val sourceFiles = mutableListOf<SourceFile>()
        val diffs = mutableListOf<String>()
        val changedRanges = mutableMapOf<String, List<ChangedRange>>()

        for (candidate in candidates) {
            snapshotFiles.add(
                SnapshotFile(
                    path = candidate.path,
                    oldPath = candidate.oldPath,
                    status = candidate.status,
                    contentSha256 = candidate.contentSha256,
                    size = candidate.size,
                ),
            )
            if (candidate.content != null) {
                sourceFiles.add(
                    SourceFile(
                        path = candidate.path,
                        oldPath = candidate.oldPath,
                        status = candidate.status,
                        content = candidate.content.toString(Charsets.UTF_8),
                        contentSha256 = candidate.contentSha256 ?: "",
                    ),
                )
            }
            val diff = fileDiff(repoRoot, options.scope, candidate, hasHead)
            if (diff.isNotBlank()) {
                diffs.add(diff)
                changedRanges[candidate.path] = DiffRanges.parseChangedRanges(diff)
            }
        }

        val combined = diffs.joinToString("\n")
        val capped = truncateDiff(combined)
        val head = parsed.head
        val snapshot = ReviewSnapshot(
            id = UUID.randomUUID().toString(),
            baseRevision = head,
            headSha = head ?: "",
            branch = if (parsed.branch == "(detached)") null else parsed.branch,
            capturedAt = ISO_MILLIS.format(Instant.now()),
            files = snapshotFiles,
        )

        return GitCollection(
            repoRoot = repoRoot.toString(),
            snapshot = snapshot,
            diff = capped.diff,
            diffTruncated = capped.truncated,
            changedRanges = changedRanges,
            files = sourceFiles,
            excluded = excluded,
            totalBytes = sourceFiles.sumOf { it.content.toByteArray(Charsets.UTF_8).size },
        )
    }

    fun buildReviewRequest(
        collection: GitCollection,
        scope: ReviewScope,
        title: String? = null,
    ): LocalReviewRequest {
        val branch = collection.snapshot.branch ?: "detached HEAD"
        return LocalReviewRequest(
            schemaVersion = 1,
            snapshot = collection.snapshot,
            title = title ?: "Local changes on $branch",
            description = "CodeSage local review (${scope.wire})",
            diff = collection.diff,
            language = detectLanguage(collection.files),
            files = collection.files,
        )
    }

    // ---------------------------------------------------------------------
    // porcelain=v2 parsing
    // ---------------------------------------------------------------------

    private class ParsedStatus(val branch: String?, val head: String?, val entries: List<RawStatus>)

    private val ENTRY_REGEX =
        Regex("^1 ([^ ]{2}) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) (.*)$", RegexOption.DOT_MATCHES_ALL)
    private val RENAME_REGEX =
        Regex("^2 ([^ ]{2}) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) (.*)$", RegexOption.DOT_MATCHES_ALL)

    private fun parseStatus(output: String): ParsedStatus {
        val tokens = output.split("\u0000")
        val entries = mutableListOf<RawStatus>()
        var branch: String? = null
        var head: String? = null

        var index = 0
        while (index < tokens.size) {
            val token = tokens[index]
            if (token.isEmpty()) {
                index += 1
                continue
            }
            if (token.startsWith("# branch.head ")) {
                branch = token.substring("# branch.head ".length)
                index += 1
                continue
            }
            if (token.startsWith("# branch.oid ")) {
                val value = token.substring("# branch.oid ".length)
                head = if (value == "(initial)") null else value
                index += 1
                continue
            }
            if (token.startsWith("# ")) {
                index += 1
                continue
            }
            if (token.startsWith("? ")) {
                entries.add(
                    RawStatus(
                        path = token.substring(2),
                        oldPath = null,
                        index = "?",
                        workTree = "?",
                        submodule = "N...",
                        untracked = true,
                        renamed = false,
                    ),
                )
                index += 1
                continue
            }
            if (token.startsWith("! ")) {
                index += 1
                continue
            }
            if (token.startsWith("u ")) {
                throw GitError("The working tree has unresolved merge conflicts.")
            }
            if (token.startsWith("1 ")) {
                val match = ENTRY_REGEX.find(token)
                if (match != null) {
                    val xy = match.groupValues[1]
                    entries.add(
                        RawStatus(
                            path = match.groupValues[8],
                            oldPath = null,
                            index = xy.take(1),
                            workTree = xy.drop(1).take(1),
                            submodule = match.groupValues[2],
                            untracked = false,
                            renamed = false,
                        ),
                    )
                }
                index += 1
                continue
            }
            if (token.startsWith("2 ")) {
                val match = RENAME_REGEX.find(token)
                if (match != null) {
                    val xy = match.groupValues[1]
                    val oldPath = tokens.getOrNull(index + 1)
                    if (oldPath != null) {
                        index += 1
                    }
                    entries.add(
                        RawStatus(
                            path = match.groupValues[9],
                            oldPath = oldPath,
                            index = xy.take(1),
                            workTree = xy.drop(1).take(1),
                            submodule = match.groupValues[2],
                            untracked = false,
                            renamed = true,
                        ),
                    )
                }
                index += 1
                continue
            }
            index += 1
        }

        return ParsedStatus(branch, head, entries)
    }

    private fun statusFor(raw: RawStatus, scope: ReviewScope): FileStatus {
        if (raw.renamed) {
            return FileStatus.RENAMED
        }
        val code = when {
            scope == ReviewScope.STAGED -> raw.index
            raw.index == "." -> raw.workTree
            else -> raw.index
        }
        if (code == "D") {
            return FileStatus.DELETED
        }
        if (code == "A" || code == "C" || raw.untracked) {
            return FileStatus.ADDED
        }
        if (raw.workTree == "D" || raw.index == "D") {
            return FileStatus.DELETED
        }
        return FileStatus.MODIFIED
    }

    private fun isIncluded(raw: RawStatus, scope: ReviewScope, includeUntracked: Boolean): Boolean {
        if (raw.untracked) {
            return scope == ReviewScope.WORKING_TREE && includeUntracked
        }
        if (scope == ReviewScope.STAGED) {
            return raw.index != "."
        }
        return raw.index != "." || raw.workTree != "."
    }

    private fun isUnsafePath(filePath: String): Boolean {
        if (filePath.isEmpty() || filePath.contains('\u0000')) {
            return true
        }
        if (Path.of(filePath).isAbsolute) {
            return true
        }
        return filePath.split("/").any { it == ".." }
    }

    private fun isBinary(buffer: ByteArray): Boolean {
        val limit = minOf(8000, buffer.size)
        for (index in 0 until limit) {
            if (buffer[index].toInt() == 0) {
                return true
            }
        }
        return false
    }

    private fun readWorkingTreeFile(repoRoot: Path, filePath: String): ReadResult {
        val absolute = safeResolve(repoRoot, filePath) ?: return ReadResult(null, "outside repository")
        return try {
            val attributes = Files.readAttributes(
                absolute,
                BasicFileAttributes::class.java,
                LinkOption.NOFOLLOW_LINKS,
            )
            if (attributes.isSymbolicLink) {
                return ReadResult(null, "symbolic link")
            }
            if (!attributes.isRegularFile) {
                return ReadResult(null, "not a regular file")
            }
            if (attributes.size() > MAX_FILE_BYTES) {
                return ReadResult(null, "larger than $MAX_FILE_BYTES bytes")
            }
            val content = Files.readAllBytes(absolute)
            if (isBinary(content)) {
                return ReadResult(null, "binary file")
            }
            ReadResult(content)
        } catch (_: Exception) {
            ReadResult(null, "unreadable file")
        }
    }

    private fun readStagedFile(repoRoot: Path, filePath: String): ReadResult {
        return try {
            val mode = GitRunner.text(repoRoot, listOf("ls-files", "-s", "--", filePath)).trim()
            if (mode.startsWith("120000 ")) {
                return ReadResult(null, "symbolic link")
            }
            val content = GitRunner.bytes(repoRoot, listOf("show", ":$filePath"))
            if (content.size > MAX_FILE_BYTES) {
                return ReadResult(null, "larger than $MAX_FILE_BYTES bytes")
            }
            if (isBinary(content)) {
                return ReadResult(null, "binary file")
            }
            ReadResult(content)
        } catch (_: Exception) {
            ReadResult(null, "unreadable staged file")
        }
    }

    private fun safeResolve(repoRoot: Path, filePath: String): Path? {
        val absolute = repoRoot.resolve(filePath).normalize()
        if (!absolute.startsWith(repoRoot)) {
            return null
        }
        return absolute
    }

    private fun readFileForScope(
        repoRoot: Path,
        filePath: String,
        scope: ReviewScope,
        status: FileStatus,
    ): ReadResult {
        if (status == FileStatus.DELETED) {
            return ReadResult(null)
        }
        return if (scope == ReviewScope.STAGED) {
            readStagedFile(repoRoot, filePath)
        } else {
            readWorkingTreeFile(repoRoot, filePath)
        }
    }

    private fun diffArgs(scope: ReviewScope, filePath: String): List<String> {
        val base = if (scope == ReviewScope.STAGED) listOf("diff", "--cached") else listOf("diff")
        return base + listOf(
            "HEAD",
            "--unified=3",
            "--no-ext-diff",
            "--no-textconv",
            "--find-renames",
            "--no-color",
            "--",
            filePath,
        )
    }

    private fun fileDiff(
        repoRoot: Path,
        scope: ReviewScope,
        candidate: Candidate,
        hasHead: Boolean,
    ): String {
        if (candidate.status == FileStatus.DELETED || candidate.content == null) {
            if (candidate.status == FileStatus.ADDED && candidate.content != null) {
                return DiffRanges.synthesizeAddedDiff(
                    candidate.path,
                    candidate.content.toString(Charsets.UTF_8),
                )
            }
            return if (hasHead) GitRunner.text(repoRoot, diffArgs(scope, candidate.path)) else ""
        }
        if (!hasHead || candidate.status == FileStatus.ADDED) {
            return DiffRanges.synthesizeAddedDiff(
                candidate.path,
                candidate.content.toString(Charsets.UTF_8),
            )
        }
        val diff = GitRunner.text(repoRoot, diffArgs(scope, candidate.path))
        if (diff.isBlank()) {
            return DiffRanges.synthesizeAddedDiff(
                candidate.path,
                candidate.content.toString(Charsets.UTF_8),
            )
        }
        return diff
    }

    private fun detectLanguage(files: List<SourceFile>): String {
        val counts = LinkedHashMap<String, Int>()
        for (file in files) {
            val extension = file.path.substringAfterLast('.', "").lowercase(Locale.ROOT)
            val language = LANGUAGE_BY_EXTENSION[".$extension"] ?: "text"
            counts[language] = (counts[language] ?: 0) + 1
        }
        var best = "text"
        var bestCount = 0
        for ((language, count) in counts) {
            if (count > bestCount) {
                best = language
                bestCount = count
            }
        }
        return best
    }

    private val LANGUAGE_BY_EXTENSION: Map<String, String> = mapOf(
        ".py" to "python",
        ".js" to "javascript",
        ".jsx" to "javascript",
        ".ts" to "typescript",
        ".tsx" to "typescript",
        ".go" to "go",
        ".rs" to "rust",
        ".java" to "java",
        ".rb" to "ruby",
        ".php" to "php",
        ".cs" to "csharp",
        ".c" to "c",
        ".h" to "c",
        ".cpp" to "cpp",
        ".hpp" to "cpp",
        ".swift" to "swift",
        ".kt" to "kotlin",
        ".kts" to "kotlin",
        ".scala" to "scala",
        ".sh" to "shell",
        ".bash" to "shell",
        ".sql" to "sql",
        ".yaml" to "yaml",
        ".yml" to "yaml",
        ".json" to "json",
        ".md" to "markdown",
    )

    private class CappedDiff(val diff: String, val truncated: Boolean)

    private fun truncateDiff(diff: String): CappedDiff {
        val bytes = diff.toByteArray(Charsets.UTF_8)
        if (bytes.size <= MAX_DIFF_BYTES) {
            return CappedDiff(diff, false)
        }
        val slice = bytes.copyOfRange(0, MAX_DIFF_BYTES).toString(Charsets.UTF_8)
        val lastNewline = slice.lastIndexOf('\n')
        val body = if (lastNewline > 0) slice.substring(0, lastNewline) else slice
        return CappedDiff(
            "$body\n\n[CodeSage: local diff truncated at $MAX_DIFF_BYTES bytes]\n",
            true,
        )
    }
}
