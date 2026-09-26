import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ActivatedRoute, Router } from '@angular/router';
import { GithubService } from '../../../core/services/github.service';
import { AuthService } from '../../../core/services/auth.service';

type CallbackState = 'processing' | 'success' | 'error';

@Component({
  selector: 'app-github-callback',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './github-callback.component.html',
  styleUrl: './github-callback.component.scss'
})
export class GithubCallbackComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly github = inject(GithubService);
  private readonly auth = inject(AuthService);

  statusMessage = signal('Finalizing GitHub App installation...');
  isSuccess = signal(true);
  state = signal<CallbackState>('processing');

  ngOnInit(): void {
    this.processCallback();
  }

  retry(): void {
    this.processCallback();
  }

  private processCallback(): void {
    const params = this.route.snapshot.queryParamMap;
    const verified = params.get('success') === 'true';
    this.isSuccess.set(verified);

    if (!verified) {
      // Backend could not verify the installation (missing/invalid state).
      // Show error UI with retry button — do not navigate away.
      this.state.set('error');
      this.statusMessage.set('GitHub App installation could not be verified. Please try again.');
      return;
    }

    // Normal path: the session survived the full-page round-trip to GitHub.
    if (this.auth.getToken()) {
      this.finalizeInstallation();
      return;
    }

    // Storage lost across the GitHub redirect — the backend carries a fresh
    // token pair in the URL (same pattern as /auth/callback) so a successful
    // install never dumps the user on the login page.
    const token = params.get('token');
    if (token) {
      this.statusMessage.set('Restoring session...');
      this.auth.completeLogin(token, params.get('refresh_token') || '').subscribe({
        next: () => this.finalizeInstallation(),
        error: () => this.showLoginFallback()
      });
      return;
    }

    // No token anywhere — ask the user to log in.
    this.showLoginFallback();
  }

  private showLoginFallback(): void {
    this.state.set('success');
    this.statusMessage.set('GitHub App installed successfully. Please log in to continue.');
    setTimeout(() => {
      this.router.navigate(['/login'], { queryParams: { message: 'app_installed' } });
    }, 2000);
  }

  private finalizeInstallation(): void {
    this.state.set('processing');
    this.statusMessage.set('Finalizing GitHub App installation...');

    this.github.getInstallStatus().subscribe({
      next: status => {
        this.statusMessage.set(
          status.installed
            ? 'GitHub App installed. Loading dashboard...'
            : 'Installation not detected yet. Loading dashboard...'
        );
        this.router.navigate(['/dashboard']);
      },
      error: () => {
        this.statusMessage.set('Could not verify installation status. Loading dashboard...');
        this.router.navigate(['/dashboard']);
      }
    });
  }
}
