import { execFile } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { promisify } from 'node:util';
import { parseChangedRanges, synthesizeAddedDiff } from './diff';
import type {
  ExcludedFile,
  FileStatus,
  GitCollection,
  ReviewScope,
  ReviewSnapshot,
  SnapshotFile,
  SourceFile
} from './types';

const execFileAsync = promisify(execFile);
const MAX_BUFFER = 32 * 1024 * 1024;
const MAX_FILE_BYTES = 512 * 1024;
const MAX_DIFF_BYTES = 1024 * 1024;

export interface CollectOptions {
  scope: ReviewScope;
  includeUntracked: boolean;
  maxFiles: number;
  maxPayloadBytes: number;
}

interface RawStatus {
  path: string;
  oldPath?: string;
  index: string;
  workTree: string;
  submodule: string;
  untracked: boolean;
  renamed: boolean;
}

interface Candidate {
  raw: RawStatus;
  path: string;
  oldPath?: string;
  status: FileStatus;
  content: Buffer | null;
  contentSha256: string | null;
  size: number;
}

export class GitError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GitError';
  }
}

export class NoChangesError extends Error {
  constructor() {
    super('No reviewable Git changes were found.');
    this.name = 'NoChangesError';
  }
}

async function gitText(cwd: string, args: string[]): Promise<string> {
  try {
    const { stdout } = await execFileAsync('git', ['--no-optional-locks', ...args], {
      cwd,
      encoding: 'utf8',
      maxBuffer: MAX_BUFFER
    });
    return stdout;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new GitError(`git ${args[0] ?? ''} failed: ${message}`);
  }
}

async function gitBuffer(cwd: string, args: string[]): Promise<Buffer> {
  try {
    const { stdout } = await execFileAsync('git', ['--no-optional-locks', ...args], {
      cwd,
      encoding: 'buffer',
      maxBuffer: MAX_BUFFER
    });
    return Buffer.isBuffer(stdout) ? stdout : Buffer.from(stdout);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new GitError(`git ${args[0] ?? ''} failed: ${message}`);
  }
}

export async function findRepositoryRoot(folder: string): Promise<string> {
  const root = (await gitText(folder, ['rev-parse', '--show-toplevel'])).trim();
  if (!root) {
    throw new GitError('Not inside a Git repository.');
  }
  return path.resolve(root);
}

function parseStatus(output: string): { branch: string | null; head: string | null; entries: RawStatus[] } {
  const tokens = output.split('\0');
  const entries: RawStatus[] = [];
  let branch: string | null = null;
  let head: string | null = null;

  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!token) {
      continue;
    }
    if (token.startsWith('# branch.head ')) {
      branch = token.slice('# branch.head '.length);
      continue;
    }
    if (token.startsWith('# branch.oid ')) {
      const value = token.slice('# branch.oid '.length);
      head = value === '(initial)' ? null : value;
      continue;
    }
    if (token.startsWith('# ')) {
      continue;
    }
    if (token.startsWith('? ')) {
      entries.push({
        path: token.slice(2),
        index: '?',
        workTree: '?',
        submodule: 'N...',
        untracked: true,
        renamed: false
      });
      continue;
    }
    if (token.startsWith('! ')) {
      continue;
    }
    if (token.startsWith('u ')) {
      throw new GitError('The working tree has unresolved merge conflicts.');
    }
    if (token.startsWith('1 ')) {
      const match = /^1 ([^ ]{2}) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) (.*)$/s.exec(
        token
      );
      if (!match) {
        continue;
      }
      entries.push({
        path: match[8] ?? '',
        index: match[1]?.[0] ?? '.',
        workTree: match[1]?.[1] ?? '.',
        submodule: match[2] ?? 'N...',
        untracked: false,
        renamed: false
      });
      continue;
    }
    if (token.startsWith('2 ')) {
      const match =
        /^2 ([^ ]{2}) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) (.*)$/s.exec(
          token
        );
      if (!match) {
        continue;
      }
      const oldPath = tokens[index + 1];
      if (oldPath !== undefined) {
        index += 1;
      }
      entries.push({
        path: match[9] ?? '',
        oldPath,
        index: match[1]?.[0] ?? '.',
        workTree: match[1]?.[1] ?? '.',
        submodule: match[2] ?? 'N...',
        untracked: false,
        renamed: true
      });
    }
  }

  return { branch, head, entries };
}

function statusFor(raw: RawStatus, scope: ReviewScope): FileStatus {
  if (raw.renamed) {
    return 'renamed';
  }
  const code = scope === 'staged' ? raw.index : raw.index === '.' ? raw.workTree : raw.index;
  if (code === 'D') {
    return 'deleted';
  }
  if (code === 'A' || code === 'C' || raw.untracked) {
    return 'added';
  }
  if (raw.workTree === 'D' || raw.index === 'D') {
    return 'deleted';
  }
  return 'modified';
}

function isIncluded(raw: RawStatus, scope: ReviewScope, includeUntracked: boolean): boolean {
  if (raw.untracked) {
    return scope === 'workingTree' && includeUntracked;
  }
  if (scope === 'staged') {
    return raw.index !== '.';
  }
  return raw.index !== '.' || raw.workTree !== '.';
}

