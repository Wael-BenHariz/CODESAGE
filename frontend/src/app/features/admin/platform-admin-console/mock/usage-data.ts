/**
 * STATIC MOCK DATA — Platform Administration console (PFE prototype).
 *
 * Demo statistics for the dashboard and the Quotas & Utilisation screens.
 * Every figure is hard-coded: nothing is aggregated, tracked or persisted.
 */

export type TrendDirection = 'up' | 'down';

export interface MockStatCard {
  readonly id: string;
  readonly label: string;
  readonly value: string;
  readonly caption: string;
  /** Display text of the trend chip, e.g. "↑ 8.2%". */
  readonly trend: string;
  readonly direction: TrendDirection;
}

/** Four dashboard cards (values per the PFE use-case slides). */
export const MOCK_PLATFORM_STATS: readonly MockStatCard[] = [
  {
    id: 'users',
    label: 'Utilisateurs',
    value: '248',
    caption: 'Utilisateurs',
    trend: '↑ 8.2%',
    direction: 'up'
  },
  {
    id: 'reviews',
    label: 'Revues',
    value: '1 284',
    caption: 'Revues réalisées',
    trend: '↑ 12.4%',
    direction: 'up'
  },
  {
    id: 'tokens',
    label: 'Tokens LLM',
    value: '2.8M',
    caption: 'Tokens utilisés',
    trend: '↑ 8.7%',
    direction: 'up'
  },
  {
    id: 'storage',
    label: 'Stockage',
    value: '18.4 GB',
    caption: 'Stockage utilisé',
    trend: '↓ 2.1%',
    direction: 'down'
  }
];

export interface MockWeekPoint {
  readonly day: string;
  readonly value: number;
}

/** Weekly "Utilisation des revues" bars (static). */
export const MOCK_REVIEW_WEEK: readonly MockWeekPoint[] = [
  { day: 'Mon', value: 148 },
  { day: 'Tue', value: 176 },
  { day: 'Wed', value: 201 },
  { day: 'Thu', value: 187 },
  { day: 'Fri', value: 215 },
  { day: 'Sat', value: 96 },
  { day: 'Sun', value: 63 }
];

export interface MockUsageTotal {
  readonly id: string;
  readonly label: string;
  readonly value: string;
}

/** Global usage cards on Quotas & Utilisation. */
export const MOCK_USAGE_TOTALS: readonly MockUsageTotal[] = [
  { id: 'reviews', label: 'Revues', value: '1 284' },
  { id: 'tokens', label: 'Tokens LLM', value: '2.8M' },
  { id: 'storage', label: 'Stockage', value: '18.4 GB' },
  { id: 'requests', label: 'Requêtes', value: '12 482' }
];

export interface MockQuotaBar {
  readonly id: string;
  readonly label: string;
  readonly percent: number;
}

export const MOCK_QUOTA_BARS: readonly MockQuotaBar[] = [
  { id: 'llm', label: 'Quota LLM', percent: 78 },
  { id: 'storage', label: 'Quota stockage', percent: 54 },
  { id: 'reviews', label: 'Quota revues', percent: 61 }
];

export interface MockOrgUsage {
  readonly organization: string;
  readonly reviews: number;
  readonly tokens: string;
  readonly storage: string;
  readonly utilization: number;
}

export const MOCK_ORG_USAGE: readonly MockOrgUsage[] = [
  { organization: 'Company A', reviews: 542, tokens: '1.2M', storage: '6.4 GB', utilization: 68 },
  { organization: 'Company B', reviews: 381, tokens: '890K', storage: '4.2 GB', utilization: 52 },
  { organization: 'Company C', reviews: 361, tokens: '710K', storage: '7.8 GB', utilization: 82 }
];

export interface MockOrgQuota {
  readonly organization: string;
  /** Max reviews per month. */
  readonly reviewQuota: number;
  /** Max LLM tokens per month. */
  readonly llmQuota: number;
  /** Storage ceiling, displayed with its unit. */
  readonly storageQuota: string;
}

export const MOCK_ORG_QUOTAS: readonly MockOrgQuota[] = [
  { organization: 'Company A', reviewQuota: 1000, llmQuota: 2000000, storageQuota: '10 GB' },
  { organization: 'Company B', reviewQuota: 800, llmQuota: 1500000, storageQuota: '8 GB' },
  { organization: 'Company C', reviewQuota: 900, llmQuota: 1800000, storageQuota: '12 GB' }
];

export function cloneMockQuotas(): MockOrgQuota[] {
  return MOCK_ORG_QUOTAS.map(quota => ({ ...quota }));
}
