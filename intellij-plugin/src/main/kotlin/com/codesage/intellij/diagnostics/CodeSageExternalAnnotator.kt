package com.codesage.intellij.diagnostics

import com.codesage.intellij.model.UnifiedSeverity
import com.intellij.lang.annotation.AnnotationHolder
import com.intellij.lang.annotation.ExternalAnnotator
import com.intellij.lang.annotation.HighlightSeverity
import com.intellij.openapi.util.TextRange
import com.intellij.psi.PsiDocumentManager
import com.intellij.psi.PsiFile
import java.nio.file.Path

/**
 * Renders the decisions taken by [FindingsCache] as daemon annotations, which
 * is what fills the editor gutter and the Problems view in an IntelliJ IDE.
 *
 * Only files that the daemon analyses (open editors) produce annotations; the
 * report panel remains the complete list. This is the one presentation
 * difference documented in PARITY.md.
 */
class CodeSageExternalAnnotator :
    ExternalAnnotator<List<FindingsCache.Placement>, List<FindingsCache.Placement>>() {

    override fun collectInformation(file: PsiFile): List<FindingsCache.Placement>? {
        val cache = file.project.getService(FindingsCache::class.java)
        val repoRoot = cache.repoRoot ?: return null
        val virtualFile = file.virtualFile ?: return null
        val relative = relativize(repoRoot, virtualFile.path) ?: return null
        return cache.placementsFor(relative).ifEmpty { null }
    }

    override fun doAnnotate(
        collectedInfo: List<FindingsCache.Placement>?,
    ): List<FindingsCache.Placement>? = collectedInfo

    override fun apply(
        file: PsiFile,
        annotationResult: List<FindingsCache.Placement>?,
        holder: AnnotationHolder,
    ) {
        if (annotationResult.isNullOrEmpty()) {
            return
        }
        val document = PsiDocumentManager.getInstance(file.project).getDocument(file) ?: return
        if (document.textLength == 0) {
            return
        }
        for (placement in annotationResult) {
            val startLineIndex = (placement.startLine - 1).coerceIn(0, document.lineCount - 1)
            val endLineIndex = (placement.endLine - 1).coerceIn(startLineIndex, document.lineCount - 1)
            val startOffset = document.getLineStartOffset(startLineIndex)
            val endOffset = minOf(
                maxOf(document.getLineEndOffset(endLineIndex), startOffset + 1),
                document.textLength,
            )
            if (endOffset <= startOffset) {
                continue
            }
            holder.newAnnotation(highlightFor(placement.severity), placement.message)
                .range(TextRange(startOffset, endOffset))
                .create()
        }
    }

    private fun highlightFor(severity: UnifiedSeverity): HighlightSeverity = when (severity) {
        UnifiedSeverity.CRITICAL, UnifiedSeverity.HIGH -> HighlightSeverity.ERROR
        UnifiedSeverity.MEDIUM -> HighlightSeverity.WARNING
        else -> HighlightSeverity.INFORMATION
    }

    private fun relativize(repoRoot: Path, absolutePath: String): String? {
        return try {
            val absolute = Path.of(absolutePath).toAbsolutePath().normalize()
            if (!absolute.startsWith(repoRoot)) {
                null
            } else {
                repoRoot.relativize(absolute).toString().replace('\\', '/')
            }
        } catch (_: Exception) {
            null
        }
    }
}
