import { TestBed, ComponentFixture } from '@angular/core/testing';

import { ConfirmDialogComponent } from './confirm-dialog.component';

describe('ConfirmDialogComponent — alertdialog with focus restore', () => {
  let fixture: ComponentFixture<ConfirmDialogComponent>;
  let confirmed: jasmine.Spy;
  let cancelled: jasmine.Spy;

  beforeEach(() => {
    confirmed = jasmine.createSpy('confirmed');
    cancelled = jasmine.createSpy('cancelled');
    TestBed.configureTestingModule({ imports: [ConfirmDialogComponent] });
    fixture = TestBed.createComponent(ConfirmDialogComponent);
    fixture.componentRef.setInput('title', 'Remove repository');
    fixture.componentRef.setInput('message', 'Remove acme/api from CodeSage?');
    fixture.componentRef.setInput('confirmLabel', 'Remove');
    fixture.componentInstance.confirmed.subscribe(confirmed);
    fixture.componentInstance.cancelled.subscribe(cancelled);
    fixture.detectChanges();
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('renders an alertdialog with bound copy (no HTML interpolation)', () => {
    const dialog = el().querySelector('[role="alertdialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.getAttribute('aria-modal')).toBe('true');
    expect(dialog?.getAttribute('aria-labelledby')).toBe('cd-title');
    expect(el().textContent).toContain('Remove acme/api from CodeSage?');
    expect(el().textContent).toContain('Remove');
  });

  it('focuses the confirm button on open and emits confirmed on click', () => {
    expect(document.activeElement).toBe(el().querySelector('.cd-confirm'));
    (el().querySelector('.cd-confirm') as HTMLButtonElement).click();
    expect(confirmed).toHaveBeenCalledTimes(1);
    expect(cancelled).not.toHaveBeenCalled();
  });

  it('cancels on Escape and on backdrop clicks only', () => {
    fixture.componentInstance.onEscape();
    expect(cancelled).toHaveBeenCalledTimes(1);

    const overlay = el().querySelector('.cd-overlay') as HTMLElement;
    overlay.dispatchEvent(new MouseEvent('click')); // target === currentTarget
    expect(cancelled).toHaveBeenCalledTimes(2);

    const dialog = el().querySelector('.cd-dialog') as HTMLElement;
    dialog.dispatchEvent(new MouseEvent('click')); // inside → ignored
    expect(cancelled).toHaveBeenCalledTimes(2);
  });

  it('disables the confirm button while busy and shows an inline error', () => {
    fixture.componentRef.setInput('busy', true);
    fixture.componentRef.setInput('error', 'Could not remove the repository.');
    fixture.detectChanges();

    expect((el().querySelector('.cd-confirm') as HTMLButtonElement).disabled).toBeTrue();
    expect(el().querySelector('.cd-error')?.textContent).toContain(
      'Could not remove the repository.'
    );
    expect(el().querySelector('.cd-error')?.getAttribute('role')).toBe('alert');
  });

  it('restores focus to the opener on destroy', () => {
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    opener.focus();

    // Re-create while the opener holds focus, so ngAfterViewInit captures it.
    fixture.destroy();
    fixture = TestBed.createComponent(ConfirmDialogComponent);
    fixture.componentRef.setInput('message', 'Sure?');
    fixture.detectChanges();
    expect(document.activeElement).toBe(el().querySelector('.cd-confirm'));

    fixture.destroy();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});
