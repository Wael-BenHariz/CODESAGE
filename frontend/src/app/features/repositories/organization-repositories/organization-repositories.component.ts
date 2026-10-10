import { CommonModule } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiError } from '../../../core/services/api.service';
import { RepositoryService } from '../../../core/services/repository.service';
import { Repository } from '../../../core/models/repository.model';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { ErrorStateComponent } from '../../../shared/components/error-state/error-state.component';
import { SpinnerComponent } from '../../../shared/components/spinner/spinner.component';

type PageState = 'loading' | 'error' | 'ready';

/** One option of the organization filter, derived from the loaded rows. */
interface OrgOption {
  id: string;
  name: string;
  count: number;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError && err.message ? err.message : fallback;
}

/**
 * Organization Repositories (repo-scoped invitations): the repositories
 * organizations shared with the signed-in user.
 *
 * Data source: `GET /repositories?visibility=organization` — the backend
 * derives the collection from the caller's live org memberships and their
 * explicit `org_member_repos` grants (accepted repo-scoped invitations)
 * plus the orgs they administer. The page never narrows a broader response
 * client-side and never falls back to unfiltered GitHub results: it
 * renders exactly what the authorized endpoint returned, so connecting a
 * GitHub account or joining an org cannot leak ungranted repositories.
 *
 * The fetch runs on every visit (no shared cache with the personal
 * `/repositories` page), so the list is fresh after an invitation is
 * accepted, after login and after a page refresh. Deep links reuse the
 * existing repository routes — a granted repository resolves through the
 * same `GET /repositories` union scope, an ungranted one 404s.
 *
 * Read-only by design: managing reviews (enable/disable/remove) stays on
 * the repository detail page under its existing authorization.
 */
@Component({
  selector: 'app-organization-repositories',
  standalone: true,
  imports: [CommonModule, RouterLink, SpinnerComponent, EmptyStateComponent, ErrorStateComponent],
  templateUrl: './organization-repositories.component.html',
  styleUrl: './organization-repositories.component.scss'
})
export class OrganizationRepositoriesComponent implements OnInit {
  private readonly repoApi = inject(RepositoryService);

  readonly state = signal<PageState>('loading');
  readonly error = signal<string | null>(null);
  readonly repositories = signal<Repository[]>([]);
  /** Selected organization id, or 'all' — one of `orgs()`, never invented. */
  readonly orgFilter = signal<string>('all');

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.state.set('loading');
    this.error.set(null);
    this.repoApi.getOrganizationRepositories().subscribe({
      next: repos => {
        this.repositories.set(repos);
        // Drop a filter whose organization no longer has granted rows.
        const ids = new Set(repos.map(repo => repo.orgId).filter((id): id is string => !!id));
        if (this.orgFilter() !== 'all' && !ids.has(this.orgFilter())) {
          this.orgFilter.set('all');
        }
        this.state.set('ready');
      },
      error: err => {
        // 401/403/404 keep the app-wide handling (re-login, forbidden
        // toast, not-found page) via the interceptors; only the message is
        // surfaced here, never a substitute data set.
        this.error.set(errorMessage(err, 'Could not load organization repositories.'));
        this.state.set('error');
      }
    });
  }

  /** Distinct organizations present in the granted set (multi-org users). */
  readonly orgs = computed<OrgOption[]>(() => {
    const byId = new Map<string, OrgOption>();
    for (const repo of this.repositories()) {
      const id = repo.orgId;
      if (!id) {
        continue;
      }
      const existing = byId.get(id);
      if (existing) {
        existing.count += 1;
      } else {
        byId.set(id, { id, name: repo.orgName || repo.owner || id, count: 1 });
      }
    }
    return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
  });

  /** Rows for the selected organization — the server already scoped them. */
  readonly filteredRepos = computed<Repository[]>(() => {
    const filter = this.orgFilter();
    if (filter === 'all') {
      return this.repositories();
    }
    return this.repositories().filter(repo => repo.orgId === filter);
  });

  setOrgFilter(id: string): void {
    this.orgFilter.set(id || 'all');
  }

  onFilterChange(event: Event): void {
    this.setOrgFilter((event.target as HTMLSelectElement).value);
  }
}
