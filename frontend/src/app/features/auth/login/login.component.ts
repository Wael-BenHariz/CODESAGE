import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss'
})
export class LoginComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);

  readonly showInstallBanner = signal(false);

  ngOnInit(): void {
    this.showInstallBanner.set(
      this.route.snapshot.queryParamMap.get('message') === 'app_installed'
    );
  }

  loginWithGitHub(): void {
    // Honor the returnUrl the RoleGuard captured when it bounced the user
    // here (AuthService itself always uses idpHint: 'github').
    const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl') ?? undefined;
    this.auth.login(returnUrl);
  }
}
