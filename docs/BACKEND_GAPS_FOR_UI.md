# Backend Gaps for UI

Endpoints or capabilities the UI would need but the backend (v0.3.0) does not
expose. Rule: **never fake these in the frontend** — build what is possible,
list the gap here, ask before adding backend routes.

Source of truth for the surrounding audit: `docs/FRONTEND_GAP_MATRIX.md`.

**Status after plan Steps 0–12 (frontend v0.3.1):** every "UI built instead"
below shipped as described — the gaps are still open on the backend side and
would remove the documented workarounds if closed. Screens inventory:
`docs/FRONTEND_SCREENS.md`. The manual E2E table for v0.3.1 is **pending**
(deferred by decision; see `docs/FRONTEND_SCREENS.md` §Verification status).

---

## 1. Org members list — `GET /orgs/{org_id}/members`

- **Wanted by:** plan Step 7 (ORG_ADMIN members list: "if an endpoint exists,
  otherwise record the gap") and Step 9 (platform admin: "show orgs/members
  from the endpoints that exist").
- **What exists today:** `GET /orgs` returns only the **caller's** orgs with
  the caller's own `role`; `org_members` rows are never enumerated for anyone.
  The only visible membership signals are: your own role per org, invitation
  records (email/role/status), and `GET /users` (global user list with realm
  role — PLATFORM_ADMIN only, no org linkage).
- **UI built instead:** invitations screen (create/list/revoke) + the caller's
  own effective role. The members table is omitted, not stubbed.

## 2. User admin endpoints — `PATCH /users/{id}` / suspend

- **Wanted by:** plan Step 9 ("Read-only unless an update endpoint exists").
- **What exists today:** `PATCH /users/me` and `DELETE /users/me` (self only).
  `GET /users` + `GET /users/{id}` are PLATFORM_ADMIN reads; there is no
  cross-user update, role-assign, activate or suspend route.
- **UI built instead:** read-only user table for PLATFORM_ADMIN.

## 3. Per-org metrics — dashboard

- **Wanted by:** plan Step 10 ("per-org numbers for ORG_ADMIN").
- **What exists today:** `GET /reviews` is org-scoped as a whole (member sees
  all reviews of all their orgs; PLATFORM_ADMIN sees everything) but
  `ReviewResponse` carries **no org or repository field**, so a client cannot
  attribute a review to an org. `GET /repositories` rows carry
  `installation_id`, and `orgs.installation_id` exists server-side, but the
  repositories API never returns the org either.
- **UI built instead:** global review counts/status/severity + recent reviews
  (all derivable from `GET /reviews`), repo counts from `GET /repositories`.
  Per-org breakdown omitted.

## 4. Review-prefs / email-notification toggles (settings page)

- **Wanted by:** existing UI checkboxes on `features/settings` (auto-review,
  security scans, performance checks, email notifications).
- **What exists today:** nothing — `review_triggers`, `min_severity_to_post`
  etc. are **org** settings (`/orgs/{id}/settings`), and there is no email
  notification preference anywhere.
- **Shipped (plan Step 8):** the checkboxes render **disabled** with an
  explicit "Not available yet — …nothing here is saved." label (per section:
  preferences / email) and their decorative `checked` state was removed;
  nothing pretends to save.

## 5. Pull-request lookup by number — `GET /pull-requests/repository/{id}?number=`

- **Wanted by:** plan Step 2 (the PR-detail URL is `owner/repo/pulls/{n}`,
  but the backend keys pull requests by UUID only).
- **What exists today:** `GET /pull-requests/{uuid}` (detail) and
  `GET /pull-requests/repository/{repository_id}` (paginated list with
  `state`/`author` filters) — no by-number route.
- **UI built instead:** resolve owner/name → repo UUID (gap 6), scan the
  repo's PR list pages for the number (100 rows/page, capped at 30 pages =
  3 000 PRs), session-cache the id; not found (or past the cap) ends in a
  genuine backend 404 via a nil UUID so the interceptor shows the generic
  not-found page instead of a blank screen.
