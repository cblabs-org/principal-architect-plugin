---
schema_version: 1
charter:
  pr_id: PR-04
  programme_id: prog-principal-architect-plugin
  slug: pr-04-cockpit-auxpane-ui
  title: "Principal Architect Cockpit AuxPane sidecar (HTTP + SSE backend, UI) and install/uninstall scripts"
  branch: feat/pr-04-cockpit-auxpane-ui
  base_branch: feat/pr-03-vcs-bus-models-and-memory-modes
  depends_on:
    - PR-03
  allowed_modules:
    - daemon/sidecars/pa_cockpit/
    - daemon/workspace-plugin/principal-architect/scripts/cockpit.py
    - scripts/install.sh
    - scripts/uninstall.sh
    - README.md
    - tests/conftest.py
    - tests/test_cockpit_api.py
  required_skills: []
  verification_floor:
    - "pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py"
  charter_locked: true
  charter_hash: "2ac0917b9e8a4a0d1a85bded6036c555aebb2de04441ffd74c5d84038fc80559"
status: APPROVED
approved_at: "2026-10-16T23:01:30Z"
github_pr: null
work_orders:
  - id: WO-04.1
    slug: wo1-cockpit-backend-http-sse
    title: "Sidecar manifest and stdlib HTTP + SSE backend (cockpit.py)"
    complexity: architect
    status: COMPLETED
    attempts: 1
    commit_sha: "1580e760053977b20b5e944d78a5d1e45028c7fb"
  - id: WO-04.2
    slug: wo2-cockpit-ui
    title: "Cockpit AuxPane frontend (index.html, styles.css, app.js)"
    complexity: standard
    status: IN_PROGRESS
  - id: WO-04.3
    slug: wo3-install-uninstall-and-docs
    title: "Host install/uninstall scripts and user-facing README"
    complexity: mechanical
    status: PENDING
---

# PR-04 — Principal Architect Cockpit AuxPane UI & Installer

| | |
|---|---|
| **Programme** | [`prog-principal-architect-plugin`](../programme-principal-architect-plugin/PROGRAM.md) · [plan](../programme-principal-architect-plugin/PROGRAM-PLAN.md) |
| **Spec** | [`SPEC.md` v1.1](../../../../SPEC.md) §4.1 (install layout), §10.1–10.3 (Cockpit AuxPane sidecar, HTTP/SSE API, UI zones) |
| **Base → head** | `feat/pr-03-vcs-bus-models-and-memory-modes` → `feat/pr-04-cockpit-auxpane-ui` (WO branches: `pr-04-cockpit-auxpane-ui/woM-<topic>`) |
| **Part I owner** | Tier 1 Chief Architect (locked — amendments only via escalation to the Chief) |
| **Part II / III owner** | Tier 2 Principal Architect for PR-04 |

<!-- ======================================================================
     PART I — PR CHARTER (authored by the Tier 1 Chief Architect; locked via charter_hash)
     ====================================================================== -->

## 1. PR Charter: Scope, Goals, & Non-Goals

### 1.1 Scope

PR-04 delivers the **AuxPane UI visibility layer and host installation scripts** of `principal-architect-plugin`: `daemon/sidecars/pa_cockpit/sidecar.json`, the stdlib HTTP + Server-Sent Events (SSE) backend `daemon/workspace-plugin/principal-architect/scripts/cockpit.py`, the adaptive host-themed frontend `daemon/sidecars/pa_cockpit/ui/{index.html,styles.css,app.js}`, the one-command installer and uninstaller `scripts/install.sh` and `scripts/uninstall.sh`, the full user-facing `README.md`, and the comprehensive integration test suite `tests/test_cockpit_api.py`.

### 1.2 Goals

