# UI Redesign Plan — CodeSage frontend

**Status:** Steps 0–8 complete (`docs: ui redesign plan`, `feat(web): design tokens…`,
`shared ui primitives`, `application shell`, `public screens on design tokens`,
`dashboard walkthrough…`, `repositories`, `review walkthrough`, `settings walkthrough…`) —
gates green through 433 tests
**Branch:** `feat/ui-redesign` (from `feat/roles-org-settings-staged-reviews`, the current
release branch carrying frontend v0.3.1)
**Ground rules:** frozen palette · no backend changes · no fake data · no new runtime
dependencies · security rules unchanged (escaped text only, write-only LLM key) ·
one commit per step with `lint` + `type-check` + `format:check` + `test:ci` green
(+ `build` on style steps).

---

## 1. Route / screen / component inventory (Step 0 audit)

### 1.1 Routes → screens (from `app.routes.ts`, unchanged by this plan except Step 9's `/help`)

| Route                                      | Screen                                | Guard            | Component size (ts/html/scss)                    | Verdict                          |
| ------------------------------------------ | ------------------------------------- | ---------------- | ------------------------------------------------ | -------------------------------- |
| `/`                                        | landing                               | public           | 12/161/445 = **618**                             | rewrite (Step 4)                 |
| `/login`                                   | auth/login                            | public           | 31/41/147 = 219                                  | restyle (Step 4)                 |
| `/github/callback`                         | auth/github-callback                  | none             | 87/18/54 = 159                                   | keep, token restyle              |
| `/invite/accept`                           | invitations/invite-accept             | none             | 145/129/88 = 362                                 | keep logic, restyle              |
| `/dashboard`                               | dashboard                             | `WRITE_ROLES`    | 107/183/442 = **732**                            | rework (Step 5)                  |
| `/repositories`                            | repository-list                       | `ANY_ROLE`       | 187/185/465 = **837**                            | rework (Step 6)                  |
| `/repositories/:owner/:repo`               | repository-detail                     | `ANY_ROLE`       | 76/72/166 = 314                                  | rework (Step 6)                  |
| `/repositories/:owner/:repo/pulls`         | pr-list                               | `ANY_ROLE`       | 77/69/271 = 417                                  | rework (Step 6)                  |
| `/repositories/:owner/:repo/pulls/:number` | pr-detail (+ review-panel, diff-view) | `ANY_ROLE`       | 191/140/300 + **728/481/786 = 1 995** + 13/14/66 | walkthrough (Step 7)             |
| `/settings`                                | settings                              | `WRITE_ROLES`    | 241/229/353 = 823                                | rework (Step 8)                  |
| `/settings/org`                            | org-settings (+ org-invitations)      | `ADMIN_ROLES`    | **727**/219/365 = **1 311** + 380                | **split into sections** (Step 8) |
| `/platform`                                | admin/platform-admin                  | `PLATFORM_ROLES` | 106/118/127 = 351                                | restyle (Step 8)                 |
| `/not-found`, `**`                         | errors/not-found                      | —                | 20/12/0                                          | token restyle                    |
| `/forbidden`                               | errors/forbidden                      | —                | 19/12/0                                          | token restyle                    |
| `/help` (new)                              | help                                  | public/any-role  | —                                                | new (Step 9)                     |

Shared: `site-header` 63/74/153 = 290 (**replaced** by the app shell in Step 3),
`toast-container` 20/21/58, `loading` 48, `error` 33, `avatar` 30, `app` 21.

**Split flags (large components):**

- `review-panel` **1 995 lines** (+1 186-line spec) — monolithic: staged banner, run states,
  summary editor, findings, scan-only findings, verdict rows. → Step 7 restructures it into
  the walkthrough tabs while **keeping the existing logic, services and `data-testid`s**.
- `org-settings` **1 311 lines** (~700-line TS flagged by the brief) — → Step 8 splits the
  template/TS into section components: `ScannersSection`, `AgentsSection`, `LimitsSection`,
  `PostingSection`, `ModelSection` (child components, one parent that owns load/save).
- `repository-list` 837 / `settings` 823 / `dashboard` 732 — large but single-purpose;
  they get reworked in place, extracted child components only where a section repeats
  (cards/table toggle, checklist, KPI tiles).
- `landing` 618 (scss 445) — full rewrite in Step 4.

### 1.2 Test baseline (must stay green)

`test:ci` **338 SUCCESS** (33 spec files) · `lint` 0 errors / **1 pre-existing warning**
(`diff-view.component.ts` `no-explicit-any`) · `type-check` clean · `format:check` clean.
Spec files are updated only when the DOM truly changes, with the reason in the commit body.

### 1.3 Bundle baseline (before)

