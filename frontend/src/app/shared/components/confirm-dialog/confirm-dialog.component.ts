import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  OnDestroy,
  Output,
  ViewChild,
  input
} from '@angular/core';

/**
 * Modal confirm dialog (plan §5 primitive, first consumer Step 6).
 * `role="alertdialog"` + `aria-modal`, focus moves to the confirm button on
 * open and is restored to the opener on close; Escape and backdrop clicks
 * cancel. All copy is bound as plain interpolation — there is no HTML input,
 * so nothing here can ever bypass the template sanitizer.
 */
@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  template: `
    <div
      class="cd-overlay"
      tabindex="-1"
      (click)="onOverlayClick($event)"
      (keyup.escape)="onEscape()"
    >
      <div
        class="cd-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="cd-title"
        aria-describedby="cd-message"
        [attr.data-testid]="testid()"
      >
        <h2 class="cd-title" id="cd-title">{{ title() }}</h2>
        <p class="cd-message" id="cd-message">{{ message() }}</p>
        @if (error()) {
          <p class="cd-error" role="alert">{{ error() }}</p>
        }
        <div class="cd-actions">
          <button type="button" class="cd-cancel" #cancel (click)="cancelled.emit()">
            {{ cancelLabel() }}
          </button>
          <button
            type="button"
            class="cd-confirm"
            [class.danger]="tone() === 'danger'"
            [disabled]="busy()"
            #confirm
            (click)="confirmed.emit()"
          >
            {{ confirmLabel() }}
          </button>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      .cd-overlay {
        position: fixed;
        inset: 0;
        z-index: var(--z-dialog);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: var(--space-4);
        background: rgba(0, 0, 0, 0.6);
      }
      .cd-dialog {
        width: 100%;
        max-width: 420px;
        background: var(--surface-1);
        border: 1px solid var(--border-strong);
        border-radius: var(--radius-md);
        padding: var(--space-5);
        box-shadow: var(--shadow-lg);
      }
      .cd-title {
        margin: 0 0 var(--space-2);
        font-family: var(--font-mono);
        font-size: var(--font-size-lg);
        color: var(--text-1);
      }
      .cd-message {
        margin: 0 0 var(--space-4);
        font-size: var(--font-size-sm);
        line-height: var(--line-height-base);
        color: var(--text-2);
      }
      .cd-error {
        margin: 0 0 var(--space-3);
        font-family: var(--font-mono);
        font-size: var(--font-size-xs);
        color: var(--danger);
      }
      .cd-actions {
        display: flex;
        justify-content: flex-end;
        gap: var(--space-2);
      }
      .cd-cancel,
      .cd-confirm {
        font-family: var(--font-mono);
        font-size: var(--font-size-sm);
        font-weight: 500;
        padding: var(--space-2) var(--space-4);
        border-radius: var(--radius-xs);
        cursor: pointer;
        transition: all var(--motion-fast) var(--motion-ease);
      }
      .cd-cancel {
        background: transparent;
        border: 1px solid var(--border-strong);
        color: var(--text-2);
      }
      .cd-cancel:hover {
        color: var(--text-1);
        background: var(--surface-2);
      }
      .cd-confirm {
        background: var(--accent);
        border: 1px solid var(--accent);
        color: var(--text-inverse);
      }
      .cd-confirm:hover:not(:disabled) {
        background: var(--accent-hover);
        border-color: var(--accent-hover);
      }
      .cd-confirm.danger {
        background: var(--danger);
        border-color: var(--danger);
        color: var(--text-inverse);
      }
      .cd-confirm:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
    `
  ]
})
export class ConfirmDialogComponent implements AfterViewInit, OnDestroy {
  title = input('Confirm');
  message = input.required<string>();
  confirmLabel = input('Confirm');
  cancelLabel = input('Cancel');
  tone = input<'default' | 'danger'>('default');
  /** Disables the confirm button while the action is in flight. */
  busy = input(false);
  /** Inline failure (role=alert) — the dialog stays open so it can be retried. */
  error = input('');
  testid = input('confirm-dialog');

  @Output() confirmed = new EventEmitter<void>();
  @Output() cancelled = new EventEmitter<void>();

  @ViewChild('confirm') private confirmBtn?: ElementRef<HTMLButtonElement>;
  private opener: HTMLElement | null = null;

  ngAfterViewInit(): void {
    this.opener = document.activeElement as HTMLElement | null;
    this.confirmBtn?.nativeElement.focus();
  }

  ngOnDestroy(): void {
    // Return focus to whatever opened the dialog (keyboard a11y).
    if (this.opener && typeof this.opener.focus === 'function') {
      this.opener.focus();
    }
  }

  /** Escape cancels — wired on the overlay (keyup) like the connect modal. */
  onEscape(): void {
    this.cancelled.emit();
  }

  /** Closes only when the backdrop itself was clicked. */
  onOverlayClick(event: Event): void {
    if (event.target === event.currentTarget) {
      this.cancelled.emit();
    }
  }
}