- **Suggested backend:** `GET /pull-requests/repository/{repository_id}/number/{number}`
  or a `?number=` query filter (true 404 when absent).

## 6. Exact repository lookup by owner/name — `GET /repositories/by-name/{owner}/{repo}`

- **Wanted by:** plan Step 2 (repository-detail, PR list and PR detail URLs
  carry `owner`/`repo`, while every repository route takes a UUID).
- **What exists today:** `GET /repositories?search=` is a fuzzy `ilike` on
  name/full_name and returns neighbours (`acme/api-v2` for `acme/api`).
- **UI built instead:** `search=owner/name&per_page=100` + an exact
  case-insensitive `full_name` match client-side, session-cached per
  repository; no match → genuine backend 404 via a nil UUID (rule 5:
  404 → generic not-found page, never a synthesized client error).
- **Suggested backend:** exact-match lookup endpoint that 404s directly.

## 7. Review status on PR list rows — `PullRequestResponse`

- **Wanted by:** the existing PR-list review badge (`pr.reviewStatus.status`).
- **What exists today:** list rows (`PullRequestResponse`) carry **no** review
  fields; only the detail (`PullRequestWithReviews`) adds `reviews_count`,
  `latest_review_id`, `latest_review_status`.
- **UI built instead:** list rows map `reviewStatus: null` (badge hidden —
  never a guess), the detail maps the pointer (`status` + `reviewId`, unknown
  vocabulary → `unknown`). Counts are not part of either shape (gap 8).

## 8. PR stats: comment/issue counts (derived from `GET /reviews/{id}`)

- **Wanted by:** plan Step 2 (stats bar on the PR detail page — the old UI
  read `reviewStatus.commentCount/issueCount`, fields no endpoint ever
  returned; the `ReviewSummary` stats schema in `backend/app/schemas/review.py`
  is dead code — no route serves it).
- **What exists today:** `PullRequestWithReviews` carries only
  `reviews_count`/`latest_review_id`/`latest_review_status`. The only real
  count source is `GET /reviews/{review_id}` → `comments_count` + the full
  `comments` list (the route returns **all** comments — no pagination, so
  `comments_count == len(comments)`).
- **UI built instead (agreed with the product owner):** the stats bar and the
  review panel share ONE cached `GET /reviews/{latest_review_id}` call per PR
  page load:
  - **Comments** = `comments_count` exactly as the API returns it.
  - **Open issues** = comments with `dismissed = false`, derived client-side,
    labelled "open issues" (the backend has no issue count).
  - Scan-report findings are never counted in either tile (different source)
    and the two sources are never summed. If the backend ever paginates
    `comments`, the list length stops being complete → "open issues" must
    render `n/a` instead.
  - Failure → tiles show `—` + a retry (never `0`; a zero only ever means a
    real zero); a 404 shows no partial stats (interceptor → not-found page);
    no review → no extra request at all.
  - Mutations (dismiss/restore/edit summary/post/validate) invalidate the
    shared cache so the tiles and the panel's own numbers update together.
- **Suggested backend:** add `comments_count` + `open_issues_count` (comments
  with `dismissed = false`) to `PullRequestWithReviews` — that would remove
  the extra request per PR page.

## 9. Scan enrichment on comments (OWASP / fix suggestion) + scan-report 404

- **Wanted by:** plan Step 3 (review-panel enrichment from
  `GET /reviews/{id}/scan-report`: `tools_failed` header, OWASP tags, fix
  suggestions, and scan findings no comment covers).
- **What exists today:** the comment enrichment columns (migration 015) carry
  `tool`, `rule_id`, `cwe`, `line_start/line_end`, `snippet`,
  `also_detected_by` — but **not** `owasp` or `fix_suggestion`; those live
  only on the scan-report findings. Also, the scan-report route 404s with
  two meanings: cross-organisation/unknown review ("Review not found") and
  an expected absence ("No scan report for this review" — reviews whose
  scans both failed, or pre-migration rows).
