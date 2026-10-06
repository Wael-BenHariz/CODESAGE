import { Component, OnInit, computed, inject, signal, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { RepositoryService } from '../../../core/services/repository.service';
import { ToastService } from '../../../core/services/toast.service';
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
  private readonly github = inject(RepositoryService);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);

  /** Cosmetic write gating for the enable/disable toggle (backend stays authoritative). */
  readonly nav = computed(() => navVisibility(this.auth.currentUser()?.role));

  owner = input.required<string>();
  repo = input.required<string>();

  repository = signal<Repository | null>(null);
  isLoading = signal(true);
  /** True when the load failed (404/5xx/network) — renders the error state. */
  loadError = signal(false);
  /** Toggle in flight — disables the button so it cannot double-submit. */
  toggling = signal(false);

  ngOnInit(): void {
    this.loadRepository();
  }

  loadRepository(): void {
    this.loadError.set(false);
    this.isLoading.set(true);
    this.github.getRepository(this.owner(), this.repo()).subscribe({
      next: repo => {
        this.repository.set(repo);
        this.isLoading.set(false);
      },
      error: () => {
        this.isLoading.set(false);
        this.loadError.set(true);
      }
    });
  }

  toggleEnabled(): void {
    const repo = this.repository();
    if (!repo || this.toggling()) {
      return; // double-submit guard
    }
    this.toggling.set(true);
    const request = repo.enabled
      ? this.github.disableRepository(repo.id)
      : this.github.enableRepository(repo.id);
    request.subscribe({
      next: () => {
        this.toggling.set(false);
        this.toast.success(repo.enabled ? 'Reviews disabled.' : 'Reviews enabled.');
        this.loadRepository();
      },
      error: () => {
        this.toggling.set(false);
        this.toast.error("Couldn't update the repository — please try again.");
      }
    });
  }
}
