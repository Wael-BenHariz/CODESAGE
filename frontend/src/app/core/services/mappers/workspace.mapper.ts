import { Workspace } from '../../models/user.model';

import { RawCapabilityFlags, mapCapabilityFlags } from './user.mapper';

export interface WorkspaceDto {
  id: string;
  type: 'PERSONAL' | 'ORG';
  name: string;
  role: 'ORG_ADMIN' | 'REVIEWER' | 'DEVELOPER' | 'NONE';
  github_account_login?: string | null;
  /** Permission flags from `capability_flags()` — rendered, never re-derived. */
  capabilities?: RawCapabilityFlags;
}

export type { Workspace };

/**
 * Map the `GET /workspaces` payload to the workspace model.
 *
 * Capability flags come from the server (`_workspace_payload`) — this
 * mapper only converts snake_case keys, it never re-derives the matrix
 * from role names.
 */
export function toWorkspace(dto: WorkspaceDto): Workspace {
  return {
    id: dto.id,
    type: dto.type,
    name: dto.name,
    role: dto.role,
    isPersonal: dto.type === 'PERSONAL',
    githubAccountLogin: dto.github_account_login ?? null,
    capabilities: mapCapabilityFlags(dto.capabilities)
  };
}

/** Map a list of workspace DTOs. */
export function toWorkspaceList(dtos: WorkspaceDto[]): Workspace[] {
  return (dtos ?? []).map(toWorkspace);
}
