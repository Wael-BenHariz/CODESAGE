import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ErrorStateComponent } from './error-state.component';

describe('ErrorStateComponent', () => {
  let fixture: ComponentFixture<ErrorStateComponent>;
  let el: HTMLElement;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [ErrorStateComponent] }).compileComponents();
    fixture = TestBed.createComponent(ErrorStateComponent);
    fixture.detectChanges();
    el = fixture.nativeElement;
  });

  it('renders the failure as role="alert" with a default message', () => {
    const state = el.querySelector('.error-state') as HTMLElement;
    expect(state.getAttribute('role')).toBe('alert');
    expect(state.textContent).toContain('Something went wrong');
  });

  it('renders no retry button unless the caller provides a retry label', () => {
    expect(el.querySelector('button.retry')).toBeNull();

    fixture.componentRef.setInput('retryLabel', 'Retry');
    fixture.detectChanges();

    const btn = el.querySelector('button.retry') as HTMLButtonElement;
    expect(btn.textContent).toContain('Retry');
  });

  it('emits retry when the retry button is activated', () => {
    fixture.componentRef.setInput('retryLabel', 'Retry');
    fixture.detectChanges();
    const spy = jasmine.createSpy('retry');
    fixture.componentInstance.retry.subscribe(spy);

    (el.querySelector('button.retry') as HTMLButtonElement).click();

    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('binds the caller testid onto the state root', () => {
    const root = (): string =>
      (el.querySelector('.error-state') as HTMLElement).getAttribute('data-testid') ?? '';

    expect(root()).toBe('');

    fixture.componentRef.setInput('testid', 'users-error');
    fixture.detectChanges();

    expect(root()).toBe('users-error');
  });
});
