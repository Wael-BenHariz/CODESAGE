import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { SettingsNavComponent } from '../../../shared/components/settings-nav/settings-nav.component';

/**
 * Personal review preferences (plan Step 4) — route
 * `/settings/review-preferences`.
 *
 * Gap 4 in docs/BACKEND_GAPS_FOR_UI.md: no backend persists personal review
 * preferences or email notifications. The controls therefore render
 * disabled with an explicit "nothing here is saved" label — they never
 * pretend to save. What review behavior actually exists is organization
 * policy (managed in Organization Settings), which this screen points to
 * without duplicating.
 */
@Component({
  selector: 'app-review-preferences',
  standalone: true,
  imports: [RouterLink, SettingsNavComponent],
  templateUrl: './review-preferences.component.html',
  styleUrl: './review-preferences.component.scss'
})
export class ReviewPreferencesComponent {}
