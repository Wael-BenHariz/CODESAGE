import { ComponentFixture, TestBed } from '@angular/core/testing';

import { HelpPopoverComponent } from './help-popover.component';

describe('HelpPopoverComponent (plan Step 9)', () => {
  let fixture: ComponentFixture<HelpPopoverComponent>;
  let component: HelpPopoverComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [HelpPopoverComponent] }).compileComponents();
    fixture = TestBed.createComponent(HelpPopoverComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('label', 'What do severities mean?');
    fixture.componentRef.setInput('content', 'Line one\nLine two');
    fixture.detectChanges();
  });

  function trigger(): HTMLButtonElement {
    return fixture.nativeElement.querySelector('[data-testid="help-trigger"]');
  }

  function panel(): HTMLElement | null {
    return fixture.nativeElement.querySelector('[data-testid="help-panel"]');
  }

  it('starts closed with an accessible disclosure trigger', () => {
    expect(trigger()).not.toBeNull();
    expect(trigger().getAttribute('aria-label')).toBe('What do severities mean?');
    expect(trigger().getAttribute('aria-expanded')).toBe('false');
    expect(trigger().getAttribute('aria-controls')).toBe(component.panelId);
    expect(panel()).toBeNull();
  });

  it('opens on click and wires aria-describedby to the panel', () => {
    trigger().click();
    fixture.detectChanges();

    expect(trigger().getAttribute('aria-expanded')).toBe('true');
    expect(panel()).not.toBeNull();
    expect(trigger().getAttribute('aria-describedby')).toBe(component.panelId);
    expect(panel()?.textContent).toBe('Line one\nLine two');
  });

  it('toggles closed on a second click', () => {
    trigger().click();
    fixture.detectChanges();
    trigger().click();
    fixture.detectChanges();

    expect(trigger().getAttribute('aria-expanded')).toBe('false');
    expect(panel()).toBeNull();
  });

  it('closes when a click lands outside the popover', () => {
    trigger().click();
    fixture.detectChanges();

    document.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    fixture.detectChanges();

    expect(trigger().getAttribute('aria-expanded')).toBe('false');
    expect(panel()).toBeNull();
  });

  it('closes on Escape and returns focus to the trigger', () => {
    trigger().click();
    fixture.detectChanges();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();

    expect(panel()).toBeNull();
    expect(document.activeElement).toBe(trigger());
  });

  it('renders markup-looking content as plain text (never innerHTML)', () => {
    fixture.componentRef.setInput('content', '<img src=x onerror="alert(1)"> & done');
    fixture.detectChanges();
    trigger().click();
    fixture.detectChanges();

    expect(panel()?.querySelector('img')).toBeNull();
    expect(panel()?.textContent).toContain('<img src=x onerror="alert(1)">');
    expect(panel()?.textContent).toContain('& done');
  });
});
