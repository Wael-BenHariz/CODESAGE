import { Component, input } from '@angular/core';

/**
 * Empty state — the "empty" leg of the four-state UI pattern.
 * Title is mandatory (every empty state explains itself in words, never a
 * bare icon); action buttons come in through content projection.
 */
@Component({
  selector: 'app-empty-state',
  standalone: true,
  template: `
    <div class="empty" [attr.data-testid]="testid() || null">
      <span class="icon" aria-hidden="true">
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
        >
          <path d="M4 7h16M4 12h16M4 17h10" />
        </svg>
      </span>
      <p class="title">{{ title() }}</p>
      @if (message()) {
        <p class="message">{{ message() }}</p>
      }
      <div class="actions"><ng-content /></div>
    </div>
  `,
  styles: [
    `
      .empty {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        gap: var(--space-2);
        padding: var(--space-7) var(--space-4);
      }
      .icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 48px;
        height: 48px;
        border-radius: var(--radius-full);
        background: var(--surface-2);
        border: 1px solid var(--border-strong);
        color: var(--text-3);
        margin-bottom: var(--space-1);
      }
      .title {
        color: var(--text-1);
        font-size: var(--font-size-md);
        font-weight: var(--font-weight-medium);
      }
      .message {
        color: var(--text-3);
        font-size: var(--font-size-sm);
        max-width: 42ch;
      }
      .actions:empty {
        display: none;
      }
      .actions {
        display: flex;
        gap: var(--space-2);
        margin-top: var(--space-3);
      }
    `
  ]
})
export class EmptyStateComponent {
  title = input.required<string>();
  message = input('');
  testid = input('');
}
