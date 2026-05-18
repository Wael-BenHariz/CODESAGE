import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { GithubService } from '../../../core/services/github.service';
import { Repository } from '../../../core/models/repository.model';

@Component({
  selector: 'app-repository-list',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './repository-list.component.html',
  styleUrl: './repository-list.component.scss'
})
export class RepositoryListComponent implements OnInit {
  private readonly github = inject(GithubService);

  repositories = signal<Repository[]>([]);
  isLoading = signal(true);
  filter = signal<'all' | 'enabled' | 'disabled'>('all');

  filteredRepos = () => {
    const repos = this.repositories();
    const f = this.filter();
    if (f === 'all') return repos;
    return repos.filter(r => f === 'enabled' ? r.enabled : !r.enabled);
  };

  ngOnInit(): void {
    this.loadRepositories();
  }

  private loadRepositories(): void {
    this.github.getRepositories().subscribe({
      next: (repos) => {
        this.repositories.set(repos);
        this.isLoading.set(false);
      },
      error: () => {
        this.isLoading.set(false);
      }
    });
  }

  setFilter(filter: 'all' | 'enabled' | 'disabled'): void {
    this.filter.set(filter);
  }

  toggleRepo(repo: Repository): void {
    if (repo.enabled) {
      this.github.disableRepository(repo.id).subscribe();
    } else {
      this.github.enableRepository(repo.id).subscribe();
    }
    this.loadRepositories();
  }

  deleteRepo(repo: Repository): void {
    if (confirm(`Are you sure you want to remove ${repo.fullName}?`)) {
      this.github.deleteRepository(repo.id).subscribe();
      this.loadRepositories();
    }
  }
}