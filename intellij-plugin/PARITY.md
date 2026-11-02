# Parity — CodeSage IntelliJ plugin vs VS Code extension

**Reference:** `vscode-extension/` version **0.1.1**, commit `87f910a`
(`feat(vscode): replace the tree view with a CodeSage review panel`).
**Plugin version:** `0.1.0` (deliberately not lockstep with the extension).

This file is the contract: anything that differs from the extension is listed here, with the
reason. Anything not listed is intended to be identical.

## 1. Definition of parity

| Layer | Claim | Proof |
|---|---|---|
| Review payload | Identical request body (snapshot, diff, files, title, description, language) | Same `git` argv, same caps/order/exclusion reasons; real-temp-repo tests ported from `git.test.ts` |
| Selection logic | Same inclusion rules, same exclusion reasons, same severity tables | Ported unit tests (`SeverityTest`, `DiffRangesTest`, `GitCollectorTest`) |
| Inline findings | Same findings chosen for inline display, same skip reason keys/labels | `FindingsCache` port of `diagnostics.ts`; byte-identical note labels in the report |
| Report HTML/CSS | **Byte-identical** to `render.ts` output for every fixture | `RendererParityTest` vs goldens generated from the real VS Code renderer |
| Strings | All user-visible strings copied verbatim | Centralised in `ReviewController`/`Renderer`/`Notifications` |
| Command surface | Same 9 contributed commands + hidden `openFinding`/`copySuggestion` | `plugin.xml` actions and report links |
| Settings | Same keys, defaults and min/max | `CodeSageSettings` / `CodeSageConfigurable` |
| Dev-token auth | Same header, same key, same prompt text | `DevTokenAuthProvider` |
| HTTP contract | Same endpoint, DTOs, error extraction, timeout/cancel semantics | `CodeSageClient`, `ApiMappingTest` |
| Request body encoding | Byte-identical to `JSON.stringify` (`null` kept, markup not escaped, same key order) | `CodeSageGson` (`serializeNulls` + `disableHtmlEscaping`) + `ApiMappingTest` |

## 2. Accepted deviations

| # | Area | VS Code | IntelliJ port | Why / impact |
|---|---|---|---|---|
| D1 | Report rendering | Webview (Chromium) | JCEF (`JBCefBrowser`) inside the `CodeSage` tool window | Same engine, same HTML/CSS → byte-identical report. No editor tab and no external browser |
| D2 | Inline findings | `DiagnosticCollection` (any file) | `ExternalAnnotator` + `FindingsCache` | Platform limitation: external annotators run only for files the daemon analyses (open editors). The report remains the complete list. Annotations use the same severity map and message text |
| D3 | Progress / notifications | Notification progress + balloons | `Task.Backgroundable` + balloon notifications | Platform chrome; text and cancellation semantics match |
| D4 | Output channel | `OutputChannel "CodeSage"` | `CodeSage Output` tool window console (`TextConsole`) | Same lines (`review completed: …`, `review failed: …`). A dedicated tool window because IntelliJ has no output-channel channel list |
| D5 | Per-tab editor button | `editor/title` contribution | Tools submenu + tab context menu + main toolbar | IntelliJ has no per-editor title-bar action slot |
| D6 | JSON | `JSON.stringify` / typed fetch mapping | **Gson** (bundled with the platform) instead of kotlinx.serialization | Avoids a Kotlin compiler plugin and an extra bundled jar. Configured with `serializeNulls()` + `disableHtmlEscaping()` so the request body matches `JSON.stringify` byte-for-byte; keys and defaults asserted by `ApiMappingTest`. *Plan assumed kotlinx.serialization* |
| D7 | Settings scope | Workspace settings (`.vscode/settings.json`) | **Application-level** `PersistentStateComponent` (`codesage.xml`) | *Plan assumed project-level.* An application `Configurable` cannot reliably receive a `Project`, and IntelliJ configuration pages are IDE-wide. Same keys/defaults; values apply to all projects in the IDE |
| D8 | Token storage | `SecretStorage` (user scope) | `PasswordSafe` (application scope) | Equivalent scope; same key name and header |
| D9 | Folder selection | Workspace folder / active editor / quick pick | Project base directory | IntelliJ opens one project at a time. Multi-root content roots are not offered as a picker; `PARITY.md` records it rather than guessing |
| D10 | Icons | Codicon `$(play)`, `$(checklist)`, … | `AllIcons` + one custom 13×13 SVG for the tool window | Glyphs are visually equivalent, not pixel-identical (platform icon set) |
| D11 | Fonts | Georgia / Aptos / Segoe UI / Cascadia Code | Same CSS stacks | Identical on hosts that have those fonts (Windows/macOS); Linux substitutes. Documented rather than silently changed |
| D12 | JCEF unavailable | n/a | **Same `CodeSage` tool window**, rendering a simplified HTML 3.2 document in a `JEditorPane` plus a banner explaining the downgrade | `JBCefApp.isSupported()` guard. The report is never handed to an external browser; `command:` links keep working through a `HyperlinkListener` |
| D13 | `command:` links | `enableCommandUris: true` | CEF `onBeforeBrowse` interception, navigation cancelled | Keeps HTML **and** CSP byte-identical (no injected scripts) |
| D14 | Git error text | `Error.message` from `execFile` | `stderr`/`stdout` tail of the failed command | Same prefix `git <subcommand> failed:`; execFile embeds “Command failed: …” which is Node-specific |
| D15 | Review completion notification | `showInformationMessage` | Balloon in the notification group | Same text, same trigger |
| D16 | Report failure diagnostics | n/a | One line in the `CodeSage Output` window when the report falls back to the simplified view or fails to render | A silent JCEF/render failure otherwise looks like "the report is empty"; the report itself stays byte-identical |

