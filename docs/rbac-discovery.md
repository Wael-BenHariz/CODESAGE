# RBAC Discovery Document

## Stack Overview
- **Frontend Framework**: Angular 17+ (standalone components, SCSS, `keycloak-angular` PKCE)
- **Backend Framework/Language**: Python 3.11+ / FastAPI
- **Database Engine**: PostgreSQL 15+ 
- **ORM/Migration Tool**: SQLAlchemy 2.0+ with async support / Alembic
- **Keycloak Integration**: 
  - Realm: `codesage-realm`
  - Client config: RS256/JWKS validation via `app/services/security/keycloak.py`
  - Identity Provider Mapper: GitHub broker maps GitHub login to user attribute `github_login`
  - Social Login Broker: GitHub OAuth App used only as broker (not for direct auth)
  - Role Mapping: Realm roles mapped to effective roles via `app/security/roles.py`

## Current Role Definitions and Resolution
Roles are defined in `/backend/app/security/roles.py`:
- `PLATFORM_ADMIN` (highest)
- `ORG_ADMIN` 
- `REVIEWER`
- `DEVELOPER`
- `NONE` (internal read-only sentinel)

Role resolution flow:
1. Token claims pass through compatibility map (`SUPER_ADMIN→PLATFORM_ADMIN`, `GUEST→NONE`)
2. Precedence: `PLATFORM_ADMIN > NONE > ORG_ADMIN > REVIEWER > DEVELOPER` 
3. No recognized claim: GitHub-brokered sessions → `DEVELOPER` (temporary F1), else → `NONE`

Role synchronization:
- Backend syncs `users.role` from JWT on every authenticated request via `get_current_user`
- Guards check `current_user.role` (synced from token), not direct token claims
- Org-scoped roles stored in `org_members.role` (DEVELOPER|REVIEWER|ORG_ADMIN only)

Current precedence (from roles.py lines 78-82):
```
PLATFORM_ADMIN > NONE > ORG_ADMIN > REVIEWER > DEVELOPER
```
Note: This contains a bug where NONE ranks above ORG_ADMIN (should be PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER > NONE)

## Permission Lists and Guards
Defined in `/backend/app/security/roles.py`:
- `require_developer` = PLATFORM_ADMIN, ORG_ADMIN, REVIEWER, DEVELOPER (all except NONE)
- `require_reviewer` = PLATFORM_ADMIN, ORG_ADMIN, REVIEWER
- `require_super_admin` = PLATFORM_ADMIN

Org-scoped authorization in `/backend/app/security/org_access.py`:
- Step 1: NONE on write endpoint → 403 immediately
- Step 2: Membership lookup → 404 if not member (PLATFORM_ADMIN bypass for reads/settings)
- Step 3: Effective role = max(JWT role, org_members.role) using ladder ranking

Ladder ranking in org_access.py lines 56-62:
```
ROLE_NONE: 0,
ROLE_DEVELOPER: 1,
ROLE_REVIEWER: 2,
ROLE_ORG_ADMIN: 3,
ROLE_PLATFORM_ADMIN: 4
```

## GitHub App Installation Handling
- Installation ID stored in `users.github_installation_id` (migration 002)
- Webhook endpoint: `/webhooks/github` (HMAC validation via `GITHUB_WEBHOOK_SECRET`)
- Install callback: `/auth/github/app/callback` (writes installation ID to user)
- Install URL endpoint: `/auth/github/app/install-url` (returns signed URL with state parameter)
- Installation tokens obtained via `app/services/github_app.py:get_installation_token()`

## Data Models
Key models in `/backend/app/db/models/`:
- **User**: `id`, `keycloak_id`, `role`, `github_id`, `login`, `email`, `github_installation_id`, LLM settings
- **Org**: `id`, `name`, `account_type`, `installation_id` (FK to GitHubInstallation)
- **OrgMember**: `org_id`, `user_id`, `role` (DEVELOPER|REVIEWER|ORG_ADMIN), unique constraint
- **Repository**: `id`, `installation_id` (FK to GitHubInstallation), `github_repo_id`, `full_name`, `enabled`
- **WatchedRepo**: `user_id`, `repo_id` (GitHub repo ID), `enabled` (review switch)
- **PullRequest**: `id`, `repository_id`, `github_pr_id`, `number`, etc.
- **Review**: `id`, `pull_request_id`, `user_id`, `status`, `summary`, `posted_at`, `posting_mode`
- **ReviewComment**: `id`, `review_id`, `file_path`, `line_number`, `body`, `severity`, `category`, `dismissed*`, validation relationships
- **ReviewFindingValidation**: `comment_id`, `reviewer_id`, `verdict`, `severity_override`, `note`, unique constraint
- **GitHubInstallation**: `id`, `installation_id` (GitHub numeric ID), `account_id`, `account_login`, `account_type`, `permissions`
- **OrgInvitation**: `org_id`, `email`, `role`, `repository_ids`, `token_hash`, `status`, `expires_at`

