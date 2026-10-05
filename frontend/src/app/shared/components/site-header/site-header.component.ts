import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, RouterLinkActive } from '@angular/router';

import { AuthService } from '../../../core/services/auth.service';
import { AuthContextService } from '../../../core/services/auth-context.service';
import { OrgSummary } from '../../../core/services/org-settings.service';

/**
 * Shared application header (plan Step 1): role-aware main nav, the org
 * switcher (shown when the caller belongs to more than one org) and the
 * user menu (switch account / logout).
 *
 * All role checks go through `AuthContextService.can()` — cosmetic only;
 * the backend re-authorizes every request. Rendered on every authenticated
 * page; public screens (landing, login, invite preview, error pages) omit it.
 */
@Component({
  selector: 'app-site-header',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive],
  templateUrl: './site-header.component.html',
  styleUrl: './site-header.component.scss'
})
export class SiteHeaderComponent implements OnInit {
  readonly auth = inject(AuthService);
  readonly ctx = inject(AuthContextService);

  ngOnInit(): void {
    // Load orgs for the switcher (shared with the guard's admin elevation).
    // Fire-and-forget: an org-list failure must never break the header —
    // nav entries still render from the JWT-derived capability checks.
    void this.ctx.ensureOrgs().catch(() => undefined);
  }

  get orgs(): OrgSummary[] {
    return this.ctx.orgs() ?? [];
  }

  /** Cosmetic capability check — see AuthContextService for semantics. */
  can(action: Parameters<AuthContextService['can']>[0]): boolean {
    return this.ctx.can(action);
  }

  get activeOrgId(): string | null {
    return this.ctx.activeOrg()?.id ?? null;
  }

  switchOrg(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    if (value) {
      this.ctx.setActiveOrg(value);
    }
  }

  logout(): void {
    this.auth.logout();
  }

  switchAccount(): void {
    this.auth.switchAccount();
  }
}