| Chunk                              | Raw                                  |
| ---------------------------------- | ------------------------------------ |
| Initial total                      | **436.79 kB** (transfer ≈ 121.71 kB) |
| `chunk-KI5GGYK4` (vendor/keycloak) | 255.23 kB                            |
| `main`                             | 67.82 kB                             |
| `chunk-UDXVDPIZ`                   | 66.67 kB                             |
| `polyfills`                        | 33.71 kB                             |
| `styles`                           | 3.84 kB                              |
| Largest lazy: pr-detail            | 57.10 kB                             |

Pre-existing build warnings: 6 component-SCSS budget warnings (4 kB budget), `js-sha256`
CommonJS warning. `dist/browser/assets` = 90 MB (monaco assets, unused — known gap).

---

## 2. Color inventory & contrast audit (palette = FROZEN)

Sources scanned: `src/styles/styles.scss`, `src/styles/_variables.scss`, every component
`.scss`, inline styles in `.ts`, and template attribute colors.

### 2.1 What the scan found

There are **two palettes** in the tree:

1. **Live palette — "CodeSage Terminal Aesthetic"** (dark). Defined in
   `src/styles/styles.scss` and hard-coded into 15 component SCSS files. This is what the
   user sees.
2. **Dead palette** — `src/styles/_variables.scss` (light blue `#0066cc`, GitHub grays …).
   **Imported nowhere** (verified: no `@import 'variables'` anywhere). Kept untouched as
   part of the inventory; candidates for deletion in Step 10 (dead-style cleanup).
3. **Legacy stragglers** — a few components still carry pre-redesign _light_ (Chakra) colors:
   `diff-view`, `toast-container`, `loading`/`error` shared components, parts of
   `review-panel` and `repository-detail`, and PR-state inline colors in `pr-detail.ts`.

### 2.2 Color inventory (distinct colors → token → contrast → verdict)

Contrast computed against WCAG 2.1 relative luminance. AA thresholds: **4.5** normal text,
**3.0** large text (≥18.66 px bold / 24 px) and non-text UI (borders/icons).

#### Live dark palette (styles.scss)

| Color                                      | Where used                                                                | Proposed token                                                                | On                    | Ratio                                                                          | Verdict                                  |
| ------------------------------------------ | ------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | --------------------- | ------------------------------------------------------------------------------ | ---------------------------------------- |
| `#0a0a0a`                                  | html/body bg (bg-primary); text-inverse on accent                         | `--surface-0` / `--text-inverse`                                              | —                     | 15.72 vs `#e5e5e5`                                                             | ✅                                       |
| `#111111`                                  | cards/panels (bg-secondary)                                               | `--surface-1`                                                                 | —                     | —                                                                              | ✅                                       |
| `#1a1a1a`                                  | inputs/wells (bg-tertiary)                                                | `--surface-2`                                                                 | —                     | —                                                                              | ✅                                       |
| `#222222`                                  | elevated menus (bg-elevated)                                              | `--surface-3`                                                                 | —                     | —                                                                              | ✅                                       |
| `#2a2a2a`                                  | hover (bg-hover) + border-default                                         | `--surface-hover` / `--border-strong`\*                                       | —                     | —                                                                              | ✅                                       |
| `#1e1e1e`                                  | border-subtle                                                             | `--border-subtle`                                                             | —                     | —                                                                              | ✅ (decorative)                          |
| `#3a3a3a`                                  | border-strong (buttons, scrollbar)                                        | `--border-control`                                                            | `#0a0a0a`             | 1.74                                                                           | ⚠️ see Q2 (interactive border <3.0)      |
| `#e5e5e5`                                  | text-primary                                                              | `--text-1`                                                                    | `#0a0a0a`             | **15.72**                                                                      | ✅ AA/AAA                                |
| `#a0a0a0`                                  | text-secondary, placeholders                                              | `--text-2`                                                                    | `#0a0a0a`             | **7.57**                                                                       | ✅ AA                                    |
| `#666666`                                  | **body paragraphs, nav links, labels, hints**                             | `--text-3` (current value)                                                    | `#0a0a0a` / `#1a1a1a` | **3.45 / 3.03**                                                                | ❌ **fails AA** (Q2)                     |
| `#444444`                                  | **placeholder text, counts, hints**                                       | — (needs a step)                                                              | `#141414`             | **1.89**                                                                       | ❌ **fails AA badly** (Q2)               |
| `#00e87b`                                  | accent / primary buttons / focus ring / success badges                    | `--accent`                                                                    | `#0a0a0a`             | **12.09**                                                                      | ✅                                       |
| `#00cc6d`                                  | accent hover                                                              | `--accent-hover`                                                              | `#0a0a0a`             | 9.29                                                                           | ✅                                       |
| `#00c96a`                                  | error-page accent (straggler variant)                                     | fold into `--accent-hover`                                                    | `#1a1a1a`             | 7.93                                                                           | ✅ (candidate to normalize)              |
| `#ffaa00`                                  | warning / `badge-warning`                                                 | `--warning`                                                                   | `#0a0a0a`             | **10.37**                                                                      | ✅                                       |
| `#ff4444`                                  | error / danger buttons                                                    | `--danger`                                                                    | `#0a0a0a`             | **5.81**                                                                       | ✅                                       |
| `#ff5555` `#ff5c5c` `#ff6666`              | per-component error text variants                                         | fold into `--danger` (or `--danger-text` mix)                                 | `#111111`             | 6.01/6.24/6.60                                                                 | ✅ (redundant steps)                     |
| `#00aaff`                                  | info / `badge-info`                                                       | `--info`                                                                      | `#0a0a0a`             | **7.72**                                                                       | ✅                                       |
| `#a855f7`                                  | purple badge                                                              | `--purple`                                                                    | `#0a0a0a` / `#1a1a1a` | 5.00 / **4.40**                                                                | ⚠️ fails AA on `--surface-2` (Q2)        |
| `#aa00ff`                                  | pr-detail/pr-list category chips                                          | `--purple-deep`                                                               | `#0a0a0a` / `#1a1a1a` | **3.92 / 3.44**                                                                | ❌ **fails AA** (Q2)                     |
| `#b188ff`                                  | pr-detail/pr-list category chips (text)                                   | `--purple-text`                                                               | `#0a0a0a`             | **7.39**                                                                       | ✅                                       |
| `rgba(…,0.06–0.3)` dims                    | badge/chip backgrounds over `--surface-1`                                 | `--accent-dim`, `--danger-dim`, `--info-dim`, `--warning-dim`, `--purple-dim` | composed              | text-on-dim: accent 9.67, warning 8.41, error 5.05, info 6.51, **purple 4.34** | ⚠️ purple-dim badge fails 4.5 (Q2)       |
| `#141414`, `#161616`, `#1f1f1f`, `#050505` | component-local surface steps (settings, landing, platform, review-panel) | fold into `--surface-1/2` steps                                               | —                     | —                                                                              | ✅ duplicate steps → normalize in Step 1 |
| `#999999`                                  | secondary text variant (pr-detail, repository-detail)                     | fold into `--text-2`                                                          | `#111111`             | 6.63                                                                           | ✅                                       |
| `#e0e0e0`                                  | heading variant                                                           | fold into `--text-1`                                                          | `#111111`             | 14.30                                                                          | ✅                                       |

