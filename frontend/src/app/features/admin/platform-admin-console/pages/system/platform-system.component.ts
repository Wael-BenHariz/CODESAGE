import { Component } from '@angular/core';

import {
  MOCK_RESOURCES,
  MOCK_SERVICES,
  MOCK_UPTIME,
  ServiceHealth
} from '../../mock/system-status';

/**
 * Platform Administration → État du système (static PFE prototype) —
 * `/platform-admin/system`.
 *
 * Static service states, resource levels, uptime figures and "last check"
 * timestamps — there is no health endpoint and no polling anywhere.
 */
@Component({
  selector: 'app-platform-system',
  standalone: true,
  templateUrl: './platform-system.component.html'
})
export class PlatformSystemComponent {
  readonly services = MOCK_SERVICES;
  readonly resources = MOCK_RESOURCES;
  readonly uptime = MOCK_UPTIME;

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
}
