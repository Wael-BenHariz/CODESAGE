import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';

/**
 * Forbidden page (plan Step 1, rule 5) — the destination when an
 * authenticated user's effective role does not allow a route (the guard's
 * UI-level 403). Public (unguarded): a NONE-role user must be able to land
 * here without a redirect loop. The backend stays authoritative for every
 * API call; this page only explains the route-level denial.
 */
@Component({
  selector: 'app-forbidden',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './forbidden.component.html',
  styleUrl: '../error-page.component.scss'
})
export class ForbiddenComponent {}
