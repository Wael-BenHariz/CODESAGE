import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

/**
 * Generic 404 page (plan Step 1, rule 5). Serves BOTH client-side routing
 * (wildcard route) and API 404s (error interceptor) — one uniform message
 * for "not found", deliberately neutral: a resource outside the caller's
 * orgs also answers 404, so this page must never imply access denied.
 * Public (unguarded): an anonymous visitor landing here must not be
 * bounced to /login.
 */
@Component({
  selector: 'app-not-found',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './not-found.component.html',
  styleUrl: '../error-page.component.scss'
})
export class NotFoundComponent {}