| # | Goal | Done when |
|---|---|---|
| **G1** | **`sidecar.json` & `cockpit.py` HTTP + SSE Backend (`SPEC.md §10.1–10.2`).** `daemon/sidecars/pa_cockpit/sidecar.json` registers `SIDECAR_UI_ENTRYPOINT_AUX_PANE` with `main: ["python3", "${PLUGIN_ROOT}/workspace-plugin/principal-architect/scripts/cockpit.py"]`, `restart_policy: "on_failure"`, `PYTHONPATH` set to `scripts/`, and **no** `agent_permissions`. `cockpit.py` runs a stdlib `ThreadingHTTPServer` binding `127.0.0.1` on `PORT` (or `0` ephemeral port), serves UI assets, and implements `GET /api/workspaces`, `GET /api/state`, `GET /api/events` (SSE), `POST /api/mode`, `POST /api/pr/approve-plan`, `POST /api/escalation/resolve`, `POST /api/pr/start`, `POST /api/wo/debug`, `POST /api/pr/graduate`, and `POST /api/sync`. | Every API route and the SSE stream are verified on a live ephemeral port in `tests/test_cockpit_api.py`. |
| **G2** | **Cockpit Frontend (`daemon/sidecars/pa_cockpit/ui/{index.html,styles.css,app.js}`) (`SPEC.md §10.3`).** `index.html` loads `/preload.js`, `/styles.css`, and `/app.js`. `styles.css` uses Antigravity host CSS variables (`--background`, `--foreground`, `--card`, `--border`, `--primary`, `--muted-foreground`). `app.js` binds `window.sidecar.onWorkspaceChange`, connects to `/api/events` (SSE), and renders Zone 1 (repo selector, `vcs_mode`/`memory_mode` badges, `[🔄 Sync]`, `[👀 Monitored]`/`[🤖 Autonomous]` toggle, Architect Model selector), Zone 2 (🔔 Human Attention Needed inbox with `[✅ Approve Plan]`, `[✅ Approve & Resume]`, `[❌ Deny]`, `[🔬 Launch Interactive Debug]`, `[🚀 Graduate PR]`), and Zone 3 (Programme → Stacked PR → Work Order DAG with `🔒 Charter by Chief`, status & receipt badges, `[💬 Jump to PA]`, `[👁️ Peek Worker]`, and `[🔬 Debug]` calling `window.sidecar.ui.toggleConversation`). | Static asset serving, DOM/CSS/JS contract checks, and `sidecar.json` schema checks pass in `tests/test_cockpit_api.py`. |
| **G3** | **Installer & Documentation (`scripts/install.sh`, `scripts/uninstall.sh`, `README.md`).** `scripts/install.sh` copies `daemon/` to `${PA_DAEMON_HOME:-$HOME/.gemini/config/plugins/pa-daemon}` while preserving any existing `state/registry.json`, sets executable permissions, and symlinks `${PA_BIN_DIR:-$HOME/.local/bin}/pa` to `<daemon_home>/workspace-plugin/principal-architect/scripts/pa_cli.py`. `scripts/uninstall.sh` removes the `pa` symlink and `<daemon_home>`. `README.md` documents the full architecture, installation, CLI reference, hook rules, memory modes, and Cockpit UI. | `tests/test_cockpit_api.py` runs `install.sh`, invokes the installed `pa --help` / `pa status --json`, verifies registry preservation on re-install, and runs `uninstall.sh` inside isolated `tmp_path` directories. |
| **G4** | **All six verification floors green & hygiene clean.** `pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py` passes from `./.venv`; `ruff check daemon tests` clean; zero I10 hygiene violations. | Cold-Firewall audit `APPROVED`. |

### 1.3 Non-Goals (explicitly out of scope for PR-04)

- Modifying any PR-01, PR-02, or PR-03 Python module (`common.py`, `schemas.py`, `state_db.py`, `pa_cli.py`, `escalation.py`, hooks, `vcs_sync.py`, `models.py`, `memory_grad.py`) — `cockpit.py` consumes them as a library / CLI.
- Self-enrollment of this repository and `v0.1.0` release tagging — **PR-05**.

## 2. Architectural Requirements, Cross-PR Interfaces, & Required Skills/Tools