function isUnsafePath(filePath: string): boolean {
  if (filePath.length === 0 || path.isAbsolute(filePath) || filePath.includes('\0')) {
    return true;
  }
  return filePath.split('/').some((segment) => segment === '..');
}

function isBinary(buffer: Buffer): boolean {
  return buffer.subarray(0, 8000).includes(0);
}

function sha256(buffer: Buffer): string {
  return createHash('sha256').update(buffer).digest('hex');
}

async function readWorkingTreeFile(
  repoRoot: string,
  filePath: string
): Promise<{ content: Buffer | null; reason?: string }> {
  const absolute = path.resolve(repoRoot, filePath);
  const relative = path.relative(repoRoot, absolute);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    return { content: null, reason: 'outside repository' };
  }
  try {
    const stat = await fs.lstat(absolute);
    if (stat.isSymbolicLink()) {
      return { content: null, reason: 'symbolic link' };
    }
    if (!stat.isFile()) {
      return { content: null, reason: 'not a regular file' };
    }
    if (stat.size > MAX_FILE_BYTES) {
      return { content: null, reason: `larger than ${MAX_FILE_BYTES} bytes` };
    }
    const content = await fs.readFile(absolute);
    if (isBinary(content)) {
      return { content: null, reason: 'binary file' };
    }
    return { content };
  } catch {
    return { content: null, reason: 'unreadable file' };
  }
}

async function readStagedFile(
  repoRoot: string,
  filePath: string
): Promise<{ content: Buffer | null; reason?: string }> {
  try {
    const mode = (await gitText(repoRoot, ['ls-files', '-s', '--', filePath])).trim();
    if (mode.startsWith('120000 ')) {
      return { content: null, reason: 'symbolic link' };
    }
    const content = await gitBuffer(repoRoot, ['show', `:${filePath}`]);
    if (content.length > MAX_FILE_BYTES) {
      return { content: null, reason: `larger than ${MAX_FILE_BYTES} bytes` };
    }
    if (isBinary(content)) {
      return { content: null, reason: 'binary file' };
    }
    return { content };
  } catch {
    return { content: null, reason: 'unreadable staged file' };
  }
}

async function readFileForScope(
  repoRoot: string,
  filePath: string,
  scope: ReviewScope,
  status: FileStatus
): Promise<{ content: Buffer | null; reason?: string }> {
  if (status === 'deleted') {
    return { content: null };
  }
  return scope === 'staged'
    ? readStagedFile(repoRoot, filePath)
    : readWorkingTreeFile(repoRoot, filePath);
}

function diffArgs(scope: ReviewScope, filePath: string): string[] {
  const base = scope === 'staged' ? ['diff', '--cached'] : ['diff'];
  return [
    ...base,
    'HEAD',
    '--unified=3',
    '--no-ext-diff',
    '--no-textconv',
    '--find-renames',
    '--no-color',
    '--',
    filePath
  ];
}

async function fileDiff(
  repoRoot: string,
  scope: ReviewScope,
  candidate: Candidate,
  hasHead: boolean
): Promise<string> {
  if (candidate.status === 'deleted' || candidate.content === null) {
    if (candidate.status === 'added' && candidate.content !== null) {
      return synthesizeAddedDiff(candidate.path, candidate.content.toString('utf8'));
    }
    if (hasHead) {
      return gitText(repoRoot, diffArgs(scope, candidate.path));
    }
    return '';
  }
  if (!hasHead || candidate.status === 'added') {
    return synthesizeAddedDiff(candidate.path, candidate.content.toString('utf8'));
  }
  const diff = await gitText(repoRoot, diffArgs(scope, candidate.path));
  if (diff.trim().length === 0) {
    return synthesizeAddedDiff(candidate.path, candidate.content.toString('utf8'));
  }
  return diff;
}

function detectLanguage(files: SourceFile[]): string {
  const counts = new Map<string, number>();
  for (const file of files) {
    const ext = path.extname(file.path).toLowerCase();
    const language = LANGUAGE_BY_EXTENSION[ext] ?? 'text';
    counts.set(language, (counts.get(language) ?? 0) + 1);
  }
  let best = 'text';
  let bestCount = 0;
  for (const [language, count] of counts) {
    if (count > bestCount) {
      best = language;
      bestCount = count;
    }
  }
  return best;
}

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  '.py': 'python',
  '.js': 'javascript',
  '.jsx': 'javascript',
  '.ts': 'typescript',
  '.tsx': 'typescript',
  '.go': 'go',
  '.rs': 'rust',
  '.java': 'java',
  '.rb': 'ruby',
  '.php': 'php',
  '.cs': 'csharp',
  '.c': 'c',
  '.h': 'c',
  '.cpp': 'cpp',
  '.hpp': 'cpp',
  '.swift': 'swift',
  '.kt': 'kotlin',
  '.kts': 'kotlin',
  '.scala': 'scala',
  '.sh': 'shell',
  '.bash': 'shell',
  '.sql': 'sql',
  '.yaml': 'yaml',
  '.yml': 'yaml',
  '.json': 'json',
  '.md': 'markdown'
};

