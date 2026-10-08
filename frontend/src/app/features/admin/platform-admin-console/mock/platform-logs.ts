/**
 * STATIC MOCK DATA — Platform Administration console (PFE prototype).
 *
 * Hard-coded execution-log rows for the Journaux screen. No log is read
 * from any backend: search, filters and the details modal all operate on
 * this local array only.
 */

export type LogLevel = 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG';

export type LogService = 'API' | 'Review' | 'LLM' | 'Queue' | 'Authentication' | 'System';

export interface MockLogEntry {
  readonly id: number;
  /** DD/MM/YYYY — kept as a display string for the demo table. */
  readonly date: string;
  /** HH:MM:SS */
  readonly time: string;
  readonly level: LogLevel;
  readonly service: LogService;
  readonly message: string;
  readonly requestId: string;
  readonly details: string;
}

export const MOCK_LOG_LEVELS: readonly LogLevel[] = ['INFO', 'WARNING', 'ERROR', 'DEBUG'];

export const MOCK_LOG_SERVICES: readonly LogService[] = [
  'API',
  'Review',
  'LLM',
  'Queue',
  'Authentication',
  'System'
];

export const MOCK_PLATFORM_LOGS: readonly MockLogEntry[] = [
  {
    id: 1,
    date: '08/10/2026',
    time: '08:42:12',
    level: 'INFO',
    service: 'Review',
    message: 'Review completed successfully',
    requestId: 'REV-2026-001284',
    details:
      'repository=codesage/api pull_request=#482 duration_ms=18421 findings=6 posted=true mode=summary-only'
  },
  {
    id: 2,
    date: '08/10/2026',
    time: '08:41:52',
    level: 'INFO',
    service: 'LLM',
    message: 'Request completed',
    requestId: 'LLM-2026-009317',
    details: 'provider=groq model=openai/gpt-oss-120b tokens_in=4821 tokens_out=612 latency_ms=1934'
  },
  {
    id: 3,
    date: '08/10/2026',
    time: '08:40:31',
    level: 'WARNING',
    service: 'Queue',
    message: 'Queue latency is high',
    requestId: 'QUE-2026-004410',
    details: 'queue=review-requests depth=37 oldest_job_age_s=94 concurrency=5 threshold_s=60'
  },
  {
    id: 4,
    date: '08/10/2026',
    time: '08:39:14',
    level: 'ERROR',
    service: 'API',
    message: 'Request failed',
    requestId: 'API-2026-013955',
    details: 'method=GET path=/api/v1/reviews status=500 duration_ms=2210 upstream=postgres'
  },
  {
    id: 5,
    date: '08/10/2026',
    time: '08:38:02',
    level: 'DEBUG',
    service: 'System',
    message: 'Scheduled cleanup finished',
    requestId: 'SYS-2026-002201',
    details: 'expired_invitations_removed=3 stale_scan_projects_removed=11 duration_ms=487'
  },
  {
    id: 6,
    date: '08/10/2026',
    time: '08:36:47',
    level: 'INFO',
    service: 'Authentication',
    message: 'User signed in',
    requestId: 'AUTH-2026-007712',
    details: 'provider=keycloak broker=github realm=codesage-realm result=success'
  },
  {
    id: 7,
    date: '08/10/2026',
    time: '08:35:19',
    level: 'INFO',
    service: 'Queue',
    message: 'Review job started',
    requestId: 'QUE-2026-004409',
    details: 'job_id=8f2c1a review_id=1284 worker=worker-2 attempt=1'
  },
  {
    id: 8,
    date: '08/10/2026',
    time: '08:33:58',
    level: 'WARNING',
    service: 'LLM',
    message: 'Rate limit reached, retrying',
    requestId: 'LLM-2026-009316',
    details: 'provider=groq status=429 retry_after_s=4 attempt=2 max_attempts=3'
  },
  {
    id: 9,
    date: '08/10/2026',
    time: '08:31:40',
    level: 'INFO',
    service: 'Review',
    message: 'Static analysis merged',
    requestId: 'REV-2026-001283',
    details: 'sonarqube_findings=14 semgrep_findings=9 merged=19 also_detected_by=6'
  },
  {
    id: 10,
    date: '08/10/2026',
    time: '08:29:05',
    level: 'ERROR',
    service: 'Review',
    message: 'Review failed: diff too large',
    requestId: 'REV-2026-001282',
    details: 'repository=acme/legacy pull_request=#119 diff_chars=512000 cap=16000 result=partial'
  },
  {
    id: 11,
    date: '08/10/2026',
    time: '08:27:33',
    level: 'INFO',
    service: 'API',
    message: 'Webhook delivered',
    requestId: 'API-2026-013954',
    details: 'event=pull_request action=synchronize signature=valid queued=true'
  },
  {
    id: 12,
    date: '08/10/2026',
    time: '08:25:11',
    level: 'DEBUG',
    service: 'Authentication',
    message: 'JWKS cache refreshed',
    requestId: 'AUTH-2026-007711',
    details: 'issuer=Keycloak keys=2 age_s=300 result=success'
  },
  {
    id: 13,
    date: '07/10/2026',
    time: '18:12:44',
    level: 'INFO',
    service: 'System',
    message: 'Nightly backup completed',
    requestId: 'SYS-2026-002200',
    details: 'target=s3://codesage-backups size_mb=812 duration_s=96 result=success'
  },
  {
    id: 14,
    date: '07/10/2026',
    time: '17:58:09',
    level: 'WARNING',
    service: 'API',
    message: 'Slow query detected',
    requestId: 'API-2026-013953',
    details: 'table=reviews duration_ms=1420 rows=4800 threshold_ms=1000'
  },
  {
    id: 15,
    date: '07/10/2026',
    time: '17:41:26',
    level: 'INFO',
    service: 'LLM',
    message: 'Provider fallback applied',
    requestId: 'LLM-2026-009315',
    details: 'from=anthropic to=groq reason=unavailable reviews_affected=2'
  },
  {
    id: 16,
    date: '07/10/2026',
    time: '16:20:57',
    level: 'ERROR',
    service: 'Queue',
    message: 'Job failed after 3 attempts',
    requestId: 'QUE-2026-004408',
    details: 'job_id=77ab90 review_id=1279 error=llm_timeout attempts=3 result=failed'
  },
  {
    id: 17,
    date: '07/10/2026',
    time: '15:03:14',
    level: 'INFO',
    service: 'Authentication',
    message: 'Invitation accepted',
    requestId: 'AUTH-2026-007710',
    details: 'org=Company B role=REVIEWER repos=3 result=success'
  },
  {
    id: 18,
    date: '07/10/2026',
    time: '14:47:38',
    level: 'DEBUG',
    service: 'Review',
    message: 'Diff chunked for specialists',
    requestId: 'REV-2026-001281',
    details: 'chunks=4 max_chunk_chars=15800 overlaps=0'
  }
];

/** Distinct dates present in the mock data (populates the date filter). */
export const MOCK_LOG_DATES: readonly string[] = [
  ...new Set(MOCK_PLATFORM_LOGS.map(entry => entry.date))
];
