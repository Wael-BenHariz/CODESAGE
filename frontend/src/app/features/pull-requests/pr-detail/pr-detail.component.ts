import { Component, OnInit, inject, signal, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { GithubService } from '../../../core/services/github.service';
import { PullRequest } from '../../../core/models/pull-request.model';

@Component({
  selector: 'app-pr-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './pr-detail.component.html',
  styleUrl: './pr-detail.component.scss'
})
export class PrDetailComponent implements OnInit {
  private readonly github = inject(GithubService);

  owner = input.required<string>();
  repo = input.required<string>();
  number = input.required<number>();

  pullRequest = signal<PullRequest | null>(null);
  isLoading = signal(true);
  isReviewing = signal(false);

  ngOnInit(): void {
    this.loadPullRequest();
  }

  private loadPullRequest(): void {
    this.github.getPullRequest(this.owner(), this.repo(), this.number()).subscribe({
      next: (pr) => {
        this.pullRequest.set(pr);
        this.isLoading.set(false);
      },
      error: () => {
        this.isLoading.set(false);
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
      case 'open': return '#2f855a';
      case 'closed': return '#c53030';
      case 'merged': return '#805ad5';
      default: return '#718096';
    }
  }
}