## 3. Behaviour intentionally preserved (quirks)

These look like bugs but are part of parity — do not “fix” them without changing the extension:

1. `codesage.reviewScope` is effectively a **no-op**: both commands pass an explicit scope, so the
   setting is only used by the fallback path in `ReviewController.run(scope = null)`.
2. `CodeSageClient.health()`, `ReportPanel.isOpen`, `AuthProvider.describe()`,
   `overallSeverity()` and `Finding.reason` are decoded/present but **never rendered**.
3. `degradedReasons` and `diffTruncated` appear **only in the output channel**, never in the report.
4. The report is script-free and keeps `Content-Security-Policy: default-src 'none'`.
5. Confirmation dialog includes the exact `Backend`/`Mode`/`Scope`/`Files`/`Transport`/
   `Excluded`/non-loopback warning block.
6. `class="status "` keeps a trailing space when there is no status modifier class.
7. Findings sort severity **descending**, then file (English collator ≈ `localeCompare`), then line.
8. `body` is hidden when it equals `message`; `Source:` appears only when `tool` **or** `ruleId`
   exists, with `· also detected by …` appended when present.

## 4. Verification status

Verified on 2026-11-02 in a `gradle:8.10-jdk17` container (no JDK/Gradle on the host), against
platform `ideaIC-2023.3`, plugin `0.1.0`:

| Gate | Command | Status |
|---|---|---|
| Renderer goldens regenerate from `render.ts` | `node scripts/parity/emit-golden.mjs --check` | **green** — 11/11 goldens match |
| CSS extraction matches `render.ts` | `node scripts/parity/emit-report-css.mjs --check` | **green** — 287 CSS lines |
| Kotlin unit + parity tests | `gradle check` | **green** — 51 tests, 0 failures |
| Report byte parity | `RendererParityTest` (inside `check`) | **green** — 11/11 fixtures byte-identical to the VS Code renderer |
| Git payload parity | `GitCollectorTest` (inside `check`) | **green** — 6 real-temp-repo tests, incl. “git status unchanged” |
| Plugin zip | `gradle buildPlugin` | **green** — `build/distributions/codesage-intellij-0.1.0.zip` (198 KB, one jar) |
| `plugin.xml` bounds | after `patchPluginXml` | `since-build="233"`, **no** `until-build` (all 2023.3+ IDEs) |
| Plugin verifier | `gradle verifyPlugin` | **compatible** with IC **2024.3** (`-PverifierIde=2024.3`) and IC **2025.1** (default), in separate runs; one deprecated `CredentialAttributes` constructor reported in both |
| Manual IDE checklist | `README.md` §Manual checklist | pending (no test accounts/IDE session) |

Test inventory (51): `RendererParityTest` 1, `RendererTest` 11, `FindingsCacheTest` 9,
`GitCollectorTest` 6, `DiffRangesTest` 7, `SeverityTest` 5, `HtmlTest` 5, `ApiMappingTest` 4,
`BackendSampleTest` 3 (a captured real `POST /local-reviews/dev` response: 2 files, 8 static
findings, rendered through DTOs → `ApiMapping` → both report views).

## 5. Build notes

- Built with `org.jetbrains.intellij.platform` **2.1.0**, Kotlin **2.0.21**, toolchain **17**,
  platform `intellijIdeaCommunity("2023.3")`, `sinceBuild=233`, no `untilBuild`.
- The `plugin.xml` ID and Gradle-patched ID are both `com.codesage.localreview`. The verifier
  rejects the word `intellij` in plugin IDs, so this differs from the package namespace.
- `instrumentationTools()` is required by the platform plugin 2.x (`instrumentCode` fails
  without it), and `kotlin.stdlib.default.dependency=false` keeps the platform stdlib.
- Three API details worth knowing when touching the code:
  - `Task` has **no** `cancel()`; `codesage.cancelReview` cancels the stored
    `ProgressIndicator` from `Task.Backgroundable.run`.
  - The report is a `toolWindow` (`CodeSage`, anchor right) backed by a project service; there is
    no `FileEditorProvider` and no editor split any more (the first version opened a light virtual
    file in an editor and fell back to a browser when that failed — both paths are gone).
  - Token input uses `Messages.showPasswordDialog` (`showPasswordInputDialog` does not exist in 233).
- **Request bodies stay byte-identical to `JSON.stringify`** (`api.ts`): `CodeSageGson` uses
  `serializeNulls()` (so `"base_revision":null` is present) and `disableHtmlEscaping()`
  (so `<`, `>`, `&` in diffs are not written as `\u003c`). `ApiMappingTest` asserts both.
- `GitRunner` captures **raw bytes** with `ProcessBuilder` (233's `ProcessOutput` has no
  `getStdoutBytes()`), so file contents and their SHA-256 match the `execFile` buffers.
- The report stylesheet is generated into `report/ReportCss.kt` by
  `scripts/parity/emit-report-css.mjs` (verbatim copy of the `<style>` block), so the CSS cannot
  drift silently.
- Goldens are generated by bundling `vscode-extension/src/render.ts` with the esbuild already
  installed in `vscode-extension/node_modules`; the extension is imported read-only.
- `verifyPlugin` can only check **one IDE version per product per run**: plugin 2.1.0 adds every
  `ide(...)` coordinate to the single `intellijPluginVerifierIdesDependency` configuration, so
  `ide("IC","2024.3")` + `ide("IC","2025.1")` resolve to 2025.1 only (Gradle conflict
  resolution). The build therefore declares one IDE (`-PverifierIde=…`, default 2025.1).
- No Gradle wrapper is committed; the Docker invocation in `README.md` is the supported path here.