\* `#2a2a2a` serves as both hover surface and default border today — tokens separate the
two roles (`--surface-hover`, `--border-strong`) with the same value.

#### Severity scale already in the app (review-panel `.sev-*` / `.scan-sev-*`)

| Severity                      | Current color | Token            | Contrast on `#1a1a1a` | Verdict                                  |
| ----------------------------- | ------------- | ---------------- | --------------------- | ---------------------------------------- |
| critical / error              | `#f56565`     | `--sev-critical` | 5.74                  | ✅                                       |
| high                          | `#ed8936`     | `--sev-high`     | 6.82                  | ✅                                       |
| medium / warning              | `#ecc94b`     | `--sev-medium`   | 10.79                 | ✅                                       |
| low / suggestion              | `#4299e1`     | `--sev-low`      | 5.70                  | ✅                                       |
| info                          | `#a0aec0`     | `--sev-info`     | 7.72                  | ✅                                       |
| (info badge border `#4a5568`) | —             | decorative       | 2.31                  | ⚠️ decorative only, text carries meaning |

All five are **existing shipped colors** and all pass AA — see **Q1** for the one decision
(keep vs unify with the terminal hues).

#### Legacy light-palette stragglers (all pre-existing; all render on light patches)

| Color                                                                      | Where                                 | Contrast                      | Verdict                                        |
| -------------------------------------------------------------------------- | ------------------------------------- | ----------------------------- | ---------------------------------------------- |
| `#f7fafc/#e2e8f0/#2d3748/#4a5568`                                          | `diff-view` light diff surface        | text 11.44                    | ✅ but off-theme (Step 7 reuses/restyles)      |
| `#2f855a` on `#c6f6d5` (diff add)                                          | `diff-view`                           | **3.79**                      | ❌ AA (Q2)                                     |
| `#c53030` on `#fed7d7` (diff del)                                          | `diff-view`                           | **4.15**                      | ❌ AA (Q2)                                     |
| `#c53030` on `#fed7d7` + `#718096` (error component)                       | `shared/error`                        | 4.15 / **3.04**               | ❌ AA (Q2)                                     |
| `#667eea` spinner on `#e2e8f0`                                             | `shared/loading`                      | decorative                    | ⚠️ off-theme (Step 2 restyle)                  |
| `#667eea` on `#edf2f7`                                                     | `repository-detail` legacy buttons    | **3.25**                      | ❌ AA (Q2)                                     |
| PR state: `#2f855a` open / `#c53030` closed / `#805ad5` merged / `#718096` | `pr-detail.ts` inline                 | **4.36 / 3.62 / 4.09 / 4.93** | ❌ first three fail AA (Q2)                    |
| `#f9fafb/#1f2937/#14532d/#7f1d1d/#1e3a5f`                                  | `toast-container` light toast         | 14.05 text                    | ✅ but off-theme (Step 2 restyle)              |
| `#ff5f56/#ffbd2e/#27c93f` on `#161616`                                     | landing "traffic lights" (decorative) | 6.05                          | ✅ decorative, may disappear in Step 4 rewrite |