- **UI built instead:** the panel fetches the report in parallel with the
  review detail (failure-isolated), joins findings back to comments by
  source rule — `tool + rule_id + file_path`, line-first with a line-less
  fallback — and renders OWASP chips + the fix suggestion per comment;
  findings no comment covers are listed separately (capped at 50 rendered,
  exact count shown) and are never merged into the comments or the stats
  tiles. The frontend's ErrorInterceptor allows `…/scan-report` 404s to
  pass through (absence = no enrichment, no navigation); access is still
  guarded by `GET /reviews/{id}`. The join is heuristic: if a comment ever
  carries a shifted `line_number`, its enrichment is skipped rather than
  guessed.
- **Suggested backend:** add `owasp` + `fix_suggestion` to the comment
  enrichment columns (migration 015 follow-up), and return `200` with an
  empty report (or a distinct status) for "no scan yet" so absence and
  access-denied stop sharing `404`.

## 10. Review → PR page link — identifiers on `ReviewResponse`

- **Wanted by:** plan Step 10 (the dashboard's "recent reviews" section —
  rows should link to the PR detail page they belong to).
- **What exists today:** `ReviewResponse` carries only `pull_request_id`
  (UUID) — no repository owner/name and no PR number. Even resolving each
  row through `GET /pull-requests/{uuid}` (member-guarded, +1 call per row)
  would yield the number but still not the `owner/repo` URL segment, so a
  link would additionally need a repository lookup per row.
- **UI built instead:** recent-review rows render status, severity, relative
  time and the error text — non-clickable, rather than guessing a URL or
  issuing an N+1 lookup fan-out.
- **Suggested backend:** add `repository_full_name` + `pull_request_number`
  to `ReviewResponse` (both already known server-side at review creation).

---

## 11. Persist + expose `source_domain` on review comments

- **Wanted by:** UI redesign Step 7 — filter/chip for the **agent domain** that produced a
  finding ("Security agent", "Performance agent", …).
- **What exists today:** `source_domain` is only an **in-memory field** on the agent comment
  (`app/services/agents/schemas.py`, stamped in `review_orchestrator.py` for one run) and is
  used by the worker to scope matching. It is **not a DB column** (migration 015 added
  `tool/rule_id/cwe/line_start/line_end/snippet/also_detected_by` only) and is **not on
  `ReviewCommentResponse`**.
- **UI built instead:** the Findings tab filters by the real `category` field
  (`bug|security|performance|style|best_practice|general`), labelled "Category" — never
  relabelled as "agent".
- **Suggested backend:** add `review_comments.source_domain`, stamp it at persist time,
  expose it on `ReviewCommentResponse`.

## 12. Expose `comment.suggestion` on `ReviewCommentResponse`

- **Wanted by:** Step 7 finding card — a fix-suggestion block for comments that have no
  scan-report match.
- **What exists today:** `review_comments.suggestion` exists as a **model column** (added in
  migration 006) and agents fill it, but the API response never returns it, so the UI can
  only show `fix_suggestion` from the scan report (joined heuristically).
- **UI built instead:** fix suggestions render only when the scan report provides
  `fix_suggestion`; otherwise the block is omitted (never invented).
- **Suggested backend:** add `suggestion` to `ReviewCommentResponse`.

## 13. Changed-files list per PR — `GET /pull-requests/{id}/files`

- **Wanted by:** Step 7 "files with findings" summary table — ideally compared against the
  PR's changed files.
- **What exists today:** `PullRequestResponse`/`PullRequestWithReviews` carry only the
  `changed_files` **count**; no route lists the changed file paths (the `PRFileChange`
  schema is dead code — no route serves it).
- **UI built instead:** the table is explicitly labelled **"Files with findings"** (derived
  from review comments + scan findings), never "changed files".
- **Suggested backend:** serve a files list (the `PRFileChange` schema already exists) or
  add `changed_file_paths` to the PR detail.

