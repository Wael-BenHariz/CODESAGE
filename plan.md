# Plan — Role-Based Frontend Redesign & UX Improvement

Frontend-only reorganization of CODESAGE around the four roles (DEVELOPER /
REVIEWER / ORG_ADMIN / PLATFORM_ADMIN, plus the read-only NONE sentinel) so every
user immediately understands what they can do. Backend authorization is never
weakened — `can()` stays cosmetic and the API re-checks every request.

## 1. Inventory (verified in code)

### Routes today (`frontend/src/app/app.routes.ts`)

| Route | Guard (`data.capabilities`) | Screen state |
|---|---|---|
| `/` `/login` `/admin` `/github/callback` `/invite/accept` `/help` `/not-found` `/forbidden` | public, `shell:false` | working |
| `/dashboard` | `write` | working — real APIs (repos, reviews, LLM, GitHub status, org posting mode) |
| `/repositories` | `read` | working — personal scope (`visibility=personal`), connect/enable/disable/delete + confirm dialogs |
| `/organization-repositories` | `read` | working — granted org repos, read-only by design |
| `/repositories/:owner/:repo` `/…/pulls` `/…/pulls/:number` | `read` | working; PR detail embeds the review panel + `canDeactivate` unsaved-summary guard |
| `/settings` | `write` | **mixed page**: Profile (login/email disabled, **"Name" input looks editable but discards changes**), Review Preferences (honest disabled), AI Model (fully working), Notifications (honest disabled), logout |
| `/settings/org` | `org:settings` (+ membership elevation in guard) | working — org settings form (5 groups, partial-PUT semantics, ceilings) + `?view=members` (role explanations + invitations). **No member-list/audit-log/statistics endpoints exist.** |
| `/platform` | `platform`, `shell:false` | real overview (`GET /users`, `GET /orgs`, read-only) + 6 **mock prototype pages** (dashboard/users/settings/system/logs/quotas) — **all in French, only one carries a "static demo" note** |
| `/platform-admin` | redirect → `/platform` | legacy alias |

### Authorization mechanics (reused as-is)

- `RoleGuard` → `AuthContextService.canCapability(action, role)` with capabilities
  `read | write | validate | org:settings | platform`; org-membership elevation for
  `org:settings`; `platform` is never elevated. `deriveRole` mirrors backend roles.py.
- Resource-level truth comes from API responses (`viewer_role` on review detail,
  per-org `role` on `GET /orgs`) — the review panel already gates
  dismiss/restore (developer+ on the staged review) and validate (reviewer+)
  on `viewer_role`, which respects the backend F2 carve-out
  (a PLATFORM_ADMIN without org membership cannot validate).
- Sidebar/topbar visibility goes through `ctx.can()` (cosmetic) and `hasOrg`
  (membership-driven for Organization Repositories).

### Backend surface relevant to the redesign (what is real)

- `PATCH /users/me` — updates **email / name / avatar_url** (profile editing IS
  supported). ⚠ `AuthService.updateProfile()` currently sends a camelCase
  `Partial<User>` body; the backend schema is snake_case, so `avatar_url`
  would be silently dropped — must be fixed before wiring a profile form.
- `GET /reviews` (page/per_page/status_filter) — **review history is supported**
  (org-scoped, dashboard only shows 5 rows). No dedicated reviews page exists.
- `GET /orgs`, `GET|PUT /orgs/{id}/settings`, `GET|PUT /platform/settings`,
  `GET|POST|DELETE /orgs/{id}/invitations`, `GET /invitations/{token}[/accept]`.
- **No endpoints**: org member list, org audit logs, org statistics, workspaces
  (layer removed in v0.6.0), email notifications, personal review preferences,
  PR diff. → those stay out or render honest "not available" notes.

### Problems found (the actual work)

1. `/settings` bundles personal + org + platform concerns; one profile field
   pretends to be editable (fake save — rule violation).
2. Sidebar groups everything under one "Settings" label; contains a duplicate
   dead link (`/platform-admin` alias) next to `/platform`.
3. Platform console mixes French labels into an English app and only 1 of 6
   mock pages honestly says it is a static prototype.
4. No reviewer home for cross-repo review history (`GET /reviews` unused as a page).
5. Org admin area has no identity of its own (reuses the personal settings nav,
   no overview, no clear selected-org context beyond the picker).
