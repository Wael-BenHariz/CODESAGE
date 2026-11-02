package com.codesage.intellij.git

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Port of `vscode-extension/test/diff.test.ts`. */
class DiffRangesTest {

    @Test
    fun `collects added lines from hunks and merges adjacent ranges`() {
        val diff = listOf(
            "diff --git a/src/a.ts b/src/a.ts",
            "--- a/src/a.ts",
            "+++ b/src/a.ts",
            "@@ -1,3 +1,4 @@",
            " const a = 1;",
            "-const b = 2;",
            "+const b = 3;",
            "+const c = 4;",
            " const d = 5;",
            "@@ -20,1 +21,1 @@",
            "-old",
            "+new",
        ).joinToString("\n")

        assertEquals(
            listOf(ChangedRange(2, 3), ChangedRange(21, 21)),
            DiffRanges.parseChangedRanges(diff),
        )
    }

    @Test
    fun `produces no range for a pure deletion`() {
        val diff = listOf(
            "diff --git a/a.txt b/a.txt",
            "--- a/a.txt",
            "+++ b/a.txt",
            "@@ -2,2 +2,1 @@",
            " keep",
            "-remove",
        ).joinToString("\n")

        assertEquals(emptyList<ChangedRange>(), DiffRanges.parseChangedRanges(diff))
    }

    @Test
    fun `handles a hunk with no explicit count`() {
        val diff = listOf(
            "diff --git a/a.txt b/a.txt",
            "--- a/a.txt",
            "+++ b/a.txt",
            "@@ -1 +1 @@",
            "-old",
            "+new",
        ).joinToString("\n")

        assertEquals(listOf(ChangedRange(1, 1)), DiffRanges.parseChangedRanges(diff))
    }

    @Test
    fun `counts an added content line that itself begins with plus plus`() {
        val diff = listOf(
            "diff --git a/a.txt b/a.txt",
            "--- a/a.txt",
            "+++ b/a.txt",
            "@@ -0,0 +1,1 @@",
            "+++header",
        ).joinToString("\n")

        assertEquals(listOf(ChangedRange(1, 1)), DiffRanges.parseChangedRanges(diff))
    }

    @Test
    fun `matches intersections, not only the first line`() {
        val ranges = listOf(ChangedRange(3, 5))
        assertTrue(DiffRanges.lineIsChanged(2, 3, ranges))
        assertTrue(DiffRanges.lineIsChanged(5, 8, ranges))
        assertTrue(DiffRanges.lineIsChanged(3, 3, ranges))
        assertFalse(DiffRanges.lineIsChanged(1, 2, ranges))
        assertFalse(DiffRanges.lineIsChanged(null, null, ranges))
    }

    @Test
    fun `creates a standard new-file diff and preserves line count`() {
        val diff = DiffRanges.synthesizeAddedDiff("src/a.ts", "one\ntwo\n")
        assertTrue(diff.contains("new file mode 100644"))
        assertTrue(diff.contains("@@ -0,0 +1,2 @@"))
        assertTrue(diff.trimEnd().endsWith("+one\n+two"))
    }

    @Test
    fun `handles an empty file`() {
        val diff = DiffRanges.synthesizeAddedDiff("empty.txt", "")
        assertTrue(diff.contains("@@ -0,0 +0,0 @@"))
    }
}
