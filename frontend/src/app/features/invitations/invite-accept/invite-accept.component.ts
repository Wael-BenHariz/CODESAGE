import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { ApiError } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { InvitationService } from '../../../core/services/invitation.service';
import {
  InvitationAcceptResult,
  InvitationPreview,
  maskEmail
} from '../../../core/models/invitation.model';

type InviteState = 'loading' | 'invalid' | 'error' | 'ready' | 'joined';

/**
 * Public invitation landing page (plan Step 12) — route `invite/accept`,
 * deliberately unguarded like `github/callback`.
 *
 * Flow: the token is previewed WITHOUT a session first (404 → one friendly
 * "invalid or expired" state — the backend maps every unusable token to the
 * same 404, so nothing is enumerable from here either), then:
 *
 * - not signed in → **Sign in to accept**, returning to this exact URL
 *   (the existing `returnUrl` pattern via `AuthService.login`);
 * - signed in → an explicit **Accept** button — never an auto-accept;
 * - account/invitation email mismatch (client-side masked compare, plus
 *   the authoritative `email_mismatch` flag from the accept response) →
 *   warning with **Continue anyway** / **Sign in with a different account**
 *   (`switchAccount` lands back here, signed out).
 *
 * The raw token only ever appears in this URL — it is never written to
 * `console`, storage, or any tracker (there are none; keep it that way).
 */
@Component({
  selector: 'app-invite-accept',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './invite-accept.component.html',
  styleUrl: './invite-accept.component.scss'
})
export class InviteAcceptComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly invitations = inject(InvitationService);

  readonly auth = inject(AuthService);

  readonly state = signal<InviteState>('loading');
  readonly preview = signal<InvitationPreview | null>(null);
  readonly result = signal<InvitationAcceptResult | null>(null);
  readonly loadError = signal<string | null>(null);
  readonly acceptError = signal<string | null>(null);
  readonly accepting = signal(false);
  readonly mismatchAcknowledged = signal(false);

  private token: string | null = null;

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    const token = this.route.snapshot.queryParamMap.get('token');
    this.token = token;
    if (!token) {
      this.state.set('invalid');
      return;
    }
    this.state.set('loading');
    this.loadError.set(null);
    this.invitations.preview(token).subscribe({
      next: preview => {
        this.preview.set(preview);
        this.state.set('ready');
      },
      error: (err: unknown) => {
        // Invalid / expired / revoked / used are ONE 404 server-side.
        if (err instanceof ApiError && err.status === 404) {
          this.state.set('invalid');
          return;
        }
        this.loadError.set(
          err instanceof ApiError && err.message ? err.message : 'Could not load the invitation.'
        );
        this.state.set('error');
      }
    });
  }

  /**
   * Signed-in email vs the preview's mask — same deterministic shape the
   * backend applies, so equal masks mean "almost certainly your account".
   * Only runs when both sides exist; the accept response re-checks.
   */
  readonly emailMismatch = computed(() => {
    const preview = this.preview();
    const email = this.auth.currentUser()?.email;
    if (!preview || !email) {
      return false;
    }
    return maskEmail(email) !== preview.email_masked;
  });

  signInToAccept(): void {
    this.auth.login(this.router.url);
  }

  switchAccount(): void {
    this.auth.switchAccount(this.router.url);
  }

  acknowledgeMismatch(): void {
    this.mismatchAcknowledged.set(true);
  }

  accept(): void {
    if (!this.token || this.accepting()) {
      return;
    }
    this.accepting.set(true);
    this.acceptError.set(null);
    this.invitations.accept(this.token).subscribe({
      next: result => {
        this.result.set(result);
        this.state.set('joined');
        this.accepting.set(false);
      },
      error: (err: unknown) => {
        this.accepting.set(false);
        // 409 (already used) / 410 (expired, revoked) surface their
        // exact backend detail; anything else gets a readable fallback.
        this.acceptError.set(
          err instanceof ApiError && err.message
            ? err.message
            : 'Could not accept the invitation. Please try again.'
        );
      }
    });
  }
}
