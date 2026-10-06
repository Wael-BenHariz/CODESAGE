import { Component, input, OnDestroy, signal } from '@angular/core';

/**
 * Copy-to-clipboard button with honest feedback: "Copied" only appears
 * after the clipboard write resolves; a rejected write shows
 * "Copy failed" (never a false success). Disabled while a write is in
 * flight. Status is announced through an aria-live region.
 */
@Component({
  selector: 'app-copy',
  standalone: true,
  template: `
    <button
      type="button"
      class="copy-btn"
      [attr.aria-label]="copied() ? 'Copied' : label()"
      [attr.data-testid]="testid() || null"
      [disabled]="pending()"
      (click)="copy()"
    >
      @if (copied()) {
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2.2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M4 12.5 9.5 18 20 6.5" />
        </svg>
      } @else {
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <rect x="9" y="9" width="12" height="12" rx="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      }
    </button>
    <span class="status" [class.ok]="copied()" [class.err]="failed()" aria-live="polite">{{
      status()
    }}</span>
  `,
  styles: [
    `
      :host {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
      }
      .copy-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        padding: 0;
        border: 1px solid transparent;
        border-radius: var(--radius-xs);
        background: transparent;
        color: var(--text-2);
        transition:
          color var(--motion-fast) var(--motion-ease),
          background var(--motion-fast) var(--motion-ease);
      }
      .copy-btn:hover:not(:disabled) {
        color: var(--text-1);
        background: var(--surface-hover);
      }
      .copy-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      .status {
        font-family: var(--font-mono);
        font-size: var(--font-size-xs);
        color: var(--text-3);
      }
      .status.ok {
        color: var(--accent);
      }
      .status.err {
        color: var(--danger);
      }
      .status:empty {
        display: none;
      }
    `
  ]
})
export class CopyButtonComponent implements OnDestroy {
  /** The text written to the clipboard. */
  value = input.required<string>();
  /** Accessible name of the button (default "Copy"). */
  label = input('Copy');
  testid = input('');

  readonly copied = signal(false);
  readonly failed = signal(false);
  readonly pending = signal(false);

  private resetTimer: ReturnType<typeof setTimeout> | null = null;

  status(): string {
    if (this.copied()) return 'Copied';
    if (this.failed()) return 'Copy failed';
    return '';
  }

  async copy(): Promise<void> {
    if (this.pending()) return;
    this.pending.set(true);
    try {
      await navigator.clipboard.writeText(this.value());
      this.copied.set(true);
      this.failed.set(false);
    } catch {
      this.copied.set(false);
      this.failed.set(true);
    } finally {
      this.pending.set(false);
      this.scheduleReset();
    }
  }

  private scheduleReset(): void {
    if (this.resetTimer !== null) clearTimeout(this.resetTimer);
    this.resetTimer = setTimeout(() => {
      this.copied.set(false);
      this.failed.set(false);
      this.resetTimer = null;
    }, 1600);
  }

  ngOnDestroy(): void {
    if (this.resetTimer !== null) clearTimeout(this.resetTimer);
  }
}
