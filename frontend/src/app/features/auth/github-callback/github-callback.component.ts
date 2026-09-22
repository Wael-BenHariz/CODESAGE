import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ActivatedRoute, Router } from '@angular/router';
import { GithubService } from '../../../core/services/github.service';

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

  statusMessage = signal('Finalizing GitHub App installation...');
  isSuccess = signal(true);

  ngOnInit(): void {
    const success = this.route.snapshot.queryParamMap.get('success') !== 'false';
    this.isSuccess.set(success);

    // Re-check install status so shared state (Install button visibility) is fresh.
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