## 14. Pipeline `stage` names on `GET /reviews/{id}/status`

- **Wanted by:** Step 7 pipeline stepper ("static analysis → agents → synthesis → posted").
- **What exists today:** `ReviewStatus` exposes `status` (pending/processing/completed/
  failed) and a **0–100 `progress` float** — no step names.
- **UI built instead:** a plain labelled progress bar with the real status vocabulary;
  duration is computed from `started_at`/`completed_at`.
- **Suggested backend:** add `stage: queued|static_analysis|agents|synthesis|posting`.

## 15. Org-wide pull-request list — `GET /pull-requests`

- **Wanted by:** app shell Step 3 — a "Pull requests" sidebar entry with a real list.
- **What exists today:** PRs are only listable per repository
  (`GET /pull-requests/repository/{repository_id}`); there is no org/global list and no
  `repository` attribution on `ReviewResponse`.
- **UI built instead:** the sidebar entry routes through repository selection
  ("Pull requests via repositories").
- **Suggested backend:** `GET /pull-requests` (org-scoped, paginated, same row shape).

## 16. Review statistics aggregation — `GET /reviews/stats`

- **Wanted by:** Step 5 dashboard — exact severity/status distribution over all reviews.
- **What exists today:** `GET /reviews` returns rows + a filtered `total`; severity
  distribution can only be computed client-side over the fetched page.
- **UI built instead:** bars computed from the **most recent 100 reviews**, labelled
  "severity of the most recent 100 reviews" — never presented as all-time.
- **Suggested backend:** `GET /reviews/stats?group_by=overall_severity|status` returning
  `{value: count}`.

## 17. Per-repository settings persistence + update route

- **Wanted by:** Step 6 repository detail "Settings" tab (`auto_review`,
  `review_on_push`, `notify_on_failure`, `max_files_per_review`).
- **What exists today:** `GET /repositories/{id}/detail` builds
  `settings=RepositorySettings()` — **always the schema defaults**, nothing persists them,
  and no route updates them. `PATCH /repositories/{id}` accepts only `enabled` /
  `default_branch`.
- **UI built instead:** the Settings tab edits only what the API really updates
  (`default_branch`; enable/disable via the existing routes). The `settings` block is shown
  read-only with an explicit "not configurable yet" note — toggles that cannot persist are
  never rendered as if they work.
- **Suggested backend:** persist per-repo settings + `PUT /repositories/{id}/settings`.

---

## Decisions / facts to confirm with the product owner

### LLM precedence (plan Step 8 — **confirmed**; wording shipped in the UI)

**Confirmed with the product owner during Step 8** and written into the
settings page as-is (`settings.component.html`,
`data-testid="llm-precedence"`): "Which model a review uses: the GitHub App
installation owner's personal model (set above) → the organization's AI model
→ the platform default. An organization can only contribute a model name — it
never changes your provider or API key — and its model applies only when the
installation owner has working personal credentials."

Code: `app/workers/review_processor.py` (`_effective_model`, review-time call
site) + `app/services/llm_client.py` (`resolve_llm_client`).

The rule as implemented:

1. **Model name:** per-user model (`PUT /settings/llm`) → org `ai_model`
   (`PUT /orgs/{id}/settings`) → platform default (`GROQ_MODEL`).
2. **Provider + API key are never overridden by the org** — the org can only
   contribute a _model name_; the personal provider/key decides which client
   is used.
3. If the installation owner has **no usable personal credentials** (no
   provider, or a provider with no stored key — except Ollama, which needs
   none), `resolve_llm_client` falls back to the **system default client** and
   the org `ai_model` is **not** consulted at all.
4. The LLM settings on the settings page belong to the signed-in user, but a
   review resolves the settings of the **GitHub App installation owner** —
   i.e. the personal config that matters is that user's, not necessarily the
   PR author's.

The confirmed UI wording above matches rule 1–3 as implemented; no open
questions remain in this section.
