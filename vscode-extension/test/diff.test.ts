import { describe, expect, it } from 'vitest';
import { lineIsChanged, parseChangedRanges, synthesizeAddedDiff } from '../src/diff';

describe('parseChangedRanges', () => {
  it('collects added lines from hunks and merges adjacent ranges', () => {
    const diff = [
      'diff --git a/src/a.ts b/src/a.ts',
      '--- a/src/a.ts',
      '+++ b/src/a.ts',
      '@@ -1,3 +1,4 @@',
      ' const a = 1;',
      '-const b = 2;',
      '+const b = 3;',
      '+const c = 4;',
      ' const d = 5;',
      '@@ -20,1 +21,1 @@',
      '-old',
      '+new'
    ].join('\n');

    expect(parseChangedRanges(diff)).toEqual([
      { start: 2, end: 3 },
      { start: 21, end: 21 }
    ]);
  });

  it('produces no range for a pure deletion', () => {
    const diff = [
      'diff --git a/a.txt b/a.txt',
      '--- a/a.txt',
      '+++ b/a.txt',
      '@@ -2,2 +2,1 @@',
      ' keep',
      '-remove'
    ].join('\n');

    expect(parseChangedRanges(diff)).toEqual([]);
  });

  it('handles a hunk with no explicit count', () => {
    const diff = [
      'diff --git a/a.txt b/a.txt',
      '--- a/a.txt',
      '+++ b/a.txt',
      '@@ -1 +1 @@',
      '-old',
      '+new'
    ].join('\n');

    expect(parseChangedRanges(diff)).toEqual([{ start: 1, end: 1 }]);
  });

  it('counts an added content line that itself begins with ++', () => {
    const diff = [
      'diff --git a/a.txt b/a.txt',
      '--- a/a.txt',
      '+++ b/a.txt',
      '@@ -0,0 +1,1 @@',
      '+++header'
    ].join('\n');

    expect(parseChangedRanges(diff)).toEqual([{ start: 1, end: 1 }]);
  });
});

describe('lineIsChanged', () => {
  const ranges = [{ start: 3, end: 5 }];

  it('matches intersections, not only the first line', () => {
    expect(lineIsChanged(2, 3, ranges)).toBe(true);
    expect(lineIsChanged(5, 8, ranges)).toBe(true);
    expect(lineIsChanged(3, 3, ranges)).toBe(true);
    expect(lineIsChanged(1, 2, ranges)).toBe(false);
    expect(lineIsChanged(null, null, ranges)).toBe(false);
  });
});

describe('synthesizeAddedDiff', () => {
  it('creates a standard new-file diff and preserves line count', () => {
    const diff = synthesizeAddedDiff('src/a.ts', 'one\ntwo\n');
    expect(diff).toContain('new file mode 100644');
    expect(diff).toContain('@@ -0,0 +1,2 @@');
    expect(diff.trimEnd().endsWith('+one\n+two')).toBe(true);
  });

  it('handles an empty file', () => {
    const diff = synthesizeAddedDiff('empty.txt', '');
    expect(diff).toContain('@@ -0,0 +0,0 @@');
  });
});
