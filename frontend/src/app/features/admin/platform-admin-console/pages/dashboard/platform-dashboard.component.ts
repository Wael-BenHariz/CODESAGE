import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { MOCK_DASHBOARD_SERVICES, ServiceHealth } from '../../mock/system-status';
import { MOCK_PLATFORM_STATS, MOCK_REVIEW_WEEK } from '../../mock/usage-data';

interface QuickAction {
  readonly link: string;
  readonly label: string;
}

/**
 * Platform Administration → Dashboard (static PFE prototype) — `/platform-admin`.
 *
 * Every figure comes from the local `mock/` modules: no API call, no
 * backend dependency, the page renders with the backend offline.
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
  readonly demoDate = 'Jeudi 8 octobre 2026';

  readonly quickActions: readonly QuickAction[] = [
    { link: '/platform-admin/users', label: 'Gérer les utilisateurs' },
    { link: '/platform-admin/logs', label: 'Consulter les journaux' },
    { link: '/platform-admin/system', label: "Voir l'état du système" },
    { link: '/platform-admin/quotas', label: 'Gérer les quotas' }
  ];

  /** Max of the week series — bar heights are relative to it. */
  readonly weekMax = Math.max(...this.week.map(point => point.value));

  healthLabel(health: ServiceHealth): string {
    switch (health) {
      case 'operational':
        return 'Opérationnel';
      case 'warning':
        return 'Attention';
      case 'error':
        return 'Erreur';
    }
  }

  /** Bar height as a percentage of the chart area (min 4%). */
  barHeight(value: number): string {
    return `${Math.max(4, Math.round((value / this.weekMax) * 100))}%`;
  }
}
