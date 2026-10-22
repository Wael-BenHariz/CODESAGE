import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ApiError } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { SettingsNavComponent } from '../../../shared/components/settings-nav/settings-nav.component';

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.message) {
    return err.message;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
}

/**
 * Personal profile screen (plan Step 4) — route `/settings/profile`.
 *
 * Identity fields (login, GitHub id, avatar) come from the GitHub identity
 * provider and are shown read-only with an explanation; they have no update
 * route. The editable fields (display name, email) persist through the real
 * `PATCH /users/me` (backend `UserUpdate`: email/name/avatar_url) — saving is
 * only wired because that endpoint exists, and every failure surfaces
 * visibly. Nothing here edits organization or platform configuration.
 */
@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, FormsModule, SettingsNavComponent],
  templateUrl: './profile.component.html',
  styleUrl: './profile.component.scss'
})
export class ProfileComponent implements OnInit {
  private readonly auth = inject(AuthService);

  readonly user = this.auth.currentUser;

  // --- form state (display name + email — the two editable fields) --------
  nameDraft = signal('');
  emailDraft = signal('');
  /** First snapshot after the user loads — drives the dirty check. */
  private baseline = signal({ name: '', email: '' });
  initialized = false;

  readonly saving = signal(false);
  readonly saved = signal(false);
  readonly saveError = signal<string | null>(null);

  ngOnInit(): void {
    this.syncFromUser();
  }

  /** Seed drafts from the session profile (idempotent — keeps its edits). */
  private syncFromUser(): void {
    const user = this.user();
    if (!user || this.initialized) {
      return;
    }
    this.initialized = true;
    this.nameDraft.set(user.name ?? '');
    this.emailDraft.set(user.email ?? '');
    this.baseline.set({ name: user.name ?? '', email: user.email ?? '' });
  }

  /** True when a draft differs from the loaded profile. */
  readonly dirty = computed(() => {
    const base = this.baseline();
    return this.nameDraft().trim() !== base.name || this.emailDraft().trim() !== base.email;
  });

  readonly canSave = computed(() => this.dirty() && !this.saving());

  onNameInput(event: Event): void {
    this.nameDraft.set((event.target as HTMLInputElement).value);
    this.saved.set(false);
    this.saveError.set(null);
  }

  onEmailInput(event: Event): void {
    this.emailDraft.set((event.target as HTMLInputElement).value);
    this.saved.set(false);
    this.saveError.set(null);
  }

  /** Client-side gate — the backend re-validates (422 surfaces inline). */
  private validate(): string | null {
    const email = this.emailDraft().trim();
    if (email === '') {
      return null; // clearing the email is allowed (backend field is nullable)
    }
    const shape = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return shape.test(email) ? null : 'Enter a valid email address (or leave it empty).';
  }

  save(): void {
    if (!this.canSave()) {
      return;
    }
    const invalid = this.validate();
    if (invalid) {
      this.saveError.set(invalid);
      return;
    }
    this.saving.set(true);
    this.saved.set(false);
    this.saveError.set(null);

    // Only the two fields the endpoint persists — the identity-provider
    // fields (login, GitHub id, avatar) are never sent.
    this.auth
      .updateProfile({ name: this.nameDraft().trim(), email: this.emailDraft().trim() })
      .subscribe({
        next: user => {
          this.saving.set(false);
          this.saved.set(true);
          this.baseline.set({ name: user.name ?? '', email: user.email ?? '' });
          this.nameDraft.set(user.name ?? '');
          this.emailDraft.set(user.email ?? '');
        },
        error: err => {
          this.saving.set(false);
          this.saveError.set(errorMessage(err, 'Could not save your profile.'));
        }
      });
  }

  /** Discard drafts back to the loaded profile (never mid-save). */
  reset(): void {
    if (this.saving()) {
      return;
    }
    const base = this.baseline();
    this.nameDraft.set(base.name);
    this.emailDraft.set(base.email);
    this.saved.set(false);
    this.saveError.set(null);
  }

  logout(): void {
    this.auth.logout();
  }
}
