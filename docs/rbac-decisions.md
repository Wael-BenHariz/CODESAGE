# RBAC Decisions Log

This document tracks assumptions and decisions made during the RBAC implementation process.

## Initial Assumptions (from discovery phase)

1. **Role Precedence Bug Confirmed**: The current implementation in `/backend/app/security/roles.py` lines 78-82 shows precedence as `PLATFORM_ADMIN > NONE > ORG_ADMIN > REVIEWER > DEVELOPER`, which incorrectly places NONE above ORG_ADMIN. This needs to be fixed to `PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER > NONE`.

2. **F1 Temporary Role Exists**: The temporary F1 DEVELOPER role for GitHub-brokered logins is present in the code (roles.py lines 84-90 and 107-116) and needs to be removed per the requirements.

3. **Workspace Concept Missing**: There is no explicit workspace model in the current schema. Organizations implicitly define scope through the orgs table and org_memberships.

4. **Authorization Scattered**: Permission checks are distributed across various files:
   - Role-based guards in `/backend/app/security/roles.py`
   - Org-scoped guards in `/backend/app/security/org_access.py`
   - Direct role checks in API route files

5. **Frontend-Backend Duplication**: Role constants and logic are duplicated between backend and frontend:
   - Backend: `/backend/app/security/roles.py`
   - Frontend: `/frontend/src/app/core/guards/role.guard.ts` and related services

6. **Field Naming Inconsistency**: The task mentions renaming to `viewer_role` consistently and removing `reviewer_role`. Need to investigate where these fields exist.

## Open Questions for Clarification

1. **Workspace Type Values**: Should workspace types be strings ("PERSONAL", "ORG") or use an enum/boolean?

2. **Personal Workspace Naming**: What should determine the name of a personal workspace? Username? A default like "Personal Workspace"?

3. **Migration Strategy**: For existing data, should we:
   - Create one personal workspace per existing user
   - Map existing organizations to org workspaces
   - Migrate existing org_members to workspace_members
   - Assign repositories based on GitHub installation → org → workspace chain

4. **GitHub App Installation Ownership**: Should GitHub App installations belong to workspaces or users? The task says "every repository, PR, review, finding and GitHub App installation belongs to exactly one workspace."

5. **Personal Workspace Creation Timing**: Should personal workspaces be created:
   - On first login only
   - On every login (idempotent)
   - Via a background process

6. **Default Workspace Context**: When a user logs in, what should be their default workspace context? Their personal workspace?

7. **Cross-Workspace Access**: How should cross-workspace access be handled? Should it return 404 (to avoid leaking existence) as mentioned for org access?

8. **Platform Admin Scope**: Is PLATFORM_ADMIN truly global across all workspaces, or does it need to be assigned to specific workspaces?

9. **Role Field Migration**: When renaming role fields to `viewer_role`, what tables/columns need to be changed?

10. **Backwards Compatibility**: During migration, how do we handle backwards compatibility for any external consumers of the API?

These questions will be logged and answered as implementation progresses, with each decision recorded here.