### 2.3 Proposed token set (`src/styles/_tokens.scss`, Step 1)

All values are **existing colors** (or the same color reused under a role name). Tints/shades
beyond these are only ever produced by mixing existing colors (`color-mix()`), never new hues.

```
Surfaces   --surface-0 #0a0a0a   --surface-1 #111111   --surface-2 #1a1a1a
           --surface-3 #222222   --surface-hover #2a2a2a   --surface-sunken #050505
Borders    --border-subtle #1e1e1e   --border-strong #2a2a2a   --border-control #3a3a3a
Text       --text-1 #e5e5e5   --text-2 #a0a0a0   --text-3 #666666 (AA issue: Q2)
           --text-inverse #0a0a0a
Accent     --accent #00e87b   --accent-hover #00cc6d   --accent-dim (10% over surface-1)
Status     --success #00e87b   --warning #ffaa00   --danger #ff4444   --info #00aaff
           --purple #a855f7 (+ matching *-dim at 10%)
Severity   --sev-critical #f56565  --sev-high #ed8936  --sev-medium #ecc94b
           --sev-low #4299e1   --sev-info #a0aec0   (+ their dim backgrounds)
Spacing    4/8/12/16/24/32/48/64 (existing $spacing scale, +12 new step = same hue family)
Radius     2/4/6 (existing $radius-sm/md/lg) + 8/12 for cards (mix of existing steps)
Type scale 11/13/15/18/22/28/34 (existing sizes in use: 11,13,15 + rem headings)
Elevation  existing shadow-sm/md/lg (black alphas — unchanged)
Motion     100/200/300 ms + `prefers-reduced-motion` kill-switch
Z-index    base 0 · sticky 100 · sidebar 200 · drawer 300 · popover 400 · toast 500 · dialog 600
```

### 2.4 Severity scale — proposal (see **Q1**)

Two candidate scales, **both built only from existing colors**:

- **Option A (recommended) — keep the scale the app already ships** (review-panel):
  critical `#f56565` · high `#ed8936` · medium `#ecc94b` · low `#4299e1` · info `#a0aec0`,
  comment vocab mapped error→critical, warning→medium, suggestion→low, info→info.
  Monotonic, all AA-passing, zero visual churn on findings, no new hues.
- **Option B — unify onto the terminal hues**: critical/error `#ff4444` · high/warning
  `#ffaa00` · medium `#a855f7` · low `#00aaff` · info `#a0a0a0`. One color per word across
  the app, but "medium = purple" is unconventional and `#a855f7` needs a lighter mix on
  elevated surfaces.

Either way **color is never the only signal**: every severity renders icon + text label +
color (rule 9).

---

## 3. Information architecture (nav tree per role)

Routes and guards stay **unchanged** (Step 3 = presentation only). New: `/help` (Step 9)
and the default-landing fix for `NONE`.

```
Public
├── /                      Landing (Step 4) — CTA → /login
├── /login                 Login (Keycloak PKCE, idpHint github)
├── /invite/accept?token=  Invitation preview / accept (public)
├── /github/callback       GitHub App post-install (no guard)
└── /not-found · /forbidden

App shell (sidebar + top bar) — shown for any authenticated session
├── Home                   /dashboard   [can('write')]   ← default landing for write roles
│                          /repositories [NONE]          ← default landing for NONE (fix)
├── Repositories           /repositories                 [ANY_ROLE]
│   └── Pull requests      /repositories → repo → /:owner/:repo/pulls
│                          ("via repositories": there is no org-wide PR-list endpoint;
│                           proposal #15 would make a real /pull-requests entry possible)
├── Settings (group)
│   ├── AI model           /settings                     [can('write')]
│   ├── Organization       /settings/org                 [can('org:settings')]
│   │   └── sections: Scanners · AI agents · Limits · Posting · Model · Invitations
│   └── Platform           /platform                     [can('platform')] (separate group item)
└── Help                   /help                         [any role, public content]

Top bar: breadcrumbs · org switcher (if >1 org) · user menu (login, effective-role badge,
logout/switch account)
Mobile ≤768 px: sidebar collapses to a drawer (burger in top bar); tables → stacked cards.
```

Role visibility uses `AuthContextService.can()` only (`read | write | validate |
org:settings | platform`) — unchanged semantics, backend stays authoritative.

---

## 4. Page layouts (per screen)

### 4.1 Dashboard / home (Step 5)

