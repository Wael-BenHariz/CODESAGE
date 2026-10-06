import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  inject,
  input,
  signal
} from '@angular/core';

/**
 * Contextual "?" help popover (plan §4.5) — a disclosure button that opens a
 * plain-text panel fed by `shared/help.copy.ts`, the same constants /help
 * renders, so wording can never drift between the page and the popover.
 *
 * Accessible by construction: a real <button> with aria-label, aria-expanded,
 * aria-controls and aria-describedby; Escape closes and restores focus, an
 * outside click closes. Text is interpolated only (escaped) — no innerHTML.
 * Panel sits on the --z-popover token.
 */
@Component({
  selector: 'app-help-popover',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      type="button"
      class="help-trigger"
      [attr.aria-label]="label()"
      [attr.aria-expanded]="open()"
      [attr.aria-controls]="panelId"
      [attr.aria-describedby]="open() ? panelId : null"
      (click)="toggle()"
      data-testid="help-trigger"
    >
      ?
    </button>
    @if (open()) {
      <div class="help-panel" [id]="panelId" data-testid="help-panel">{{ content() }}</div>
    }
  `,
  styles: [
    `
      :host {
        position: relative;
        display: inline-flex;
        vertical-align: middle;
      }

      .help-trigger {
        width: 18px;
        height: 18px;
        padding: 0;
        margin-left: 4px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        font-weight: 700;
        line-height: 1;
        color: var(--text-2);
        background: var(--surface-2);
        border: 1px solid var(--border-strong);
        border-radius: var(--radius-full);
        cursor: pointer;
      }

      .help-trigger:hover {
        color: var(--text-1);
        border-color: var(--text-3);
      }

      .help-trigger:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: 2px;
      }

      .help-trigger[aria-expanded='true'] {
        color: var(--text-inverse);
        background: var(--accent);
        border-color: var(--accent);
      }

      .help-panel {
        position: absolute;
        top: calc(100% + 6px);
        left: 0;
        z-index: var(--z-popover);
        width: max-content;
        max-width: min(320px, calc(100vw - 48px));
        padding: 10px 12px;
        font-size: var(--font-size-xs);
        font-weight: 400;
        line-height: 1.6;
        letter-spacing: normal;
        text-transform: none;
        text-align: left;
        white-space: pre-line;
        color: var(--text-2);
        background: var(--surface-2);
        border: 1px solid var(--border-strong);
        border-radius: var(--radius-md);
        box-shadow: var(--shadow-lg);
      }
    `
  ]
})
export class HelpPopoverComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** Accessible name of the trigger (a question, e.g. "What do severities mean?"). */
  readonly label = input.required<string>();
  /** Plain-text panel body (newline-separated), rendered escaped. */
  readonly content = input.required<string>();
  readonly open = signal(false);

  private static sequence = 0;
  readonly panelId = `help-popover-panel-${++HelpPopoverComponent.sequence}`;

  toggle(): void {
    this.open.update(value => !value);
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.open()) return;
    const target = event.target as Node | null;
    if (target !== null && !this.host.nativeElement.contains(target)) {
      this.open.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (!this.open()) return;
    this.open.set(false);
    const trigger = this.host.nativeElement.querySelector<HTMLButtonElement>('.help-trigger');
    trigger?.focus();
  }
}
