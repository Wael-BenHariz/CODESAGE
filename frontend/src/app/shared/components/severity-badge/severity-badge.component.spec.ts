import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SeverityBadgeComponent, SeverityLevel } from './severity-badge.component';

describe('SeverityBadgeComponent', () => {
  let fixture: ComponentFixture<SeverityBadgeComponent>;
  let el: HTMLElement;

  const levels: SeverityLevel[] = ['critical', 'high', 'medium', 'low', 'info'];

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [SeverityBadgeComponent] }).compileComponents();
    fixture = TestBed.createComponent(SeverityBadgeComponent);
    el = fixture.nativeElement;
  });

  it('renders every level of the frozen 5-step scale with icon AND text (never colour alone)', () => {
    for (const level of levels) {
      fixture.componentRef.setInput('severity', level);
      fixture.detectChanges();

      const badge = el.querySelector('.sev-badge') as HTMLElement;
      expect(badge.textContent?.trim().toLowerCase()).toBe(level);
      expect(badge.querySelector('svg')).not.toBeNull();
      expect(badge.className).toContain(`sev-${level}`);
    }
  });

  it('uses distinct icon markup per level so the colour is redundant signal', () => {
    const markupOf = (level: SeverityLevel): string => {
      fixture.componentRef.setInput('severity', level);
      fixture.detectChanges();
      return (el.querySelector('.sev-badge svg') as SVGElement).outerHTML;
    };

    const markup = levels.map(markupOf);
    expect(new Set(markup).size).toBe(levels.length);
  });

  it('is a compact uppercase monospace chip', () => {
    fixture.componentRef.setInput('severity', 'high');
    fixture.detectChanges();

    const badge = el.querySelector('.sev-badge') as HTMLElement;
    expect(getComputedStyle(badge).textTransform).toBe('uppercase');
    expect(getComputedStyle(badge).fontFamily.toLowerCase()).toContain('mono');
  });
});
