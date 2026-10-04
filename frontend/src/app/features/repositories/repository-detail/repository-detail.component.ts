import { Component, OnInit, computed, inject, signal, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { GithubService } from '../../../core/services/github.service';
import { navVisibility } from '../../../core/guards/role.guard';
import { Repository } from '../../../core/models/repository.model';

@Component({
  selector: 'app-repository-detail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './repository-detail.component.html',
  styleUrl: './repository-detail.component.scss'
})
export class RepositoryDetailComponent implements OnInit {
  private readonly github = inject(GithubService);
  private readonly auth = inject(AuthService);

  /** Cosmetic write gating for the enable/disable toggle (backend stays authoritative). */
  readonly nav = computed(() => navVisibility(this.auth.currentUser()?.role));

  owner = input.required<string>();
  repo = input.required<string>();

  repository = signal<Repository | null>(null);
  isLoading = signal(true);

  ngOnInit(): void {
    this.loadRepository();
  }

  private loadRepository(): void {
    this.github.getRepository(this.owner(), this.repo()).subscribe({
      next: repo => {
        this.repository.set(repo);
        this.isLoading.set(false);
      },
      error: () => {
        this.isLoading.set(false);
      }
    });
  }

  toggleEnabled(): void {
    const repo = this.repository();
    if (repo) {
      if (repo.enabled) {
        this.github.disableRepository(repo.id).subscribe();
      } else {
        this.github.enableRepository(repo.id).subscribe();
      }
      this.loadRepository();
    }
  }
}
