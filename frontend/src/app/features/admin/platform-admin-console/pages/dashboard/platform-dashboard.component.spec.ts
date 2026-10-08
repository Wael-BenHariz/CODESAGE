import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { PlatformDashboardComponent } from './platform-dashboard.component';

describe('PlatformDashboardComponent (static mock data)', () => {
  let fixture: ComponentFixture<PlatformDashboardComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [PlatformDashboardComponent],
      providers: [provideRouter([])]
    });
    fixture = TestBed.createComponent(PlatformDashboardComponent);
    fixture.detectChanges();
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('renders the four statistic cards', () => {
    expect(el().querySelector('[data-testid="pa-stat-users"]')?.textContent).toContain('248');
    expect(el().querySelector('[data-testid="pa-stat-reviews"]')?.textContent).toContain('1 284');
    expect(el().querySelector('[data-testid="pa-stat-tokens"]')?.textContent).toContain('2.8M');
    expect(el().querySelector('[data-testid="pa-stat-storage"]')?.textContent).toContain('18.4 GB');
  });

  it('renders the static system health summary', () => {
    const health = el().querySelector('[data-testid="pa-health-api"]')?.textContent ?? '';
    expect(health).toContain('API');
    expect(health).toContain('Opérationnel');
    expect(el().querySelectorAll('.pa-health-card').length).toBe(4);
  });

  it('renders the weekly usage chart with one bar per day', () => {
    expect(el().querySelectorAll('.pa-chart-bar').length).toBe(7);
    expect(el().querySelectorAll('.pa-chart-label')[0].textContent).toBe('Mon');
  });

  it('links the quick actions to the console pages', () => {
    const hrefs = Array.from(el().querySelectorAll('.pa-quick-actions a')).map(
      a => a.getAttribute('href') ?? ''
    );
    expect(hrefs).toEqual([
      '/platform-admin/users',
      '/platform-admin/logs',
      '/platform-admin/system',
      '/platform-admin/quotas'
    ]);
  });
});
