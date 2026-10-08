import { CommonModule } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AdminLoginError, AdminLoginService } from '../../../core/services/admin-login.service';

/**
 * Dedicated platform-admin sign-in — route `/admin` (public, `shell: false`).
 *
 * The app's `/login` screen only offers GitHub (`AuthService.login` hard-codes
 * `idpHint: 'github'`), which cannot reach a realm-native account; Keycloak's
 * own login form works but is not part of our UI. This screen takes a
 * username + password, delegates everything to {@link AdminLoginService} and
 * lands on the admin interface (`/platform`), which stays guarded by
 * `PLATFORM_ROLES` and re-authorized by the backend on every request.
 *
 * States: idle → pending (submit disabled, no double submit) → success
 * (navigate) or inline error (`role="alert"`), never a silent failure.
 */
@Component({
  selector: 'app-admin-login',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './admin-login.component.html',
  styleUrl: './admin-login.component.scss'
})
export class AdminLoginComponent {
  private readonly router = inject(Router);
  private readonly adminLogin = inject(AdminLoginService);

  readonly form = new FormGroup({
    username: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required]
    }),
    password: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required]
    })
  });

  /** Submit lock — mirrors the project rule: mutations disable while pending. */
  readonly pending = signal(false);
  readonly error = signal<string | null>(null);

  async submit(): Promise<void> {
    if (this.pending()) {
      return;
    }
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { username, password } = this.form.getRawValue();
    this.pending.set(true);
    this.error.set(null);

    try {
      await this.adminLogin.login(username.trim(), password);
      await this.router.navigate(['/platform']);
    } catch (err) {
      // AdminLoginError carries copy we wrote; anything else stays generic —
      // never render a server payload verbatim.
      this.error.set(err instanceof AdminLoginError ? err.message : 'Sign-in failed. Try again.');
    } finally {
      this.pending.set(false);
    }
  }
}
