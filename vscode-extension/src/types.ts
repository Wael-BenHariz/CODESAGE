export type ReviewScope = 'workingTree' | 'staged';

export type FileStatus = 'added' | 'modified' | 'deleted' | 'renamed';

export type UnifiedSeverity = 'info' | 'low' | 'medium' | 'high' | 'critical';

export type NativeSeverity =
  | 'suggestion'
  | 'info'
  | 'warning'
  | 'error'
  | 'low'
  | 'medium'
  | 'high'
  | 'critical';

export type FindingSource = 'static' | 'agent' | 'comment';

export interface SnapshotFile {
  path: string;
  oldPath?: string;
  status: FileStatus;
  contentSha256: string | null;
  size: number;
}

export interface ReviewSnapshot {
  id: string;
  baseRevision: string | null;
  headSha: string;
  branch: string | null;
  capturedAt: string;
  files: SnapshotFile[];
}

export interface SourceFile {
  path: string;
  oldPath?: string;
  status: FileStatus;
  content: string;
  contentSha256: string;
}

export interface ExcludedFile {
  path: string;
  reason: string;
}

export interface GitCollection {
  repoRoot: string;
  snapshot: ReviewSnapshot;
  diff: string;
  diffTruncated: boolean;
  changedRanges: Record<string, import('./diff').ChangedRange[]>;
  files: SourceFile[];
  excluded: ExcludedFile[];
  totalBytes: number;
}

export interface LocalReviewRequest {
  schemaVersion: 1;
  snapshot: ReviewSnapshot;
  title: string;
  description?: string;
  diff: string;
  language: string;
  files: SourceFile[];
}

export interface Finding {
  id: string;
  source: FindingSource;
  nativeSeverity: NativeSeverity | string;
  severity: UnifiedSeverity;
  filePath: string;
  oldPath?: string;
  lineStart: number | null;
  lineEnd: number | null;
  message: string;
  body: string;
  suggestion: string | null;
  snippet: string | null;
  tool: string | null;
  ruleId: string | null;
  category: string | null;
  alsoDetectedBy: string[];
  reason?: string;
}

export interface ReviewStatistics {
  filesReviewed: number;
  issuesFound: number;
  bySeverity: Record<string, number>;
  byCategory: Record<string, number>;
}

export interface LocalReviewResult {
  schemaVersion: number;
  snapshot: ReviewSnapshot;
  summary: string;
  overallSeverity: string;
  statistics: ReviewStatistics;
  findings: Finding[];
  degradedReasons: string[];
  agentFailures: string[];
  diffTruncated: boolean;
  durationMs: number;
}

export interface AuthProvider {
  readonly kind: 'dev' | 'none';
  getHeaders(): Promise<Record<string, string>>;
  describe(): string;
}
