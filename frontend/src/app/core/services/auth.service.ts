import { Injectable, signal, computed, inject } from '@angular/core';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { Observable, tap, catchError, of, map } from 'rxjs';
import { User, AuthResponse } from '../models/user.model';
import { environment } from '@env/environment';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  private readonly _currentUser = signal<User | null>(null);
  private readonly _isLoading = signal<boolean>(false);
  private readonly _error = signal<string | null>(null);

  readonly currentUser = this._currentUser.asReadonly();
  readonly isLoading = this._isLoading.asReadonly();
  readonly error = this._error.asReadonly();
  readonly isAuthenticated = computed(() => this._currentUser() !== null);

  constructor() {
    this.initializeAuth();
  }

  private initializeAuth(): void {
    const token = this.getToken();
    const userData = this.getStoredUser();

    if (token && userData) {
      this._currentUser.set(userData);
      this.validateToken(token).subscribe({
        error: () => {
          this.logout();
        }
      });
    }
  }

  login(): void {
    // Fetch fresh OAuth URL from backend each time (never cached)
    this.http.get<{ authorization_url: string }>(`${environment.apiUrl}/auth/github`).subscribe({
      next: response => {
        window.location.href = response.authorization_url;
      },
      error: error => {
        console.error('Failed to initiate GitHub OAuth:', error);
        this._error.set('Failed to start GitHub login. Please try again.');
      }
    });
  }

  switchAccount(): void {
    // Clear all auth data and re-login
    this.removeToken();
    this.removeUser();
    localStorage.removeItem('codesage_refresh_token');
    this._currentUser.set(null);
    this.login();
  }

  completeLogin(token: string, refreshToken: string): Observable<User> {
    this._isLoading.set(true);
    this._error.set(null);

    // Store tokens immediately
    this.setToken(token);
    if (refreshToken) {
      localStorage.setItem('codesage_refresh_token', refreshToken);
    }

    // Fetch user info from backend
    return this.http.get<User>(`${environment.apiUrl}/auth/me`).pipe(
      tap(user => {
        this.setUser(user);
        this._currentUser.set(user);
        this._isLoading.set(false);
      }),
      catchError(error => {
        this._isLoading.set(false);
        this._error.set(error.error?.message || 'Failed to load user profile');
        throw error;
      })
    );
  }

  handleCallback(code: string): Observable<User> {
    this._isLoading.set(true);
    this._error.set(null);

    return this.http
      .post<AuthResponse>(`${environment.apiUrl}/auth/github/callback`, { code })
      .pipe(
        map(response => response.user),
        tap(user => {
          this.setUser(user);
          this._currentUser.set(user);
          this._isLoading.set(false);
          this.router.navigate(['/dashboard']);
        }),
        catchError(error => {
          this._isLoading.set(false);
          this._error.set(error.error?.message || 'Authentication failed');
          throw error;
        })
      );
  }

  logout(): void {
    this.removeToken();
    this.removeUser();
    this._currentUser.set(null);
    this.router.navigate(['/login']);
  }

  refreshToken(): Observable<AuthResponse> {
    return this.http.post<AuthResponse>(`${environment.apiUrl}/auth/refresh`, {}).pipe(
      tap(response => {
        this.setToken(response.accessToken);
        this.setUser(response.user);
        this._currentUser.set(response.user);
      }),
      catchError(error => {
        this.logout();
        throw error;
      })
    );
  }

  updateProfile(updates: Partial<User>): Observable<User> {
    return this.http.patch<User>(`${environment.apiUrl}/users/me`, updates).pipe(
      tap(user => {
        this._currentUser.set(user);
        this.setUser(user);
      })
    );
  }

  private validateToken(_token: string): Observable<User> {
    return this.http.get<User>(`${environment.apiUrl}/auth/me`).pipe(
      tap(user => {
        this._currentUser.set(user);
        this.setUser(user);
      }),
      catchError(() => {
        this.logout();
        return of(null as unknown as User);
      })
    );
  }

  getToken(): string | null {
    return localStorage.getItem(environment.tokenKey);
  }

  private setToken(token: string): void {
    localStorage.setItem(environment.tokenKey, token);
  }

  private removeToken(): void {
    localStorage.removeItem(environment.tokenKey);
  }

  private getStoredUser(): User | null {
    const userData = localStorage.getItem(environment.userKey);
    return userData ? JSON.parse(userData) : null;
  }

  private setUser(user: User): void {
    localStorage.setItem(environment.userKey, JSON.stringify(user));
  }

  private removeUser(): void {
    localStorage.removeItem(environment.userKey);
  }
}
