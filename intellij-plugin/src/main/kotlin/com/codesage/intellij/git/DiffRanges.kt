package com.codesage.intellij.git

/** Port of `vscode-extension/src/diff.ts`. */
data class ChangedRange(val start: Int, val end: Int)

object DiffRanges {
    private val HUNK_HEADER = Regex("^@@ -(\\d+)(?:,(\\d+))? \\+(\\d+)(?:,(\\d+))? @@")

    private class MutableRange(var start: Int, var end: Int)

    /** Collects added lines from hunks and merges adjacent ranges. */
    fun parseChangedRanges(diff: String): List<ChangedRange> {
        val ranges = mutableListOf<MutableRange>()
        val lines = diff.split(Regex("\r?\n"))
        var inHunk = false
        var newLine = 0

        fun addLine(line: Int) {
            val last = ranges.lastOrNull()
            if (last != null && line <= last.end + 1) {
                last.end = maxOf(last.end, line)
                return
            }
            ranges.add(MutableRange(line, line))
        }

        for (line in lines) {
            val header = HUNK_HEADER.find(line)
            if (header != null) {
                inHunk = true
                newLine = header.groupValues[3].toInt()
                continue
            }
            if (line.startsWith("diff --git ")) {
                inHunk = false
                continue
            }
            if (!inHunk) {
                continue
            }
            if (line.startsWith("\\")) {
                continue
            }
            if (line.startsWith("+")) {
                addLine(newLine)
                newLine += 1
                continue
            }
            if (line.startsWith("-")) {
                continue
            }
            if (line.startsWith(" ")) {
                newLine += 1
                continue
            }
            if (line.isEmpty()) {
                continue
            }
            inHunk = false
        }

        return ranges.map { ChangedRange(it.start, it.end) }
    }

    fun lineIsChanged(lineStart: Int?, lineEnd: Int?, ranges: List<ChangedRange>): Boolean {
        if (lineStart == null) {
            return false
        }
        val start = maxOf(1, lineStart)
        val end = maxOf(start, lineEnd ?: start)
        return ranges.any { start <= it.end && end >= it.start }
    }

    /** Builds a new-file diff for untracked or newly added files. */
    fun synthesizeAddedDiff(path: String, content: String): String {
        val normalized = content.replace("\r\n", "\n")
        val lines = if (normalized.isEmpty()) mutableListOf() else normalized.split("\n").toMutableList()
        if (lines.isNotEmpty() && lines[lines.size - 1].isEmpty()) {
            lines.removeAt(lines.size - 1)
        }
        val body = lines.joinToString("\n") { "+$it" }
        val header = listOf(
            "diff --git a/$path b/$path",
            "new file mode 100644",
            "index 0000000..0000000",
            "--- /dev/null",
            "+++ b/$path",
        )
        if (lines.isEmpty()) {
            return header.joinToString("\n") + "\n@@ -0,0 +0,0 @@\n"
        }
        return header.joinToString("\n") + "\n@@ -0,0 +1,${lines.size} @@\n$body\n"
    }
}
