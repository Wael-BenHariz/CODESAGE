import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { LLMSettings, LLMTestResponse, LlmSettingsService } from './llm-settings.service';

describe('LlmSettingsService — /settings/llm group (plan Step 8)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: LlmSettingsService;

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get', 'put', 'delete', 'post']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(LlmSettingsService);
  });

  it('maps GET /settings/llm to camelCase — flag only, never a key', () => {
    api.get.and.returnValue(
      of({
        provider: 'groq',
        model: 'openai/gpt-oss-120b',
        base_url: null,
        has_api_key: true,
        is_using_default: false
      })
    );

    let settings: LLMSettings | undefined;
    service.getLLMSettings().subscribe(s => (settings = s));

    expect(api.get).toHaveBeenCalledWith('/settings/llm');
    expect(settings).toEqual({
      provider: 'groq',
      model: 'openai/gpt-oss-120b',
      baseUrl: null,
      hasApiKey: true, // the only key-related field that exists
      isUsingDefault: false
    }); // toEqual pins the exact shape — an api_key field would fail it
  });

  it('sends api_key in the PUT payload only when a key was typed', () => {
    api.put.and.returnValue(of({ saved: true }));

    service
      .saveLLMSettings({ provider: 'openai', model: 'gpt-4o', apiKey: 'sk-secret' })
      .subscribe();
    expect(api.put).toHaveBeenCalledWith('/settings/llm', {
      provider: 'openai',
      model: 'gpt-4o',
      base_url: null,
      api_key: 'sk-secret'
    });

    // Absent key → field omitted entirely (blank = keep the stored one).
    service.saveLLMSettings({ provider: 'openai', model: 'gpt-4o' }).subscribe();
    expect(api.put).toHaveBeenCalledWith('/settings/llm', {
      provider: 'openai',
      model: 'gpt-4o',
      base_url: null
    });

    // Blank string is falsy too — never wipes the stored key.
    service.saveLLMSettings({ provider: 'openai', model: 'gpt-4o', apiKey: '' }).subscribe();
    expect(api.put).toHaveBeenCalledWith('/settings/llm', {
      provider: 'openai',
      model: 'gpt-4o',
      base_url: null
    });
  });

  it('passes baseUrl through as base_url when provided', () => {
    api.put.and.returnValue(of({ saved: true }));

    service
      .saveLLMSettings({ provider: 'ollama', model: 'llama3', baseUrl: 'http://localhost:11434' })
      .subscribe();

    expect(api.put).toHaveBeenCalledWith('/settings/llm', {
      provider: 'ollama',
      model: 'llama3',
      base_url: 'http://localhost:11434'
    });
  });

  it('clears the settings via DELETE /settings/llm', () => {
    api.delete.and.returnValue(of({ cleared: true }));

    let cleared = false;
    service.clearLLMSettings().subscribe(r => (cleared = r.cleared));

    expect(api.delete).toHaveBeenCalledWith('/settings/llm');
    expect(cleared).toBeTrue();
  });

  it('tests the saved config via POST and maps latency_ms', () => {
    api.post.and.returnValue(
      of({ success: true, response: 'pong', error: null, model: 'm1', latency_ms: 123 })
    );

    let out: LLMTestResponse | undefined;
    service.testLLMSettings().subscribe(r => (out = r));

    expect(api.post).toHaveBeenCalledWith('/settings/llm/test', {});
    expect(out).toEqual({
      success: true,
      response: 'pong',
      error: null,
      model: 'm1',
      latencyMs: 123
    });
  });
});