### 2.1 Architectural requirements

| # | Requirement |
|---|---|
| **R1** | **Stdlib-only HTTP + SSE server (`cockpit.py`).** `cockpit.py` must use Python's standard library (`http.server.ThreadingHTTPServer`, `urllib.parse`, `json`, `threading`, `time`) with zero third-party web framework dependencies. It must expose a programmatic factory `create_server(host="127.0.0.1", port=0, *, daemon_home=None) -> ThreadingHTTPServer` so `tests/test_cockpit_api.py` can start and stop the server cleanly in a background thread on an ephemeral port. |
| **R2** | **Complete `GET /api/state` payload.** `GET /api/state?workspace=<path_or_uri>` must return a JSON object containing: `env` (`vcs_mode`, `memory_mode`, `execution_mode`, `architect_model`, `workspace_dir`, `repo_root`), `programmes`, `prs` (each PR with `charter_locked`, `charter_hash`, `pa_conversation_id`, `latest_audit`, and `work_orders` enriched with `receipt_id`, `tree_hash`, `subagent_id`, `attempts`, `complexity`, `required_skills`), `attention_queue` (open items sorted by `priority ASC, created_at ASC`), and `escalations` (open escalations). |
| **R3** | **Responsive SSE stream (`GET /api/events`).** Sends `Content-Type: text/event-stream`, `Cache-Control: no-cache`, and immediately flushes an initial `event: state\ndata: <json>\n\n` event upon connection, followed by periodic state-change checks (computing a lightweight fingerprint over `.state/state.db` mtime and workspace file mtimes) and heartbeat comments (`: keepalive\n\n`). Supports `?once=1` query parameter (which closes the stream after sending the initial `event: state` frame) for deterministic, non-hanging HTTP client tests while also supporting persistent streaming. |
| **R4** | **Mutation endpoints (`POST /api/*`).** All `POST` endpoints accept JSON bodies, validate required fields (`400` on missing/invalid parameters, `404` on unknown workspace/PR/WO/escalation), execute the corresponding state/CLI action, and return `200` with `{"ok": true, ...}` JSON (or `400`/`409`/`500` with `{"ok": false, "error": "..."}` on failure). `POST /api/escalation/resolve` supports `decision: "approve" | "deny"`; when approving a boundary expansion with `requested_files`, it appends missing `requested_files` to the target `WORKORDER.md`'s `allowed_files`, re-computes `spec_hash`, and marks both the escalation and any linked `attention_queue` item `RESOLVED`. |
| **R5** | **Sidecar & Frontend contract (`SPEC.md §10.1 & §10.3`).** `sidecar.json` must NOT include `agent_permissions`. `index.html`, `styles.css`, and `app.js` must use host CSS variables (`--background`, `--foreground`, `--card`, `--border`, `--primary`, `--muted-foreground`), load `/preload.js`, guard `window.sidecar` calls so standalone browsers/tests do not throw `TypeError`, and wire all three UI zones (`Zone 1` header/mode/model, `Zone 2` 🔔 Human Attention Needed inbox, `Zone 3` Programme → PR → WO DAG with `toggleConversation`). |
| **R6** | **Environment-isolatable `install.sh` & `uninstall.sh`.** Both scripts must honour `PA_DAEMON_HOME` (default `$HOME/.gemini/config/plugins/pa-daemon`) and `PA_BIN_DIR` (default `$HOME/.local/bin`) so tests can run them safely inside `tmp_path` without mutating the developer's real `$HOME`. `install.sh` must preserve `<PA_DAEMON_HOME>/state/` across upgrades/re-installs. |
| **R7** | **Hygiene (I10).** Zero internal identifiers, machine-specific absolute paths, or personal emails in any committed file, test fixture, or commit message. |

### 2.2 Cross-PR interfaces exported by PR-04 (stability contract)

