---
schema_version: 1
wo_id: WO-04.2
pr_id: PR-04
title: Cockpit AuxPane frontend (daemon/sidecars/pa_cockpit/ui/{index.html,styles.css,app.js})
  and UI contract tests
complexity: standard
status: COMPLETED
allowed_files:
- daemon/sidecars/pa_cockpit/ui/index.html
- daemon/sidecars/pa_cockpit/ui/styles.css
- daemon/sidecars/pa_cockpit/ui/app.js
- tests/test_cockpit_api.py
forbidden_files:
- SPEC.md
- docs/positioning-paper.md
- .agents/skills/principal-architect-workspace/pr-04-cockpit-auxpane-ui/PROJECT.md
- .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
- daemon/workspace-plugin/principal-architect/scripts/cockpit.py
- daemon/workspace-plugin/principal-architect/scripts/common.py
- daemon/workspace-plugin/principal-architect/scripts/schemas.py
- daemon/workspace-plugin/principal-architect/scripts/state_db.py
- daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
- daemon/workspace-plugin/principal-architect/scripts/escalation.py
- daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py
- daemon/workspace-plugin/principal-architect/scripts/models.py
- daemon/workspace-plugin/principal-architect/scripts/memory_grad.py
required_skills: []
verification_command: ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py
  tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py
  tests/test_memory_modes.py tests/test_cockpit_api.py && ./.venv/bin/ruff check daemon
  tests
max_attempts: 5
max_structural_failures: 2
spec_hash: e008ea36ebaa5d052420c57c5be088ab126fea93ddd3fe7ee37c0a01a2444539
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: rcpt_42c8bdb73051
  commit_sha: 4a780c096a418945a8d44675d7aaece50049e499
  files_modified:
  - daemon/sidecars/pa_cockpit/ui/index.html
  - daemon/sidecars/pa_cockpit/ui/styles.css
  - daemon/sidecars/pa_cockpit/ui/app.js
  - tests/test_cockpit_api.py
  verification_summary: "120 passed in 47.16s; ruff check daemon tests: All checks passed!"
  out_of_scope_findings:
  - "Running pa_cli.py wo verify directly against an unenrolled repository creates .agents/skills/principal-architect-workspace/.state/state.db, which causes test_pa_status_synthetic_and_dogfood to fail until .state/state.db is removed."
  escalation_request: null
  decisions_made:
  - "Implemented semantic 3-zone HTML5 layout (Zone 1 #zone-header, Zone 2 #zone-attention, Zone 3 #zone-dag) in daemon/sidecars/pa_cockpit/ui/index.html loading /styles.css, /preload.js, and /app.js."
  - "Styled all Cockpit components in daemon/sidecars/pa_cockpit/ui/styles.css using the six Antigravity host theme CSS variables (--background, --foreground, --card, --border, --primary, --muted-foreground) with clean fallback defaults for standalone browser sessions."
  - "Implemented guarded window.sidecar.onWorkspaceChange and window.sidecar.ui.toggleConversation bindings, live EventSource('/api/events') streaming with /api/state fallback, and all 7 POST mutation actions in daemon/sidecars/pa_cockpit/ui/app.js."
  dead_ends: []
---

# WO-04.2 — Cockpit AuxPane Frontend (`index.html`, `styles.css`, `app.js`) & UI Contract Tests

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-04` (`pr-04-cockpit-auxpane-ui`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T23:01:30Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement the adaptive host-themed Principal Architect Cockpit AuxPane UI (`daemon/sidecars/pa_cockpit/ui/{index.html,styles.css,app.js}`) per `SPEC.md §10.3` and Charter G2/R5, and extend `tests/test_cockpit_api.py` with static asset serving and DOM/CSS/JS contract verification tests.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/sidecars/pa_cockpit/ui/index.html`
  - `daemon/sidecars/pa_cockpit/ui/styles.css`
  - `daemon/sidecars/pa_cockpit/ui/app.js`
  - `tests/test_cockpit_api.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-04-cockpit-auxpane-ui/wo2-cockpit-ui/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md` (in particular, do NOT modify `cockpit.py` or any Python module in `daemon/workspace-plugin/principal-architect/scripts/`). Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh` on the workspace repository. Commit only on the currently checked-out branch `pr-04-cockpit-auxpane-ui/wo2-cockpit-ui` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R7):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file, test fixture, or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/sidecars/pa_cockpit/ui/index.html` (`SPEC.md §10.3` & Charter G2/R5):**
  - Valid HTML5 document with `<title>Principal Architect Cockpit</title>`.
  - Loads `<link rel="stylesheet" href="/styles.css">`, `<script src="/preload.js"></script>`, and `<script src="/app.js" defer></script>`.
  - Defines semantic layout containers for the three Cockpit zones:
    1. **Zone 1 (`#zone-header` / `header.cockpit-header`)**:
       - Repository selector (`#workspace-select`), environment badges (`#badge-vcs-mode`, `#badge-memory-mode`), `[🔄 Sync]` button (`#btn-sync` calling `POST /api/sync`).
       - Execution Mode toggle (`#btn-mode-monitored` `[👀 Monitored]` and `#btn-mode-autonomous` `[🤖 Autonomous]` calling `POST /api/mode`).
       - Architect Model selector (`#architect-model-select` calling `POST /api/mode` with `architect_model`).
    2. **Zone 2 (`#zone-attention` / `section.attention-inbox`)**:
       - Header `🔔 Human Attention Needed` with open badge count (`#attention-count`).
       - Container `#attention-list` rendering open `attention_queue` items sorted by `priority ASC, created_at ASC`, with empty-state placeholder when zero items require attention.
    3. **Zone 3 (`#zone-dag` / `section.programme-dag`)**:
       - Header `Programme & Stacked PR DAG` with container `#dag-container` rendering Programme cards -> Stacked PR cards -> Work Order rows.

