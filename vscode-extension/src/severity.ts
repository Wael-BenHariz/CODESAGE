import type { NativeSeverity, UnifiedSeverity } from './types';

const AGENT_SEVERITY: Record<string, UnifiedSeverity> = {
  suggestion: 'low',
  info: 'info',
  warning: 'medium',
  error: 'high'
};

const STATIC_SEVERITY: Record<string, UnifiedSeverity> = {
  info: 'info',
  low: 'low',
  medium: 'medium',
  high: 'high',
  critical: 'critical'
};

export const SEVERITY_RANK: Record<UnifiedSeverity, number> = {
  info: 0,
  low: 1,
  medium: 2,
  high: 3,
  critical: 4
};

export function normalizeSeverity(
  value: NativeSeverity | string | null | undefined,
  source: 'static' | 'agent' | 'comment'
): UnifiedSeverity {
  const key = String(value ?? '').toLowerCase();
  if (source === 'static') {
    return STATIC_SEVERITY[key] ?? 'info';
  }
  return AGENT_SEVERITY[key] ?? STATIC_SEVERITY[key] ?? 'info';
}

export function overallSeverity(value: string | null | undefined): UnifiedSeverity {
  const key = String(value ?? '').toLowerCase();
  if (key === 'error') {
    return 'critical';
  }
  if (key === 'warning') {
    return 'medium';
  }
  if (key === 'suggestion') {
    return 'low';
  }
  return STATIC_SEVERITY[key] ?? 'info';
}

export function compareFindings(
  left: { severity: UnifiedSeverity; filePath: string; lineStart: number | null },
  right: { severity: UnifiedSeverity; filePath: string; lineStart: number | null }
): number {
  const severity = SEVERITY_RANK[right.severity] - SEVERITY_RANK[left.severity];
  if (severity !== 0) {
    return severity;
  }
  const file = left.filePath.localeCompare(right.filePath);
  if (file !== 0) {
    return file;
  }
  return (left.lineStart ?? Number.MAX_SAFE_INTEGER) - (right.lineStart ?? Number.MAX_SAFE_INTEGER);
}
