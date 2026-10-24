import type {
  AuthProvider,
  Finding,
  LocalReviewRequest,
  LocalReviewResult,
  ReviewSnapshot,
  SnapshotFile
} from './types';
import { normalizeSeverity } from './severity';

export class ApiError extends Error {
  readonly status: number | null;
  readonly detail: unknown;

  constructor(message: string, status: number | null, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

interface ApiClientOptions {
  baseUrl: string;
  auth: AuthProvider;
  timeoutMs: number;
}

interface ApiSnapshotFile {
  path: string;
  old_path?: string;
  status: string;
  content_sha256: string | null;
  size: number;
}

interface ApiSnapshot {
  id: string;
  base_revision: string | null;
  head_sha: string;
  branch: string | null;
  captured_at: string;
  files: ApiSnapshotFile[];
}

interface ApiFinding {
  id: string;
  source: string;
  native_severity?: string;
  severity: string;
  file_path: string;
  old_path?: string;
  line_start: number | null;
  line_end: number | null;
  message: string;
  body: string;
  suggestion?: string | null;
  snippet?: string | null;
  tool?: string | null;
  rule_id?: string | null;
  category?: string | null;
  also_detected_by?: string[];
  reason?: string;
}

interface ApiResult {
  schema_version: number;
  snapshot: ApiSnapshot;
  summary: string;
  overall_severity: string;
  statistics: {
    files_reviewed: number;
    issues_found: number;
    by_severity: Record<string, number>;
    by_category: Record<string, number>;
  };
  findings: ApiFinding[];
  degraded_reasons?: string[];
  agent_failures?: string[];
  diff_truncated?: boolean;
  duration_ms?: number;
}

function mapSnapshot(snapshot: ApiSnapshot): ReviewSnapshot {
  return {
    id: snapshot.id,
    baseRevision: snapshot.base_revision,
    headSha: snapshot.head_sha,
    branch: snapshot.branch,
    capturedAt: snapshot.captured_at,
    files: snapshot.files.map(
      (file): SnapshotFile => ({
        path: file.path,
        oldPath: file.old_path,
        status: file.status as SnapshotFile['status'],
        contentSha256: file.content_sha256,
        size: file.size
      })
    )
  };
}

function mapFinding(finding: ApiFinding): Finding {
  const source =
    finding.source === 'static' || finding.source === 'agent' || finding.source === 'comment'
      ? finding.source
      : 'static';
  return {
    id: finding.id,
    source,
    nativeSeverity: finding.native_severity ?? finding.severity,
    severity: normalizeSeverity(finding.severity, source),
    filePath: finding.file_path,
    oldPath: finding.old_path,
    lineStart: finding.line_start,
    lineEnd: finding.line_end,
    message: finding.message,
    body: finding.body,
    suggestion: finding.suggestion ?? null,
    snippet: finding.snippet ?? null,
    tool: finding.tool ?? null,
    ruleId: finding.rule_id ?? null,
    category: finding.category ?? null,
    alsoDetectedBy: finding.also_detected_by ?? [],
    reason: finding.reason
  };
}

function mapResult(result: ApiResult): LocalReviewResult {
  return {
    schemaVersion: result.schema_version,
    snapshot: mapSnapshot(result.snapshot),
    summary: result.summary,
    overallSeverity: result.overall_severity,
    statistics: {
      filesReviewed: result.statistics.files_reviewed,
      issuesFound: result.statistics.issues_found,
      bySeverity: result.statistics.by_severity,
      byCategory: result.statistics.by_category
    },
    findings: result.findings.map(mapFinding),
    degradedReasons: result.degraded_reasons ?? [],
    agentFailures: result.agent_failures ?? [],
    diffTruncated: result.diff_truncated ?? false,
    durationMs: result.duration_ms ?? 0
  };
}

function requestBody(request: LocalReviewRequest): unknown {
  return {
    schema_version: request.schemaVersion,
    snapshot: {
      id: request.snapshot.id,
      base_revision: request.snapshot.baseRevision,
      head_sha: request.snapshot.headSha,
      branch: request.snapshot.branch,
      captured_at: request.snapshot.capturedAt,
      files: request.snapshot.files.map((file) => ({
        path: file.path,
        old_path: file.oldPath,
        status: file.status,
        content_sha256: file.contentSha256,
        size: file.size
      }))
    },
    title: request.title,
    description: request.description,
    diff: request.diff,
    language: request.language,
    files: request.files.map((file) => ({
      path: file.path,
      old_path: file.oldPath,
      status: file.status,
      content: file.content,
      content_sha256: file.contentSha256
    }))
  };
}

async function errorMessage(response: Response): Promise<{ message: string; detail: unknown }> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { message: `CodeSage request failed (${response.status})`, detail: undefined };
  }
  if (payload && typeof payload === 'object') {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string') {
      return { message: detail, detail };
    }
    if (Array.isArray(detail)) {
      const errors = detail as Array<{ msg?: unknown; loc?: unknown }>;
      const first = errors[0];
      if (first && typeof first.msg === 'string') {
        return { message: `Invalid review request: ${first.msg}`, detail };
      }
    }
  }
  return { message: `CodeSage request failed (${response.status})`, detail: payload };
}

function mergeAbortSignals(signal: AbortSignal | undefined, timeoutMs: number): {
  signal: AbortSignal;
  cleanup: () => void;
} {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const forward = (): void => controller.abort();
  if (signal) {
    if (signal.aborted) {
      controller.abort();
    } else {
      signal.addEventListener('abort', forward, { once: true });
    }
  }
  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', forward);
    }
  };
}

export class CodeSageClient {
  private readonly apiBase: string;
  private readonly auth: AuthProvider;
  private readonly timeoutMs: number;

  constructor(options: ApiClientOptions) {
    this.apiBase = `${options.baseUrl.replace(/\/+$/, '')}/api/v1`;
    this.auth = options.auth;
    this.timeoutMs = options.timeoutMs;
  }

  async health(signal?: AbortSignal): Promise<boolean> {
    const merged = mergeAbortSignals(signal, Math.min(this.timeoutMs, 10000));
    try {
      const response = await fetch(`${this.apiBase.replace(/\/api\/v1$/, '')}/health`, {
        signal: merged.signal,
        headers: await this.auth.getHeaders()
      });
      return response.ok;
    } catch {
      return false;
    } finally {
      merged.cleanup();
    }
  }

  async submitDevReview(
    request: LocalReviewRequest,
    signal?: AbortSignal
  ): Promise<LocalReviewResult> {
    const merged = mergeAbortSignals(signal, this.timeoutMs);
    try {
      const response = await fetch(`${this.apiBase}/local-reviews/dev`, {
        method: 'POST',
        signal: merged.signal,
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          ...(await this.auth.getHeaders())
        },
        body: JSON.stringify(requestBody(request))
      });
      if (!response.ok) {
        const error = await errorMessage(response);
        throw new ApiError(error.message, response.status, error.detail);
      }
      return mapResult((await response.json()) as ApiResult);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      if (error instanceof Error && error.name === 'AbortError') {
        throw new ApiError('CodeSage review request timed out or was cancelled.', null);
      }
      throw new ApiError('Could not reach the CodeSage backend.', null);
    } finally {
      merged.cleanup();
    }
  }
}
