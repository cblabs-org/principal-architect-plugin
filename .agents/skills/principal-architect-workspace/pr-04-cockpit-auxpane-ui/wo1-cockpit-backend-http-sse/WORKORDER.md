---
schema_version: 1
wo_id: WO-04.1
pr_id: PR-04
title: Sidecar manifest (sidecar.json) and stdlib HTTP + SSE backend (cockpit.py)
complexity: architect
status: IN_PROGRESS
allowed_files:
- daemon/sidecars/pa_cockpit/sidecar.json
- daemon/workspace-plugin/principal-architect/scripts/cockpit.py
- tests/conftest.py
- tests/test_cockpit_api.py
forbidden_files:
- SPEC.md
- docs/positioning-paper.md
- .agents/skills/principal-architect-workspace/pr-04-cockpit-auxpane-ui/PROJECT.md
- .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
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
spec_hash: e2be44ce4c70512121e96d73c2721dc4e07bfcc8fbae85528790c691049af012
completion: null
---

# WO-04.1 — Sidecar Manifest (`sidecar.json`) & Stdlib HTTP + SSE Backend (`cockpit.py`)

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-04` (`pr-04-cockpit-auxpane-ui`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T23:01:30Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/sidecars/pa_cockpit/sidecar.json` (`SPEC.md §10.1`) and the stdlib-only HTTP + Server-Sent Events (SSE) backend `daemon/workspace-plugin/principal-architect/scripts/cockpit.py` (`SPEC.md §10.2`), together with comprehensive live ephemeral-port integration tests in `tests/test_cockpit_api.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/sidecars/pa_cockpit/sidecar.json`
  - `daemon/workspace-plugin/principal-architect/scripts/cockpit.py`
  - `tests/conftest.py`
  - `tests/test_cockpit_api.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-04-cockpit-auxpane-ui/wo1-cockpit-backend-http-sse/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT modify any PR-01..PR-03 Python module (`common.py`, `schemas.py`, `state_db.py`, `pa_cli.py`, `escalation.py`, hooks, `vcs_sync.py`, `models.py`, `memory_grad.py`). Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh` on the workspace repository. Commit only on the currently checked-out branch `pr-04-cockpit-auxpane-ui/wo1-cockpit-backend-http-sse` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R7):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file, test fixture, or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/sidecars/pa_cockpit/sidecar.json` (`SPEC.md §10.1` & Charter G1/R5):**
  Create `daemon/sidecars/pa_cockpit/sidecar.json` with the exact schema `v1` structure:
  ```json
  {
    "schema": "v1",
    "ui": {
      "entrypoint": "SIDECAR_UI_ENTRYPOINT_AUX_PANE",
      "title": "Principal Architect Cockpit",
      "subtitle": "Programme, Stacked PRs, Work Orders & Escalation Queue"
    },
    "main": [
      "python3",
      "${PLUGIN_ROOT}/workspace-plugin/principal-architect/scripts/cockpit.py"
    ],
    "restart_policy": "on_failure",
    "env": {
      "PYTHONPATH": "${PLUGIN_ROOT}/workspace-plugin/principal-architect/scripts"
    }
  }
  ```
  Ensure `agent_permissions` is **not** present anywhere in `sidecar.json`.

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/cockpit.py` (`SPEC.md §10.2` & Charter G1, R1–R4):**
  1. **Stdlib Server Factory (`create_server`, `CockpitHTTPServer`, `main`):**
     - Use only Python standard library modules (`http.server.ThreadingHTTPServer`, `http.server.BaseHTTPRequestHandler`, `urllib.parse`, `json`, `threading`, `time`, `os`, `sys`, `io`, `contextlib`, `pathlib.Path`) plus the sibling modules in `daemon/workspace-plugin/principal-architect/scripts/` (`common`, `schemas`, `state_db`, `models`, `pa_cli`, `vcs_sync`, `post_tool_receipt`).
     - Define `CockpitHTTPServer(ThreadingHTTPServer)` with `daemon_threads = True`, `allow_reuse_address = True`, `self.daemon_home: Path`, `self.ui_dir: Path`, and `self._pa_stop_sse: bool = False`. Override `server_close(self)` to set `self._pa_stop_sse = True` before calling `super().server_close()` so active SSE handler loops exit immediately on teardown.
     - Expose `create_server(host: str = "127.0.0.1", port: int = 0, *, daemon_home: str | Path | None = None) -> CockpitHTTPServer`:
       - Resolves `daemon_home` via `Path(daemon_home) if daemon_home is not None else common.daemon_home()`.
       - Resolves `ui_dir`: checks `Path(daemon_home) / "sidecars" / "pa_cockpit" / "ui"` first, falling back to `Path(__file__).resolve().parents[3] / "sidecars" / "pa_cockpit" / "ui"`.
       - Returns the bound `CockpitHTTPServer((host, port), CockpitRequestHandler)`.
     - Expose `main(argv: Sequence[str] | None = None) -> int`:
       - Reads `host = os.environ.get("HOST", "127.0.0.1")` and `port = int(os.environ.get("PORT", "0"))` (with optional `--host` and `--port` CLI flags).
       - Starts `server = create_server(host=host, port=port)`, prints `{"listening": f"http://{server.server_address[0]}:{server.server_address[1]}"}` with `flush=True`, and serves until `KeyboardInterrupt`.
  2. **Workspace Resolution & Static UI Asset Serving:**
     - Helper `_resolve_workspace(raw_workspace: str | None, daemon_home: Path) -> Path`:
       - Strips `file://` prefix via `common._strip_file_uri(raw_workspace)` when provided.
       - If omitted/empty, checks `os.environ.get("PA_DEFAULT_WORKSPACE")`, then the first enrolled entry in `state_db.Registry(daemon_home / "state" / "registry.json").list()`, then `common.find_repo_root(Path.cwd())`.
       - Resolves `real_root = Path(os.path.realpath(candidate))` and checks that `common.workspace_dir(real_root).is_dir()` (raising `LookupError` -> HTTP `404` JSON `{"ok": false, "error": "..."}` if not enrolled/found).
     - Serve static UI routes on `GET`:
       - `/` and `/index.html`: serve `<ui_dir>/index.html` (`Content-Type: text/html; charset=utf-8`) if it exists, or a minimal valid fallback HTML page (`<!doctype html><html><head><title>Principal Architect Cockpit</title></head><body></body></html>`) if `ui/index.html` has not been created yet.
       - `/styles.css`: serve `<ui_dir>/styles.css` (`Content-Type: text/css; charset=utf-8`) if it exists, else `/* cockpit styles */`.
       - `/app.js`: serve `<ui_dir>/app.js` (`Content-Type: application/javascript; charset=utf-8`) if it exists, else `// cockpit app`.
       - `/preload.js`: serve `<ui_dir>/preload.js` if present, else return `200` (`Content-Type: application/javascript; charset=utf-8`) with a safe no-op shim (`window.sidecar = window.sidecar || { onWorkspaceChange: function() {}, ui: { toggleConversation: function() {} } };`) so standalone browsers and tests never fail when not proxied by Antigravity.
  3. **State Synthesis (`build_workspace_state` & `GET /api/state` & `GET /api/workspaces`):**
     - `GET /api/workspaces`:
       - Reads `entries = state_db.Registry(daemon_home / "state" / "registry.json").list()`.
       - Determines `active_workspace` (first enrolled workspace or `PA_DEFAULT_WORKSPACE` if enrolled).
       - Returns `200` JSON: `{"ok": True, "workspaces": [e.to_dict() for e in entries], "active_workspace": active_workspace}`.
     - `build_workspace_state(repo_root: str | Path, *, daemon_home: str | Path | None = None) -> dict[str, Any]`:
       - Opens `StateDB(ws_dir / ".state" / "state.db")`.
       - Builds `env`:
         - `vcs_mode`: `db.get_config("vcs_mode") or "local"`
         - `memory_mode`: `db.get_config("memory_mode") or "builtin"`
         - `execution_mode`: `db.get_config("execution_mode") or "monitored"`
         - `architect_model`: `db.get_config("architect_model") or models.select_architect_model(repo_root=real_root)`
         - `architect_model_options`: `list(models.ARCHITECT_MODEL_PREFERENCE)`
         - `workspace_dir`: `str(ws_dir)`
         - `repo_root`: `str(real_root)`
       - Builds `programmes`: loads all `<ws_dir>/programme-*/PROGRAM.md` via `schemas.load_program`, returning dicts with `programme_id`, `slug`, `title`, `status` (`.value`), `vcs_mode`, `memory_mode`, `execution_mode`, `architect_model`, `prs`, `approved_at`, `created_at`.
       - Builds `prs`: loads all `<ws_dir>/pr-*/PROJECT.md` via `schemas.load_project`, sorted by `charter.pr_id`. For each PR:
         - Extracts `pr_id`, `programme_id`, `slug`, `title`, `branch`, `base_branch`, `depends_on`, `allowed_modules`, `required_skills`, `verification_floor`, `charter_locked`, `charter_hash`, `charter_valid` (`schemas.verify_charter_hash(proj_doc)`), `status` (`proj_doc.spec.status.value`), `approved_at`, `github_pr`.
         - Looks up `pa_conversation_id` from `db.get_config(f"pa_session:{pr_id}")` or the latest row in `sessions` where `pr_id = ? AND role IN ('pa', 'principal-architect', 'chief', 'chief-architect')`.
         - Looks up `latest_audit` from `db.get_config(f"latest_audit:{pr_id}")` (parsed JSON) or the highest `<pr_dir>/AUDIT-round-*.md` via `schemas.load_audit`.
         - Builds `work_orders`: merges `proj_doc.spec.work_orders` and any `<pr_dir>/wo*/WORKORDER.md` loaded via `schemas.load_workorder`. Each WO dict includes:
           `wo_id`, `id` (same as `wo_id`), `pr_id`, `slug`, `title`, `branch` (`f"{proj_doc.spec.charter.slug}/{slug}"`), `status`, `complexity`, `required_skills`, `allowed_files`, `verification_command`, `spec_hash`, `spec_valid`, `attempts`, `max_attempts`, `commit_sha`, `receipt_id`, `tree_hash`, `verified_at`, and `subagent_id` (resolved from `db.get_config(f"wo_session:{wo_id}")`, `sessions` table where `wo_id = ?`, or `completion`).
       - Builds `escalations`: `db.open_escalations()`.
       - Builds `attention_queue`: `db.list_open()` (already ordered by `priority ASC, created_at ASC`), enriching each item with `escalation` details (`trigger_code`, `reason`, `requested_files`, `pr_id`, `wo_id`) if `escalation_id` is linked.
       - Returns `{"ok": True, "env": env, "programmes": programmes, "prs": prs, "attention_queue": attention_queue, "escalations": escalations}`.
     - `GET /api/state?workspace=<path_or_uri>` returns `200` JSON with `build_workspace_state(repo_root, daemon_home=daemon_home)`.
  4. **Responsive SSE Stream (`GET /api/events`, Charter R3):**
     - Accepts `?workspace=<path_or_uri>` and optional `?once=1`.
     - Sends status `200` and headers `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `Connection: close` (if `once=1`) or `keep-alive`.
     - Immediately computes `state = build_workspace_state(repo_root, daemon_home=daemon_home)` and writes `f"event: state\ndata: {json.dumps(state)}\n\n".encode("utf-8")` followed by `self.wfile.flush()`.
     - If `once` in `("1", "true", "yes")`, returns immediately after flushing the initial `event: state` frame.
     - Otherwise loops while `not getattr(self.server, "_pa_stop_sse", False)`:
       - Sleeps in short intervals (~`0.1`–`0.25`s).
       - Computes a lightweight fingerprint `_workspace_fingerprint(repo_root, daemon_home)` over `<ws_dir>/.state/state.db` (`-wal` included), `<daemon_home>/state/registry.json`, and `<ws_dir>/**/*.md` `(str(p), stat.st_mtime_ns, stat.st_size)`.
       - When the fingerprint changes, recomputes `state` and flushes `event: state\ndata: <json>\n\n`.
       - Emits `: keepalive\n\n` every ~5 seconds when no state change has occurred.
       - Catches `(BrokenPipeError, ConnectionResetError, OSError)` and exits cleanly.
  5. **Mutation Endpoints (`POST /api/*`, Charter R4):**
     - Parse JSON request body (returning `400` `{"ok": False, "error": "Invalid JSON body"}` on malformed JSON).
     - `POST /api/mode`:
       - Accepts `{"workspace"?: str, "mode"?: "monitored" | "autonomous", "architect_model"?: str}`.
       - Validates that at least one of `mode` or `architect_model` is provided; if `mode` is provided, validates `mode in ("monitored", "autonomous")` (`400` otherwise). If `architect_model` is provided, validates it is a non-empty string (`400` otherwise).
       - Updates `execution_mode` (via `pa_cli.main(["mode", mode, "--repo", str(repo_root)])` or `StateDB.set_config` + `PROGRAM.md`) and/or `architect_model` (`db.set_config("architect_model", architect_model)` and `PROGRAM.md` `architect_model` field if present).
       - Returns `200` `{"ok": True, "execution_mode": ..., "architect_model": ...}`.
     - `POST /api/pr/approve-plan`:
       - Accepts `{"workspace"?: str, "pr_id": str, "approved_by"?: str}`.
       - Validates `pr_id` (`400` if missing).
       - Invokes `pa_cli.main(["pr", "approve-plan", "--pr", pr_id, "--by", approved_by, "--repo", str(repo_root)])` (capturing stdout/stderr). If `rc != 0`, returns `404` or `400` with `{"ok": False, "error": ...}`.
       - Also resolves any open `R1_MON_PLAN_APPROVAL` escalations and attention queue items for `pr_id` in `StateDB`.
       - Returns `200` `{"ok": True, "pr_id": pr_id, "status": "APPROVED", ...}`.
     - `POST /api/escalation/resolve`:
       - Accepts `{"workspace"?: str, "escalation_id": str, "decision": "approve" | "deny", "requested_files"?: list[str], "resolution_note"?: str}`.
       - Validates `escalation_id` and `decision in ("approve", "deny")` (`400` if missing/invalid).
       - Looks up `escalation_id` in `StateDB` (`SELECT * FROM escalations WHERE escalation_id = ?`); returns `404` if not found.
       - When `decision == "approve"`:
         - Determines `files_to_add = requested_files if requested_files is not None else json.loads(row["requested_files"] or "[]")`.
         - If `files_to_add` is non-empty and the escalation has a `wo_id`, finds the matching `WORKORDER.md` under `<ws_dir>`, appends any missing paths from `files_to_add` to `wo_doc.spec.allowed_files`, updates `wo_doc.spec.spec_hash = schemas.compute_spec_hash(wo_doc)`, and saves `WORKORDER.md` via `schemas.dump_document`.
         - Calls `pa_cli.main(["wo", "resolve", ...])` or directly marks the escalation `RESOLVED` in `StateDB`, dequeues any linked open `attention_queue` rows (`status="RESOLVED"`), and if the WO was `BLOCKED` or `ESCALATED_TO_PA`, restores WO status to `IN_PROGRESS`.
       - When `decision == "deny"`:
         - Marks the escalation `DENIED` via `db.resolve_escalation(escalation_id, status="DENIED")` and dequeues any linked open `attention_queue` rows (`status="DISMISSED"`).
       - Returns `200` `{"ok": True, "escalation_id": escalation_id, "decision": decision, "status": "RESOLVED" if decision == "approve" else "DENIED", "allowed_files": updated_allowed_files}`.
     - `POST /api/pr/start`:
       - Accepts `{"workspace"?: str, "pr_id": str, "conversation_id"?: str}`. Validates `pr_id` (`400` if missing).
       - Runs `pa_cli.main(["pr", "start", pr_id, "--repo", str(repo_root), ...])` and returns `200` with `{"ok": True, ...}` (or `404`/`409` on failure).
     - `POST /api/wo/debug`:
       - Accepts `{"workspace"?: str, "wo_id": str, "conversation_id"?: str}`. Validates `wo_id` (`400` if missing).
       - Runs `pa_cli.main(["wo", "debug", wo_id, "--repo", str(repo_root), ...])` and returns `200` with `{"ok": True, ...}` (or `404` if unknown WO).
     - `POST /api/pr/graduate`:
       - Accepts `{"workspace"?: str, "pr_id": str}`. Validates `pr_id` (`400` if missing).
       - Runs `pa_cli.main(["pr", "graduate", pr_id, "--repo", str(repo_root)])`. If blocked (e.g. `R6` audit not approved), returns `409` `{"ok": False, "error": ...}`; on success returns `200` `{"ok": True, ...}`.
     - `POST /api/sync`:
       - Accepts `{"workspace"?: str}` (or empty body).
       - Runs `vcs_sync.sync_state(repo_root)` (or `pa_cli.main(["sync", "--repo", str(repo_root)])`) and returns `200` `{"ok": True, "sync": ...}`.

- [ ] **`tests/test_cockpit_api.py` (and `tests/conftest.py` if needed):**
  Write comprehensive integration tests starting `cockpit.create_server(host="127.0.0.1", port=0, daemon_home=...)` on a live ephemeral port in a background thread and exercising via `urllib.request` / `http.client`:
  1. **`sidecar.json` contract (`SPEC.md §10.1`):**
     - Validates `schema == "v1"`, `ui.entrypoint == "SIDECAR_UI_ENTRYPOINT_AUX_PANE"`, `main` points to `cockpit.py`, `restart_policy == "on_failure"`, `env.PYTHONPATH` points to `scripts`, and `"agent_permissions" not in data`.
  2. **`GET /api/workspaces` & `GET /api/state` (`SPEC.md §10.2`):**
     - Verifies enrolled workspace discovery from `registry.json`.
     - Verifies `GET /api/state?workspace=file://...` strips `file://` and returns `env`, `programmes`, `prs` (with `charter_locked`, `charter_hash`, `pa_conversation_id`, `latest_audit`, and `work_orders` enriched with `receipt_id`, `tree_hash`, `subagent_id`, `attempts`, `complexity`, `required_skills`), `attention_queue` sorted by `priority ASC, created_at ASC`, and `escalations`.
  3. **`GET /api/events` SSE stream (`SPEC.md §10.2` & Charter R3):**
     - Verifies `Content-Type: text/event-stream`, immediate `event: state\ndata: ...` frame on connect (using `?once=1` and also testing live persistent SSE stream receiving a second `event: state` push when `state.db` / `PROJECT.md` changes).
  4. **All `POST` mutation endpoints (`SPEC.md §10.2` & Charter R4):**
     - `POST /api/mode`: switches `monitored` <-> `autonomous` and updates `architect_model`; rejects invalid mode with `400`.
     - `POST /api/pr/approve-plan`: transitions `PROJECT.md` to `APPROVED` while keeping `charter_hash` valid.
     - `POST /api/escalation/resolve`:
       - Approving a boundary escalation appends `requested_files` to `WORKORDER.md`'s `allowed_files`, recomputes valid `spec_hash`, marks the escalation `RESOLVED`, and dequeues the linked `attention_queue` item.
       - Denying an escalation marks it `DENIED` and dismisses the linked `attention_queue` item without altering `allowed_files`.
     - `POST /api/pr/start`: starts/claims a PR and records `pa_conversation_id`.
     - `POST /api/wo/debug`: pins the worker conversation and resolves the open escalation.
     - `POST /api/pr/graduate`: returns `409` when PR is not `AUDIT_APPROVED`, and returns `200` + graduates PR after `write_audit_round(..., verdict="APPROVED")`.
     - `POST /api/sync`: runs `sync_state` and returns synced counts.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the full verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py && ./.venv/bin/ruff check daemon tests
   ```
2. Update Part II `## Completion Report` of this `WORKORDER.md` (leaving Part I untouched so `spec_hash` remains valid), and run `./.venv/bin/python daemon/workspace-plugin/principal-architect/scripts/pa_cli.py wo verify WO-04.1` (or compute `post_tool_receipt.compute_tree_hash`, populate `status: COMPLETED` and `completion:` in frontmatter, and commit on `pr-04-cockpit-auxpane-ui/wo1-cockpit-backend-http-sse` with trailers `PA-WorkOrder: WO-04.1` and `PA-Verified-Hash: <tree_hash>`).
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report rather than filing issues directly.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

_Pending execution by Tier 3 Worker._
