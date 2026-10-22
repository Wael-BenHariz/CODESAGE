import { Component, HostListener, computed, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { EmptyStateComponent } from '../../../../../shared/components/empty-state/empty-state.component';
import {
  MOCK_LOG_DATES,
  MOCK_LOG_LEVELS,
  MOCK_LOG_SERVICES,
  MOCK_PLATFORM_LOGS,
  MockLogEntry
} from '../../mock/platform-logs';

/**
 * Platform Administration → Journaux (static PFE prototype) —
 * `/platform/logs`.
 *
 * Renders the local `MOCK_PLATFORM_LOGS` array: search and the three
 * filters operate on it in memory, and clicking a row opens the details
 * modal built from the same object. No log is ever fetched.
 */
@Component({
  selector: 'app-platform-logs',
  standalone: true,
  imports: [FormsModule, EmptyStateComponent],
  templateUrl: './platform-logs.component.html'
})
export class PlatformLogsComponent {
  readonly logs = MOCK_PLATFORM_LOGS;
  readonly levels = MOCK_LOG_LEVELS;
  readonly services = MOCK_LOG_SERVICES;
  readonly dates = MOCK_LOG_DATES;

  readonly search = signal('');
  readonly levelFilter = signal('');
  readonly serviceFilter = signal('');
  readonly dateFilter = signal('');
  readonly selected = signal<MockLogEntry | null>(null);

  readonly filtered = computed(() => {
    const query = this.search().trim().toLowerCase();
    const level = this.levelFilter();
    const service = this.serviceFilter();
    const date = this.dateFilter();

    return this.logs.filter(entry => {
      const matchesQuery =
        query === '' ||
        [entry.message, entry.service, entry.requestId].some(field =>
          field.toLowerCase().includes(query)
        );
      return (
        matchesQuery &&
        (level === '' || entry.level === level) &&
        (service === '' || entry.service === service) &&
        (date === '' || entry.date === date)
      );
    });
  });

  openLog(entry: MockLogEntry): void {
    this.selected.set(entry);
  }

  closeLog(): void {
    this.selected.set(null);
  }

  /** Close only when the backdrop itself was clicked. */
  onOverlayClick(event: Event): void {
    if (event.target === event.currentTarget) {
      this.closeLog();
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.closeLog();
  }

  /** Full timestamp for the details modal. */
  timestamp(entry: MockLogEntry): string {
    return `${entry.date} ${entry.time}`;
  }
}
