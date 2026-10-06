import { Component, OnInit, inject, signal, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { PullRequest } from '../../../core/models/pull-request.model';

@Component({
  selector: 'app-pr-list',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './pr-list.component.html',
  styleUrl: './pr-list.component.scss'
})
export class PrListComponent implements OnInit {
  private readonly github = inject(PullRequestService);

  owner = input.required<string>();
  repo = input.required<string>();

  pullRequests = signal<PullRequest[]>([]);
  isLoading = signal(true);
  /** True when the load failed (404/5xx/network) — renders the error state. */
  loadError = signal(false);
  filter = signal<'all' | 'open' | 'closed'>('all');

  get openCount() {
    return this.pullRequests().filter(pr => pr.state === 'open').length;
  }

  get closedCount() {
    return this.pullRequests().filter(pr => pr.state === 'closed' || pr.state === 'merged').length;
  }

  get filteredPRs() {
    const prs = this.pullRequests();
    const f = this.filter();
    if (f === 'all') return prs;
    return prs.filter(pr => pr.state === f);
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
  }

  getStateIcon(state: string): string {
    switch (state) {
      case 'open':
        return '🟢';
      case 'closed':
        return '🔴';
      case 'merged':
        return '🟣';
      default:
        return '⚪';
    }
  }
}
