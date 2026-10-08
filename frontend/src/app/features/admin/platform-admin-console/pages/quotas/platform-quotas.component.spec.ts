import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { PlatformQuotasComponent } from './platform-quotas.component';
import { ToastService } from '../../../../../core/services/toast.service';

describe('PlatformQuotasComponent (static mock data)', () => {
  let fixture: ComponentFixture<PlatformQuotasComponent>;
  let component: PlatformQuotasComponent;
  let toast: ToastService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [PlatformQuotasComponent],
      providers: [provideRouter([])]
    });
    fixture = TestBed.createComponent(PlatformQuotasComponent);
    component = fixture.componentInstance;
    toast = TestBed.inject(ToastService);
    fixture.detectChanges();
  });

  it('renders the usage cards, quota bars and organization tables', () => {
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="pa-usage-reviews"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="pa-quota-bar-llm"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="pa-org-usage-table"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="pa-org-quotas-table"]')).not.toBeNull();
  });

  it('prefills the quota modal from the local quota copy', () => {
    component.openQuotaModal();
    expect(component.modalOpen()).toBe(true);
    expect(component.orgDraft()).toBe('Company A');
    expect(component.reviewQuotaDraft()).toBe(1000);

    component.setOrgDraft('Company B');
    expect(component.reviewQuotaDraft()).toBe(800);
  });

  it('saves quota edits to local state with a toast', () => {
    component.openQuotaModal();
    component.reviewQuotaDraft.set(1500);
    component.storageQuotaDraft.set('14 GB');
    component.saveQuotas();
    fixture.detectChanges();

    expect(component.modalOpen()).toBe(false);
    expect(component.quotas()[0].reviewQuota).toBe(1500);
    expect(component.quotas()[0].storageQuota).toBe('14 GB');
    expect(
      toast
        .toasts()
        .some((t: { message: string }) => t.message === 'Les quotas ont été mis à jour.')
    ).toBe(true);

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('1500');
  });
});
