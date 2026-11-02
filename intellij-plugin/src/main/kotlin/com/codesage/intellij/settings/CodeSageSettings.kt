package com.codesage.intellij.settings

import com.codesage.intellij.model.ReviewScope
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.components.service

/**
 * Port of the `codesage.*` settings from `vscode-extension/package.json`.
 *
 * Keys, defaults and min/max values are identical. The only structural
 * difference is scope: IntelliJ has no workspace-level settings service that a
 * configuration page can receive, so these live once per IDE installation
 * instead of once per project (documented in PARITY.md).
 */
@State(name = "CodeSageSettings", storages = [Storage("codesage.xml")])
@Service(Service.Level.APP)
class CodeSageSettings : PersistentStateComponent<CodeSageSettings.State> {

    data class State(
        var backendUrl: String = DEFAULT_BACKEND_URL,
        var authMode: String = "dev",
        var reviewScope: String = "workingTree",
        var includeUntracked: Boolean = true,
        var changedLinesOnly: Boolean = true,
        var includeFileLevel: Boolean = true,
        var confirmBeforeSend: Boolean = true,
        var maxFiles: Int = 25,
        var maxPayloadBytes: Long = 4L * 1024 * 1024,
        var requestTimeoutMs: Long = 240_000L,
        var showSuggestions: Boolean = true,
    )

    private var myState = State()

    override fun getState(): State = myState

    override fun loadState(state: State) {
        myState = state
    }

    val config: CodeSageConfig
        get() = CodeSageConfig.from(myState)

    fun update(transform: (State) -> Unit) {
        transform(myState)
    }

    companion object {
        const val DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"

        fun getInstance(): CodeSageSettings = service()
    }
}

/** Immutable snapshot of the settings, read once per review like `readConfig()`. */
data class CodeSageConfig(
    val backendUrl: String,
    val reviewScope: ReviewScope,
    val includeUntracked: Boolean,
    val changedLinesOnly: Boolean,
    val includeFileLevel: Boolean,
    val confirmBeforeSend: Boolean,
    val maxFiles: Int,
    val maxPayloadBytes: Long,
    val requestTimeoutMs: Long,
    val showSuggestions: Boolean,
) {
    companion object {
        fun from(state: CodeSageSettings.State): CodeSageConfig = CodeSageConfig(
            backendUrl = state.backendUrl.ifBlank { CodeSageSettings.DEFAULT_BACKEND_URL },
            reviewScope = ReviewScope.fromWire(state.reviewScope),
            includeUntracked = state.includeUntracked,
            changedLinesOnly = state.changedLinesOnly,
            includeFileLevel = state.includeFileLevel,
            confirmBeforeSend = state.confirmBeforeSend,
            maxFiles = state.maxFiles.coerceIn(1, 25),
            maxPayloadBytes = state.maxPayloadBytes.coerceIn(1024L, 4L * 1024 * 1024),
            requestTimeoutMs = state.requestTimeoutMs.coerceIn(10_000L, 240_000L),
            showSuggestions = state.showSuggestions,
        )
    }
}
