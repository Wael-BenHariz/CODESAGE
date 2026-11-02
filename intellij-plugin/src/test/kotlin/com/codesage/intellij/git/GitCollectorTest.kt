package com.codesage.intellij.git

import com.codesage.intellij.model.FileStatus
import com.codesage.intellij.model.ReviewScope
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.TimeUnit

/**
 * Port of `vscode-extension/test/git.test.ts`.
 *
 * Uses real Git repositories, exactly like the VS Code suite, so the payload
 * shape is verified against the same `git` invocations.
 */
class GitCollectorTest {

    private val repositories = mutableListOf<Path>()

    private val options = GitCollector.Options(
        scope = ReviewScope.WORKING_TREE,
        includeUntracked = true,
        maxFiles = 25,
        maxPayloadBytes = 4L * 1024 * 1024,
    )

    @After
    fun cleanUp() {
        for (repository in repositories) {
            repository.toFile().deleteRecursively()
        }
    }

    @Test
    fun `collects modified, untracked, deleted and spaced paths without mutating git state`() {
        val dir = createRepo()
        commitInitial(
            dir,
            mapOf(
                "src/a.ts" to "export const a = 1;\n",
                "src/delete.ts" to "gone\n",
                "src/rename.ts" to "rename me\n",
            ),
        )

        Files.writeString(dir.resolve("src/a.ts"), "export const a = 2;\n")
        Files.writeString(dir.resolve("src/new file.ts"), "new\n")
        Files.delete(dir.resolve("src/delete.ts"))
        Files.move(dir.resolve("src/rename.ts"), dir.resolve("src/renamed.ts"))

        val before = statusSnapshot(dir)
        val collection = GitCollector.collect(dir, options)
        val after = statusSnapshot(dir)

        assertEquals(before, after)
        val paths = collection.files.map { it.path }
        assertTrue(paths.containsAll(listOf("src/a.ts", "src/new file.ts", "src/renamed.ts")))
        assertEquals(
            FileStatus.DELETED,
            collection.snapshot.files.first { it.path == "src/delete.ts" }.status,
        )
        assertEquals(
            FileStatus.DELETED,
            collection.snapshot.files.first { it.path == "src/rename.ts" }.status,
        )
        assertEquals(
            FileStatus.ADDED,
            collection.snapshot.files.first { it.path == "src/renamed.ts" }.status,
        )
        assertTrue(collection.diff.contains("src/new file.ts"))
        assertTrue(collection.diff.contains("src/a.ts"))
        assertTrue(collection.files.first { it.path == "src/a.ts" }.content.contains("2"))
    }

    @Test
    fun `keeps oldPath for a staged rename`() {
        val dir = createRepo()
        commitInitial(dir, mapOf("src/old.ts" to "same content\n"))
        Files.move(dir.resolve("src/old.ts"), dir.resolve("src/new.ts"))
        git(dir, "add", "-A")

        val collection = GitCollector.collect(dir, options.copy(scope = ReviewScope.STAGED))
        val renamed = collection.snapshot.files.first { it.path == "src/new.ts" }
        assertEquals(FileStatus.RENAMED, renamed.status)
        assertEquals("src/old.ts", renamed.oldPath)
    }

    @Test
    fun `reads staged content from the index, not the working tree`() {
        val dir = createRepo()
        commitInitial(dir, mapOf("a.ts" to "base\n"))

        Files.writeString(dir.resolve("a.ts"), "staged\n")
        git(dir, "add", "a.ts")
        Files.writeString(dir.resolve("a.ts"), "worktree\n")

        val staged = GitCollector.collect(dir, options.copy(scope = ReviewScope.STAGED))
        val working = GitCollector.collect(dir, options)

        assertEquals("staged\n", staged.files.first { it.path == "a.ts" }.content)
        assertEquals("worktree\n", working.files.first { it.path == "a.ts" }.content)
    }

    @Test
    fun `excludes binary files with a reason`() {
        val dir = createRepo()
        commitInitial(dir, mapOf("a.txt" to "hello\n"))
        Files.writeString(dir.resolve("a.txt"), "hello again\n")
        Files.write(dir.resolve("binary.bin"), byteArrayOf(0, 1, 2, 3))

        val collection = GitCollector.collect(dir, options)
        assertFalse(collection.files.any { it.path == "binary.bin" })
        assertTrue(collection.excluded.any { it.path == "binary.bin" && it.reason == "binary file" })
    }

    @Test
    fun `throws a clear error when there is nothing to review`() {
        val dir = createRepo()
        commitInitial(dir, mapOf("a.txt" to "clean\n"))
        try {
            GitCollector.collect(dir, options)
            fail("expected NoChangesError")
        } catch (_: NoChangesError) {
            // expected
        }
    }

    @Test
    fun `builds a language and snapshot payload for the backend`() {
        val dir = createRepo()
        commitInitial(dir, mapOf("a.py" to "print(1)\n"))
        Files.writeString(dir.resolve("a.py"), "print(2)\n")

        val collection = GitCollector.collect(dir, options)
        val request = GitCollector.buildReviewRequest(collection, ReviewScope.WORKING_TREE)

        assertEquals(1, request.schemaVersion)
        assertEquals("python", request.language)
        assertEquals(64, request.snapshot.files.first().contentSha256?.length)
        assertEquals("print(2)\n", request.files.first().content)
    }

    // ------------------------------------------------------------------

    private fun createRepo(): Path {
        val dir = Files.createTempDirectory("codesage-intellij-git-")
        repositories.add(dir)
        git(dir, "init", "-q")
        git(dir, "config", "user.email", "test@example.com")
        git(dir, "config", "user.name", "Test User")
        return dir
    }

    private fun commitInitial(dir: Path, files: Map<String, String>) {
        for ((name, content) in files) {
            val absolute = dir.resolve(name)
            Files.createDirectories(absolute.parent)
            Files.writeString(absolute, content)
        }
        git(dir, "add", ".")
        git(dir, "commit", "-q", "-m", "initial")
    }

    private fun statusSnapshot(dir: Path): String {
        val process = ProcessBuilder(
            "git", "--no-optional-locks", "status", "--porcelain=v2", "-z", "--branch",
        )
            .directory(dir.toFile())
            .redirectErrorStream(true)
            .start()
        val output = process.inputStream.readBytes().toString(Charsets.UTF_8)
        process.waitFor(30, TimeUnit.SECONDS)
        return output
    }

    private fun git(cwd: Path, vararg args: String): String {
        val process = ProcessBuilder(listOf("git") + args)
            .directory(cwd.toFile())
            .redirectErrorStream(true)
            .start()
        val output = process.inputStream.readBytes().toString(Charsets.UTF_8)
        assertTrue("git $args failed: $output", process.waitFor(60, TimeUnit.SECONDS))
        assertEquals("git $args failed: $output", 0, process.exitValue())
        return output
    }
}
