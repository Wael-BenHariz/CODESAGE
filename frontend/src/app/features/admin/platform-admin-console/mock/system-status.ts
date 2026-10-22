/**
 * STATIC MOCK DATA — Platform Administration console (PFE prototype).
 *
 * Hard-coded "operational" states, resource levels and uptime figures for
 * the System Monitoring screens. Nothing here is measured: there is no
 * polling, no health endpoint, no real monitoring.
 */

export type ServiceHealth = 'operational' | 'warning' | 'error';

export interface MockServiceStatus {
  readonly id: string;
  readonly name: string;
  readonly health: ServiceHealth;
  /** Demo text ("10 seconds ago") — never a real measurement. */
  readonly lastCheck: string;
}

/** Labels used by the dashboard's health summary. */
export const MOCK_DASHBOARD_SERVICES: readonly MockServiceStatus[] = [
  { id: 'api', name: 'API', health: 'operational', lastCheck: '10 seconds ago' },
  {
    id: 'database',
    name: 'Database',
    health: 'operational',
    lastCheck: '12 seconds ago'
  },
  { id: 'queue', name: 'Queue', health: 'operational', lastCheck: '8 seconds ago' },
  {
    id: 'review-engine',
    name: 'Review Engine',
    health: 'operational',
    lastCheck: '15 seconds ago'
  }
];

/** Full six-service list on the System Monitoring page. */
export const MOCK_SERVICES: readonly MockServiceStatus[] = [
  ...MOCK_DASHBOARD_SERVICES,
  { id: 'llm', name: 'LLM Service', health: 'operational', lastCheck: '11 seconds ago' },
  { id: 'storage', name: 'Storage', health: 'operational', lastCheck: '20 seconds ago' }
];

export interface MockResource {
  readonly id: string;
  readonly label: string;
  readonly percent: number;
}

export const MOCK_RESOURCES: readonly MockResource[] = [
  { id: 'cpu', label: 'CPU', percent: 72 },
  { id: 'memory', label: 'Memory', percent: 61 },
  { id: 'storage', label: 'Storage', percent: 48 }
];

export const MOCK_UPTIME = {
  uptime: '12 days 08h 32m',
  lastRestart: '2026-09-25'
} as const;
