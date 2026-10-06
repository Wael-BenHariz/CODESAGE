import { Component, computed, input } from '@angular/core';

/**
 * Loading spinner — the "loading" leg of the four-state UI pattern
 * (loading / empty / error+retry / success). Sizes: sm | md | lg.
 * Keeps spinning under prefers-reduced-motion (the global kill-switch in
 * styles.scss exempts .cs-spinner): a static spinner would lie about state.
 */
@Component({
  selector: 'app-spinner',
  standalone: true,
  template: `
    <div
      class="spinner-wrap"
      role="status"
      [attr.aria-label]="label() || 'Loading'"
      [attr.data-testid]="testid() || null"
    >
      <span
        class="cs-spinner"
        [style.width.px]="sizePx()"
        [style.height.px]="sizePx()"
        [style.borderWidth.px]="borderPx()"
      ></span>
      @if (label()) {
        <span class="label">{{ label() }}</span>
      }
    </div>
  `,
  styles: [
    `
      .spinner-wrap {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
      }
      .cs-spinner {
        display: inline-block;
        border-style: solid;
        border-color: var(--border-control);
        border-top-color: var(--accent);
        border-radius: var(--radius-full);
        animation: cs-spin 0.9s linear infinite;
      }
      .label {
        color: var(--text-2);
        font-size: var(--font-size-sm);
      }
      @keyframes cs-spin {
        to {
          transform: rotate(360deg);
        }
      }
    `
  ]
})
export class SpinnerComponent {
  size = input<'sm' | 'md' | 'lg'>('md');
  /** Visible text next to the spinner; also used as the accessible name. */
  label = input('');
  /** Optional data-testid for the wrapping status element. */
  testid = input('');

  readonly sizePx = computed(() => (this.size() === 'sm' ? 16 : this.size() === 'lg' ? 48 : 32));
  readonly borderPx = computed(() => (this.size() === 'sm' ? 2 : this.size() === 'lg' ? 4 : 3));
}