1. **Setup checklist** (auto-hidden when complete): GitHub App installed
   (`GET /github/status → installed`), repositories connected+enabled (`GET /repositories`),
   personal LLM key (`GET /settings/llm → has_api_key`), org posting mode
   (`GET /orgs/{id}/settings → posting_mode`, admins only). Each item links to its screen.
2. **KPI tiles** (`—` on failure, never `0`): repositories total/enabled, reviews
   total/pending/completed/failed, awaiting approval — all from envelope `total`s.
3. **Severity distribution** — CSS/SVG bars of `overall_severity` (real field).
4. **Recent reviews** — status chip, severity, relative time, error text; rows are
   **non-clickable** (gap 10: no repo/number on `ReviewResponse`).
5. **Awaiting approval** callout when `status_filter=ready_to_post` returns rows.

### 4.2 Repositories (Step 6)

List: card/table toggle · search · enabled filter · status chip · enable/disable switch
(confirm dialog on disable and delete) · install/connect flow · empty state with CTA.
Detail: header from `GET /repositories/{id}/detail` (`total_prs`, `total_reviews`,
`default_branch`, `language`, `private`, `webhook_enabled`) + tabs **Pull requests** /
**Settings** (default branch editable via `PATCH /repositories/{id}`; `enabled` via the
existing enable/disable routes; the API's `settings` block is always-default and has no
update route → shown read-only or omitted, proposal #17). PR list: state + author filters,
pagination, clean rows, **no review badge on rows** (gap 7).

### 4.3 PR review walkthrough (Step 7)

```
Header   title #number · author · head→base branches · state chip · GitHub link
         size (+additions/−deletions/·files from PullRequestResponse) · review status badge
         [Re-review]  [Retry (failed, DEVELOPER+, confirm)]
Sticky   ready_to_post → "Awaiting your approval" + findings to post / dismissed
bar        + [Post…] (existing confirm dialog). auto mode → one-line explanation instead.
         posted → "Posted to GitHub <relative time>" + GitHub link.
Pipeline poll GET /reviews/{id}/status → progress bar (progress has no step names →
         plain bar, proposal #14); terminal state stops polling (backoff, unsubscribe on leave);
         completed → "Reviewed in {duration}" from started_at/completed_at.
Tabs     Overview · Findings · Static analysis   (ARIA tabs, arrow-key nav)
Overview summary (editable in staged mode, plain text otherwise) · stat tiles from the ONE
         shared GET /reviews/{id} · tools-failed banner
Findings filters severity / tool / category ("agent domain" blocked — source_domain is not
         exposed, proposal #11) / status open·dismissed·validated · search · group by file
         (collapsible, per-file counts, expand/collapse all) · files-with-findings summary
         table (labelled explicitly: NOT all changed files — proposal #13)
         finding card: severity strip+icon+label · tool chips · "detected by both SonarQube
         and Semgrep" (also_detected_by) · CWE/OWASP · message · line range · escaped snippet
         with line numbers · fix suggestion · verdict row (who/when/note) · "Human validated"
         · dismiss/restore
Static    scan-report only (never summed with comments): per-tool ran/failed/disabled,
analysis  counts labelled by source, summary.by_severity/by_tool.
```

### 4.4 Settings (Step 8)

Sub-navigation (in-page, no new routes): **AI model** (personal LLM, write-only key,
kept precedence copy verbatim) · **Organization** (section components: Scanners, AI agents,
Limits, Posting, Model — each with plain-language description, effective value,
inherited/overridden badge, ceiling, reset, inline 422) · **Members & invitations**
(role explanations, status badges; no members table — gap 1) · **Platform** (read-only
users/orgs as today). Not-available sections stay disabled with the explicit label.

### 4.5 Help (Step 9)

`/help`: pipeline SVG diagram · severity meanings · role table (from
`docs/ROLES_SETTINGS_RELEASE.md`) · staged vs automatic posting · how to invite ·
glossary (CWE, OWASP, false positive, dismissed vs validated). Contextual "?" popovers
reuse the shared copy constants.

---

## 5. Component list (Step 2 primitives, `shared/ui/`)

| Primitive                    | Variants / notes                                                                  | Spec                |
| ---------------------------- | --------------------------------------------------------------------------------- | ------------------- |
| `ui-button`                  | primary / secondary / ghost / danger + `loading` (disabled + spinner + aria-busy) | ✅                  |
| `ui-icon-button`             | icon-only, `aria-label` required                                                  | ✅                  |
| `ui-card`                    | surface + border, optional header/footer slots                                    | ✅                  |
| `ui-badge`                   | severity / status / tool / role chip (icon+text, never color alone)               | ✅                  |
| `ui-tabs`                    | ARIA tablist, arrow keys, panel ids                                               | ✅                  |
| `ui-segmented`               | 2–3 option toggle (card/table)                                                    | ✅                  |
| `ui-switch`                  | labelled, keyboard toggle                                                         | ✅                  |
| `ui-select` / `ui-input`     | label + help + error text wiring (`aria-describedby`)                             | ✅                  |
| `ui-table`                   | sortable-ish header, stacked-card mode ≤390 px                                    | ✅                  |
| `ui-empty`                   | icon + explanation + next action                                                  | ✅                  |
| `ui-skeleton`                | block/line variants, `prefers-reduced-motion`                                     | ✅                  |
| `ui-popover`                 | help "?" text, focus + ESC close                                                  | ✅                  |
| `ui-dialog`                  | focus trap, ESC, restore focus, `role="dialog"`                                   | ✅                  |
| `ui-banner`                  | info/warning/danger/success, dismissible                                          | ✅                  |
| `ui-stepper` / `ui-progress` | pipeline + setup checklist                                                        | ✅                  |
| `ui-stat-tile`               | value (`—` on null) + label + optional delta source note                          | ✅                  |
| `ui-kv`                      | key-value list (definitions)                                                      | ✅                  |
| `ui-code`                    | escaped text, line numbers, wrap toggle                                           | ✅                  |
| `ui-icon`                    | inline SVG set (original, ~20 glyphs, `currentColor`)                             | ✅                  |
| restyles                     | `toast`, `loading`, `error`, `avatar` onto the same tokens                        | existing specs stay |

---

## 6. Widget → endpoint → field table (rule 4)

Every number/badge/status rendered anywhere must appear here.

| Widget (screen)                                                         | Endpoint                                                  | Field(s)                                                                                                                                                                        |
| ----------------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Checklist: GitHub App installed (dashboard)                             | `GET /github/status`                                      | `installed`                                                                                                                                                                     |
| Checklist: repos connected (dashboard)                                  | `GET /repositories?per_page=1`                            | `total`                                                                                                                                                                         |
| Checklist: repos enabled (dashboard)                                    | `GET /repositories?enabled=true&per_page=1`               | `total`                                                                                                                                                                         |
| Checklist: personal LLM key (dashboard)                                 | `GET /settings/llm`                                       | `has_api_key`, `is_using_default`                                                                                                                                               |
| Checklist: org posting mode (dashboard, admins)                         | `GET /orgs/{org_id}/settings`                             | `posting_mode`, `overridden.posting_mode`                                                                                                                                       |
| KPI repositories total / enabled (dashboard)                            | `GET /repositories[?enabled=true]&per_page=1`             | `total`                                                                                                                                                                         |
| KPI reviews total / pending / completed / failed / awaiting (dashboard) | `GET /reviews[?status_filter=…]&per_page=1`               | `total`                                                                                                                                                                         |
| Severity distribution (dashboard)                                       | `GET /reviews?per_page=100`                               | `items[].overall_severity` (labelled "most recent 100"; proposal #16 for exact counts)                                                                                          |
| Recent reviews rows (dashboard)                                         | `GET /reviews?per_page=10`                                | `status`, `overall_severity`, `error_message`, `created_at`, `completed_at`, `posted_at`                                                                                        |
| Setup/empty states, install CTA (repositories)                          | `GET /github/status`, `GET /auth/github/app/install-url`  | `installed`, `url`                                                                                                                                                              |
| Repository cards/table (list)                                           | `GET /repositories`                                       | `full_name`, `enabled`, `language`, `default_branch`, `private`, `webhook_enabled`, `created_at`                                                                                |
| Repo detail header counts                                               | `GET /repositories/{id}/detail`                           | `total_prs`, `total_reviews`, `settings` (read-only), `default_branch`                                                                                                          |
| PR rows (list)                                                          | `GET /pull-requests/repository/{id}`                      | `number`, `title`, `state`, `author_login`, `created_at`, `additions`, `deletions`, `changed_files`                                                                             |
| PR header size (walkthrough)                                            | `GET /pull-requests/{id}`                                 | `additions`, `deletions`, `changed_files`, `base_branch`, `head_branch`, `state`                                                                                                |
| Review status badge / stats (walkthrough)                               | `GET /reviews/{id}` (shared single request)               | `status`, `overall_severity`, `comments_count`, `comments[]`, `viewer_role`, `posting_mode`, `posted_at`, `github_review_id`                                                    |
| Pipeline progress + duration                                            | `GET /reviews/{id}/status` (poll)                         | `status`, `progress`, `started_at`, `completed_at`, `error_message`                                                                                                             |
| Staged banner counts                                                    | `GET /reviews/{id}`                                       | `comments[].dismissed` (open = `dismissed=false`), `posting_mode`, `posted_at`                                                                                                  |
| Findings (tab)                                                          | `GET /reviews/{id}`                                       | `comments[]`: `severity`, `category`, `file_path`, `line_number`/`line_start`/`line_end`, `tool`, `rule_id`, `cwe`, `snippet`, `also_detected_by`, `dismissed`, `validations[]` |
| "Detected by both tools"                                                | `GET /reviews/{id}` (+ scan-report)                       | `comments[].also_detected_by`, scan `findings[].also_detected_by`                                                                                                               |
| OWASP chips + fix suggestion                                            | `GET /reviews/{id}/scan-report`                           | `findings[].owasp`, `findings[].fix_suggestion` (joined by tool+rule+file)                                                                                                      |
| Static analysis tab                                                     | `GET /reviews/{id}/scan-report`                           | `tools_run`, `tools_failed[]`, `summary.by_severity/by_tool`, `findings[]`                                                                                                      |
| "Human validated" / verdict row                                         | `GET /reviews/{id}`                                       | `comments[].validations[]`: `verdict`, `severity_override`, `note`, `reviewer_login`, `created_at`                                                                              |
| Retry failed review                                                     | `POST /reviews/{id}/retry`                                | request only                                                                                                                                                                    |
| Re-review                                                               | `POST /pull-requests/{id}/review`                         | `review_id`, `status`                                                                                                                                                           |
| Org settings sections                                                   | `GET/PUT /orgs/{id}/settings`                             | `overrides`, `effective`, `ceilings`, `overridden`                                                                                                                              |
| Platform defaults/ceilings                                              | `GET/PUT /platform/settings`                              | `defaults`, `effective_defaults`, `ceilings`, `hard_caps`                                                                                                                       |
| LLM model section                                                       | `GET/PUT/DELETE /settings/llm`, `POST /settings/llm/test` | `provider`, `model`, `base_url`, `has_api_key`, `is_using_default`                                                                                                              |
| Members/invitations                                                     | `GET/POST/DELETE /orgs/{id}/invitations`                  | `email`, `role`, `status`, `expires_at`                                                                                                                                         |
| Org switcher / role badge                                               | `GET /orgs`, `GET /auth/me`                               | `id`, `name`, `role`, `user.role`, `user.login`                                                                                                                                 |
| Platform users/orgs                                                     | `GET /users`, `GET /orgs`                                 | pagination + rows (read-only)                                                                                                                                                   |

**Deliberately not built** (no data source → proposals §7): changed-files list, agent-domain
filter, per-file review badges on PR rows, clickable dashboard review rows, global PR list,
exact severity aggregates.

---

## 7. Backend proposals (rule 5 — collected, NOT implemented)

New in this redesign (appended to `docs/BACKEND_GAPS_FOR_UI.md` §11–§17):

11. **Persist + expose `source_domain` on comments** — the Step-7 "agent domain" filter is
    impossible: the column does not exist (015 added only tool/rule/cwe/lines/snippet/
    also_detected_by), it is only an in-memory field in `review_orchestrator`. Fallback
    shipped: filter by the real `category` field (labelled "Category").
12. **Expose `comment.suggestion` on `ReviewCommentResponse`** — stored in the DB (model
    column) but never returned; comment-only findings therefore show no fix suggestion.
13. **Changed-files list per PR** (`GET /pull-requests/{id}/files`) — the "files with
    findings" table must be labelled "files with findings", not "changed files", because
    `PullRequestWithReviews` only carries the `changed_files` _count_.
14. **`stage` names on `GET /reviews/{id}/status`** (`queued → static-analysis → agents →
synthesis → posting`) — today only a 0–100 `progress` float exists, so the pipeline
    stepper ships as a plain progress bar.
15. **Org-wide PR list** (`GET /pull-requests`) — would let the sidebar "Pull requests"
    entry open a real list instead of routing through repository selection.
16. **Severity/status aggregation** (`GET /reviews/stats` or `?group_by=overall_severity`) —
    the dashboard distribution is computed from the most recent 100 rows and labelled so.
17. **Per-repository settings persistence + update route** — `GET /repositories/{id}/detail`
    returns a constant default `RepositorySettings()` and nothing can ever change it
    (`auto_review`, `max_files_per_review`, …); `PATCH` supports only `enabled`/
    `default_branch`.

Carried over (already documented): §1 members list, §2 user admin, §3 per-org metrics,
§7 PR-list review badge, §8 PR stats, §10 review → PR link, §5/§6 exact lookups.

---

## 8. Decisions (delegated: take the recommended option, record here)

The product owner delegated all open decisions ("do whatever is recommended"). Taken:

- **Q1 → Option A (keep the existing 5-color severity scale).** critical `#f56565`,
  high `#ed8936`, medium `#ecc94b`, low `#4299e1`, info `#a0aec0`; comment vocab maps
  error→critical, warning→medium, suggestion→low, info→info. Existing colors, all AA,
  no visual churn on findings.
- **Q2 → fix the pre-existing AA failures with mixes of existing colors only.** Every
  changed pair is listed below — nothing changes silently. New values are produced by
  mixing existing colors (Sass `mix()`), never a new hue:

  | Was (fails AA)                                           | Where                    | Becomes                                                                                                                                       | Why it is still "the same palette"                 |
  | -------------------------------------------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
  | `#666666` as body/label text (3.0–3.45)                  | global `--text-3`        | `#808080` = `mix(#a0a0a0, #666666)` on dark → 4.6+ on `#0a0a0a`–`#1a1a1a`                                                                     | midpoint of two existing neutrals                  |
  | `#444444` placeholder/hint text (1.89–2.03)              | inputs, counts           | same `--text-3` step                                                                                                                          | one muted step for all muted text                  |
  | `#aa00ff` chip text (3.44–3.92)                          | pr-detail/pr-list        | `#b188ff` (existing, 6.49–7.39)                                                                                                               | already a shipped color                            |
  | `#a855f7` on `--surface-2/3` (3.63–4.40)                 | purple badge on elevated | `--purple-text` = `#b188ff` on surfaces ≥`#1a1a1a`                                                                                            | same hue, lighter step already shipped             |
  | purple badge on purple-dim (4.34)                        | badges                   | text `#b188ff` on the same dim (6.5+)                                                                                                         | as above                                           |
  | `#2f855a`/`#c53030`/`#805ad5` PR-state chips (3.62–4.36) | pr-detail inline         | open→`#00cc6d` (shipped accent-hover, 9.02), closed→`#ff4444` (shipped danger, 5.81), merged→`#b188ff` (shipped, 7.39), default→`--text-2`    | all shipped palette colors, semantic fit unchanged |
  | `diff-view` add/del text (3.79/4.15)                     | diff rows                | darker/lighter mixes of `#2f855a`/`#c53030` with `#ffffff`/`#0a0a0a` until ≥4.5                                                               | same two hues                                      |
  | `shared/error` text (4.15/3.04)                          | error component          | tokenized onto dark: `--danger` on `--danger-dim`                                                                                             | component moves to the dark theme anyway           |
  | `repository-detail` `#667eea` on `#edf2f7` (3.25)        | legacy buttons           | `--accent`/`--purple-text` tokens (component restyles to dark)                                                                                | shipped colors                                     |
  | `--border-control #3a3a3a` vs `--surface-0` (1.74)       | interactive borders      | border uses `--text-3` step (`#808080`, 4.6) **only where the border is the sole affordance**; decorative separators stay `#1e1e1e`/`#2a2a2a` | mix of existing neutrals                           |

- **Q3 → no test accounts will be provided; best effort instead.** Public screens are
  captured (15 files). For authenticated screens the redesign is verified with the
  existing unit-test suites plus, where the local cluster allows it, headless captures
  against locally provisioned dev-only Keycloak users; anything still not capturable is
  listed as a known limitation in the final report (never skipped silently).
- **Q4 → keep the existing Google Fonts link.** "No external fonts or CDNs" applies to
  _new_ additions; removing Inter would be an unrequested visual change. Recorded as a
  pre-existing dependency in the final report.

---

## 9. Commit plan

| Step | Commit                                                       | Gate                                        |
| ---- | ------------------------------------------------------------ | ------------------------------------------- |
| 0    | `docs: ui redesign plan`                                     | docs only (this file + BACKEND_GAPS §11–17) |
| 1    | `feat(web): design tokens and base styles`                   | + `build`                                   |
| 2    | `feat(web): shared ui primitives`                            | + `build`                                   |
| 3    | `feat(web): sidebar app shell`                               | + `build`                                   |
| 4    | `feat(web): landing page that explains codesage`             | + `build`                                   |
| 5    | `feat(web): guided onboarding and dashboard`                 | + `build`                                   |
| 6    | `feat(web): repositories redesign`                           | + `build`                                   |
| 7    | `feat(web): pull request review walkthrough`                 | + `build`                                   |
| 8    | `feat(web): settings redesign with explanations`             | + `build`                                   |
| 9    | `feat(web): contextual help and how it works page`           | + `build`                                   |
| 10   | `chore(web): accessibility, responsive and performance pass` | + `build`                                   |
| 11   | `chore(web): release frontend v0.3.2`                        | cluster gates (user approval first)         |
| 12   | `docs: ui redesign`                                          | docs                                        |

---

## 10. Baseline (Step 0, verified before any change)

- Tests: `npm run test:ci` → **338 SUCCESS** (33 spec files), coverage 89.66 % statements.
- Lint: 0 errors, 1 pre-existing warning (`diff-view.component.ts`).
- Type-check: clean · Format: check clean.
- Bundle: initial **436.79 kB** raw / 121.71 kB transfer, styles 3.84 kB (§1.3).
- Before-screenshots (`docs/ui/before/`, Chrome headless, against the deployed v0.3.1 UI at
  `http://10.171.24.201`): `index`, `login`, `not-found`, `forbidden`, `github-callback`
  × 1440/1024/390 = **15 files**. Authenticated screens pending test accounts (Q3).
- Palette extracted (§2): 3 source groups, 22 live-palette colors + 5 severity colors +
  legacy stragglers, contrast computed for every text-bearing pair.
