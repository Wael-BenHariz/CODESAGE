/**
 * STATIC MOCK DATA — Platform Administration console (PFE prototype).
 *
 * Initial values for the Paramètres screens. Saving a section only commits
 * the form state to the component's local signals and shows a toast — no
 * setting here is ever persisted, and no LLM provider is contacted.
 */

export interface MockGeneralSettings {
  platformName: string;
  appUrl: string;
  maintenanceMode: boolean;
  defaultLanguage: string;
}

export interface MockAiSettings {
  provider: string;
  model: string;
  maxConcurrentRequests: number;
  reviewTimeoutSeconds: number;
}

export interface MockSecuritySettings {
  sessionDurationMinutes: number;
  maxLoginAttempts: number;
  invitationExpiryDays: number;
  enforcedAuth: boolean;
}

export const MOCK_GENERAL_SETTINGS: MockGeneralSettings = {
  platformName: 'CODESAGE',
  appUrl: 'https://codesage.example.com',
  maintenanceMode: false,
  defaultLanguage: 'Français'
};

export const MOCK_AI_SETTINGS: MockAiSettings = {
  provider: 'Gemini',
  model: 'Gemini 2.5 Pro',
  maxConcurrentRequests: 10,
  reviewTimeoutSeconds: 300
};

export const MOCK_SECURITY_SETTINGS: MockSecuritySettings = {
  sessionDurationMinutes: 60,
  maxLoginAttempts: 5,
  invitationExpiryDays: 7,
  enforcedAuth: true
};

export const MOCK_LANGUAGE_OPTIONS: readonly string[] = ['Français', 'English', 'Deutsch'];

export const MOCK_AI_PROVIDER_OPTIONS: readonly string[] = [
  'Gemini',
  'Groq',
  'OpenAI',
  'Anthropic',
  'Ollama'
];

export const MOCK_AI_MODEL_OPTIONS: readonly string[] = [
  'Gemini 2.5 Pro',
  'Gemini 2.0 Flash',
  'openai/gpt-oss-120b',
  'llama-3.3-70b-versatile'
];

export function cloneGeneralSettings(): MockGeneralSettings {
  return { ...MOCK_GENERAL_SETTINGS };
}

export function cloneAiSettings(): MockAiSettings {
  return { ...MOCK_AI_SETTINGS };
}

export function cloneSecuritySettings(): MockSecuritySettings {
  return { ...MOCK_SECURITY_SETTINGS };
}
