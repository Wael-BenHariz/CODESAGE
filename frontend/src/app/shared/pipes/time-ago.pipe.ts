import { Pipe, PipeTransform } from '@angular/core';

/**
 * Relative timestamp ("3h ago") for dense list rows (plan §4.1 recent
 * reviews). Pure pipe — it re-evaluates when the source date changes
 * (rows are replaced wholesale on each load), so nothing ticks in the
 * background; the absolute timestamp stays in the row's `title`/`datetime`.
 */
@Pipe({ name: 'timeAgo', standalone: true })
export class TimeAgoPipe implements PipeTransform {
  transform(value: string | Date | null | undefined): string {
    if (!value) {
      return '';
    }
    const then = new Date(value).getTime();
    if (Number.isNaN(then)) {
      return '';
    }
    const diffMs = Date.now() - then;
    if (diffMs < 60_000) {
      return 'just now';
    }
    const minutes = Math.floor(diffMs / 60_000);
    if (minutes < 60) {
      return `${minutes}m ago`;
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
      return `${hours}h ago`;
    }
    const days = Math.floor(hours / 24);
    if (days < 30) {
      return `${days}d ago`;
    }
    const months = Math.floor(days / 30);
    if (months < 12) {
      return `${months}mo ago`;
    }
    return `${Math.floor(months / 12)}y ago`;
  }
}
