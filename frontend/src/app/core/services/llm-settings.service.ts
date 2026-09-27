import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';
import { ApiService } from './api.service';

/** Current LLM settings (the API key itself never crosses the wire). */
export interface LLMSettings {
  provider: string | null;
  model: string | null;
  baseUrl: string | null;
  hasApiKey: boolean;
  isUsingDefault: boolean;
}

/** Save payload — omit `apiKey` (or send it blank) to keep the stored key. */
export interface LLMSettingsUpdate {
  provider: string;
  model: string;
  apiKey?: string;
  baseUrl?: string;
}

export interface LLMTestResponse {
  success: boolean;
  response: string | null;
  error: string | null;
  model: string;
  latencyMs: number;
}

interface LLMSettingsResponseDto {
  provider: string | null;
  model: string | null;
  base_url: string | null;
  has_api_key: boolean;
  is_using_default: boolean;
}

interface LLMTestResponseDto {
  success: boolean;
  response: string | null;
  error: string | null;
  model: string;
  latency_ms: number;
}

@Injectable({ providedIn: 'root' })
export class LlmSettingsService {
  private readonly api = inject(ApiService);

  getLLMSettings(): Observable<LLMSettings> {
    return this.api.get<LLMSettingsResponseDto>('/settings/llm').pipe(
      map(dto => ({
        provider: dto.provider,
        model: dto.model,
        baseUrl: dto.base_url,
        hasApiKey: dto.has_api_key,
        isUsingDefault: dto.is_using_default
      }))
    );
  }

  saveLLMSettings(update: LLMSettingsUpdate): Observable<{ saved: boolean }> {
    const payload: { provider: string; model: string; base_url: string | null; api_key?: string } =
      {
        provider: update.provider,
        model: update.model,
        base_url: update.baseUrl ?? null
      };
    // Blank key = keep the stored one, so the field is left out entirely.
    if (update.apiKey) {
      payload.api_key = update.apiKey;
    }
    return this.api.put<{ saved: boolean }>('/settings/llm', payload);
  }

  clearLLMSettings(): Observable<{ cleared: boolean }> {
    return this.api.delete<{ cleared: boolean }>('/settings/llm');
  }

  testLLMSettings(): Observable<LLMTestResponse> {
    return this.api.post<LLMTestResponseDto>('/settings/llm/test', {}).pipe(
      map(dto => ({
        success: dto.success,
        response: dto.response,
        error: dto.error,
        model: dto.model,
        latencyMs: dto.latency_ms
      }))
    );
  }
}
