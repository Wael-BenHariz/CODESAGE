import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError, catchError } from 'rxjs';
import { environment } from '@env/environment';

/**
 * Error thrown by every ApiService call. Extends `Error` (existing
 * consumers only read `.message`, which is unchanged), but keeps the HTTP
 * status and FastAPI's raw `detail` payload so callers that need
 * field-level validation (422 `detail: [{loc, msg}]` arrays, org/settings
 * ceiling strings) can render errors inline.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Raw FastAPI `detail` — string | {loc,msg}[] | undefined. */
    readonly detail: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.apiUrl;

  get<T>(endpoint: string, params?: Record<string, string | number>): Observable<T> {
    let httpParams = new HttpParams();
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        httpParams = httpParams.set(key, String(value));
      });
    }
    return this.http
      .get<T>(`${this.baseUrl}${endpoint}`, { params: httpParams })
      .pipe(catchError(this.handleError));
  }

  post<T>(endpoint: string, body: unknown): Observable<T> {
    return this.http.post<T>(`${this.baseUrl}${endpoint}`, body).pipe(catchError(this.handleError));
  }

  put<T>(endpoint: string, body: unknown): Observable<T> {
    return this.http.put<T>(`${this.baseUrl}${endpoint}`, body).pipe(catchError(this.handleError));
  }

  patch<T>(endpoint: string, body: unknown): Observable<T> {
    return this.http
      .patch<T>(`${this.baseUrl}${endpoint}`, body)
      .pipe(catchError(this.handleError));
  }

  delete<T>(endpoint: string): Observable<T> {
    return this.http.delete<T>(`${this.baseUrl}${endpoint}`).pipe(catchError(this.handleError));
  }

  private handleError(error: HttpErrorResponse): Observable<never> {
    let message = 'An unknown error occurred';

    if (error.error instanceof ErrorEvent) {
      message = error.error.message;
    } else if (typeof error.error?.detail === 'string') {
      // FastAPI HTTPException: { detail: "..." } — surface the real reason.
      message = error.error.detail;
    } else if (Array.isArray(error.error?.detail)) {
      // FastAPI validation error: detail is [{ loc, msg }] — message stays
      // generic; ApiError.detail carries the per-field payload.
      const first = error.error.detail[0]?.msg;
      message = first ? String(first) : `Error ${error.status}: ${error.statusText}`;
    } else {
      message = error.error?.message || `Error ${error.status}: ${error.statusText}`;
    }

    const detail = error.error && typeof error.error === 'object' ? error.error.detail : undefined;
    return throwError(() => new ApiError(message, error.status, detail));
  }
}
