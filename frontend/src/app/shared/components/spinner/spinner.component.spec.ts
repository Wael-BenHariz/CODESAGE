import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SpinnerComponent } from './spinner.component';

describe('SpinnerComponent', () => {
  let fixture: ComponentFixture<SpinnerComponent>;

  function wrapper(): HTMLElement {
    return fixture.nativeElement.querySelector('.spinner-wrap');
  }

  function spinnerEl(): HTMLElement {
    return fixture.nativeElement.querySelector('.cs-spinner');
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [SpinnerComponent] }).compileComponents();
    fixture = TestBed.createComponent(SpinnerComponent);
  });

  it('announces itself through role="status" with a default accessible name', () => {
    fixture.detectChanges();

    expect(wrapper().getAttribute('role')).toBe('status');
    expect(wrapper().getAttribute('aria-label')).toBe('Loading');
  });

  it('uses the label as accessible name and visible text when provided', () => {
    fixture.componentRef.setInput('label', 'Loading reviews');
    fixture.detectChanges();

    expect(wrapper().getAttribute('aria-label')).toBe('Loading reviews');
    expect(wrapper().textContent).toContain('Loading reviews');
  });

  it('maps size to px (sm 16 / md 32 / lg 48) and border width', () => {
    fixture.detectChanges();
    expect(spinnerEl().style.width).toBe('32px');
    expect(spinnerEl().style.borderWidth).toBe('3px');

    fixture.componentRef.setInput('size', 'sm');
    fixture.detectChanges();
    expect(spinnerEl().style.width).toBe('16px');
    expect(spinnerEl().style.borderWidth).toBe('2px');

    fixture.componentRef.setInput('size', 'lg');
    fixture.detectChanges();
    expect(spinnerEl().style.width).toBe('48px');
    expect(spinnerEl().style.borderWidth).toBe('4px');
  });

  it('binds data-testid onto the status wrapper only when provided', () => {
    fixture.detectChanges();
    expect(wrapper().hasAttribute('data-testid')).toBeFalse();

    fixture.componentRef.setInput('testid', 'repos-loading');
    fixture.detectChanges();
    expect(wrapper().getAttribute('data-testid')).toBe('repos-loading');
  });
});
