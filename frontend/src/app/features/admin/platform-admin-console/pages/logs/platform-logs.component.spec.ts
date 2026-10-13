import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { PlatformLogsComponent } from './platform-logs.component';

describe('PlatformLogsComponent (static mock data)', () => {
  let fixture: ComponentFixture<PlatformLogsComponent>;
  let component: PlatformLogsComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [PlatformLogsComponent],
      providers: [provideRouter([])]
    });
    fixture = TestBed.createComponent(PlatformLogsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('renders the mock log rows', () => {
    expect(component.filtered().length).toBe(18);
    expect(el().querySelector('[data-testid="pa-logs-table"]')).not.toBeNull();
  });

  it('searches the logs locally', () => {
    component.search.set('queue latency');
    fixture.detectChanges();
    expect(component.filtered().length).toBe(1);
    expect(component.filtered()[0].level).toBe('WARNING');
  });

  it('filters by level and date locally', () => {
    component.levelFilter.set('ERROR');
    fixture.detectChanges();
    expect(component.filtered().every(entry => entry.level === 'ERROR')).toBe(true);
    expect(component.filtered().length).toBeGreaterThan(0);

    component.levelFilter.set('');
    component.dateFilter.set('07/10/2026');
    fixture.detectChanges();
    expect(component.filtered().every(entry => entry.date === '07/10/2026')).toBe(true);
  });

  it('opens the details modal for the clicked entry and closes it', () => {
    component.openLog(component.filtered()[0]);
    fixture.detectChanges();

    const modal = el().querySelector('[data-testid="pa-log-modal"]');
    expect(modal).not.toBeNull();
    expect(modal?.textContent).toContain('Request ID');
    expect(modal?.textContent).toContain('REV-2026-001284');

    component.closeLog();
    fixture.detectChanges();
    expect(el().querySelector('[data-testid="pa-log-modal"]')).toBeNull();
  });
});
