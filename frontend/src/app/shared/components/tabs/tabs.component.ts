import { Component, ElementRef, input, output, viewChild } from '@angular/core';

export interface TabDef {
  id: string;
  label: string;
}

/**
 * Tablist primitive (plan §5 — built when its first consumer landed, Step 6).
 * ARIA tabs with MANUAL activation (APG): arrows/Home/End move focus, and the
 * focused tab is activated by click or Enter/Space — which the native
 * `<button>` gives us for free, so no key handling beyond focus movement.
 * Panels are rendered by the consumer (`role="tabpanel"` + `id="panel-{id}"`
 * / `aria-labelledby="tab-{id}"` to match the attributes emitted here).
 */
@Component({
  selector: 'app-tabs',
  standalone: true,
  template: `
    <div class="tablist" #tablist role="tablist" tabindex="-1" (keydown)="onKeydown($event)">
      @for (tab of tabs(); track tab.id) {
        <button
          type="button"
          role="tab"
          class="tab"
          [class.active]="tab.id === active()"
          [attr.id]="'tab-' + tab.id"
          [attr.aria-selected]="tab.id === active()"
          [attr.aria-controls]="'panel-' + tab.id"
          [attr.tabindex]="tab.id === active() ? 0 : -1"
          [attr.data-testid]="'tab-' + tab.id"
          (click)="activeChange.emit(tab.id)"
        >
          {{ tab.label }}
        </button>
      }
    </div>
  `,
  styles: [
    `
      .tablist {
        display: flex;
        gap: var(--space-1);
        border-bottom: 1px solid var(--border-subtle);
      }
      .tab {
        appearance: none;
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        margin-bottom: -1px;
        padding: var(--space-3) var(--space-4);
        font-family: var(--font-mono);
        font-size: var(--font-size-sm);
        font-weight: 500;
        color: var(--text-3);
        cursor: pointer;
        transition: color var(--motion-fast) var(--motion-ease);
      }
      .tab:hover {
        color: var(--text-1);
      }
      .tab.active {
        color: var(--text-1);
        border-bottom-color: var(--accent);
      }
      :host {
        display: block;
      }
    `
  ]
})
export class TabsComponent {
  tabs = input.required<TabDef[]>();
  active = input.required<string>();
  readonly activeChange = output<string>();

  private readonly host = viewChild.required<ElementRef<HTMLDivElement>>('tablist');

  /** Focus movement only — activation stays on click/Enter (manual pattern). */
  onKeydown(event: KeyboardEvent): void {
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) {
      return;
    }
    const buttons = Array.from(
      this.host().nativeElement.querySelectorAll<HTMLButtonElement>('[role="tab"]')
    );
    const current = buttons.findIndex(btn => btn === document.activeElement);
    if (current < 0) {
      return;
    }
    event.preventDefault();
    let next = current;
    if (event.key === 'ArrowRight') next = (current + 1) % buttons.length;
    if (event.key === 'ArrowLeft') next = (current - 1 + buttons.length) % buttons.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = buttons.length - 1;
    buttons[next]?.focus();
  }
}
