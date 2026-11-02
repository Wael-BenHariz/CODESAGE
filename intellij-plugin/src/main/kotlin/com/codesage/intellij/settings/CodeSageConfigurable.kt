package com.codesage.intellij.settings

import com.intellij.openapi.options.Configurable
import com.intellij.ui.components.JBCheckBox
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.FormBuilder
import javax.swing.JComboBox
import javax.swing.JComponent

/**
 * Settings page mirroring the ten `codesage.*` keys of the VS Code extension.
 *
 * Numbers are clamped on apply with the same bounds the VS Code JSON schema
 * declares, so an out-of-range value can never reach the backend.
 */
class CodeSageConfigurable : Configurable {
    private var panel: JComponent? = null

    private val backendUrl = JBTextField()
    private val scope = JComboBox(arrayOf("workingTree", "staged"))
    private val includeUntracked = JBCheckBox("Include untracked files in working-tree reviews.")
    private val changedLinesOnly = JBCheckBox("Show diagnostics only on changed lines.")
    private val includeFileLevel = JBCheckBox("Show file-level diagnostics when a finding has no line number.")
    private val confirmBeforeSend = JBCheckBox("Ask for confirmation before sending local source code.")
    private val showSuggestions = JBCheckBox("Show suggestion text in highlights and the review report.")
    private val maxFiles = JBTextField()
    private val maxPayloadBytes = JBTextField()
    private val requestTimeoutMs = JBTextField()

    override fun getDisplayName(): String = "CodeSage"

    override fun createComponent(): JComponent {
        panel?.let { return it }
        val built = FormBuilder.createFormBuilder()
            .addLabeledComponent("Backend URL:", backendUrl)
            .addComponent(includeUntracked)
            .addComponent(changedLinesOnly)
            .addComponent(includeFileLevel)
            .addComponent(confirmBeforeSend)
            .addComponent(showSuggestions)
            .addLabeledComponent("Default review scope:", scope)
            .addLabeledComponent("Maximum changed files:", maxFiles)
            .addLabeledComponent("Maximum payload (bytes):", maxPayloadBytes)
            .addLabeledComponent("Request timeout (ms):", requestTimeoutMs)
            .addComponentFillVertically(javax.swing.JPanel(), 0)
            .panel
        panel = built
        reset()
        return built
    }

    override fun isModified(): Boolean {
        val state = CodeSageSettings.getInstance().state
        return backendUrl.text.trim() != state.backendUrl ||
            selectedScope() != state.reviewScope ||
            includeUntracked.isSelected != state.includeUntracked ||
            changedLinesOnly.isSelected != state.changedLinesOnly ||
            includeFileLevel.isSelected != state.includeFileLevel ||
            confirmBeforeSend.isSelected != state.confirmBeforeSend ||
            showSuggestions.isSelected != state.showSuggestions ||
            maxFiles.text.trim().toIntOrNull()?.coerceIn(1, 25) != state.maxFiles ||
            maxPayloadBytes.text.trim().toLongOrNull()?.coerceIn(1024L, 4L * 1024 * 1024) !=
            state.maxPayloadBytes ||
            requestTimeoutMs.text.trim().toLongOrNull()?.coerceIn(10_000L, 240_000L) !=
            state.requestTimeoutMs
    }

    override fun apply() {
        CodeSageSettings.getInstance().update { state ->
            state.backendUrl = backendUrl.text.trim().ifBlank { CodeSageSettings.DEFAULT_BACKEND_URL }
            state.reviewScope = selectedScope()
            state.includeUntracked = includeUntracked.isSelected
            state.changedLinesOnly = changedLinesOnly.isSelected
            state.includeFileLevel = includeFileLevel.isSelected
            state.confirmBeforeSend = confirmBeforeSend.isSelected
            state.showSuggestions = showSuggestions.isSelected
            state.maxFiles = parseMaxFiles(state.maxFiles)
            state.maxPayloadBytes = parseMaxPayload(state.maxPayloadBytes)
            state.requestTimeoutMs = parseTimeout(state.requestTimeoutMs)
        }
    }

    override fun reset() {
        val state = CodeSageSettings.getInstance().state
        backendUrl.text = state.backendUrl
        scope.selectedItem = if (state.reviewScope == "staged") "staged" else "workingTree"
        includeUntracked.isSelected = state.includeUntracked
        changedLinesOnly.isSelected = state.changedLinesOnly
        includeFileLevel.isSelected = state.includeFileLevel
        confirmBeforeSend.isSelected = state.confirmBeforeSend
        showSuggestions.isSelected = state.showSuggestions
        maxFiles.text = state.maxFiles.toString()
        maxPayloadBytes.text = state.maxPayloadBytes.toString()
        requestTimeoutMs.text = state.requestTimeoutMs.toString()
    }

    override fun disposeUIResources() {
        panel = null
    }

    private fun selectedScope(): String = scope.selectedItem as? String ?: "workingTree"

    private fun parseMaxFiles(current: Int): Int =
        maxFiles.text.trim().toIntOrNull()?.coerceIn(1, 25) ?: current

    private fun parseMaxPayload(current: Long): Long =
        maxPayloadBytes.text.trim().toLongOrNull()?.coerceIn(1024L, 4L * 1024 * 1024) ?: current

    private fun parseTimeout(current: Long): Long =
        requestTimeoutMs.text.trim().toLongOrNull()?.coerceIn(10_000L, 240_000L) ?: current
}
