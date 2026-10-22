import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { MOCK_DASHBOARD_SERVICES, ServiceHealth } from '../../mock/system-status';
import { MOCK_PLATFORM_STATS, MOCK_REVIEW_WEEK } from '../../mock/usage-data';

interface QuickAction {
  readonly link: string;
  readonly label: string;
}

/**
 * Platform Administration → Dashboard (static PFE prototype) —
 * `/platform/dashboard`.
 *
 * Every figure comes from the local `mock/` modules: no API call, no
 * backend dependency, the page renders with the backend offline. The
 * console shell labels it as a prototype.
 */
@Component({
  selector: 'app-platform-dashboard',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './platform-dashboard.component.html'
})
export class PlatformDashboardComponent {
  readonly stats = MOCK_PLATFORM_STATS;
  readonly services = MOCK_DASHBOARD_SERVICES;
  readonly week = MOCK_REVIEW_WEEK;

  /** Static demo date — never `new Date()` (the whole screen is mock data). */
  readonly demoDate = 'Thursday, October 8, 2026';

  readonly quickActions: readonly QuickAction[] = [
    { link: '/platform/users', label: 'Manage users' },
    { link: '/platform/logs', label: 'Browse logs' },
    { link: '/platform/system', label: 'View system status' },
    { link: '/platform/quotas', label: 'Manage quotas' }
  ];

  /** Max of the week series — bar heights are relative to it. */
  readonly weekMax = Math.max(...this.week.map(point => point.value));

  healthLabel(health: ServiceHealth): string {
    switch (health) {
      case 'operational':
        return 'Operational';
      case 'warning':
        return 'Warning';
      case 'error':
        return 'Error';
    }
  }

  /** Bar height as a percentage of the chart area (min 4%). */
  barHeight(value: number): string {
    return `${Math.max(4, Math.round((value / this.weekMax) * 100))}%`;
  }
}
