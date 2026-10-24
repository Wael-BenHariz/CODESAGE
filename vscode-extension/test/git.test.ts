import { execFileSync } from 'node:child_process';
import { mkdtemp, rm, writeFile, mkdir, rename, unlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { buildReviewRequest, collectLocalReview, NoChangesError } from '../src/git';

const repositories: string[] = [];

async function createRepo(): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), 'codesage-ext-git-'));
  repositories.push(dir);
  git(dir, ['init', '-q']);
  git(dir, ['config', 'user.email', 'test@example.com']);
  git(dir, ['config', 'user.name', 'Test User']);
  return dir;
}

function git(cwd: string, args: string[], input?: string): string {
  return execFileSync('git', args, {
    cwd,
    input,
    encoding: 'utf8'
  });
}

async function commitInitial(dir: string, files: Record<string, string>): Promise<void> {
  for (const [name, content] of Object.entries(files)) {
    const absolute = path.join(dir, name);
    await mkdir(path.dirname(absolute), { recursive: true });
    await writeFile(absolute, content, 'utf8');
  }
  git(dir, ['add', '.']);
  git(dir, ['commit', '-q', '-m', 'initial']);
}

function statusSnapshot(dir: string): string {
  return execFileSync('git', ['--no-optional-locks', 'status', '--porcelain=v2', '-z', '--branch'], {
    cwd: dir,
    encoding: 'utf8'
  });
}

const options = {
  scope: 'workingTree' as const,
  includeUntracked: true,
  maxFiles: 25,
  maxPayloadBytes: 4 * 1024 * 1024
};

afterEach(async () => {
  await Promise.all(repositories.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

describe('collectLocalReview', () => {
  it('collects modified, untracked, deleted and spaced paths without mutating Git state', async () => {
    const dir = await createRepo();
    await commitInitial(dir, {
      'src/a.ts': 'export const a = 1;\n',
      'src/delete.ts': 'gone\n',
      'src/rename.ts': 'rename me\n'
    });

    await writeFile(path.join(dir, 'src/a.ts'), 'export const a = 2;\n', 'utf8');
    await writeFile(path.join(dir, 'src/new file.ts'), 'new\n', 'utf8');
    await unlink(path.join(dir, 'src/delete.ts'));
    await rename(path.join(dir, 'src/rename.ts'), path.join(dir, 'src/renamed.ts'));

    const before = statusSnapshot(dir);
    const collection = await collectLocalReview(dir, options);
    const after = statusSnapshot(dir);

    expect(after).toBe(before);
    expect(collection.files.map((file) => file.path)).toEqual(
      expect.arrayContaining(['src/a.ts', 'src/new file.ts', 'src/renamed.ts'])
    );
    expect(collection.snapshot.files.find((file) => file.path === 'src/delete.ts')?.status).toBe('deleted');
    expect(collection.snapshot.files.find((file) => file.path === 'src/rename.ts')?.status).toBe('deleted');
    expect(collection.snapshot.files.find((file) => file.path === 'src/renamed.ts')?.status).toBe('added');
    expect(collection.diff).toContain('src/new file.ts');
    expect(collection.diff).toContain('src/a.ts');
    expect(collection.files.find((file) => file.path === 'src/a.ts')?.content).toContain('2');
  });

  it('keeps oldPath for a staged rename', async () => {
    const dir = await createRepo();
    await commitInitial(dir, { 'src/old.ts': 'same content\n' });
    await rename(path.join(dir, 'src/old.ts'), path.join(dir, 'src/new.ts'));
    git(dir, ['add', '-A']);

    const collection = await collectLocalReview(dir, { ...options, scope: 'staged' });
    const renamed = collection.snapshot.files.find((file) => file.path === 'src/new.ts');
    expect(renamed?.status).toBe('renamed');
    expect(renamed?.oldPath).toBe('src/old.ts');
  });

  it('reads staged content from the index, not the working tree', async () => {
    const dir = await createRepo();
    await commitInitial(dir, { 'a.ts': 'base\n' });

    await writeFile(path.join(dir, 'a.ts'), 'staged\n', 'utf8');
    git(dir, ['add', 'a.ts']);
    await writeFile(path.join(dir, 'a.ts'), 'worktree\n', 'utf8');

    const staged = await collectLocalReview(dir, { ...options, scope: 'staged' });
    const working = await collectLocalReview(dir, options);

    expect(staged.files.find((file) => file.path === 'a.ts')?.content).toBe('staged\n');
    expect(working.files.find((file) => file.path === 'a.ts')?.content).toBe('worktree\n');
  });

  it('excludes binary files with a reason', async () => {
    const dir = await createRepo();
    await commitInitial(dir, { 'a.txt': 'hello\n' });
    await writeFile(path.join(dir, 'a.txt'), 'hello again\n', 'utf8');
    await writeFile(path.join(dir, 'binary.bin'), Buffer.from([0, 1, 2, 3]));

    const collection = await collectLocalReview(dir, options);
    expect(collection.files.some((file) => file.path === 'binary.bin')).toBe(false);
    expect(collection.excluded).toContainEqual({
      path: 'binary.bin',
      reason: 'binary file'
    });
  });

  it('throws a clear error when there is nothing to review', async () => {
    const dir = await createRepo();
    await commitInitial(dir, { 'a.txt': 'clean\n' });
    await expect(collectLocalReview(dir, options)).rejects.toBeInstanceOf(NoChangesError);
  });
});

describe('buildReviewRequest', () => {
  it('builds a language and snapshot payload for the backend', async () => {
    const dir = await createRepo();
    await commitInitial(dir, { 'a.py': 'print(1)\n' });
    await writeFile(path.join(dir, 'a.py'), 'print(2)\n', 'utf8');

    const collection = await collectLocalReview(dir, options);
    const request = buildReviewRequest(collection, 'workingTree');

    expect(request.schemaVersion).toBe(1);
    expect(request.language).toBe('python');
    expect(request.snapshot.files[0]?.contentSha256).toHaveLength(64);
    expect(request.files[0]?.content).toBe('print(2)\n');
  });
});
