// GENERATED FILE - do not edit.
// Produced by scripts/parity/emit-report-css.mjs from vscode-extension/src/render.ts.
// The stylesheet is copied verbatim so the IntelliJ report renders exactly like the
// VS Code webview. Run `node scripts/parity/emit-report-css.mjs` to regenerate.

package com.codesage.intellij.report

internal object ReportCss {
    val CSS: String = """    :root {
      --bg: #171717;
      --panel: #202020;
      --line: #3a332b;
      --text: #f3eee5;
      --muted: #b8ada0;
      --accent: #e0a84b;
      --accent-2: #6bb6a8;
      --danger: #ee6f68;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      color: var(--text);
      background:
        linear-gradient(135deg, rgba(224, 168, 75, 0.08), transparent 32%),
        linear-gradient(315deg, rgba(107, 182, 168, 0.07), transparent 28%),
        var(--bg);
      font-family: "Aptos", "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.55;
    }

    main {
      max-width: 860px;
      margin: 0 auto;
      padding: 22px;
    }

    header {
      border-bottom: 1px solid var(--line);
      margin-bottom: 18px;
      padding-bottom: 16px;
    }

    h1 {
      margin: 0;
      font-family: "Georgia", serif;
      font-size: 28px;
      font-weight: 600;
      letter-spacing: 0;
    }

    .subtitle {
      color: var(--muted);
      margin: 6px 0 0;
    }

    section {
      margin: 18px 0;
    }

    h2 {
      color: var(--accent);
      font-size: 13px;
      letter-spacing: 0;
      margin: 0 0 8px;
      text-transform: uppercase;
    }

    .summary,
    .issues,
    .excluded {
      background: rgba(32, 32, 32, 0.86);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
    }

    .summary .md p {
      margin: 8px 0;
    }

    .summary .md > :first-child {
      margin-top: 0;
    }

    .summary .md > :last-child {
      margin-bottom: 0;
    }

    .summary .md h3,
    .summary .md h4,
    .summary .md h5 {
      color: var(--accent);
      font-size: 12px;
      letter-spacing: 0.06em;
      margin: 16px 0 6px;
      text-transform: uppercase;
    }

    .summary .md ul,
    .summary .md ol {
      padding-left: 20px;
    }

    .summary .md li {
      margin: 4px 0;
    }

    .summary .md strong {
      color: var(--text);
      font-weight: 600;
    }

    .summary .md em {
      color: var(--muted);
    }

    .summary .md code {
      background: rgba(0, 0, 0, 0.28);
      border-radius: 4px;
      padding: 1px 4px;
    }

    ul {
      margin: 0;
      padding-left: 20px;
    }

    li {
      margin: 7px 0;
    }

    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 13px;
    }

    code {
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 13px;
    }

    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--accent-2);
      font-size: 12px;
      margin-top: 12px;
    }

    .status::before {
      background: var(--accent-2);
      border-radius: 50%;
      content: "";
      height: 8px;
      width: 8px;
    }

    .status-muted {
      color: var(--muted);
    }

    .status-muted::before {
      background: var(--muted);
    }

    .status-error {
      color: var(--danger);
    }

    .status-error::before {
      background: var(--danger);
    }

    .file-group {
      border-top: 1px solid var(--line);
      margin-top: 14px;
      padding-top: 14px;
    }

    .file-group:first-child {
      border-top: 0;
      margin-top: 0;
      padding-top: 0;
    }

    .file-head {
      align-items: baseline;
      display: flex;
      gap: 12px;
      justify-content: space-between;
      margin-bottom: 6px;
    }

    .file-path {
      color: var(--accent-2);
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 13px;
      word-break: break-word;
    }

    .file-count {
      color: var(--muted);
      font-size: 12px;
    }

    .finding {
      margin: 10px 0;
    }

    .finding-title {
      color: inherit;
      display: block;
      text-decoration: none;
    }

    .finding-title:hover .msg,
    .finding-title:focus .msg {
      text-decoration: underline;
    }

    .sev {
      font-size: 11px;
      letter-spacing: 0.08em;
      margin-right: 8px;
      text-transform: uppercase;
    }

    .sev-high {
      color: var(--danger);
    }

    .sev-medium {
      color: var(--accent);
    }

    .sev-low {
      color: var(--accent-2);
    }

    .sev-info {
      color: var(--muted);
    }

    .loc {
      color: var(--muted);
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 12px;
      margin-right: 8px;
    }

    .body,
    .suggestion {
      margin: 4px 0 0;
      white-space: pre-wrap;
    }

    .body {
      color: var(--muted);
    }

    .suggestion {
      color: var(--accent);
    }

    .suggestion a {
      color: var(--accent-2);
    }

    .source,
    .note {
      color: var(--muted);
      font-size: 12px;
      margin: 4px 0 0;
    }

    .note {
      font-style: italic;
    }

    .snippet {
      background: rgba(0, 0, 0, 0.25);
      border: 1px solid var(--line);
      border-radius: 6px;
      margin: 8px 0 0;
      padding: 8px 10px;
    }"""
}
