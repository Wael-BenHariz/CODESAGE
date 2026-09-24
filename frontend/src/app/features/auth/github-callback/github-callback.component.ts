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
    const verified = this.route.snapshot.queryParamMap.get('success') === 'true';
    this.isSuccess.set(verified);

    if (!verified) {
      // Backend could not verify the installation (missing/invalid state).
      // Show error UI with retry button — do not navigate away.
      this.state.set('error');
      this.statusMessage.set('GitHub App installation could not be verified. Please try again.');
      return;
    }

    // Hard rule: never call a protected endpoint unless a JWT exists in storage.
    if (!this.auth.getToken()) {
      // Session lost (e.g. storage cleared) — no protected API calls here.
      this.state.set('success');
      this.statusMessage.set('GitHub App installed successfully. Please log in to continue.');
      setTimeout(() => {
        this.router.navigate(['/login'], { queryParams: { message: 'app_installed' } });
      }, 2000);
      return;
    }

    // JWT present in localStorage — the session survives the redirect, so
    // verify the installation normally and continue to the dashboard.
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