- [ ] **`daemon/sidecars/pa_cockpit/ui/styles.css` (`SPEC.md §10.3` & Charter G2/R5):**
  - Must reference and use all six Antigravity host theme CSS variables with clean default fallbacks on `:root`:
    - `--background`
    - `--foreground`
    - `--card`
    - `--border`
    - `--primary`
    - `--muted-foreground`
  - Provide responsive, compact AuxPane styling (`320px–520px` sidebar width friendly) for:
    - `.cockpit-header`, `.mode-toggle`, `.badge`, `.btn`, `.btn-primary`, `.btn-danger`
    - `.attention-inbox`, `.attention-card` (with priority P0/P1/P2 visual accents)
    - `.programme-card`, `.pr-card`, `.wo-row`, `.status-pill`, `.charter-badge`, `.receipt-badge`.

- [ ] **`daemon/sidecars/pa_cockpit/ui/app.js` (`SPEC.md §10.3` & Charter G2/R5):**
  - Guard all `window.sidecar` interactions so standalone browsers and tests never throw `TypeError`:
    - Bind `if (window.sidecar && typeof window.sidecar.onWorkspaceChange === "function") { window.sidecar.onWorkspaceChange((uri) => setActiveWorkspace(uri)); }`.
    - Provide helper `jumpToConversation(conversationId)` that calls `window.sidecar.ui.toggleConversation(conversationId)` when available.
  - Connect to `/api/events?workspace=<encoded>` via `new EventSource(...)`, listening for `addEventListener("state", ...)` to live-render state updates without page reloads, plus initial `/api/workspaces` and `/api/state` fetch fallback.
  - Implement action helpers calling `fetch(..., { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(...) })` for:
    - `POST /api/sync` (`[🔄 Sync]`)
    - `POST /api/mode` (`[👀 Monitored]` / `[🤖 Autonomous]` toggle and Architect Model `<select>` change)
    - `POST /api/pr/approve-plan` (`[✅ Approve Plan]`)
    - `POST /api/escalation/resolve` (`[✅ Approve & Resume]` with `decision: "approve"` and `requested_files`, and `[❌ Deny]` with `decision: "deny"`)
    - `POST /api/pr/start` (`[▶️ Start PR]`)
    - `POST /api/wo/debug` (`[🔬 Launch Interactive Debug]` / `[🔬 Debug]`, which calls `POST /api/wo/debug` and then `window.sidecar.ui.toggleConversation(conversationId)`)
    - `POST /api/pr/graduate` (`[🚀 Graduate PR]`)
  - Render **Zone 2 (`🔔 Human Attention Needed` inbox)** cards with action buttons matching `SPEC.md §10.3`:
    - Plan approval items (`APPROVE_PLAN` / `R1_MON_PLAN_APPROVAL`): `[✅ Approve Plan]` (`POST /api/pr/approve-plan`) and `[💬 Open PA Thread]` (`toggleConversation`).
    - Boundary expansion / escalation items (`EXPAND_ALLOWED_FILES` / `RESOLVE_ESCALATION`): file checkboxes (`requested_files`) + `[✅ Approve & Resume]` (`POST /api/escalation/resolve` `decision: "approve"`) and `[❌ Deny]` (`decision: "deny"`).
    - Worker circuit-breaker / blocker items (`DEBUG_WORKER` / `R3_REPEAT_FAILURE_CIRCUIT_BREAKER` / `R4_STRUCTURAL_BLOCKER`): `[🔬 Launch Interactive Debug]` (`POST /api/wo/debug` + `toggleConversation`).
    - Graduation items (`GRADUATE_PR` / `R6`): `[🚀 Graduate PR]` (`POST /api/pr/graduate`).
  - Render **Zone 3 (Programme -> Stacked PR -> Work Order DAG)**:
    - Programme header (`title`, `status`, `vcs_mode`, `memory_mode`, `execution_mode`).
    - Each Stacked PR card showing:
      - `pr_id`, `title`, `branch -> base_branch`, `status` badge
      - `🔒 Charter by Chief` badge (`charter_locked` / `charter_hash` prefix)
      - Latest audit verdict badge (`latest_audit.verdict` & round)
      - Action buttons: `[💬 Jump to PA]` (`toggleConversation(pr.pa_conversation_id)`), `[▶️ Start PR]` (`POST /api/pr/start`), `[✅ Approve Plan]` (when `PLANNED`), `[🚀 Graduate PR]` (enabled when `status === "AUDIT_APPROVED"`).
      - Nested Work Order rows showing `wo_id`, `title`, `status`, `complexity` badge, `required_skills` pills, attempt counter (`attempts/max_attempts`), cryptographic receipt badge (`receipt_id` / `tree_hash` short SHA), `[👁️ Peek Worker]` (`toggleConversation(wo.subagent_id)`), and `[🔬 Debug]` (`POST /api/wo/debug` + `toggleConversation`).

