import { Injectable, signal, inject } from '@angular/core';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { Observable, tap, catchError, throwError } from 'rxjs';
import { KeycloakService } from 'keycloak-angular';
import { User } from '../models/user.model';
import { environment } from '@env/environment';

/**
 * Application auth state backed by Keycloak.
 *
 * keycloak-js owns the tokens (PKCE S256, silent refresh, SSO session) — it
 * is initialized by APP_INITIALIZER before any of this runs. This service
 * owns the app-level pieces: the user profile (GET /auth/me), the login /
 * logout / switch-account entry points, and the signals templates bind to.
 */
@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly keycloak = inject(KeycloakService);

  private readonly _currentUser = signal<User | null>(null);
  private readonly _isLoading = signal<boolean>(false);
  private readonly _error = signal<string | null>(null);

  /**
   * Set once logout()/switchAccount() has started tearing the session down.
   * Guarantees idempotency: no duplicate server call, no duplicate redirect —
   * regardless of double-clicks. Reset when a new login starts.
   */
  private sessionClosed = false;

  readonly currentUser = this._currentUser.asReadonly();
  readonly isLoading = this._isLoading.asReadonly();
  readonly error = this._error.asReadonly();

  constructor() {
    // Restore the cached profile synchronously so the first rendered page
    // (e.g. dashboard) has a user immediately, then refresh it below.
    const cached = this.getStoredUser();
    if (cached) {
      this._currentUser.set(cached);
    }

    // APP_INITIALIZER has already completed check-sso init by the time any
    // component/service can inject this class.
    if (this.keycloak.isLoggedIn()) {
      this.loadUser().subscribe({ error: () => undefined });
    } else if (cached) {
      // Cached profile without a Keycloak session is stale — drop it.
      this.clearSession();
    }
  }

  /** True when this browser holds a live Keycloak session. */
  isAuthenticated(): boolean {
    return this.keycloak.isLoggedIn();
  }

  /**
   * Start the GitHub social login. `idpHint: 'github'` skips the Keycloak
   * login form and forwards straight to the GitHub broker — every login goes
   * through GitHub. `returnUrl` (from the guard) is honored; anything else
   * lands on the dashboard.
   */
  login(returnUrl?: string): void {
    this._error.set(null);
    this.sessionClosed = false;
    const target =
      returnUrl && returnUrl.startsWith('/') && !returnUrl.startsWith('//')
        ? returnUrl
        : '/dashboard';
    this.keycloak
      .login({
        idpHint: 'github',
        redirectUri: `${window.location.origin}${target}`
      })
      .catch((err: unknown) => {
        console.error('Failed to start Keycloak login:', err);
        this._error.set('Failed to start GitHub login. Please try again.');
      });
  }

  /**
   * Switch account: end the current Keycloak SSO session (server-side session
   * invalidated, local profile dropped) and land on the login page so the
   * next login() starts from a clean slate.
   */
  switchAccount(): void {
    if (this.sessionClosed) {
      return;
    }
    this.sessionClosed = true;
    this.clearSession();
    this.keycloak.logout(`${window.location.origin}/login`).catch(() => {
      this.router.navigate(['/login']);
    });
  }

  /**
   * Best-effort server-side logout: POSTs /auth/logout while the Keycloak
   * token is still attached (backend revokes stored GitHub tokens and sets a
   * revocation cutoff), then ALWAYS tears down local state and redirects
   * through Keycloak's end-session endpoint. Idempotent.
   */
  logout(): void {
    if (this.sessionClosed) {
      return;
    }
    this.sessionClosed = true;

    const wasLoggedIn = this.keycloak.isLoggedIn();
    if (wasLoggedIn) {
      // Fire-and-forget: must start BEFORE the end-session redirect below.
      // Errors are swallowed — teardown happens either way.
      this.http.post(`${environment.apiUrl}/auth/logout`, {}).subscribe({ error: () => undefined });
    }

    this.clearSession();
    if (wasLoggedIn) {
      this.keycloak.logout(`${window.location.origin}/`).catch(() => {
        this.router.navigate(['/login']);
      });
    } else {
      this.router.navigate(['/login']);
    }
  }

  /**
   * GET /auth/me — (re)loads the profile. The role in the response always
   * reflects the current JWT: the backend derives it from the token on every
   * request, never from the database.
   */
  loadUser(): Observable<User> {
    this._isLoading.set(true);
    this._error.set(null);

    return this.http.get<User>(`${environment.apiUrl}/auth/me`).pipe(
      tap(user => {
        this._currentUser.set(user);
        this.setUser(user);
        this._isLoading.set(false);
      }),
      catchError(error => {
        this._isLoading.set(false);
        // FastAPI errors carry `detail`; keep `message` for plain Error bodies.
        const detail =
          typeof error.error?.detail === 'string' ? error.error.detail : error.error?.message;
        this._error.set(detail || 'Failed to load user profile');
        return throwError(() => error);
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

  private getStoredUser(): User | null {
    try {
      const userData = localStorage.getItem(environment.userKey);
      return userData ? (JSON.parse(userData) as User) : null;
    } catch {
      return null;
    }
  }

  private setUser(user: User): void {
    localStorage.setItem(environment.userKey, JSON.stringify(user));
  }

  /** Clears local profile state (cache + signal). No navigation. */
  private clearSession(): void {
    localStorage.removeItem(environment.userKey);
    this._currentUser.set(null);
  }
}
