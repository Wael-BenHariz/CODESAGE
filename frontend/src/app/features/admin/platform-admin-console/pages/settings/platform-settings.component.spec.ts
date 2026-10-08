import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { PlatformSettingsComponent } from './platform-settings.component';
import { ToastService } from '../../../../../core/services/toast.service';

describe('PlatformSettingsComponent (static mock data)', () => {
  let fixture: ComponentFixture<PlatformSettingsComponent>;
  let component: PlatformSettingsComponent;
  let toast: ToastService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [PlatformSettingsComponent],
      providers: [provideRouter([])]
    });
    fixture = TestBed.createComponent(PlatformSettingsComponent);
    component = fixture.componentInstance;
    toast = TestBed.inject(ToastService);
    fixture.detectChanges();
  });

  it('renders the three settings sections with demo defaults', () => {
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Paramètres généraux');
    expect(text).toContain('Paramètres IA');
    expect(text).toContain('Sécurité');
    expect(component.general().platformName).toBe('CODESAGE');
    expect(component.ai().provider).toBe('Gemini');
    expect(component.security().sessionDurationMinutes).toBe(60);
  });

  it('toggles the maintenance switch locally', () => {
    expect(component.general().maintenanceMode).toBe(false);
    component.toggleGeneral('maintenanceMode');
    expect(component.general().maintenanceMode).toBe(true);
  });

  it('keeps typed values in local state', () => {
    component.setAiNumber('maxConcurrentRequests', '25');
    expect(component.ai().maxConcurrentRequests).toBe(25);

    component.setGeneral('appUrl', 'https://demo.example.com');
    expect(component.general().appUrl).toBe('https://demo.example.com');
  });

  it('shows a success toast on save without any persistence', () => {
    component.saveSecurity();
    expect(
      toast
        .toasts()
        .some((t: { message: string }) => t.message === 'Les paramètres ont été enregistrés.')
    ).toBe(true);
  });
});
