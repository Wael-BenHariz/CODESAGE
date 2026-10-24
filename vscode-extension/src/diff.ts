export interface ChangedRange {
  start: number;
  end: number;
}

const HUNK_HEADER = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/;

export function parseChangedRanges(diff: string): ChangedRange[] {
  const ranges: ChangedRange[] = [];
  const lines = diff.split(/\r?\n/);
  let inHunk = false;
  let newLine = 0;

  const addLine = (line: number): void => {
    const last = ranges[ranges.length - 1];
    if (last && line <= last.end + 1) {
      last.end = Math.max(last.end, line);
      return;
    }
    ranges.push({ start: line, end: line });
  };

  for (const line of lines) {
    const header = HUNK_HEADER.exec(line);
    if (header) {
      inHunk = true;
      newLine = Number(header[3]);
      continue;
    }
    if (line.startsWith('diff --git ')) {
      inHunk = false;
      continue;
    }
    if (!inHunk) {
      continue;
    }
    if (line.startsWith('\\')) {
      continue;
    }
    if (line.startsWith('+')) {
      addLine(newLine);
      newLine += 1;
      continue;
    }
    if (line.startsWith('-')) {
      continue;
    }
    if (line.startsWith(' ')) {
      newLine += 1;
      continue;
    }
    if (line.length === 0) {
      continue;
    }
    inHunk = false;
  }

  return ranges;
}

export function lineIsChanged(
  lineStart: number | null,
  lineEnd: number | null,
  ranges: readonly ChangedRange[]
): boolean {
  if (lineStart === null) {
    return false;
  }
  const start = Math.max(1, lineStart);
  const end = Math.max(start, lineEnd ?? start);
  return ranges.some((range) => start <= range.end && end >= range.start);
}

export function synthesizeAddedDiff(path: string, content: string): string {
  const normalized = content.replace(/\r\n/g, '\n');
  const lines = normalized.length === 0 ? [] : normalized.split('\n');
  if (lines.length > 0 && lines[lines.length - 1] === '') {
    lines.pop();
  }
  const body = lines.map((line) => `+${line}`).join('\n');
  const header = [
    `diff --git a/${path} b/${path}`,
    'new file mode 100644',
    'index 0000000..0000000',
    '--- /dev/null',
    `+++ b/${path}`
  ];
  if (lines.length === 0) {
    return `${header.join('\n')}\n@@ -0,0 +0,0 @@\n`;
  }
  return `${header.join('\n')}\n@@ -0,0 +1,${lines.length} @@\n${body}\n`;
}
