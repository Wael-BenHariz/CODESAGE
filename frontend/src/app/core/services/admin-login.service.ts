import { Injectable, inject } from '@angular/core';
import { KeycloakService } from 'keycloak-angular';
import { firstValueFrom } from 'rxjs';

import { ApiService } from './api.service';
import { AuthContextService } from './auth-context.service';
import { AuthService } from './auth.service';
import { deriveRole } from '../guards/role.guard';

/** Shape of `GET /auth/keycloak/config` (backend `app/api/routes/auth.py`). */
interface KeycloakAppConfig {
  url: string;
  realm: string;
  clientId: string;
}

/** Subset of Keycloak's token response this flow needs. */
interface PasswordGrantResponse {
  access_token: string;
  refresh_token: string;
  /** Optional: the password grant does not issue one (keycloak-js copes). */
  id_token?: string;
}

/** Keycloak `error` codes we translate into honest, static copy. */
type TokenErrorCode = 'invalid_grant' | 'unauthorized_client' | 'invalid_client';

/**
 * Sign-in failure with user-facing copy. The message is always a literal we
 * wrote — Keycloak payloads are never interpolated into the UI.
 */
export class AdminLoginError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AdminLoginError';
  }
}

/**
 * Dedicated platform-admin credential sign-in for `/admin`
 * (`features/admin/admin-login`), for operator/testing use where the app's
 * only other entry point (GitHub broker) cannot reach a realm-native account.
 *
 * Flow:
 * 1. `GET /auth/keycloak/config` — where Keycloak lives + which client to use;
 * 2. **Resource Owner Password** grant against Keycloak's token endpoint.
 *    Requires `directAccessGrantsEnabled` on `codesage-angular`
 *    (`infrastructure/k8s/base/keycloak/keycloak-configmap.yaml` — the live
 *    realm was updated with the same flag). The request deliberately uses
 *    `fetch`, not `HttpClient`: it must stay out of the app's interceptors,
 *    whose 401 recovery (refresh → retry → logout) exists for our own API and
 *    would tear the session down on a mistyped password;
 * 3. the token's realm roles are checked **with the same `deriveRole` the
 *    `/platform` route guard uses**, so this page and the guard can never
 *    disagree about who gets in — fail closed;
 * 4. keycloak-js is re-initialized with the returned tokens, then
 *    `GET /auth/me` runs (JIT-provisions the `users` row and caches the
 *    profile the guard reads). Any later API call refreshes normally through
 *    `updateToken` and re-authorizes server-side.
 *
 * The backend is untouched: the password goes browser → Keycloak only, and
 * `GET /users`, `GET /orgs`, `GET/PUT /platform/settings` keep their
 * `require_super_admin` / `PLATFORM_ADMIN` guards.
 */
@Injectable({ providedIn: 'root' })
export class AdminLoginService {
  private readonly api = inject(ApiService);
  private readonly keycloak = inject(KeycloakService);
  private readonly auth = inject(AuthService);
  private readonly context = inject(AuthContextService);

  /**
   * Sign in with a username and password, or reject with
   * {@link AdminLoginError}. Resolves only once the session, the profile and
   * the org context are all ready for `/platform`.
   */
  async login(username: string, password: string): Promise<void> {
    const config = await firstValueFrom(this.api.get<KeycloakAppConfig>('/auth/keycloak/config'));
    const tokens = await this.requestTokens(config, username, password);
    this.assertPlatformAdmin(tokens.access_token);

    const authenticated = await this.keycloak.init({
      config: { url: config.url, realm: config.realm, clientId: config.clientId },
      initOptions: {
        token: tokens.access_token,
        refreshToken: tokens.refresh_token,
        idToken: tokens.id_token,
        // No browser SSO cookie backs a password-grant session, so the
        // login-status iframe has nothing to report. Skipping it makes
        // init() take the updateToken(-1) path instead: one forced refresh
        // that proves the refresh token before the first API call.
        checkLoginIframe: false
      },
      bearerExcludedUrls: ['/auth/keycloak/config']
    });
    if (!authenticated) {
      throw new AdminLoginError('Sign-in did not establish a session. Try again.');
    }

    try {
      await firstValueFrom(this.auth.loadUser());
    } catch (err) {
      // A session the API cannot resolve is not a session — leave no token
      // behind for the next screen to trip over.
      this.keycloak.clearToken();
      throw err;
    }

    // The previous account's org list/selection must not leak into this one.
    this.context.resetOrgs();
  }

  /** Browser-facing token endpoint for the configured realm/client. */
  private requestTokens(
    config: KeycloakAppConfig,
    username: string,
    password: string
  ): Promise<PasswordGrantResponse> {
    const tokenUrl = `${config.url}/realms/${encodeURIComponent(
      config.realm
    )}/protocol/openid-connect/token`;
    const body = new URLSearchParams({
      grant_type: 'password',
      client_id: config.clientId,
      username,
      password
    });

    return fetch(tokenUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString()
    }).then(
      async response => {
        if (!response.ok) {
          throw new AdminLoginError(await this.errorMessage(response));
        }
        return (await response.json()) as PasswordGrantResponse;
      },
      () => {
        // Network/parse failure — never surface transport internals.
        throw new AdminLoginError('Could not reach the sign-in service. Try again.');
      }
    );
  }

  /** Map a rejected token grant to copy an operator can act on. */
  private async errorMessage(response: Response): Promise<string> {
    let code: TokenErrorCode | undefined;
    let description = '';
    try {
      const payload = (await response.json()) as { error?: string; error_description?: string };
      code = payload.error as TokenErrorCode | undefined;
      description = (payload.error_description ?? '').toLowerCase();
    } catch {
      // Non-JSON error body — fall through to the generic message.
    }

    switch (code) {
      case 'invalid_grant':
        if (description.includes('disabled')) {
          return 'This account is disabled.';
        }
        if (description.includes('locked')) {
          return 'Too many failed attempts — this account is temporarily locked. Wait a moment and try again.';
        }
        return 'Incorrect username or password.';
      case 'unauthorized_client':
        return 'Password sign-in is disabled for this application.';
      case 'invalid_client':
        return 'The sign-in service rejected this application. Contact an operator.';
      default:
        return 'Sign-in failed. Try again.';
    }
  }

  /**
   * Fail closed when the account holds no platform-admin role. Uses the same
   * derivation as `RoleGuard` (compat map included) so a legacy `SUPER_ADMIN`
   * claim is treated identically on both sides.
   */
  private assertPlatformAdmin(accessToken: string): void {
    const roles = decodeRealmRoles(accessToken);
    if (deriveRole(roles) !== 'PLATFORM_ADMIN') {
      throw new AdminLoginError(
        'This account has no platform-admin role. Ask an administrator to grant it before signing in here.'
      );
    }
  }
}

/** Realm roles from a JWT payload — no token is trusted beyond its claims. */
function decodeRealmRoles(accessToken: string): string[] {
  const segment = accessToken.split('.')[1] ?? '';
  if (!segment) {
    throw new AdminLoginError('The sign-in service returned an unreadable token.');
  }

  const base64 =
    segment.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (segment.length % 4)) % 4);

  let payload: unknown;
  try {
    const bytes = Uint8Array.from(atob(base64), char => char.charCodeAt(0));
    payload = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new AdminLoginError('The sign-in service returned an unreadable token.');
  }

  const roles = (payload as { realm_access?: { roles?: unknown } }).realm_access?.roles;
  return Array.isArray(roles)
    ? roles.filter((role): role is string => typeof role === 'string')
    : [];
}
