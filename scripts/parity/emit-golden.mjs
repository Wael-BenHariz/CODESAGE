#!/usr/bin/env node
/**
 * Generates the report goldens used by the IntelliJ parity test.
 *
 * The goldens are produced by the *real* VS Code renderer
 * (vscode-extension/src/render.ts), bundled on the fly with the esbuild that is
 * already installed in vscode-extension/node_modules. The VS Code extension is
 * imported read-only and never modified.
 *
 * Run: node scripts/parity/emit-golden.mjs [--check]
 */
import { execFileSync } from 'node:child_process';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '../..');
const renderTs = path.join(repoRoot, 'vscode-extension/src/render.ts');
const esbuild = path.join(repoRoot, 'vscode-extension/node_modules/esbuild/bin/esbuild');
const parityDir = path.join(repoRoot, 'intellij-plugin/src/test/resources/parity');
const fixturesFile = path.join(parityDir, 'fixtures.json');
const expectedDir = path.join(parityDir, 'expected');

function toState(view) {
  switch (view.kind) {
    case 'loading':
      return { kind: 'loading', message: view.message };
    case 'cancelled':
      return { kind: 'cancelled' };
    case 'error':
      return { kind: 'error', message: view.message };
    case 'result':
      return {
        kind: 'result',
        result: view.result,
        collection: view.collection ?? null,
        diagnostics: view.diagnostics
          ? {
              shown: new Set(view.diagnostics.shown ?? []),
              reasons: new Map(Object.entries(view.diagnostics.reasons ?? {}))
            }
          : null
      };
    default:
      throw new Error(`unknown fixture kind: ${view.kind}`);
  }
}

async function loadRenderer() {
  const dir = await mkdtemp(path.join(tmpdir(), 'codesage-parity-'));
  const outfile = path.join(dir, 'render.mjs');
  try {
    execFileSync(
      process.execPath,
      [esbuild, renderTs, '--bundle', '--format=esm', '--platform=node', `--outfile=${outfile}`],
      { stdio: 'inherit' }
    );
    return await import(pathToFileURL(outfile).href);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const { renderReportHtml } = await loadRenderer();
const fixtures = JSON.parse(await readFile(fixturesFile, 'utf8'));
const generated = new Map();

for (const fixture of fixtures) {
  generated.set(`${fixture.name}.html`, renderReportHtml(toState(fixture.view)));
}

if (process.argv.includes('--check')) {
  const existing = new Set(await readdir(expectedDir).catch(() => []));
  let failures = 0;
  for (const [name, html] of generated) {
    const current = await readFile(path.join(expectedDir, name), 'utf8').catch(() => null);
    if (current !== html) {
      console.error(`golden out of date: ${name}`);
      failures += 1;
    }
    existing.delete(name);
  }
  for (const stale of existing) {
    console.error(`stale golden (no fixture): ${stale}`);
    failures += 1;
  }
  if (failures > 0) process.exit(1);
  console.log(`All ${generated.size} goldens match vscode-extension/src/render.ts.`);
} else {
  await mkdir(expectedDir, { recursive: true });
  for (const [name, html] of generated) {
    await writeFile(path.join(expectedDir, name), html, 'utf8');
  }
  console.log(`Wrote ${generated.size} goldens to ${path.relative(repoRoot, expectedDir)}.`);
}
