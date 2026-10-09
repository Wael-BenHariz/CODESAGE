# Keycloak Changes for Workspace RBAC

This document describes the exact steps needed to update the Keycloak realm to support the workspace-based RBAC model.

## Changes Made

### 1. Realm Roles Updates
- Marked ORG_ADMIN, REVIEWER, and DEVELOPER realm roles as DEPRECATED
  - Added descriptions indicating these roles are deprecated in favor of workspace roles
  - Kept the roles for transition period to avoid breaking existing deployments
- Kept PLATFORM_ADMIN role unchanged (still global)
- Kept SUPER_ADMIN and GUEST roles for compatibility (to be removed in v0.4.0)

### 2. Groups Updates
- Removed groups for ORG_ADMIN, REVIEWER, and DEVELOPER roles
  - These groups were mapping users to the deprecated realm roles
  - Kept groups for PLATFORM_ADMIN, SUPER_ADMIN, and GUEST

### 3. Identity Provider Mapper Updates
- Modified the githubLogin protocol mapper in the github-claims client scope
  - Changed claim name from "githubLogin" to "github_login" to match the expected attribute name
  - This ensures the GitHub login is available in the access token as the "github_login" claim
  - **Safety note (2026-10-09):** the backend (`_via_github`, JIT login fallback)
    and the frontend guard accept **both** spellings — the live realm still
    emits `githubLogin` (the realm has not been re-imported) and applying this
    rename cannot break identity detection either way.

## Steps to Apply Changes to an Existing Realm

### Prerequisites
- Access to Keycloak admin console
- The realm name is "codesage-realm" (as used in this deployment)
- Backup of the current realm configuration (recommended)

### Step-by-Step Instructions

#### 1. Update Realm Role Descriptions
1. Log in to Keycloak admin console
2. Select the "codesage-realm" realm
3. Go to "Roles" → "Realm Roles"
4. For each of the following roles, edit the description:
   - ORG_ADMIN: Change description to "Administers one organization: org settings, invitations, member roles (DEPRECATED: use workspace roles instead)"
   - REVIEWER: Change description to "Validates review findings (confirm / false positive / severity override) in their orgs (DEPRECATED: use workspace roles instead)"
   - DEVELOPER: Change description to "Can install GitHub App, manage repos, view own reviews, staged-post controls (DEPRECATED: use workspace roles instead)"
5. Save changes for each role

#### 2. Remove Deprecated Groups
1. Go to "Groups" in the left sidebar
2. Delete the following groups:
   - /org-admins
   - /reviewers
   - /developers
3. Confirm deletion when prompted
4. Keep the following groups:
   - /platform-admins
   - /super-admins
   - /guests

#### 3. Update GitHub Identity Protocol Mapper
1. Go to "Identity Providers" in the left sidebar
2. Click on the "github" identity provider
3. Go to the "Mappers" tab
4. Find the mapper named "githubLogin" (type: "oidc-usermodel-attribute-mapper")
5. Click to edit this mapper
6. Change the "Mapper Name" field to "githubLogin" (if needed)
7. In the "Mapper Configuration" section:
   - Find the "Claim Name" field
   - Change it from "githubLogin" to "github_login"
   - Keep "User Attribute" as "githubLogin"
   - Keep "ID Token Claim" and "Access Token Claim" set to "ON"
8. Save the changes

#### 4. Verify GitHub Identity Provider Configuration
1. While still in the GitHub identity provider configuration:
   - Ensure "Add Read Token Role on Create" is still enabled (this is standard Keycloak behavior)
   - Ensure the sync mode is set to "IMPORT" (under the Config tab)
   - Verify that the mappers for githubLogin, githubId, and picture are present under the "Mappers" tab

### Backend Code Changes Required

In addition to the Keycloak changes, the following backend code changes are required:

1. **app/security/roles.py**: 
   - Updated derive_role function to remove the F1 DEVELOPER fallback logic
   - Fixed precedence order to: PLATFORM_ADMIN > ORG_ADMIN > REVIEWER > DEVELOPER > NONE
   - Updated comments to reflect removal of temporary F1 role

2. **app/db/models/**:
   - Added new models: Workspace, WorkspaceMember, DismissalRequest, InstallRequest, Notification
   - Updated existing models to include workspace_id foreign keys and relationships
   - Added migration script (020_workspace_rbac.py) with data backfill

3. **app/tests/conftest.py**:
   - Added test fixtures for workspaces and workspace memberships

### Verification Steps

After applying these changes, verify the following:

1. **Token Inspection**: 
   - When a user logs in via GitHub broker, decode the access token and verify:
     - It contains a "github_login" claim with the user's GitHub username
     - It does NOT contain any automatic DEVELOPER role from the F1 fallback
     - The user's realm roles are correctly mapped (if any)

2. **Workspace Creation**:
   - On first login, a personal workspace should be automatically created for the user
   - The user should be assigned as ORG_ADMIN in their personal workspace

3. **Role Resolution**:
   - Users with no realm roles, no GitHub identity and no workspace membership should have effective role NONE
   - A GitHub-brokered session with no realm roles derives the ORG_ADMIN signup default (global floor; membership still governs per-workspace access)
   - Users with workspace membership should have effective role based on their highest workspace role (never below the JWT floor)
   - Users with recognized realm roles derive their effective role from the realm role
   - PLATFORM_ADMIN realm role should always grant highest effective role

### Transition Notes

During the transition period:
- Existing users with ORG_ADMIN, REVIEWER, or DEVELOPER realm roles will continue to have those roles effective
- New users logging in via GitHub broker will start with no realm role but derive the global ORG_ADMIN signup default; workspace membership still decides per-workspace access, and any explicit realm role outranks the default
- Administrators should gradually migrate users from relying on realm roles to workspace membership
- After the transition period (future release), the deprecated realm roles can be removed entirely