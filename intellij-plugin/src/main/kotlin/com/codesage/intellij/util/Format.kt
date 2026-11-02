package com.codesage.intellij.util

import java.security.MessageDigest
import java.util.Locale

object ByteFormat {
    /** Port of `formatBytes` from `vscode-extension/src/controller.ts`. */
    fun format(bytes: Long): String = when {
        bytes < 1024 -> "$bytes B"
        bytes < 1024 * 1024 -> String.format(Locale.ROOT, "%.1f KiB", bytes / 1024.0)
        else -> String.format(Locale.ROOT, "%.1f MiB", bytes / (1024.0 * 1024.0))
    }
}

object Sha256 {
    fun hex(bytes: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
        val out = StringBuilder(digest.size * 2)
        for (byte in digest) {
            val value = byte.toInt() and 0xFF
            out.append("0123456789abcdef"[value shr 4]).append("0123456789abcdef"[value and 0xF])
        }
        return out.toString()
    }
}
