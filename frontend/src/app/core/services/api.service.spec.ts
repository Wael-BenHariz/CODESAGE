import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { ApiError, ApiService } from './api.service';
import { environment } from '@env/environment';

describe('ApiService — HTTP plumbing (plan Step 1)', () => {
  let http: HttpTestingController;
  let service: ApiService;
  const base = environment.apiUrl;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()]
    });
    http = TestBed.inject(HttpTestingController);
    service = TestBed.inject(ApiService);
  });

  afterEach(() => http.verify()); // every request matched + flushed

  it('GET prefixes the API base URL and stringifies params', () => {
    let body: unknown;
    service
      .get<{ items: string[] }>('/reviews', { page: 1, status_filter: 'pending' })
      .subscribe(v => (body = v));

    const req = http.expectOne(`${base}/reviews?page=1&status_filter=pending`);
    expect(req.request.method).toBe('GET');
    req.flush({ items: ['a'] });
    expect(body).toEqual({ items: ['a'] });
  });

  it('GET without params sends no query string', () => {
    service.get('/settings/llm').subscribe();

    const req = http.expectOne(`${base}/settings/llm`);
    expect(req.request.params.keys().length).toBe(0);
    req.flush({});
  });

  it('POST/PUT/PATCH/DELETE use the matching verb with the body', () => {
    service.post('/a', { x: 1 }).subscribe();
    const post = http.expectOne(`${base}/a`);
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual({ x: 1 });
    post.flush({});

    service.put('/b', { y: 2 }).subscribe();
    expect(http.expectOne(`${base}/b`).request.method).toBe('PUT');

    service.patch('/c', { z: 3 }).subscribe();
    expect(http.expectOne(`${base}/c`).request.method).toBe('PATCH');

    service.delete('/d').subscribe();
    expect(http.expectOne(`${base}/d`).request.method).toBe('DELETE');
  });

  it('surfaces a FastAPI string detail as the ApiError message', () => {
    let err: ApiError | undefined;
    service.get('/reviews/x').subscribe({ error: e => (err = e) });

    http
      .expectOne(`${base}/reviews/x`)
      .flush({ detail: 'Review not found' }, { status: 404, statusText: 'Not Found' });

    expect(err).toBeInstanceOf(ApiError);
    expect(err?.message).toBe('Review not found');
    expect(err?.status).toBe(404);
    expect(err?.detail).toBe('Review not found');
  });

  it('keeps a 422 detail array on the error and takes the first msg', () => {
    const detail = [{ loc: ['body', 'provider'], msg: 'Value is not a valid provider' }];
    let err: ApiError | undefined;
    service.put('/settings/llm', {}).subscribe({ error: e => (err = e) });

    http
      .expectOne(`${base}/settings/llm`)
      .flush({ detail }, { status: 422, statusText: 'Unprocessable Entity' });

    expect(err?.message).toBe('Value is not a valid provider'); // inline-field ready
    expect(err?.detail).toEqual(detail); // the raw per-field payload
    expect(err?.status).toBe(422);
  });

  it('falls back to a status message when the body carries no detail', () => {
    let err: ApiError | undefined;
    service.delete('/x').subscribe({ error: e => (err = e) });

    http.expectOne(`${base}/x`).flush('boom', { status: 500, statusText: 'Server Error' });

    expect(err?.message).toBe('Error 500: Server Error');
    expect(err?.detail).toBeUndefined();
  });

  it('uses the client-side ErrorEvent message for network failures', () => {
    let err: ApiError | undefined;
    service.delete('/settings/llm').subscribe({ error: e => (err = e) });

    http
      .expectOne(`${base}/settings/llm`)
      .error(new ErrorEvent('Network error', { message: 'Network unreachable' }));

    expect(err).toBeInstanceOf(ApiError);
    expect(err?.message).toBe('Network unreachable');
  });
});
