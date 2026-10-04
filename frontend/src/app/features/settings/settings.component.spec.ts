import { TestBed, ComponentFixture } from '@angular/core/testing';
import { signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { KeycloakService } from 'keycloak-angular';

import { AuthService } from '../../core/services/auth.service';

import { SettingsComponent } from './settings.component';
import {
  LLMSettings,
  LLMSettingsUpdate,
  LlmSettingsService
} from '../../core/services/llm-settings.service';
import { OrgSettingsService } from '../../core/services/org-settings.service';

describe('SettingsComponent — AI model settings', () => {
  let fixture: ComponentFixture<SettingsComponent>;
  let component: SettingsComponent;
  let svc: jasmine.SpyObj<LlmSettingsService>;
  let orgSvc: jasmine.SpyObj<OrgSettingsService>;
  /** Writable view of the fake session user (role drives the org link). */
  let authSignal: ReturnType<typeof signal<{ role: string } | null>>;

  const savedConfig: LLMSettings = {
    provider: 'groq',
    model: 'openai/gpt-oss-20b',
    baseUrl: null,
    hasApiKey: true,
    isUsingDefault: false
  };

  const defaultConfig: LLMSettings = {
    provider: null,
    model: null,
    baseUrl: null,
    hasApiKey: false,
    isUsingDefault: true
  };

  beforeEach(async () => {
    localStorage.removeItem('codesage_token');
    localStorage.removeItem('codesage_user');

    svc = jasmine.createSpyObj<LlmSettingsService>('LlmSettingsService', [
      'getLLMSettings',
      'saveLLMSettings',
      'clearLLMSettings',
      'testLLMSettings'
    ]);
    svc.getLLMSettings.and.returnValue(of(savedConfig));
    svc.saveLLMSettings.and.returnValue(of({ saved: true }));
    svc.clearLLMSettings.and.returnValue(of({ cleared: true }));
    svc.testLLMSettings.and.returnValue(
      of({
        success: true,
        response: 'OK',
        error: null,
        model: 'openai/gpt-oss-20b',
        latencyMs: 123
      })
    );

    orgSvc = jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', ['listOrgs']);
    orgSvc.listOrgs.and.returnValue(of([]));

    authSignal = signal<{ role: string } | null>(null);

    await TestBed.configureTestingModule({
      imports: [SettingsComponent],
      providers: [
        provideHttpClient(),
        // SettingsComponent imports RouterModule (org-settings link).
        provideRouter([]),
        { provide: LlmSettingsService, useValue: svc },
        { provide: OrgSettingsService, useValue: orgSvc },
        // Only currentUser().role is read by the org-link logic; null
        // mirrors the real AuthService in tests (no Keycloak session).
        { provide: AuthService, useValue: { currentUser: authSignal } },
        // AuthService (injected by the component) depends on KeycloakService.
        {
          provide: KeycloakService,
          useValue: jasmine.createSpyObj<KeycloakService>('KeycloakService', ['isLoggedIn'])
        }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(SettingsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges(); // ngOnInit -> loadSettings (synchronous of())
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function modelOptions(): string[] {
    const dl = el().querySelector('#llm-model-suggestions') as HTMLDataListElement;
    return Array.from(dl.querySelectorAll('option')).map(o => o.value);
  }

  it('loads saved settings and shows the personal-key badge + masked placeholder', () => {
    expect(svc.getLLMSettings).toHaveBeenCalled();
    expect(component.settings()?.hasApiKey).toBeTrue();
    expect(component.hasSavedKey).toBeTrue();
    expect(el().textContent).toContain('Personal key configured — groq openai/gpt-oss-20b');
    expect(el().textContent).not.toContain('Using system default');
    const keyInput = el().querySelector('#llm-api-key') as HTMLInputElement;
    expect(keyInput.getAttribute('placeholder')).toBe('••••••••');
  });

  it('prefills the model with the provider default whenever the provider changes', () => {
    component.model = 'something-typed';
    component.onProviderChange('openai');
    expect(component.provider).toBe('openai');
    expect(component.model).toBe('gpt-4o');
    component.onProviderChange('anthropic');
    expect(component.model).toBe('claude-sonnet-4-6');
    component.onProviderChange('gemini');
    expect(component.model).toBe('gemini-2.5-flash');
    component.onProviderChange('ollama');
    expect(component.model).toBe('llama3');
    component.onProviderChange('groq');
    expect(component.model).toBe('openai/gpt-oss-120b');
  });

  it('shows the base URL field only when ollama is selected', () => {
    expect(el().querySelector('#llm-base-url')).toBeNull();
    component.onProviderChange('ollama');
    fixture.detectChanges();
    expect(el().querySelector('#llm-base-url')).not.toBeNull();
    component.onProviderChange('groq');
    fixture.detectChanges();
    expect(el().querySelector('#llm-base-url')).toBeNull();
  });

  it('offers per-provider model suggestions through the datalist', () => {
    expect(component.suggestions.length).toBeGreaterThan(0);
    expect(el().querySelector('#llm-model')?.getAttribute('list')).toBe('llm-model-suggestions');
    expect(modelOptions()).toContain('openai/gpt-oss-120b');
    expect(modelOptions()).toContain('openai/gpt-oss-20b');
    component.onProviderChange('ollama');
    fixture.detectChanges();
    expect(modelOptions()).toContain('llama3');
    component.onProviderChange('groq');
    fixture.detectChanges();
    expect(modelOptions()).not.toContain('gpt-4o');
  });

  it('saves WITHOUT an api_key field when the key input is blank (backend keeps stored key)', () => {
    component.apiKey = '   ';
    component.saveSettings();
    expect(svc.saveLLMSettings).toHaveBeenCalled();
    const payload: LLMSettingsUpdate = svc.saveLLMSettings.calls.mostRecent().args[0];
    expect(payload.provider).toBe('groq');
    expect(payload.model).toBe('openai/gpt-oss-20b');
    expect('apiKey' in payload).toBeFalse();
    expect(component.saveMessage()).toContain('Saved — using personal groq');
    // plaintext field cleared after a successful save
    expect(component.apiKey).toBe('');
  });

  it('includes api_key in the payload only when the user typed one', () => {
    component.apiKey = 'sk-new-key';
    component.saveSettings();
    const payload: LLMSettingsUpdate = svc.saveLLMSettings.calls.mostRecent().args[0];
    expect(payload.apiKey).toBe('sk-new-key');
  });

  it('validates before saving (no provider / empty model)', () => {
    component.provider = '';
    component.saveSettings();
    expect(svc.saveLLMSettings).not.toHaveBeenCalled();
    expect(component.saveError()).toContain('Select a provider');
    component.provider = 'openai';
    component.model = '   ';
    component.saveSettings();
    expect(svc.saveLLMSettings).not.toHaveBeenCalled();
    expect(component.saveError()).toContain('Model must not be empty');
  });

  it('tests the SAVED configuration with no arguments (tampered form is ignored)', () => {
    component.model = 'tampered-form-model';
    component.apiKey = 'tampered-key';
    component.testConnection();
    expect(svc.testLLMSettings).toHaveBeenCalled();
    expect(svc.testLLMSettings.calls.mostRecent().args.length).toBe(0);
    expect(component.testResult()?.ok).toBeTrue();
    expect(component.testResult()?.text).toContain('Connected');
    expect(component.testResult()?.text).toContain('123ms');
  });

  it('surfaces a failed connection test with the backend error text', () => {
    svc.testLLMSettings.and.returnValue(
      of({ success: false, response: null, error: 'Groq API error 401', model: 'x', latencyMs: 10 })
    );
    component.testConnection();
    expect(component.testResult()?.ok).toBeFalse();
    expect(component.testResult()?.text).toContain('Groq API error 401');
  });

  it('reset clears to the system default: banner shows and Reset disables', () => {
    svc.getLLMSettings.and.returnValue(of(defaultConfig));
    component.resetToDefault();
    expect(svc.clearLLMSettings).toHaveBeenCalled();
    expect(component.settings()?.isUsingDefault).toBeTrue();
    fixture.detectChanges();
    expect(el().textContent).toContain('Using system default — Groq');
    const resetBtn = Array.from(el().querySelectorAll('button.btn-danger')).find(b =>
      b.textContent?.includes('Reset to default')
    ) as HTMLButtonElement;
    expect(resetBtn.disabled).toBeTrue();
  });

  it('renders the load-error state with a Retry button when GET fails', () => {
    svc.getLLMSettings.and.returnValue(throwError(() => new Error('boom')));
    const fresh = TestBed.createComponent(SettingsComponent);
    fresh.detectChanges();
    const text = (fresh.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('boom');
    expect(text).toContain('Retry');
  });

  it('hides the org-settings link when the caller manages no org', () => {
    expect(orgSvc.listOrgs).toHaveBeenCalled();
    expect(el().querySelector('[data-testid="org-settings-link"]')).toBeNull();
  });

  it('shows the org-settings link for an ORG_ADMIN membership (effective role)', () => {
    // DEVELOPER claim + ORG_ADMIN membership → effective ORG_ADMIN (plan §2).
    authSignal.set({ role: 'DEVELOPER' });
    orgSvc.listOrgs.and.returnValue(
      of([{ id: 'org-1', name: 'acme', account_type: 'Organization', role: 'ORG_ADMIN' }])
    );
    const fresh = TestBed.createComponent(SettingsComponent);
    fresh.detectChanges();
    const link = (fresh.nativeElement as HTMLElement).querySelector(
      '[data-testid="org-settings-link"]'
    );
    expect(link).not.toBeNull();
    expect(link?.getAttribute('href')).toBe('/settings/org');
  });

  it('stays hidden when listing orgs fails (fail closed)', () => {
    orgSvc.listOrgs.and.returnValue(throwError(() => new Error('nope')));
    const fresh = TestBed.createComponent(SettingsComponent);
    fresh.detectChanges();
    expect(
      (fresh.nativeElement as HTMLElement).querySelector('[data-testid="org-settings-link"]')
    ).toBeNull();
  });
});