6. `SettingsNavComponent` mixes personal/org/platform destinations — personal
   settings navigation must not link org/platform admin.

## 2. Role ↔ capability matrix (Phase 2 deliverable)

Legend: ✅ allowed, ❌ blocked, 🔶 resource-level (backend decides per org/review).

| Capability (mechanism) | NONE | DEVELOPER | REVIEWER | ORG_ADMIN | PLATFORM_ADMIN |
|---|---|---|---|---|---|
| Read repositories/reviews/PRs (`read`) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Dashboard (`write`) | ❌ | ✅ | ✅ | ✅ | ✅ |
| Trigger/retry review (`write`) | ❌ | ✅ | ✅ | ✅ | ✅ |
| Dismiss/restore finding, edit summary, post staged review (`write` + staged review `viewer_role ≠ NONE`) | ❌ | 🔶 | 🔶 | 🔶 | 🔶 |
| Validate finding — confirm / false positive / needs investigation (`validate`: staged review `viewer_role ≥ REVIEWER`, **no platform bypass**) | ❌ | ❌ | 🔶 | 🔶 | 🔶 (needs membership) |
| Personal AI model config + test (`/settings/ai-model`, `write`) | ❌ | ✅ | ✅ | ✅ | ✅ |
| Profile edit (name/email via `PATCH /users/me`) | ❌ | ✅ | ✅ | ✅ | ✅ |
| Personal review preferences | ❌ | honest "not available" (no backend) — same for every role | | | |
| Org settings + invitations (`org:settings`, membership elevation) | ❌ | 🔶 (if ORG_ADMIN membership) | ❌ | ✅ | ✅ (global floor) |
| Org defaults/ceilings edit (`platform` + payload) | ❌ | ❌ | ❌ | ❌ | ✅ |
| Platform console (`platform`) | ❌ | ❌ | ❌ | ❌ | ✅ |
| Manage platform users | read-only (`GET /users` exists; **no update route** — no edit controls, honest note) | | | | |

Navigation visibility derives from this matrix via the existing
`AuthContextService.can()`; resource-level actions keep reading
`viewer_role` / per-org `role` from API responses.

## 3. Implementation steps

1. **Sidebar rework** (`sidebar.component.html/.spec`): grouped nav —
   *Main* (Dashboard, Repositories, Organization Repositories [membership-gated,
   kept for the dedicated org-member roles], Reviews [new]), *Personal*
   (Profile, Review Preferences, AI Model), *Organization* (Settings,
   Members & Invitations — `org:settings`), *Platform administration*
   (Platform console — `platform`; drop the dead `/platform-admin` link).
   Keep testids `nav-*`, drawer behavior, focus handling, active highlight.
2. **Routes** (`app.routes.ts` + spec): add `/reviews` (`read`),
   `/settings/profile`, `/settings/review-preferences`, `/settings/ai-model`
   (`write`), and `/settings` → redirect to `/settings/profile`
   (compatibility; checked all `/settings` link sites).
3. **Personal settings split**: new `features/settings/profile`,
   `features/settings/review-preferences`, `features/settings/ai-model`
   components; delete the old mixed `settings.component.*`.
   - Profile: identity (login, GitHub id, avatar) read-only with explanations +
     **real** `PATCH /users/me` for name/email (fix `AuthService.updateProfile`
     to send snake_case), 4-state + validation + 422 surfacing. Logout kept here.
   - Review preferences: honest "no backend" (disabled controls + notes), plus
     pointer that org-wide review policy lives in Organization Settings.
   - AI model: the existing working LLM form moved verbatim (save/test/reset,
     secret handling, precedence note).
   - `SettingsNavComponent` becomes personal-only (Profile · Review
     preferences · AI model); org/platform entries removed from it.
4. **Reviews page** (`features/reviews/review-list`): `GET /reviews` list with
   status filter + pagination, severity badge, staged/posted state; per-row
   *Open* resolves PR → repository through existing endpoints and navigates
   (no fabricated links; row-level loading/error states).
5. **Org workspace** (`org-settings.component`): own `OrgWorkspaceNavComponent`
   (Overview · Settings · Members & invitations via `?view=`), page header
   names the selected org + role; new Overview panel from real `GET /orgs` +
   `GET /orgs/{id}/settings` data; Members view gains an honest note that a
   member-list API does not exist yet (invitations remain the live record).
   Workspaces/Audit logs/Statistics are **not** added (no backend — documented).