| Module / Asset | Symbol / Path | Contract |
|---|---|---|
| `cockpit.py` | `create_server(host="127.0.0.1", port=0, *, daemon_home=None)`, `build_workspace_state(repo_root)`, `main(argv=None)` | HTTP + SSE sidecar backend consumed by `sidecar.json` and `tests/test_cockpit_api.py`. |
| `daemon/sidecars/pa_cockpit/` | `sidecar.json`, `ui/index.html`, `ui/styles.css`, `ui/app.js` | AuxPane sidecar manifest and frontend bundle installed into `<daemon_home>/sidecars/pa_cockpit/`. |
| `scripts/install.sh`, `scripts/uninstall.sh` | Shell installers honouring `PA_DAEMON_HOME` and `PA_BIN_DIR` | Consumed by users and by PR-05 dogfood installation. |

### 2.3 Required skills & tools

| Kind | Item | Notes |
|---|---|---|
| Runtime | `./.venv/bin/python` (Python 3.11+, stdlib `http.server`) | Provisioned in `./.venv`. |
| Test / lint | `./.venv/bin/pytest`, `./.venv/bin/ruff` | Verification floor runs all 6 test suites (`PR-01`..`PR-04`). |
| Shell | `bash` | Used to test `scripts/install.sh` and `scripts/uninstall.sh`. |

### 2.4 Delivery constraints for the Tier 2 PA

- Decompose into **3 sequential, single-writer Work Orders** (`wo1-cockpit-backend-http-sse`, `wo2-cockpit-ui`, `wo3-install-uninstall-and-docs`), each with a tight `allowed_files` subset of `allowed_modules` and the verification floor `pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py`.
- Spawn **exactly one Tier 3 Execution Worker per `WORKORDER.md`**; never execute Work Orders inline.
- Record the user's standing programme approval of Part II in this file (`status: APPROVED`, `approved_at`, and a dated line in §4) before spawning the first Worker.
- At Step 6A: fast-forward `feat/pr-04-cockpit-auxpane-ui` to the final WO tip, push to `origin`, open the GitHub PR with `--base feat/pr-03-vcs-bus-models-and-memory-modes --head feat/pr-04-cockpit-auxpane-ui`, record `github_pr` in `PROJECT.md`, and pause for the Cold-Firewall audit.

<!-- ======================================================================
     PART II — IMPLEMENTATION PLAN & WORK ORDER BREAKDOWN (authored by the Tier 2 Principal Architect)
     ====================================================================== -->

## 3. Implementation Plan & Work Order Breakdown

### 3.1 File-Level Architecture & Integration Design

1. **`daemon/sidecars/pa_cockpit/sidecar.json` (`SPEC.md §10.1`):**
   - Exact schema `v1` manifest registering `SIDECAR_UI_ENTRYPOINT_AUX_PANE` (`title: "Principal Architect Cockpit"`, `subtitle: "Programme, Stacked PRs, Work Orders & Escalation Queue"`), `main: ["python3", "${PLUGIN_ROOT}/workspace-plugin/principal-architect/scripts/cockpit.py"]`, `restart_policy: "on_failure"`, `env.PYTHONPATH: "${PLUGIN_ROOT}/workspace-plugin/principal-architect/scripts"`, and **no** `agent_permissions`.
