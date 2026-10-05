import { Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { PullRequestService } from '../../../core/services/pull-request.service';
import { navVisibility } from '../../../core/guards/role.guard';
import { PullRequest } from '../../../core/models/pull-request.model';
import { ReviewPanelComponent } from '../review-panel/review-panel.component';
import { SiteHeaderComponent } from '../../../shared/components/site-header/site-header.component';

@Component({
  selector: 'app-pr-detail',
  standalone: true,
  imports: [SiteHeaderComponent, CommonModule, RouterLink, ReviewPanelComponent],
  templateUrl: './pr-detail.component.html',
  styleUrl: './pr-detail.component.scss'
})
export class PrDetailComponent implements OnInit {
  private readonly github = inject(PullRequestService);
  private readonly auth = inject(AuthService);

  /** Cosmetic write gating for the review trigger (backend stays authoritative). */
  readonly nav = computed(() => navVisibility(this.auth.currentUser()?.role));

  owner = input.required<string>();
  repo = input.required<string>();
  number = input.required<number>();

  pullRequest = signal<PullRequest | null>(null);
  isLoading = signal(true);
  /** True when the load failed (404/5xx/network) — renders the error state. */
  loadError = signal(false);
  isReviewing = signal(false);

  ngOnInit(): void {
    this.loadPullRequest();
  }

  loadPullRequest(): void {
    this.loadError.set(false);
    this.isLoading.set(true);
    this.github.getPullRequest(this.owner(), this.repo(), this.number()).subscribe({
      next: pr => {
        this.pullRequest.set(pr);
        this.isLoading.set(false);
      },
      error: () => {
        this.isLoading.set(false);
        this.loadError.set(true);
      }
    });
  }

  triggerReview(): void {
    const pr = this.pullRequest();
    if (pr) {
      this.isReviewing.set(true);
      this.github.triggerReview(pr.id).subscribe({
        next: () => {
          this.isReviewing.set(false);
          this.loadPullRequest();
        },
        error: () => {
          this.isReviewing.set(false);
        }
      });
    }
  }

  getStateColor(state: string): string {
    switch (state) {
      case 'open':
        return '#2f855a';
      case 'closed':
        return '#c53030';
      case 'merged':
        return '#805ad5';
      default:
        return '#718096';
    }
  }
}
