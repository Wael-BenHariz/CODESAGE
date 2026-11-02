#!/usr/bin/env node
/**
 * Extracts the report stylesheet from the VS Code renderer and writes it as a
 * Kotlin constant, so the IntelliJ report cannot drift from the VS Code one.
 *
 * Source of truth: vscode-extension/src/render.ts (the `renderReportHtml`
 * template). Generated file: intellij-plugin/.../report/ReportCss.kt
 *
 * Run: node scripts/parity/emit-report-css.mjs [--check]
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '../..');
const renderTs = path.join(repoRoot, 'vscode-extension/src/render.ts');
const outFile = path.join(
  repoRoot,
  'intellij-plugin/src/main/kotlin/com/codesage/intellij/report/ReportCss.kt'
);

const OPEN = '  <style>\n';
const CLOSE = '\n  </style>';

export async function extractCss() {
  const source = await readFile(renderTs, 'utf8');
  const start = source.indexOf(OPEN);
  if (start < 0) throw new Error('render.ts: <style> block not found');
  const end = source.indexOf(CLOSE, start);
  if (end < 0) throw new Error('render.ts: </style> block not found');
  return source.slice(start + OPEN.length, end);
}

export function kotlinFile(css) {
  if (css.includes('"""')) throw new Error('CSS contains a Kotlin raw-string terminator');
  if (css.includes('$')) throw new Error('CSS contains "$", which needs escaping in a Kotlin raw string');
  return `// GENERATED FILE - do not edit.
// Produced by scripts/parity/emit-report-css.mjs from vscode-extension/src/render.ts.
// The stylesheet is copied verbatim so the IntelliJ report renders exactly like the
// VS Code webview. Run \`node scripts/parity/emit-report-css.mjs\` to regenerate.

package com.codesage.intellij.report

internal object ReportCss {
    val CSS: String = """${css}"""
}
`;
}

const css = await extractCss();
const content = kotlinFile(css);

if (process.argv.includes('--check')) {
  const current = await readFile(outFile, 'utf8').catch(() => '');
  if (current !== content) {
    console.error('ReportCss.kt is out of date. Run: node scripts/parity/emit-report-css.mjs');
    process.exit(1);
  }
  console.log(`ReportCss.kt matches render.ts (${css.split('\n').length} CSS lines).`);
} else {
  await mkdir(path.dirname(outFile), { recursive: true });
  await writeFile(outFile, content, 'utf8');
  console.log(`Wrote ${path.relative(repoRoot, outFile)} (${css.split('\n').length} CSS lines).`);
}
