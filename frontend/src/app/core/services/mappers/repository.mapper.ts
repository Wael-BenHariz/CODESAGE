import { Repository } from '../../models/repository.model';
import { PaginatedResponse } from '../../models/pagination.model';

/**
 * Repository route group (`/repositories/*`) mapping layer — the ONE place
 * snake_case repository payloads become the camelCase `Repository` model
 * (Step 0 constraint #3). Pure functions, no HTTP.
 *
 * Wire shape: `RepositoryResponse` / `RepositoryListResponse` in
 * `backend/app/schemas/repository.py`.
 */
export interface RepositoryDto {
  id: string;
  installation_id: string;
  github_repo_id: number;
  name: string;
  full_name: string;
  /** Backend fills it from full_name; still tolerated when absent. */
  owner?: string | null;
  description: string | null;
  private: boolean;
  default_branch: string;
  language: string | null;
  stars: number;
  forks: number;
  open_issues: number;
  webhook_enabled: boolean;
  webhook_id?: number | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export type RepositoryListDto = PaginatedResponse<RepositoryDto>;

/** Tolerant mapper: null/missing optional fields become safe defaults. */
export function toRepository(dto: RepositoryDto): Repository {
  const owner = dto.owner || dto.full_name?.split('/')[0] || '';
  return {
    id: dto.id,
    name: dto.name ?? '',
    fullName: dto.full_name ?? '',
    owner,
    description: dto.description ?? null,
    private: Boolean(dto.private),
    defaultBranch: dto.default_branch ?? '',
    language: dto.language ?? null,
    stars: dto.stars ?? 0,
    forks: dto.forks ?? 0,
    openIssues: dto.open_issues ?? 0,
    webhookEnabled: Boolean(dto.webhook_enabled),
    enabled: Boolean(dto.enabled),
    createdAt: dto.created_at ?? '',
    updatedAt: dto.updated_at ?? ''
  };
}

export function toRepositoryList(dto: RepositoryListDto): Repository[] {
  return (dto?.items ?? []).map(toRepository);
}