function truncateDiff(diff: string): { diff: string; truncated: boolean } {
  if (Buffer.byteLength(diff, 'utf8') <= MAX_DIFF_BYTES) {
    return { diff, truncated: false };
  }
  const slice = Buffer.from(diff, 'utf8').subarray(0, MAX_DIFF_BYTES).toString('utf8');
  const lastNewline = slice.lastIndexOf('\n');
  const body = lastNewline > 0 ? slice.slice(0, lastNewline) : slice;
  return {
    diff: `${body}\n\n[CodeSage: local diff truncated at ${MAX_DIFF_BYTES} bytes]\n`,
    truncated: true
  };
}

export async function collectLocalReview(
  folder: string,
  options: CollectOptions
): Promise<GitCollection> {
  const repoRoot = await findRepositoryRoot(folder);
  const status = await gitText(repoRoot, [
    'status',
    '--porcelain=v2',
    '-z',
    '--branch',
    '--untracked-files=all',
    '--find-renames'
  ]);
  const parsed = parseStatus(status);
  const hasHead = parsed.head !== null;

  const included = parsed.entries.filter((entry) =>
    isIncluded(entry, options.scope, options.includeUntracked)
  );
  const candidates: Candidate[] = [];
  const excluded: ExcludedFile[] = [];

  for (const raw of included) {
    if (isUnsafePath(raw.path)) {
      excluded.push({ path: raw.path, reason: 'unsafe path' });
      continue;
    }
    if (raw.submodule.startsWith('S')) {
      excluded.push({ path: raw.path, reason: 'submodule' });
      continue;
    }
    if (raw.path.endsWith('/')) {
      excluded.push({ path: raw.path, reason: 'directory' });
      continue;
    }
    const fileStatus = statusFor(raw, options.scope);
    const read = await readFileForScope(repoRoot, raw.path, options.scope, fileStatus);
    if (read.reason) {
      excluded.push({ path: raw.path, reason: read.reason });
      continue;
    }
    if (candidates.length >= options.maxFiles) {
      excluded.push({ path: raw.path, reason: `more than ${options.maxFiles} files` });
      continue;
    }
    const content = read.content;
    const size = content?.length ?? 0;
    const selectedBytes = candidates.reduce((total, item) => total + item.size, 0);
    if (selectedBytes + size > options.maxPayloadBytes) {
      excluded.push({
        path: raw.path,
        reason: `payload would exceed ${options.maxPayloadBytes} bytes`
      });
      continue;
    }
    candidates.push({
      raw,
      path: raw.path,
      oldPath: raw.oldPath,
      status: fileStatus,
      content,
      contentSha256: content ? sha256(content) : null,
      size
    });
  }

  if (candidates.length === 0) {
    throw new NoChangesError();
  }

  const snapshotFiles: SnapshotFile[] = [];
  const sourceFiles: SourceFile[] = [];
  const diffs: string[] = [];
  const changedRanges: Record<string, import('./diff').ChangedRange[]> = {};

  for (const candidate of candidates) {
    snapshotFiles.push({
      path: candidate.path,
      oldPath: candidate.oldPath,
      status: candidate.status,
      contentSha256: candidate.contentSha256,
      size: candidate.size
    });
    if (candidate.content !== null) {
      sourceFiles.push({
        path: candidate.path,
        oldPath: candidate.oldPath,
        status: candidate.status,
        content: candidate.content.toString('utf8'),
        contentSha256: candidate.contentSha256 ?? ''
      });
    }
    const diff = await fileDiff(repoRoot, options.scope, candidate, hasHead);
    if (diff.trim().length > 0) {
      diffs.push(diff);
      changedRanges[candidate.path] = parseChangedRanges(diff);
    }
  }

  const combined = diffs.join('\n');
  const capped = truncateDiff(combined);
  const snapshot: ReviewSnapshot = {
    id: randomUUID(),
    baseRevision: parsed.head,
    headSha: parsed.head ?? '',
    branch: parsed.branch === '(detached)' ? null : parsed.branch,
    capturedAt: new Date().toISOString(),
    files: snapshotFiles
  };

  return {
    repoRoot,
    snapshot,
    diff: capped.diff,
    diffTruncated: capped.truncated,
    changedRanges,
    files: sourceFiles,
    excluded,
    totalBytes: sourceFiles.reduce((total, file) => total + Buffer.byteLength(file.content, 'utf8'), 0)
  };
}

export function buildReviewRequest(
  collection: GitCollection,
  scope: ReviewScope,
  title?: string
): {
  schemaVersion: 1;
  snapshot: ReviewSnapshot;
  title: string;
  description: string;
  diff: string;
  language: string;
  files: SourceFile[];
} {
  const branch = collection.snapshot.branch ?? 'detached HEAD';
  return {
    schemaVersion: 1,
    snapshot: collection.snapshot,
    title: title ?? `Local changes on ${branch}`,
    description: `CodeSage local review (${scope})`,
    diff: collection.diff,
    language: detectLanguage(collection.files),
    files: collection.files
  };
}