2. **`daemon/workspace-plugin/principal-architect/scripts/cockpit.py` (`SPEC.md §10.2`):**
   - Stdlib-only `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler` binding `127.0.0.1` on `PORT` (or `0` ephemeral port), exposing `create_server(host="127.0.0.1", port=0, *, daemon_home=None) -> ThreadingHTTPServer`, `build_workspace_state(repo_root) -> dict[str, Any]`, and `main(argv=None) -> int`.
   - Serves UI assets (`index.html`, `styles.css`, `app.js`) from `daemon/sidecars/pa_cockpit/ui/` and provides a safe no-op `/preload.js` stub when accessed directly outside the Antigravity host proxy.
   - `GET /api/workspaces`: reads `Registry(daemon_home / "state" / "registry.json").list()` plus active workspace detection.
   - `GET /api/state?workspace=<path_or_uri>`: strips `file://` prefix via `common._strip_file_uri`, resolves `repo_root`, synthesizes `env` (`vcs_mode`, `memory_mode`, `execution_mode`, `architect_model`, `workspace_dir`, `repo_root`), `programmes`, `prs` (sorted by `pr_id`, enriched with `charter_locked`, `charter_hash`, `pa_conversation_id`, `latest_audit`, and per-WO `receipt_id`, `tree_hash`, `subagent_id`, `attempts`, `complexity`, `required_skills`), `attention_queue` (open items sorted `priority ASC, created_at ASC`), and `escalations` (open escalations).
   - `GET /api/events?workspace=<path_or_uri>[&once=1]`: sets `Content-Type: text/event-stream`, `Cache-Control: no-cache`, flushes initial `event: state\ndata: <json>\n\n` immediately, exits immediately if `once=1`, otherwise loops checking a lightweight mtime fingerprint over `.state/state.db` (`-wal` included) and workspace Markdown files (`PROGRAM.md`, `PROGRAM-PLAN.md`, `PROJECT.md`, `WORKORDER.md`, `AUDIT_ROUND_*.md`) to push `event: state` deltas and `: keepalive\n\n` comments.
   - `POST /api/mode`: validates `mode in ("monitored", "autonomous")` and optional `architect_model`, delegates to `pa_cli.main(["mode", mode, "--repo", ...])` and persists `architect_model` in `StateDB.set_config`.
   - `POST /api/pr/approve-plan`: calls `pa_cli.main(["pr", "approve-plan", "--pr", pr_id, "--by", approved_by, "--repo", ...])`.
   - `POST /api/escalation/resolve`: validates `escalation_id` and `decision in ("approve", "deny")`; when `decision == "approve"` and `requested_files` are present on a boundary escalation, appends missing paths to the target `WORKORDER.md`'s `spec.allowed_files`, updates `spec.spec_hash = compute_spec_hash(doc)`, dumps `WORKORDER.md`, and calls `pa_cli.main(["wo", "resolve", ...])` (which resolves both the escalation and any linked `attention_queue` rows). When `decision == "deny"`, calls `StateDB.resolve_escalation(escalation_id, status="DENIED")` and dequeues any linked `attention_queue` items as `DISMISSED`.
   - `POST /api/pr/start`, `POST /api/wo/debug`, `POST /api/pr/graduate`, `POST /api/sync`: delegate to the corresponding `pa_cli.main(...)` subcommands and return structured JSON results (`200` on success, `400`/`404`/`409` on validation or precondition errors).
3. **`daemon/sidecars/pa_cockpit/ui/{index.html,styles.css,app.js}` (`SPEC.md §10.3`):**
   - `index.html`: loads `/preload.js`, `/styles.css`, and `/app.js`, and defines semantic containers for Zone 1 (`#zone-header`), Zone 2 (`#zone-attention`), and Zone 3 (`#zone-dag`).
   - `styles.css`: uses Antigravity host theme CSS variables (`--background`, `--foreground`, `--card`, `--border`, `--primary`, `--muted-foreground`) with sensible fallbacks for standalone browser testing.
   - `app.js`: guards `window.sidecar?.onWorkspaceChange` and `window.sidecar?.ui?.toggleConversation`, connects to `/api/events` via `EventSource` with fallback `/api/state` fetch, and renders all interactive controls across Zone 1, Zone 2, and Zone 3.
4. **`scripts/install.sh`, `scripts/uninstall.sh`, and `README.md` (`SPEC.md §4.1`):**
   - `scripts/install.sh` & `scripts/uninstall.sh` honour `PA_DAEMON_HOME` (default `$HOME/.gemini/config/plugins/pa-daemon`) and `PA_BIN_DIR` (default `$HOME/.local/bin`), preserve `<PA_DAEMON_HOME>/state/` across upgrades, mark scripts `+x`, and manage the `pa` symlink.
   - `README.md` provides complete user-facing documentation covering architecture, installation, enrollment, dual-mode hooks, memory modes, Cockpit UI, and CLI reference.

