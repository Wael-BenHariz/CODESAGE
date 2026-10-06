import { Component, EventEmitter, input, Output } from '@angular/core';

/**
 * Error state — the "error + retry" leg of the four-state UI pattern.
 * role="alert" so assistive tech announces the failure; the retry button
 * only renders when the caller opts in with a retry label (it always has
 * visible text — never an icon-only retry).
 *
 * Copy rule: a 404 must never be rendered as "no access" — that mapping
 * belongs to the caller.
 */
@Component({
  selector: 'app-error-state',
  standalone: true,
  template: `
    <div class="error-state" role="alert" [attr.data-testid]="testid() || null">
      <svg
        class="ico"
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <path d="M12 3 2.5 20h19L12 3z" />
        <path d="M12 10v4" />
        <path d="M12 17.5v.5" />
      </svg>
      <p class="msg">{{ message() }}</p>
      @if (retryLabel()) {
        <button type="button" class="btn btn-secondary retry" (click)="retry.emit()">
          {{ retryLabel() }}
        </button>
      }
    </div>
  `,
  styles: [
    `
      .error-state {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: var(--space-3);
        padding: var(--space-4);
        background: var(--danger-dim);
        border: 1px solid var(--border-strong);
        border-radius: var(--radius-md);
        color: var(--danger);
      }
      .ico {
        flex-shrink: 0;
      }
      .msg {
        flex: 1;
        min-width: 200px;
        font-size: var(--font-size-sm);
        color: var(--danger);
      }
      .retry {
        color: var(--text-1);
      }
    `
  ]
})
export class ErrorStateComponent {
  message = input<string>('Something went wrong');
  /** When non-empty, a retry button with this label is rendered. */
  retryLabel = input('');
  testid = input('');

  @Output() retry = new EventEmitter<void>();
}
