import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ActivatedRoute, Router } from '@angular/router';
import { GithubAppService } from '../../../core/services/github-app.service';
import { AuthService } from '../../../core/services/auth.service';
import { SpinnerComponent } from '../../../shared/components/spinner/spinner.component';

type CallbackState = 'processing' | 'success' | 'error';

@Component({
  selector: 'app-github-callback',
  standalone: true,
  imports: [CommonModule, RouterLink, SpinnerComponent],
  templateUrl: './github-callback.component.html',
  styleUrl: './github-callback.component.scss'
})
export class GithubCallbackComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly github = inject(GithubAppService);
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

    // The Keycloak SSO session survives the full-page round-trip to GitHub:
    // APP_INITIALIZER ran check-sso (silent iframe) while this page loaded,
    // before ngOnInit. No tokens ever ride on this URL.
    if (this.auth.isAuthenticated()) {
      this.finalizeInstallation();
      return;
    }

    // No session — ask the user to log in.
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
