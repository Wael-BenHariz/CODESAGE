import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SkeletonComponent } from './skeleton.component';

describe('SkeletonComponent', () => {
  let fixture: ComponentFixture<SkeletonComponent>;
  let el: HTMLElement;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [SkeletonComponent] }).compileComponents();
    fixture = TestBed.createComponent(SkeletonComponent);
    fixture.detectChanges();
    el = fixture.nativeElement.querySelector('.skeleton');
  });

  it('renders a decorative block (aria-hidden, no text)', () => {
    expect(el).not.toBeNull();
    expect(el.getAttribute('aria-hidden')).toBe('true');
    expect(el.textContent?.trim()).toBe('');
  });

  it('applies the requested dimensions', () => {
    expect(el.style.width).toBe('100%');
    expect(el.style.height).toBe('16px');

    fixture.componentRef.setInput('width', '120px');
    fixture.componentRef.setInput('height', '32px');
    fixture.detectChanges();

    expect(el.style.width).toBe('120px');
    expect(el.style.height).toBe('32px');
  });

  it('binds an optional data-testid', () => {
    expect(el.hasAttribute('data-testid')).toBeFalse();

    fixture.componentRef.setInput('testid', 'users-loading');
    fixture.detectChanges();

    expect(el.getAttribute('data-testid')).toBe('users-loading');
  });
});