- [ ] **Extend `tests/test_cockpit_api.py` (Charter G2 & R5):**
  Keep all existing `WO-04.1` tests intact and add a new test function (e.g. `test_cockpit_frontend_assets_and_ui_contract`) verifying:
  1. `GET /`, `GET /index.html`, `GET /styles.css`, `GET /app.js`, and `GET /preload.js` all return `200` with expected `Content-Type` headers and serve the real files from `daemon/sidecars/pa_cockpit/ui/`.
  2. `index.html` includes `<script src="/preload.js"></script>`, `<link rel="stylesheet" href="/styles.css">`, `<script src="/app.js"`, and the 3 zone containers (`zone-header`, `zone-attention`, `zone-dag`).
  3. `styles.css` uses all required Antigravity host CSS variables (`--background`, `--foreground`, `--card`, `--border`, `--primary`, `--muted-foreground`).
  4. `app.js` binds `onWorkspaceChange`, `toggleConversation`, `EventSource` on `/api/events`, all 7 `POST` endpoints (`/api/mode`, `/api/pr/approve-plan`, `/api/escalation/resolve`, `/api/pr/start`, `/api/wo/debug`, `/api/pr/graduate`, `/api/sync`), and renders the `SPEC.md §10.3` UI labels (`🔔 Human Attention Needed`, `🔒 Charter by Chief`, `Approve Plan`, `Approve & Resume`, `Deny`, `Launch Interactive Debug`, `Graduate PR`, `Jump to PA`, `Peek Worker`).

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the full verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute `tree_hash = post_tool_receipt.compute_tree_hash(repo_root, doc.spec.allowed_files)`, update `WORKORDER.md` frontmatter (`status: COMPLETED`, `completion:`) and Part II `## Completion Report` (leaving Part I untouched so `spec_hash` remains valid), and commit on `pr-04-cockpit-auxpane-ui/wo2-cockpit-ui` with trailers `PA-WorkOrder: WO-04.2` and `PA-Verified-Hash: <tree_hash>`.
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report rather than filing issues directly.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

- **Status:** `COMPLETED` (attempt 1)
- **Receipt ID:** `rcpt_42c8bdb73051`
- **Tree Hash (`allowed_files`):** `42c8bdb7305122ef3ac2f28f211c6c9d2bced616fe7935d3d65d16b053ff77cb`
- **Files Modified:**
  - `daemon/sidecars/pa_cockpit/ui/index.html`
  - `daemon/sidecars/pa_cockpit/ui/styles.css`
  - `daemon/sidecars/pa_cockpit/ui/app.js`
  - `tests/test_cockpit_api.py`
- **Verification Summary:**
  - `./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py` -> `120 passed in 47.16s`
  - `./.venv/bin/ruff check daemon tests` -> `All checks passed!`
- **Decisions Made:**
  - Authored `daemon/sidecars/pa_cockpit/ui/index.html` with semantic containers for Zone 1 (`#zone-header`), Zone 2 (`#zone-attention`), and Zone 3 (`#zone-dag`), loading `/styles.css`, `/preload.js`, and `/app.js`.
  - Authored `daemon/sidecars/pa_cockpit/ui/styles.css` referencing all 6 Antigravity host theme CSS variables (`--background`, `--foreground`, `--card`, `--border`, `--primary`, `--muted-foreground`) with responsive `320px–520px` sidebar-friendly layout rules.
  - Authored `daemon/sidecars/pa_cockpit/ui/app.js` with guarded `window.sidecar` bindings (`onWorkspaceChange`, `ui.toggleConversation`), `EventSource("/api/events")` live state rendering, and interactive `fetch` handlers for all 7 `POST` endpoints (`/api/sync`, `/api/mode`, `/api/pr/approve-plan`, `/api/escalation/resolve`, `/api/pr/start`, `/api/wo/debug`, `/api/pr/graduate`).
  - Extended `tests/test_cockpit_api.py` with `test_cockpit_frontend_assets_and_ui_contract` verifying static asset serving and HTML/CSS/JS contracts.
- **Out-of-Scope Findings:**
  - Running `pa_cli.py wo verify` directly against an unenrolled repository creates `.agents/skills/principal-architect-workspace/.state/state.db`, which causes `test_pa_status_synthetic_and_dogfood` (`assert not (common.workspace_dir(this_repo) / ".state" / "state.db").exists()`) to fail on subsequent test runs until `.state/state.db` is removed.
- **Dead Ends:** None.
