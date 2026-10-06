import { TestBed, ComponentFixture } from '@angular/core/testing';

import { TabsComponent, TabDef } from './tabs.component';

describe('TabsComponent — ARIA tablist with manual activation', () => {
  let fixture: ComponentFixture<TabsComponent>;

  const defs: TabDef[] = [
    { id: 'prs', label: 'Pull requests' },
    { id: 'settings', label: 'Settings' }
  ];

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [TabsComponent] });
    fixture = TestBed.createComponent(TabsComponent);
    fixture.componentRef.setInput('tabs', defs);
    fixture.componentRef.setInput('active', 'prs');
    fixture.detectChanges();
  });

  function tabs(): HTMLButtonElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
  }

  it('renders one tab button per definition with aria wiring', () => {
    expect(tabs().length).toBe(2);
    expect(tabs()[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs()[1].getAttribute('aria-selected')).toBe('false');
    expect(tabs()[0].getAttribute('aria-controls')).toBe('panel-prs');
    expect(tabs()[0].getAttribute('id')).toBe('tab-prs');
    expect(tabs()[0].getAttribute('tabindex')).toBe('0');
    expect(tabs()[1].getAttribute('tabindex')).toBe('-1');
    expect(fixture.nativeElement.querySelector('[role="tablist"]')).not.toBeNull();
  });

  it('emits activeChange on click (activation stays manual)', () => {
    // A spy sidesteps TS narrowing of `let x = null` assigned in a callback.
    const emitted = jasmine.createSpy('activeChange');
    fixture.componentInstance.activeChange.subscribe(emitted);

    tabs()[1].click();
    expect(emitted).toHaveBeenCalledWith('settings');
    // Focus movement must not activate on its own.
    expect(fixture.componentInstance.active()).toBe('prs');
  });

  it('moves focus with arrows/Home/End without activating', () => {
    tabs()[0].focus();
    const key = (k: string) =>
      fixture.nativeElement
        .querySelector('[role="tablist"]')
        .dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
    let emitted: string | null = null;
    fixture.componentInstance.activeChange.subscribe(v => (emitted = v));

    key('ArrowRight');
    expect(document.activeElement).toBe(tabs()[1]);
    key('Home');
    expect(document.activeElement).toBe(tabs()[0]);
    key('End');
    expect(document.activeElement).toBe(tabs()[1]);
    key('ArrowLeft');
    expect(document.activeElement).toBe(tabs()[0]);

    expect(emitted).toBeNull(); // arrows never activate
  });

  it('wraps arrow focus at both ends', () => {
    tabs()[0].focus();
    const key = (k: string) =>
      fixture.nativeElement
        .querySelector('[role="tablist"]')
        .dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));

    key('ArrowLeft'); // first → last
    expect(document.activeElement).toBe(tabs()[1]);
    key('ArrowRight'); // last → first
    expect(document.activeElement).toBe(tabs()[0]);
  });
});
