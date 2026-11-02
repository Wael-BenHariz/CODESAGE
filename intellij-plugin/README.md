# CodeSage Local Review — IntelliJ plugin

Kotlin/IntelliJ-Platform port of the CodeSage **VS Code extension** (`vscode-extension/`, v0.1.1).
Same commands, same settings, same Git payload, same findings, same report — rendered with the
**same HTML and stylesheet** as the VS Code webview, inside JCEF.

The VS Code extension is the reference implementation and is **not modified** by this module.

- Parity matrix and accepted deviations: [`PARITY.md`](PARITY.md)
- VS Code source of truth: `vscode-extension/src/` @ `87f910a`

## Requirements

| Requirement | Notes |
|---|---|
| IntelliJ-based IDE **2023.3+** (`since-build=233`) | IntelliJ IDEA, PyCharm, WebStorm, GoLand, Rider, … |
| JCEF enabled | Bundled and enabled by default. If unavailable, the report still opens in the **CodeSage tool window** as a simplified (no-CSS) view |
| `git` on `PATH` | The collector shells out to the CLI, exactly like the VS Code extension (no JGit) |
| CodeSage backend with dev mode | `POST /api/v1/local-reviews/dev`, loopback only |

## Build and run

The repo host has no JDK/Gradle, so the supported local build uses Docker (same pattern as
`repo-tenant-service`):

```bash
# Compile + unit/parity tests
docker run --rm -u "$(id -u):$(id -g)" \
  -v "$PWD/intellij-plugin":/workspace \
  -v codesage-gradle:/home/gradle/.gradle \
  -w /workspace gradle:8.10-jdk17 gradle check

# Installable zip -> intellij-plugin/build/distributions/
docker run --rm -u "$(id -u):$(id -g)" \
  -v "$PWD/intellij-plugin":/workspace \
  -v codesage-gradle:/home/gradle/.gradle \
  -w /workspace gradle:8.10-jdk17 gradle buildPlugin
```

With a local JDK 17 + Gradle 8.5+ installed, plain `gradle check buildPlugin` works from
`intellij-plugin/`. Install the zip via **Settings → Plugins → ⚙ → Install Plugin from Disk…**.

**Status of the gates (last run 2026-11-02):** `gradle check` → **51 tests, 0 failures**
(includes the 11-fixture byte-parity gate, a real backend response render test, the
inline-annotation decision tests and the real-temp-repo Git tests);
`gradle buildPlugin` → `build/distributions/codesage-intellij-0.1.0.zip` (~198 KB);
`node scripts/parity/emit-golden.mjs --check` and `emit-report-css.mjs --check` → green.
`gradle verifyPlugin` reports the plugin compatible with IntelliJ IDEA **2024.3** and **2025.1**
(one deprecated PasswordSafe credential-attributes constructor warning in both; plugin 2.1.0
verifies one IDE version per product per run, see `PARITY.md` §5).
These checks plus `gradle verifyPlugin` are wired into the `intellij-plugin` job in
`.github/workflows/ci-cd.yaml`; it uploads the installable ZIP as a workflow artifact. The plugin
declares `since-build=233` with **no** `until-build`, so every 2023.3+ IDE accepts it. See
`PARITY.md` §4 for the full table; the manual IDE checklist below is still pending.

Run a sandbox IDE with the plugin:

```bash
gradle runIde        # or the Docker command with `runIde`
```

## Commands

Every command from `vscode-extension/package.json`, with identical titles:

| Command | Where |
|---|---|
| `CodeSage: Review Local Changes` | Tools → CodeSage, tab context menu, main toolbar |
| `CodeSage: Review Staged Changes` | Tools → CodeSage |
| `CodeSage: Cancel Review` | Tools → CodeSage |
| `CodeSage: Clear Results` | Tools → CodeSage |
| `CodeSage: Show Review Report` | Tools → CodeSage |
| `CodeSage: Set Development Token` | Tools → CodeSage |
| `CodeSage: Show Output` | Tools → CodeSage (`CodeSage Output` tool window) |
| `CodeSage: Open Settings` | Tools → CodeSage, Settings → CodeSage |
| `codesage.openFinding` / `codesage.copySuggestion` | Report links only (hidden, like the VS Code palette entries) |

Findings also appear as editor annotations (gutter + Problems view) for **open** files; the
report is the complete list.

## Where the report appears

The report is the **`CodeSage` tool window** (right side dock) — the port of the VS Code
`WebviewPanel`. Nothing is opened in an external browser. It renders the byte-identical VS Code
HTML in an embedded browser (JCEF); if JCEF is disabled (`-Dide.browser.jcef.enabled=false`) or
missing, the same report is shown in the same tool window as a simplified HTML 3.2 view with a
banner explaining the downgrade. Closing the tool window keeps the results; `CodeSage: Show
Review Report` brings them back.

