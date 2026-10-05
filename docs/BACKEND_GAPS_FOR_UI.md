# Backend Gaps for UI

Endpoints or capabilities the UI would need but the backend (v0.3.0) does not
expose. Rule: **never fake these in the frontend** — build what is possible,
list the gap here, ask before adding backend routes.

Source of truth for the surrounding audit: `docs/FRONTEND_GAP_MATRIX.md`.

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
- **Decision (plan Step 8):** remove the fake checkboxes, or render them
  disabled with a "not available yet" label. They must not pretend to save.

---

## Decisions / facts to confirm with the product owner

### LLM precedence (plan Step 8 — confirm wording before it reaches the UI)

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

Pending confirmation: is the above the wording we want to show users
("your personal model wins; otherwise your organization's AI model; otherwise
the platform default — and your organization can never change your provider
or key")?
