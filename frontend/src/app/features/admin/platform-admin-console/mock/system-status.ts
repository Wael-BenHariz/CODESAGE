/**
 * STATIC MOCK DATA — Platform Administration console (PFE prototype).
 *
 * Hard-coded "operational" states, resource levels and uptime figures for
 * the État du système screens. Nothing here is measured: there is no
 * polling, no health endpoint, no real monitoring.
 */

export type ServiceHealth = 'operational' | 'warning' | 'error';

export interface MockServiceStatus {
  readonly id: string;
  readonly name: string;
  readonly health: ServiceHealth;
  /** Demo text ("Il y a 10 secondes") — never a real measurement. */
  readonly lastCheck: string;
}

/** French labels used by the dashboard's health summary. */
export const MOCK_DASHBOARD_SERVICES: readonly MockServiceStatus[] = [
  { id: 'api', name: 'API', health: 'operational', lastCheck: 'Il y a 10 secondes' },
  {
    id: 'database',
    name: 'Base de données',
    health: 'operational',
    lastCheck: 'Il y a 12 secondes'
  },
  { id: 'queue', name: 'Queue', health: 'operational', lastCheck: 'Il y a 8 secondes' },
  {
    id: 'review-engine',
    name: 'Moteur de revue',
    health: 'operational',
    lastCheck: 'Il y a 15 secondes'
  }
];

/** Full six-service list on the État du système page. */
export const MOCK_SERVICES: readonly MockServiceStatus[] = [
  ...MOCK_DASHBOARD_SERVICES,
  { id: 'llm', name: 'LLM Service', health: 'operational', lastCheck: 'Il y a 11 secondes' },
  { id: 'storage', name: 'Storage', health: 'operational', lastCheck: 'Il y a 20 secondes' }
];

export interface MockResource {
  readonly id: string;
  readonly label: string;
  readonly percent: number;
}

export const MOCK_RESOURCES: readonly MockResource[] = [
  { id: 'cpu', label: 'CPU', percent: 72 },
  { id: 'memory', label: 'Mémoire', percent: 61 },
  { id: 'storage', label: 'Stockage', percent: 48 }
];

export const MOCK_UPTIME = {
  uptime: '12 jours 08h 32m',
  lastRestart: '25/09/2026'
} as const;
