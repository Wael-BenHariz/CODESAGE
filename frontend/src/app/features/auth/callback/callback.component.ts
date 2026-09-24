import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-callback',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './callback.component.html',
  styleUrl: './callback.component.scss'
})
export class CallbackComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);

  error: string | null = null;

  ngOnInit(): void {
    const token = this.route.snapshot.queryParamMap.get('token');
    const refreshToken = this.route.snapshot.queryParamMap.get('refresh_token');
    const error = this.route.snapshot.queryParamMap.get('error');

    if (error) {
      this.error = error;
      return;
    }

    if (!token) {
      this.error = 'No authentication token received';
      return;
    }

    // Store tokens and fetch user info
    this.auth.completeLogin(token, refreshToken || '').subscribe({
      next: () => {
        this.router.navigate(['/dashboard']);
      },
      error: _err => {
        this.error = 'Authentication failed. Please try again.';
      }
    });
  }
}
