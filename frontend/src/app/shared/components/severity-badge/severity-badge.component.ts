import { NgClass } from '@angular/common';
import { Component, input } from '@angular/core';

export type SeverityLevel = 'critical' | 'high' | 'medium' | 'low' | 'info';

/**
 * Severity badge — the frozen 5-step scale (plan §2.4 Option A):
 *   critical #f56565 · high #ed8936 · medium #ecc94b · low #4299e1 · info #a0aec0
 * Severity is never signalled by colour alone: every badge renders a
 * distinct icon shape AND the written level.
 */
@Component({
  selector: 'app-severity-badge',
  standalone: true,
  imports: [NgClass],
  template: `
    <span class="sev-badge" [ngClass]="'sev-' + severity()">
      @switch (severity()) {
        @case ('critical') {
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <path d="M5.2 1h5.6L15 5.2v5.6L10.8 15H5.2L1 10.8V5.2z" />
          </svg>
        }
        @case ('high') {
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <path d="M8 2 15 14H1z" />
          </svg>
        }
        @case ('medium') {
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <path d="M8 2 14 8 8 14 2 8z" />
          </svg>
        }
        @case ('low') {
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <circle cx="8" cy="8" r="6" />
          </svg>
        }
        @case ('info') {
          <svg
            width="12"
            height="12"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            aria-hidden="true"
          >
            <circle cx="8" cy="8" r="6" />
          </svg>
        }
      }
      <span class="label">{{ severity() }}</span>
    </span>
  `,
  styles: [
    `
      .sev-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 8px;
        border-radius: var(--radius-xs);
        font-family: var(--font-mono);
        font-size: var(--font-size-xs);
        font-weight: var(--font-weight-semibold);
        letter-spacing: 0.03em;
        text-transform: uppercase;
        color: var(--text-2);
        background: transparent;
      }
      .sev-critical {
        color: var(--sev-critical);
        background: var(--sev-critical-dim);
      }
      .sev-high {
        color: var(--sev-high);
        background: var(--sev-high-dim);
      }
      .sev-medium {
        color: var(--sev-medium);
        background: var(--sev-medium-dim);
      }
      .sev-low {
        color: var(--sev-low);
        background: var(--sev-low-dim);
      }
      .sev-info {
        color: var(--sev-info);
        background: var(--sev-info-dim);
      }
    `
  ]
})
export class SeverityBadgeComponent {
  severity = input.required<SeverityLevel>();
}