## API Endpoints and Authorization
### Mutating Endpoints Current Authorization:
1. **Repository Management** (`/repositories*`):
   - Connect/Enable/Disable/Update: `require_developer` (WRITE_ROLES)
   - List/Get: `get_current_user` (ANY_ROLE including NONE)

2. **Pull Request Management** (`/pull-requests*`):
   - Trigger Review: `require_developer` + `require_pull_request_access(ROLE_DEVELOPER, write=True)`
   - Get/List: `require_pull_request_access(ROLE_DEVELOPER, write=False)`

3. **Review Management** (`/reviews*`):
   - Retry/Delete: `require_developer` + `require_review_access(ROLE_DEVELOPER, write=True)`
   - Resolve Comment: `require_developer` + `require_review_access(ROLE_DEVELOPER, write=True)`
   - Update Summary/Dismiss/Restore/Post: `require_review_access(ROLE_DEVELOPER, write=True, platform_admin_bypass=False)`
   - Validate Comment: `require_review_access(ROLE_REVIEWER, write=True, platform_admin_bypass=False)`
   - Get Scan Report/Get Status: `require_review_access(ROLE_DEVELOPER, write=False)`

4. **Organization Management** (`/orgs*`):
   - List Orgs: `get_current_user` (any role)
   - Get/Update Settings: `require_org_role(ROLE_ORG_ADMIN, write=[False|True])`

5. **Invitations** (`/invitations*` and `/orgs/*/invitations*`):
   - Create: `require_org_role(ROLE_ORG_ADMIN, write=True, platform_admin_bypass=False)`
   - List: `require_org_role(ROLE_ORG_ADMIN, write=False, platform_admin_bypass=True)`
   - Revoke: `require_org_role(ROLE_ORG_ADMIN, write=True, platform_admin_bypass=True)`
   - Preview/Public endpoints: No auth
   - Accept: `get_current_user` (any role, NONE included)

6. **Settings** (`/settings/llm*`):
   - Get/PUT/DELETE: `require_developer` (LLM settings mutation)
   - Test: `require_developer`

7. **Platform Admin** (`/platform*`):
   - All endpoints: `require_super_admin` (PLATFORM_ADMIN only)

## Existing Tests
- **Backend Tests**: Located in `/backend/tests/` (~203 unit tests + 5 e2e)
  - Run with: `pytest tests/ -v`
  - Requires local Postgres (`codesage_test`) + Redis (db 15)
  - `conftest.py` sets all required env vars before any `app.*` import
  - E2E tests in `tests/e2e/` are DB-free

- **Frontend Tests**: Located in `/frontend/`
  - Unit tests: `npm run test` (Karma/Jasmine, watch mode)
  - CI tests: `npm run test:ci` (Headless Chrome/Edge)
  - Currently 482 tests passing

## Key Observations for RBAC Redesign
1. **Current Role Storage**: Global realm roles in `users.role`, org-scoped roles in `org_members.role`
2. **Precedence Bug**: Current implementation has `PLATFORM_ADMIN > NONE > ORG_ADMIN > REVIEWER > DEVELOPER` but should be `PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER > NONE`
3. **Workspace Concept Missing**: No explicit workspace model; orgs implicitly define scope
4. **F1 Temporary Role**: GitHub-brokered logins get temporary DEVELOPER role until realm group assigned
5. **Authorization Pattern**: Mix of direct role checks (`require_developer`) and org-scoped guards (`require_*_access`)
6. **Frontend Guards**: Mirror backend logic but duplicated; role constants defined in `role.guard.ts`
7. **Capabilities**: Current capabilities are implicit in guards rather than explicitly defined lists

## Files to Examine Further
- `/backend/app/security/roles.py` - Role definitions and derivation
- `/backend/app/security/org_access.py` - Org-scoped authorization logic
- `/frontend/src/app/core/guards/role.guard.ts` - Frontend role guards
- `/frontend/src/app/core/services/auth-context.service.ts` - Frontend capability checks
- `/frontend/src/app/core/services/org-settings.service.ts` - Frontend role helpers
- Various API route files showing current authorization patterns