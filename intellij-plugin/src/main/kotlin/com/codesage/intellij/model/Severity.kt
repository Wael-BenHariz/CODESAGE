package com.codesage.intellij.model

import java.text.Collator
import java.util.Locale

/**
 * Port of `vscode-extension/src/severity.ts`.
 *
 * Kind ordering matches the VS Code implementation: static findings keep the
 * five-level scale, agent findings are mapped honestly, and unknown values fall
 * back to `info` rather than being dropped.
 */
object Severity {
    private val AGENT_SEVERITY = mapOf(
        "suggestion" to UnifiedSeverity.LOW,
        "info" to UnifiedSeverity.INFO,
        "warning" to UnifiedSeverity.MEDIUM,
        "error" to UnifiedSeverity.HIGH,
    )

    private val STATIC_SEVERITY = mapOf(
        "info" to UnifiedSeverity.INFO,
        "low" to UnifiedSeverity.LOW,
        "medium" to UnifiedSeverity.MEDIUM,
        "high" to UnifiedSeverity.HIGH,
        "critical" to UnifiedSeverity.CRITICAL,
    )

    val RANK: Map<UnifiedSeverity, Int> = mapOf(
        UnifiedSeverity.INFO to 0,
        UnifiedSeverity.LOW to 1,
        UnifiedSeverity.MEDIUM to 2,
        UnifiedSeverity.HIGH to 3,
        UnifiedSeverity.CRITICAL to 4,
    )

    fun normalize(value: String?, source: FindingSource): UnifiedSeverity {
        val key = value?.lowercase(Locale.ROOT) ?: ""
        if (source == FindingSource.STATIC) {
            return STATIC_SEVERITY[key] ?: UnifiedSeverity.INFO
        }
        return AGENT_SEVERITY[key] ?: STATIC_SEVERITY[key] ?: UnifiedSeverity.INFO
    }

    fun overall(value: String?): UnifiedSeverity {
        val key = value?.lowercase(Locale.ROOT) ?: ""
        return when (key) {
            "error" -> UnifiedSeverity.CRITICAL
            "warning" -> UnifiedSeverity.MEDIUM
            "suggestion" -> UnifiedSeverity.LOW
            else -> STATIC_SEVERITY[key] ?: UnifiedSeverity.INFO
        }
    }

    /**
     * Severity descending, then file ascending, then line ascending.
     *
     * `localeCompare` in the VS Code renderer is locale aware; an English
     * collator reproduces its ordering for the common case (and the goldens
     * pin it for ASCII paths).
     */
    fun compareFindings(
        leftSeverity: UnifiedSeverity,
        leftFile: String,
        leftLine: Int?,
        rightSeverity: UnifiedSeverity,
        rightFile: String,
        rightLine: Int?,
    ): Int {
        val severity = RANK.getValue(rightSeverity) - RANK.getValue(leftSeverity)
        if (severity != 0) {
            return severity
        }
        val file = collator().compare(leftFile, rightFile)
        if (file != 0) {
            return file
        }
        return (leftLine ?: Int.MAX_VALUE) - (rightLine ?: Int.MAX_VALUE)
    }

    fun compareFindings(left: Finding, right: Finding): Int = compareFindings(
        left.severity,
        left.filePath,
        left.lineStart,
        right.severity,
        right.filePath,
        right.lineStart,
    )

    private fun collator(): Collator = Collator.getInstance(Locale.ENGLISH)
}
