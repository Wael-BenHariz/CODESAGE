import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ToastService } from '../../../../../core/services/toast.service';
import {
  MOCK_AI_MODEL_OPTIONS,
  MOCK_AI_PROVIDER_OPTIONS,
  MOCK_LANGUAGE_OPTIONS,
  MockAiSettings,
  MockGeneralSettings,
  MockSecuritySettings,
  cloneAiSettings,
  cloneGeneralSettings,
  cloneSecuritySettings
} from '../../mock/platform-settings';

/**
 * Platform Administration → Paramètres (static PFE prototype) —
 * `/platform-admin/settings`.
 *
 * Three sections (généraux / IA / sécurité) edit local copies of the mock
 * settings. "Enregistrer" only commits to the component's signals and shows
 * a success toast: nothing is persisted, no LLM provider is contacted, and
 * a page refresh restores the demo defaults.
 */
@Component({
  selector: 'app-platform-settings',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './platform-settings.component.html'
})
export class PlatformSettingsComponent {
  private readonly toast = inject(ToastService);

  readonly languages = MOCK_LANGUAGE_OPTIONS;
  readonly providers = MOCK_AI_PROVIDER_OPTIONS;
  readonly models = MOCK_AI_MODEL_OPTIONS;

  readonly general = signal<MockGeneralSettings>(cloneGeneralSettings());
  readonly ai = signal<MockAiSettings>(cloneAiSettings());
  readonly security = signal<MockSecuritySettings>(cloneSecuritySettings());

  // ─── generic field setters ───────────────────────────────────────────────

  setGeneral<K extends keyof MockGeneralSettings>(key: K, value: MockGeneralSettings[K]): void {
    this.general.update(state => ({ ...state, [key]: value }));
  }

  setAi<K extends keyof MockAiSettings>(key: K, value: MockAiSettings[K]): void {
    this.ai.update(state => ({ ...state, [key]: value }));
  }

  setSecurity<K extends keyof MockSecuritySettings>(key: K, value: MockSecuritySettings[K]): void {
    this.security.update(state => ({ ...state, [key]: value }));
  }

  setGeneralNumber<K extends keyof MockGeneralSettings>(key: K, raw: unknown): void {
    const value = (raw === '' ? 0 : Number(raw)) as unknown as MockGeneralSettings[K];
    this.general.update(state => ({ ...state, [key]: value }));
  }

  setAiNumber<K extends keyof MockAiSettings>(key: K, raw: unknown): void {
    const value = (raw === '' ? 0 : Number(raw)) as unknown as MockAiSettings[K];
    this.ai.update(state => ({ ...state, [key]: value }));
  }

  setSecurityNumber<K extends keyof MockSecuritySettings>(key: K, raw: unknown): void {
    const value = (raw === '' ? 0 : Number(raw)) as unknown as MockSecuritySettings[K];
    this.security.update(state => ({ ...state, [key]: value }));
  }

  toggleGeneral(key: 'maintenanceMode'): void {
    this.general.update(state => ({ ...state, [key]: !state[key] }));
  }

  toggleSecurity(key: 'enforcedAuth'): void {
    this.security.update(state => ({ ...state, [key]: !state[key] }));
  }

  // ─── save (local only) ───────────────────────────────────────────────────

  saveGeneral(): void {
    this.toast.success('Les paramètres ont été enregistrés.');
  }

  saveAi(): void {
    this.toast.success('Les paramètres ont été enregistrés.');
  }

  saveSecurity(): void {
    this.toast.success('Les paramètres ont été enregistrés.');
  }
}
