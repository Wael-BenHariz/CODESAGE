# RBAC Target Design

This document specifies the exact target design for implementing per-workspace RBAC in CodeSage as described in section 2 of the task.

## 2.1 Workspaces

- New concept **Workspace** with `type` = `PERSONAL` or `ORG`.
- Every user gets exactly one PERSONAL workspace, created automatically on first login (including first GitHub-broker login). The user is `ORG_ADMIN` in it.
- ORG workspaces have many members, each with a per-workspace role.
- Every repository, PR, review, finding and GitHub App installation belongs to exactly one workspace.
- Roles are PER WORKSPACE (membership table), except `PLATFORM_ADMIN`, which stays global.

## 2.2 Roles and Precedence

`PLATFORM_ADMIN (global) > ORG_ADMIN > REVIEWER > DEVELOPER > NONE`
(Fix the old precedence bug where NONE ranked above ORG_ADMIN. Effective role = highest role among the user's realm role and the workspace membership role, using this order.)

Rename the field consistently to `viewer_role` everywhere (remove `reviewer_role`). Use explicit whitelists, never `!== 'NONE'`.

## 2.3 Permission Lists (replace WRITE_ROLES)

Define in ONE shared place on the backend (single source of truth) and mirror them on the frontend:
- `VIEW_ROLES` = all roles incl. NONE
- `TRIGGER_ROLES` = DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN
- `REQUEST_ROLES` (comment, request dismissal) = DEVELOPER, REVIEWER, ORG_ADMIN, PLATFORM_ADMIN
- `REVIEW_ROLES` (validate, override severity, dismiss/restore, edit summary, post) = REVIEWER, ORG_ADMIN, PLATFORM_ADMIN
- `REPO_CONFIG_ROLES` (connect, enable/disable, auto-review toggle, edit default branch) = REVIEWER, ORG_ADMIN, PLATFORM_ADMIN
- `REPO_ADMIN_ROLES` (install GitHub App, delete repo, workspace settings, manage members) = ORG_ADMIN, PLATFORM_ADMIN
- `PLATFORM_ROLES` = PLATFORM_ADMIN

## 2.4 Capability Matrix to Enforce

| Capability | NONE | DEV | REVIEWER | ORG_ADMIN | PLATFORM |
|---|---|---|---|---|---|
| View repos/PRs/reviews | Y | Y | Y | Y | Y |
| Trigger / retry review | N | Y | Y | Y | Y |
| Comment / request dismissal | N | Y | Y | Y | Y |
| Validate, override severity, note | N | N | Y | Y | Y |
| Dismiss / restore finding | N | N | Y | Y | Y |
| Edit summary | N | N | Y | Y | Y |
| Post to GitHub | N | N | Y | Y | Y |
| Connect / enable / disable repo, auto-review toggle, default branch | N | N | Y | Y | Y |
| Install GitHub App, delete repo | N | N | N | Y | Y |
| Workspace settings, members | N | N | N | Y | Y |
| Platform admin | N | N | N | N | Y |

In a PERSONAL workspace the user is ORG_ADMIN, so they get everything above except platform admin.

## 2.5 Business Rules

- State checks for review actions (shared by all): review `status === 'ready_to_post'` AND `posted_at === null`. Validation, dismissal, restore, edit and post are all blocked once posted.
- Split the old single `canEdit` into `canEditSummary`, `canDismiss`, `canPost`, `canValidate`, `canRequestDismissal`, each combining role list + state check.
- Fix the validation UI bug: validation controls show when the comment exists, the review is not posted and `canValidate`. NOT "when the comment has validations".
- Dismissal requests: a DEVELOPER can create a `DismissalRequest` (finding_id, reason, status PENDING/APPROVED/REJECTED, requested_by, resolved_by, timestamps). A REVIEWER+ approves (finding becomes dismissed) or rejects. Posting is blocked while pending requests exist.
- Self-review rule: in an ORG workspace with more than 1 member, a user cannot validate/dismiss/approve findings on a PR they authored (compare PR author's GitHub login/user id to the actor). This rule is DISABLED in PERSONAL workspaces and ORG workspaces with a single member.
- Request-install flow: in an ORG workspace, a non-admin user sees "Request GitHub App install". This creates an `InstallRequest` (workspace_id, requested_by, status, resolved_by) and notifies ORG_ADMINs (in-app notification at minimum). Admin approve/reject UI included.
- Remove the temporary "F1" expiring DEVELOPER role. New behavior: GitHub-broker login creates the personal workspace (ORG_ADMIN there) and grants DEVELOPER only in org workspaces the user was invited to / is a member of. No membership means NONE in that workspace.
- Edit default branch is now gated by `REPO_CONFIG_ROLES` in both UI and backend.