### 3.2 Work Order Ledger

| WO ID | Slug & Branch | Base Branch | Complexity | Allowed Files | Summary | Status |
|---|---|---|---|---|---|---|
| **WO-04.1** | [`wo1-cockpit-backend-http-sse`](wo1-cockpit-backend-http-sse/WORKORDER.md)<br>`pr-04-cockpit-auxpane-ui/wo1-cockpit-backend-http-sse` | `feat/pr-03-vcs-bus-models-and-memory-modes` | `architect` | `daemon/sidecars/pa_cockpit/sidecar.json`, `daemon/workspace-plugin/principal-architect/scripts/cockpit.py`, `tests/conftest.py`, `tests/test_cockpit_api.py` | `sidecar.json` manifest + stdlib `ThreadingHTTPServer` HTTP/SSE backend (`cockpit.py`) implementing all 10 API endpoints and live ephemeral-port test suite. | `COMPLETED` (`1580e76`, `rcpt_124a60280b90`) |
| **WO-04.2** | [`wo2-cockpit-ui`](wo2-cockpit-ui/WORKORDER.md)<br>`pr-04-cockpit-auxpane-ui/wo2-cockpit-ui` | `pr-04-cockpit-auxpane-ui/wo1-cockpit-backend-http-sse` | `standard` | `daemon/sidecars/pa_cockpit/ui/index.html`, `daemon/sidecars/pa_cockpit/ui/styles.css`, `daemon/sidecars/pa_cockpit/ui/app.js`, `tests/test_cockpit_api.py` | Cockpit AuxPane frontend (`index.html`, `styles.css`, `app.js`) implementing Zone 1, Zone 2, and Zone 3 with host CSS variables, SSE binding, and `window.sidecar` integration + UI contract tests. | `IN_PROGRESS` |
| **WO-04.3** | [`wo3-install-uninstall-and-docs`](wo3-install-uninstall-and-docs/WORKORDER.md)<br>`pr-04-cockpit-auxpane-ui/wo3-install-uninstall-and-docs` | `pr-04-cockpit-auxpane-ui/wo2-cockpit-ui` | `mechanical` | `scripts/install.sh`, `scripts/uninstall.sh`, `README.md`, `tests/test_cockpit_api.py` | Environment-isolatable `install.sh` & `uninstall.sh` preserving `state/registry.json`, full user-facing `README.md`, and end-to-end installer tests in `tmp_path`. | `PLANNED` |

<!-- ======================================================================
     PART III — OUTCOME & GRADUATION SUMMARY (authored by the Tier 2 Principal Architect)
     ====================================================================== -->

## 4. Outcome & Session Log

- **2026-10-16T23:01:30Z — Part II Implementation Plan Approved:** Recorded user's standing programme-level autonomous execution authorization (`status: APPROVED`). Decomposed `PR-04` into 3 sequential single-writer Work Orders (`WO-04.1` `wo1-cockpit-backend-http-sse`, `WO-04.2` `wo2-cockpit-ui`, `WO-04.3` `wo3-install-uninstall-and-docs`).
- **2026-10-16T23:21:31Z — `WO-04.1` (`wo1-cockpit-backend-http-sse`) Completed:** Delivered `daemon/sidecars/pa_cockpit/sidecar.json` (`SIDECAR_UI_ENTRYPOINT_AUX_PANE`, zero `agent_permissions`), stdlib `CockpitHTTPServer` + `create_server` + `build_workspace_state` in `daemon/workspace-plugin/principal-architect/scripts/cockpit.py` implementing all 10 `GET`/`SSE`/`POST` routes, and live ephemeral-port tests in `tests/test_cockpit_api.py` (`119 passed`, `ruff check` clean, commit `1580e760053977b20b5e944d78a5d1e45028c7fb`, receipt `rcpt_124a60280b90`).
