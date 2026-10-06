import { Component, OnInit, inject, signal, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { PullRequest } from '../../../core/models/pull-request.model';
import { SpinnerComponent } from '../../../shared/components/spinner/spinner.component';
import { EmptyStateComponent } from '../../../shared/components/empty-state/empty-state.component';
import { ErrorStateComponent } from '../../../shared/components/error-state/error-state.component';

/**
 * Pull-request list (plan §4.2): state + author filters and pagination over
 * the loaded window (client-side — the backend `state` filter is an exact
 * match, so a server-side "closed" would exclude merged rows; see Step 6
 * notes). Rows show a WRITTEN state chip (color + text, never color-only)
 * and deliberately NO review badge: list responses carry no review fields
 * (docs/BACKEND_GAPS_FOR_UI.md gap 7).
 *
 * The standalone route renders the page header; embedded in the repository
 * detail's "Pull requests" tab (`embedded` input) the header hides.
 */
@Component({
  selector: 'app-pr-list',
  standalone: true,
  imports: [CommonModule, RouterLink, SpinnerComponent, EmptyStateComponent, ErrorStateComponent],
  templateUrl: './pr-list.component.html',
  styleUrl: './pr-list.component.scss'
})
export class PrListComponent implements OnInit {
  private readonly github = inject(PullRequestService);

  owner = input.required<string>();
  repo = input.required<string>();
  /** Embedded in repository-detail → suppresses the standalone page header. */
  embedded = input(false);

  pullRequests = signal<PullRequest[]>([]);
  isLoading = signal(true);
  /** True when the load failed (404/5xx/network) — renders the error state. */
  loadError = signal(false);
  filter = signal<'all' | 'open' | 'closed'>('all');
  /** Author filter (case-insensitive substring over the loaded window). */
  authorFilter = signal('');
  /** 1-based page over the filtered rows. */
  page = signal(1);
  readonly pageSize = 10;
  /** The backend hands us at most this many rows per request. */
  readonly windowCap = 100;

  get openCount(): number {
    return this.pullRequests().filter(pr => pr.state === 'open').length;
  }

  get closedCount(): number {
    return this.pullRequests().filter(pr => pr.state === 'closed' || pr.state === 'merged').length;
  }

  /**
   * State + author filters, both client-side over the loaded window.
   * "Closed" includes merged rows so the rows always match the count shown
   * on the chip (the old `pr.state === 'closed'` filter hid merged PRs while
   * the chip counted them).
   */
  get filteredPRs(): PullRequest[] {
    const prs = this.pullRequests();
    const f = this.filter();
    const author = this.authorFilter().trim().toLowerCase();

    return prs.filter(pr => {
      const stateOk =
        f === 'all' ||
        (f === 'open' ? pr.state === 'open' : pr.state === 'closed' || pr.state === 'merged');
      if (!stateOk) {
        return false;
      }
      if (!author) {
        return true;
      }
      return pr.author.login.toLowerCase().includes(author);
    });
  }

  get pageCount(): number {
    return Math.max(Math.ceil(this.filteredPRs.length / this.pageSize), 1);
  }

  /** Rows for the current page (paged AFTER the filters). */
  get pageRows(): PullRequest[] {
    const start = (this.page() - 1) * this.pageSize;
    return this.filteredPRs.slice(start, start + this.pageSize);
  }

  get pageRangeLabel(): string {
    const total = this.filteredPRs.length;
    if (total === 0) {
      return '';
    }
    const start = (this.page() - 1) * this.pageSize + 1;
    const end = Math.min(this.page() * this.pageSize, total);
    return `${start}–${end} of ${total}`;
  }

  ngOnInit(): void {
    this.loadPullRequests();
  }

  loadPullRequests(): void {
    this.loadError.set(false);
    this.isLoading.set(true);
    this.github.getPullRequests(this.owner(), this.repo()).subscribe({
      next: prs => {
        this.pullRequests.set(prs);
        this.isLoading.set(false);
      },
      error: () => {
        this.isLoading.set(false);
        this.loadError.set(true);
      }
    });
  }

  setFilter(filter: 'all' | 'open' | 'closed'): void {
    this.filter.set(filter);
    this.page.set(1); // a new filter re-slices the rows
  }

  onAuthorInput(event: Event): void {
    this.authorFilter.set((event.target as HTMLInputElement).value);
    this.page.set(1);
  }

  clearFilters(): void {
    this.filter.set('all');
    this.authorFilter.set('');
    this.page.set(1);
  }

  goTo(target: number): void {
    this.page.set(Math.min(Math.max(target, 1), this.pageCount));
  }
}
