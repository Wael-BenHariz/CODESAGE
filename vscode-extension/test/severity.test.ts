import { describe, expect, it } from 'vitest';
import { compareFindings, normalizeSeverity, overallSeverity } from '../src/severity';

describe('normalizeSeverity', () => {
  it('keeps the static five-level scale', () => {
    expect(normalizeSeverity('critical', 'static')).toBe('critical');
    expect(normalizeSeverity('high', 'static')).toBe('high');
    expect(normalizeSeverity('medium', 'static')).toBe('medium');
    expect(normalizeSeverity('low', 'static')).toBe('low');
    expect(normalizeSeverity('info', 'static')).toBe('info');
  });

  it('maps the agent vocabulary honestly', () => {
    expect(normalizeSeverity('suggestion', 'agent')).toBe('low');
    expect(normalizeSeverity('info', 'agent')).toBe('info');
    expect(normalizeSeverity('warning', 'agent')).toBe('medium');
    expect(normalizeSeverity('error', 'agent')).toBe('high');
  });

  it('falls back to info for unknown values', () => {
    expect(normalizeSeverity('unknown', 'static')).toBe('info');
    expect(normalizeSeverity(undefined, 'agent')).toBe('info');
  });
});

describe('overallSeverity', () => {
  it('matches the existing frontend review badge mapping', () => {
    expect(overallSeverity('error')).toBe('critical');
    expect(overallSeverity('warning')).toBe('medium');
    expect(overallSeverity('suggestion')).toBe('low');
    expect(overallSeverity('info')).toBe('info');
  });
});

describe('compareFindings', () => {
  it('sorts by severity, file, then line', () => {
    const findings = [
      { severity: 'low' as const, filePath: 'b.ts', lineStart: 1 },
      { severity: 'critical' as const, filePath: 'z.ts', lineStart: 9 },
      { severity: 'high' as const, filePath: 'a.ts', lineStart: 3 },
      { severity: 'high' as const, filePath: 'a.ts', lineStart: 1 }
    ];
    findings.sort(compareFindings);
    expect(findings.map((finding) => `${finding.severity}:${finding.filePath}:${finding.lineStart}`)).toEqual([
      'critical:z.ts:9',
      'high:a.ts:1',
      'high:a.ts:3',
      'low:b.ts:1'
    ]);
  });
});
