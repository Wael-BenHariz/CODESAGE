import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import {
  LLMSettings,
  LLMSettingsUpdate,
  LlmSettingsService
} from '../../core/services/llm-settings.service';
import { OrgSettingsService, canManageSettings } from '../../core/services/org-settings.service';
import { SiteHeaderComponent } from '../../shared/components/site-header/site-header.component';

type LLMProvider = 'groq' | 'openai' | 'anthropic' | 'gemini' | 'ollama';

/** Prefill model per provider when the user picks one (STEP 10). */
const DEFAULT_MODEL: Record<LLMProvider, string> = {
  groq: 'openai/gpt-oss-120b',
  openai: 'gpt-4o',
  anthropic: 'claude-sonnet-4-6',
  gemini: 'gemini-2.5-flash',
  ollama: 'llama3'
};

/** STEP 11: datalist suggestions shown while typing the model name. */
const MODEL_SUGGESTIONS: Record<LLMProvider, string[]> = {
  groq: ['openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'qwen/qwen3.8-27b', 'allam-2-7b'],
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'o3-mini'],
  anthropic: ['claude-opus-4-5', 'claude-sonnet-4-6', 'claude-haiku-4-5'],
  gemini: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash'],
  ollama: ['llama3', 'mistral', 'codellama', 'qwen2.5-coder']
};

const PROVIDERS: { value: LLMProvider; label: string }[] = [
  { value: 'groq', label: 'Groq' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'gemini', label: 'Google Gemini' },
  { value: 'ollama', label: 'Ollama (local)' }
];

interface StatusMessage {
  ok: boolean;
  text: string;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [SiteHeaderComponent, CommonModule, FormsModule, RouterModule],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss'
})
export class SettingsComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly llm = inject(LlmSettingsService);
  private readonly orgSettings = inject(OrgSettingsService);

  user = this.auth.currentUser;

  /** Show the org-settings link when the caller can edit at least one org
   *  (effective role ≥ ORG_ADMIN — plan §2; the route guard re-checks). */
  canManageOrgSettings = signal(false);

  readonly providers = PROVIDERS;

  // LLM form fields (plain fields keep ngModel ergonomics simple).
  provider = '';
  model = '';
  apiKey = '';
  baseUrl = '';

  // LLM async state.
  settings = signal<LLMSettings | null>(null);
  loading = signal(true);
  loadError = signal<string | null>(null);
  isSaving = signal(false);
  saveMessage = signal<string | null>(null);
  saveError = signal<string | null>(null);
  testing = signal(false);
  testResult = signal<StatusMessage | null>(null);
  reverting = signal(false);

  ngOnInit(): void {
    this.loadSettings();
    this.checkOrgAdminAccess();
  }

  /** Fail-closed: no org list (or no qualifying membership) = no link. */
  private checkOrgAdminAccess(): void {
    const role = this.auth.currentUser()?.role ?? null;
    if (role === 'PLATFORM_ADMIN') {
      this.canManageOrgSettings.set(true);
      return;
    }
    this.orgSettings.listOrgs().subscribe({
      next: orgs => this.canManageOrgSettings.set(orgs.some(o => canManageSettings(role, o.role))),
      error: () => this.canManageOrgSettings.set(false)
    });
  }

  get hasSavedKey(): boolean {
    return this.settings()?.hasApiKey ?? false;
  }

  get isOllama(): boolean {
    return this.provider === 'ollama';
  }

  get suggestions(): string[] {
    return this.provider ? MODEL_SUGGESTIONS[this.provider as LLMProvider] : [];
  }

  loadSettings(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.llm.getLLMSettings().subscribe({
      next: settings => {
        this.settings.set(settings);
        this.provider = settings.provider ?? '';
        this.model = settings.model ?? '';
        this.baseUrl = settings.baseUrl ?? '';
        this.apiKey = ''; // the key never comes back from the server
        this.loading.set(false);
      },
      error: err => {
        this.loadError.set(errorMessage(err, 'Could not load AI settings.'));
        this.loading.set(false);
      }
    });
  }

  onProviderChange(value: string): void {
    this.provider = value;
    // Prefill with the default model for the chosen provider.
    this.model = value ? DEFAULT_MODEL[value as LLMProvider] : '';
    this.testResult.set(null);
    this.saveMessage.set(null);
    this.saveError.set(null);
  }

  saveSettings(): void {
    this.saveMessage.set(null);
    this.saveError.set(null);
    this.testResult.set(null);

    if (!this.provider) {
      this.saveError.set('Select a provider first.');
      return;
    }
    if (!this.model.trim()) {
      this.saveError.set('Model must not be empty.');
      return;
    }

    const update: LLMSettingsUpdate = {
      provider: this.provider,
      model: this.model.trim()
    };
    // Blank key = keep the stored one — omitted from the payload entirely.
    const key = this.apiKey.trim();
    if (key) {
      update.apiKey = key;
    }
    if (this.isOllama) {
      const url = this.baseUrl.trim();
      if (url) {
        update.baseUrl = url;
      }
    }

    this.isSaving.set(true);
    this.llm.saveLLMSettings(update).subscribe({
      next: () => {
        this.isSaving.set(false);
        this.saveMessage.set(`Saved — using personal ${this.provider} ${update.model}`);
        this.apiKey = ''; // never keep plaintext around after a save
        this.loadSettings(); // refresh flags (hasApiKey / isUsingDefault)
      },
      error: err => {
        this.isSaving.set(false);
        this.saveError.set(errorMessage(err, 'Could not save settings.'));
      }
    });
  }

  testConnection(): void {
    this.saveMessage.set(null);
    this.saveError.set(null);
    this.testResult.set(null);
    this.testing.set(true);
    // No arguments on purpose: the server tests the SAVED configuration
    // (key decrypted server-side, never re-sent from the browser).
    this.llm.testLLMSettings().subscribe({
      next: result => {
        this.testing.set(false);
        this.testResult.set(
          result.success
            ? {
                ok: true,
                text: `Connected — "${result.response}" in ${result.latencyMs}ms`
              }
            : { ok: false, text: result.error || 'Connection failed.' }
        );
      },
      error: err => {
        this.testing.set(false);
        this.testResult.set({
          ok: false,
          text: errorMessage(err, 'Connection test failed.')
        });
      }
    });
  }

  resetToDefault(): void {
    this.saveMessage.set(null);
    this.saveError.set(null);
    this.testResult.set(null);
    this.reverting.set(true);
    this.llm.clearLLMSettings().subscribe({
      next: () => {
        this.reverting.set(false);
        this.loadSettings();
        this.saveMessage.set('Reverted to the system default (Groq).');
      },
      error: err => {
        this.reverting.set(false);
        this.saveError.set(errorMessage(err, 'Could not reset settings.'));
      }
    });
  }

  logout(): void {
    this.auth.logout();
  }
}