6. **Reviewer experience** (`review-panel`): add a *History* tab listing every
   past run of this PR (data already fetched via
   `GET /pull-requests/{id}/reviews` — no extra request); label the verdict row
   ("Review verdict") so finding management is visually distinct from reading;
   keep all existing actions, testids, unsaved-changes guard, staged flow.
7. **Platform console** (`platform-admin-console*`): translate all French
   labels/copy to English (nav, pages, mocks, toasts), add one honest
   prototype banner driven by route data (`data.prototype` on mock children,
   never on the real overview), and a "Back to app" link so the shell-less
   console still reaches the main app. Remove `app-settings-nav` from the real
   overview (its own console nav suffices; no duplicate links).
8. **Docs/UX consistency pass**: topbar breadcrumbs for the new routes;
   dashboard checklist link points at `/settings/ai-model`.
9. **Tests**: update sidebar/settings-nav/org-settings/routes/console specs;
   new specs for profile, review-preferences, ai-model, review-list;
   run `npm run test:ci`, `lint`, `type-check`, `format:check`, `build` and fix
   regressions.

## 4. Explicit non-goals (honesty constraints)

- No fabricated audit logs, statistics, workspaces, member lists, scanner
  status, quota mutation, user-role mutation — the backend has none.
- `NONE` stays read-only; no role is widened to make a screen reachable.
- Monaco diff integration stays out of scope (documented gap; placeholder
  remains explicitly labeled as not available).
- No new design system — tokens (`styles/_tokens.scss`) only.

## 5. Status — COMPLETED (all gates green)

Every step below was implemented and verified; details of the verification run
are in §6.

### Completed work

1. **Sidebar reworked** (`sidebar.component.{html,ts,scss}`): four labelled
   groups — *Main* (Dashboard, Repositories, Organization Repositories
   [membership-gated — kept for the dedicated org-member roles], Reviews),
   *Personal* (Profile, Review Preferences, AI Model), *Organization*
   (Organization Settings, Members & Invitations), *Platform administration*
   (Platform Console). The dead `/platform-admin` alias link was removed;
   org entries highlight from the live `?view=` query.
2. **Routes** (`app.routes.ts`): `/reviews` (`read`), `/settings/profile`,
   `/settings/review-preferences`, `/settings/ai-model` (`write`),
   `/settings` → compatibility redirect to `settings/profile`.
3. **Personal settings split**: `features/settings/profile` (identity
   read-only + real `PATCH /users/me` for name/email; avatar/login/GitHub id
   shown as managed by GitHub), `features/settings/review-preferences`
   (honest no-backend panel + pointer to the org workspace),
   `features/settings/ai-model` (the working LLM form moved verbatim). The
   old mixed `settings.component.*` was **deleted** — including the
   "Name" input that silently discarded changes (the fake-save violation).
   `AuthService.updateProfile` was fixed to send the snake_case
   `email`/`name` body the backend schema actually accepts.
   `SettingsNavComponent` is now personal-only (Profile · Review
   preferences · AI model) with no org/platform links.
4. **Reviews page** (`features/reviews/review-list`): `GET /reviews` list
   with status filter + pagination, severity/posted/awaiting-post chips,
   expandable summary + run metadata, and a per-row *Open pull request*
   action that resolves PR → repository via `GET /pull-requests/{id}` +
   `GET /repositories/{id}` (both added as service methods — endpoints
   already existed) and navigates; failures stay visible on the row.
5. **Org workspace** (`org-settings.component.*`): own
   `OrgWorkspaceNavComponent` (Overview · Settings · Members & invitations,
   `?view=`), org picker + effective-role badge lifted into a shared context
   bar above every panel, page title per panel + selected org named in the
   subtitle, new **Overview** panel rendered from the same real payloads
   (`GET /orgs` + `GET /orgs/{id}/settings`), and an honest note that a
   member-list API does not exist yet. Workspaces / audit logs / statistics
   were **not** added (no backend — the workspace layer was removed in
   v0.6.0).
