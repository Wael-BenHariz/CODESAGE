package com.codesage.intellij.git

import java.io.ByteArrayOutputStream
import java.nio.file.Path
import java.util.concurrent.TimeUnit

class GitError(message: String) : RuntimeException(message)

class NoChangesError : RuntimeException("No reviewable Git changes were found.")

/**
 * Runs the system `git` binary with the same arguments as the VS Code
 * extension. JGit is deliberately not used: it normalises paths and diffs
 * differently, which would change the review payload.
 *
 * Output is captured as raw bytes (not decoded and re-encoded), so the file
 * contents and their SHA-256 hashes match the `execFile` buffers the VS Code
 * extension sends to the backend.
 */
object GitRunner {
    private const val TIMEOUT_SECONDS = 600L

    fun text(cwd: Path, args: List<String>): String = run(cwd, args).stdout

    fun bytes(cwd: Path, args: List<String>): ByteArray = run(cwd, args).stdoutBytes

    private fun run(cwd: Path, args: List<String>): Parsed {
        val command = listOf("git", "--no-optional-locks") + args
        val process = try {
            ProcessBuilder(command).directory(cwd.toFile()).start()
        } catch (error: Exception) {
            throw GitError("git ${args.firstOrNull() ?: ""} failed: ${error.message}")
        }

        val stderrBytes = ByteArrayOutputStream()
        val drain = Thread {
            try {
                process.errorStream.copyTo(stderrBytes)
            } catch (_: Exception) {
                // The process exiting closes the stream; nothing to report here.
            }
        }.apply {
            isDaemon = true
            start()
        }

        val stdoutBytes = try {
            process.inputStream.readBytes()
        } catch (error: Exception) {
            process.destroyForcibly()
            throw GitError("git ${args.firstOrNull() ?: ""} failed: ${error.message}")
        }

        if (!process.waitFor(TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            process.destroyForcibly()
            throw GitError("git ${args.firstOrNull() ?: ""} failed: timed out after $TIMEOUT_SECONDS s")
        }
        drain.join(5_000)

        val stdout = stdoutBytes.toString(Charsets.UTF_8)
        val stderr = stderrBytes.toByteArray().toString(Charsets.UTF_8)
        if (process.exitValue() != 0) {
            val detail = stderr.ifBlank { stdout }.trim()
            throw GitError("git ${args.firstOrNull() ?: ""} failed: $detail")
        }
        return Parsed(stdout, stdoutBytes)
    }

    private class Parsed(val stdout: String, val stdoutBytes: ByteArray)
}
