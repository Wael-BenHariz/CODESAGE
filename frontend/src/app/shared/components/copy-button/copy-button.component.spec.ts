import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CopyButtonComponent } from './copy-button.component';

describe('CopyButtonComponent', () => {
  let fixture: ComponentFixture<CopyButtonComponent>;
  let el: HTMLElement;
  let writeText: jasmine.Spy;

  function button(): HTMLButtonElement {
    return el.querySelector('.copy-btn') as HTMLButtonElement;
  }

  function status(): string {
    return (el.querySelector('.status') as HTMLElement).textContent?.trim() ?? '';
  }

  /** Flush one macrotask so the copy() continuation lands — but well before
   *  the 1600 ms status-reset timer (whenStable would wait for that timer
   *  and the assertions would see the reverted status). */
  function flushCopy(): Promise<void> {
    return new Promise<void>(resolve => setTimeout(resolve, 0));
  }

  beforeEach(async () => {
    writeText = jasmine.createSpy('writeText').and.resolveTo(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true
    });

    await TestBed.configureTestingModule({ imports: [CopyButtonComponent] }).compileComponents();
    fixture = TestBed.createComponent(CopyButtonComponent);
    fixture.componentRef.setInput('value', 'abc123');
    fixture.detectChanges();
    el = fixture.nativeElement;
  });

  afterEach(() => fixture.destroy());

  it('writes the value to the clipboard and reports Copied only on success', async () => {
    button().click();
    await flushCopy();
    fixture.detectChanges();

    expect(writeText).toHaveBeenCalledWith('abc123');
    expect(status()).toBe('Copied');
    expect(button().getAttribute('aria-label')).toBe('Copied');
    expect(button().disabled).toBeFalse();
  });

  it('never claims success when the clipboard write rejects', async () => {
    writeText.and.rejectWith(new Error('denied'));

    button().click();
    await flushCopy();
    fixture.detectChanges();

    expect(status()).toBe('Copy failed');
    expect(button().getAttribute('aria-label')).toBe('Copy');
  });

  it('is disabled while a write is in flight', async () => {
    let resolveWrite: (v: void) => void = () => undefined;
    writeText.and.returnValue(new Promise<void>(res => (resolveWrite = res)));

    button().click();
    fixture.detectChanges();
    expect(button().disabled).toBeTrue();

    resolveWrite();
    await flushCopy();
    fixture.detectChanges();
    expect(button().disabled).toBeFalse();
  });

  it('uses the caller label as the default accessible name', () => {
    expect(button().getAttribute('aria-label')).toBe('Copy');

    fixture.componentRef.setInput('label', 'Copy run command');
    fixture.detectChanges();
    expect(button().getAttribute('aria-label')).toBe('Copy run command');
  });

  it('binds an optional data-testid', () => {
    expect(button().hasAttribute('data-testid')).toBeFalse();

    fixture.componentRef.setInput('testid', 'copy-sha');
    fixture.detectChanges();
    expect(button().getAttribute('data-testid')).toBe('copy-sha');
  });
});