## Settings (Settings → CodeSage)

All ten `codesage.*` keys, defaults and min/max identical to the VS Code schema:

| Key | Default | Bounds |
|---|---|---|
| `backendUrl` | `http://127.0.0.1:8000` | http/https |
| `authMode` | `dev` | dev only (as in VS Code) |
| `reviewScope` | `workingTree` | `workingTree` / `staged` |
| `includeUntracked` | `true` | — |
| `changedLinesOnly` | `true` | — |
| `includeFileLevel` | `true` | — |
| `confirmBeforeSend` | `true` | — |
| `maxFiles` | `25` | 1–25 |
| `maxPayloadBytes` | `4194304` | 1024–4194304 |
| `requestTimeoutMs` | `240000` | 10000–240000 |
| `showSuggestions` | `true` | — |

Settings are stored **per IDE installation** (`codesage.xml` in the IDE config), not per project.
See `PARITY.md` §“Deviation D8” for why.

## Development token

`CodeSage: Set Development Token` stores the token in the IDE password safe
(`PasswordSafe`, application level) under the same key the VS Code extension uses
(`codesage.devToken`) and sends it as `X-CodeSage-Dev-Token`. Leave the field empty to clear it.
It must match `LOCAL_REVIEW_DEV_TOKEN` on the backend, and the backend must run with
`LOCAL_REVIEW_DEV_MODE=true`.

## Parity verification

The report renderer is asserted **byte-for-byte** against the real VS Code renderer:

```bash
# Regenerate the goldens from vscode-extension/src/render.ts (needs vscode-extension/node_modules)
node scripts/parity/emit-golden.mjs

# CI-style drift check (no writes)
node scripts/parity/emit-golden.mjs --check
node scripts/parity/emit-report-css.mjs --check
```

- `src/test/resources/parity/fixtures.json` — 11 report states (loading/cancelled/error + result
  variants: full, empty, escaped, markdown, file-level, all skip reasons, excluded files,
  encoding edge cases).
- `src/test/resources/parity/expected/*.html` — generated by the **real** VS Code renderer
  (esbuild bundle of `render.ts`), never by hand.
- `RendererParityTest` re-renders the fixtures with the Kotlin renderer and fails on any
  character difference.

Other tests mirror the VS Code suite: severity tables/comparator, diff/hunk logic, escaping and
`command:` URI encoding, JSON contract, and real-temp-repo Git collection (including the
“git status unchanged after collection” assertion).

## Manual checklist

Automated gates cannot cover IDE chrome; run `runIde` and check:

1. Review local changes (working tree) → the `CodeSage` tool window opens on the right with the report, annotations appear.
2. Review staged changes → only staged files in the report.
3. Cancel mid-review → “Review cancelled” state, no error balloon.
4. Start a second review while one runs → “A CodeSage review is already running.”
5. Missing token → prompt offers “Set Development Token”; cancel aborts the review.
6. Invalid token → “The CodeSage development token is invalid. Set it again and retry.”
7. Backend dev mode off (404) → “CodeSage dev mode is not enabled on this backend …”.
8. Non-Git project folder → “Open a Git repository folder first.” / Git error message.
9. Oversized payload → 413 friendly message.
10. Report links: finding title opens the file at the line; `Copy` copies the suggestion.
11. `Clear Results` removes annotations and hides the report tool window.
12. `Show Review Report` reopens the tool window with the last report.
13. Settings persist across IDE restart; out-of-range values clamp.
14. `Show Output` reveals the `CodeSage Output` tool window with the completion line.
15. Untracked files included/excluded according to the setting.
16. Changed-lines-only off shows every finding inline.
17. Non-loopback backend URL shows the “source code leaves this machine” warning.
18. JCEF disabled (`-Dide.browser.jcef.enabled=false`) → the report still appears in the `CodeSage`
    tool window (simplified view + banner); no external browser window opens.
19. No browser window opens at any point during or after a review.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| “Missing CodeSage development token …” | Set it with `CodeSage: Set Development Token` |
| Report shows the simplified view + banner | JCEF is disabled or unavailable; the `CodeSage Output` window logs the reason. Enable JCEF in the IDE registry to get the styled report |
| No inline annotations | External annotators only run for files **open in the editor**, and with `changedLinesOnly` (default) only on lines of the reviewed diff — the report shows `Not shown inline: …` per finding. Turn `changedLinesOnly` off to annotate the whole file |
| `git … failed: …` | The project folder is not a Git repository, or Git is missing from `PATH` |
| “Review failed” with no detail | Check the `CodeSage Output` tool window (`Show Output`) for the exact message |

## Scope

Internal, install-from-disk distribution (`buildPlugin`). No Marketplace metadata, signing or
publishing in this version. No backend, API-contract or VS Code changes.