6. **Reviewer experience** (`review-panel.component.*`): new **History** tab
   (every past run from the already-fetched `GET /pull-requests/{id}/reviews`;
   status/date/duration/current-chip/failed error), verdict controls grouped
   under a visible "Review verdict" label so finding management is distinct
   from reading. All staged actions, `viewer_role` gating (developer vs
   reviewer), the unsaved-changes guard and the confirm dialog are unchanged.
   The PR page's "Changes" placeholder was rewritten as an honest
   not-available note linking to GitHub's files view.
7. **Platform console**: all six prototype pages translated to English
   (nav, page copy, mock data, toasts) — the app is English-only otherwise;
   an honest **prototype banner** renders on every mock page (route-URL
   driven, never on the real API-backed overview); toasts now say
   "(prototype — local only)"; the console topbar gained a "Back to app"
   link (the console renders without the app shell). The real overview
   dropped the mixed `app-settings-nav` (no duplicate links; the console's
   own sidebar provides navigation).
8. **Consistency**: topbar breadcrumbs for the new routes
   (Reviews; Settings/Profile|Review Preferences|AI Model; Organization
   view titles), dashboard checklist links to `/settings/ai-model`.
9. **Docs**: `docs/FRONTEND_SCREENS.md` (route + screen tables),
   `docs/FRONTEND_GAP_MATRIX.md` (`PATCH /users/me` now used; `GET /reviews`
   now serves the history page), `docs/BACKEND_GAPS_FOR_UI.md` (gaps 2 & 4
   reflect the new screens) updated.
10. **Tests**: sidebar/settings-nav/org-workspace-nav/org-settings/routes/
    role-guard/console-page/review-panel specs updated; new specs for
    profile, review-preferences, ai-model, review-list.

### Verification (actual results, from `frontend/`)

- `npm run type-check` — clean (app + spec tsconfigs).
- `npm run test:ci` — **562 SUCCESS, 0 failures** (was 567 before this
  change; the deleted mixed-settings spec's 14 cases were replaced by 34
  across the four new/updated suites).
- `npm run lint` — all files pass.
- `npm run format:check` — clean (after `npm run format`).
- `npm run build` — completes; only the pre-existing component-SCSS budget
  warnings (e.g. `review-panel.component.scss` was already 19.23 kB over
  before this change, 20.73 kB after — same warning class, no new category).
- Backend: **untouched** (this was a frontend-only task). The two service
  additions (`getPullRequestById`, `getRepositoryById`) call existing
  endpoints.

### Deployment (local k3s, runbook docs/ROLES_SETTINGS_RELEASE.md §6)

- Tag: `v0.6.0-simple-rbac` — the tag the working-tree manifests pin
  (`kubectl diff` on the rendered base was empty: manifests == cluster).
- Only the **frontend** image was rebuilt (backend/worker/semgrep-service/
  repo-tenant sources unchanged; their `v0.6.0-simple-rbac` images were
  already current and running).
- Pushed to `127.0.0.1:5000/codesage/frontend:v0.6.0-simple-rbac` —
  registry digest `sha256:7673208f…` → `sha256:6f9d6f6a…`.
- Same-tag gotcha applied: stale containerd ref evicted via the `ctr-evict`
  socket-mount pod (`runAsUser: 0`), then `rollout restart` — the new pod
  `codesage-frontend-5fb8d855d6-2ns5s` runs the exact pushed digest (2/2
  Running, 0 restarts).
- Smoke: the served `main-SNEII6K4.js` (via pod IP and the ingress-nginx
  NodePort chain) contains the new routes/nav markers
  (`settings/profile`, `settings/review-preferences`, `settings/ai-model`,
  `Platform administration`, `Review Preferences`,
  `Organization Repositories`).
- Note (pre-existing, unrelated to this rollout): direct port-80 on the
  node IP answers 404; the live entry is the ingress-nginx HTTP NodePort
  (31189), and the controller has been flapping (160 restarts).

### Genuine blockers / remaining gaps (unchanged by design)

- No backend for: personal review preferences, email notifications, org
  member lists, org audit logs, org statistics, workspaces (removed
  v0.6.0), PR diffs. All are either rendered as honest unavailable panels or
  omitted from navigation — never faked.
- `GET /users` is read-only for PLATFORM_ADMIN (no cross-user update route),
  so the real overview offers no edit controls; the prototype Users page is
  clearly labelled as local-only.
- The 12-check manual E2E table (docs/FRONTEND_SCREENS.md) remains pending
  test accounts; automated gates listed above all passed.
