---
schema_version: 1
charter:
  pr_id: PR-05
  slug: pr-05-dogfood-self-enrollment-and-release
  programme_id: prog-principal-architect-plugin
  title: "Dogfood self-enrollment, workspace migration, state reconciliation, and v0.1.0 release"
  branch: feat/pr-05-dogfood-self-enrollment-and-release
  base_branch: feat/pr-04-cockpit-auxpane-ui
  depends_on:
    - PR-04
  allowed_modules:
    - CHANGELOG.md
    - README.md
    - .gitignore
    - pyproject.toml
    - daemon/plugin.json
    - daemon/workspace-plugin/principal-architect/plugin.json
    - .agents/plugins/principal-architect-workspace/
    - .agents/skills/principal-architect-workspace/
    - tests/test_state_db_and_sync.py
  required_skills: []
  verification_floor:
    - "pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py"
  charter_locked: true
  charter_hash: "814b217d643808d255816fe07d98603c8df048a20ba2d133b847e536f608f457"
status: PLANNED
approved_at: null
github_pr: null
work_orders: []
---

# PR-05: Dogfood self-enrollment, workspace migration, state reconciliation, and v0.1.0 release

<!-- PART I — PR CHARTER (CHIEF ARCHITECT ONLY — LOCKED BY charter_hash) -->

## 1. Scope, Goals & Non-Goals (Charter — Chief Architect)

### 1.1 Purpose & Strategic Role in the Programme

`PR-05` (`pr-05-dogfood-self-enrollment-and-release`, Phase 5) is the final stacked PR in the 5-PR programme (`main` → `PR-01` → `PR-02` → `PR-03` → `PR-04` → `PR-05`). Now that all four implementation phases of `SPEC.md v1.1` have graduated (`PR-01` through `PR-04`), `PR-05` proves the plugin on its own repository (dogfooding the legacy workspace migration, `pa sync` state reconciliation, and `pa status --json` reporting across all 5 PRs) and prepares the `v0.1.0` release artifacts (`CHANGELOG.md` and release version metadata).

### 1.2 In-Scope Deliverables

1. **Self-Enrollment & Legacy Workspace Migration (`wo1-self-enroll-and-migrate`):**
   - Execute `scripts/install.sh` and `pa enroll .` against this repository using an isolated `PA_DAEMON_HOME` / `PA_BIN_DIR` so that `pa enroll` exercises its tracked `git mv` migration from `.agents/skills/principal-architect-workspace/` to `.agents/plugins/principal-architect-workspace/` and creates `.agents/plugins/principal-architect-workspace/.gitignore` (ignoring `.state/`).
   - Add `.agents/plugins/principal-architect-workspace/.state/` to root `.gitignore` as defensive coverage alongside the workspace `.gitignore`.
   - Remove the empty `.agents/skills` directory once migrated, and remove any untracked/gitignored runtime artifacts (`.agents/plugins.json`, `.agents/plugins/principal-architect-workspace/.state/`) after capturing verification output so zero machine-specific paths remain on disk.
   - Verify that all committed documents in `.agents/plugins/principal-architect-workspace/` (`PROGRAM.md`, `PR-01`..`PR-05` `PROJECT.md`s, all `WORKORDER.md`s, and `AUDIT-round-1.md`s) load and validate cleanly with `schemas.verify_charter_hash` and `schemas.verify_spec_hash`.
2. **State Reconciliation & Dogfood Verification Suite (`wo2-sync-and-reconcile`):**
   - Run `pa sync` and `pa status --json` against this repository (under an isolated `PA_DAEMON_HOME`) to verify that `state.db` reconciles all 5 PRs (`PR-01`..`PR-05`), all Work Order commit trailers (`PA-WorkOrder`, `PA-Verified-Hash`), and all Cold-Firewall audit commits (`PA-Audit-Verdict` + `AUDIT-round-1.md`).
   - Add a permanent dogfood test in `tests/test_state_db_and_sync.py` (`test_dogfood_self_enroll_sync_and_status_on_repo_workspace`) that copies the repository's committed `.agents/plugins/principal-architect-workspace/` into an isolated `tmp_repo`, runs `pa enroll`, `pa sync`, and `pa status --json`, and asserts that all 5 PRs (`PR-01`..`PR-05`), their Work Orders, and `charter_hash`/`spec_hash` locks are valid and reconciled.
3. **`v0.1.0` Release Artifacts (`wo3-release-v0-1-0`):**
   - Author `CHANGELOG.md` documenting the `v0.1.0` release across all 5 PRs (`PR-01` Schemas & Enrollment, `PR-02` Role Agents & Dual-Mode Hooks R1–R6, `PR-03` VCS Bus, Model Routing & Memory Modes, `PR-04` Cockpit AuxPane UI & Installer, `PR-05` Self-Enrollment & Dogfood Verification).
   - Verify and align version `0.1.0` across `pyproject.toml`, `daemon/plugin.json`, and `daemon/workspace-plugin/principal-architect/plugin.json`, and update `README.md` if needed to reference `.agents/plugins/principal-architect-workspace/`.

### 1.3 Explicit Non-Goals

- Do **not** alter any runtime behavior or schemas in `daemon/workspace-plugin/principal-architect/scripts/*.py` (`common.py`, `schemas.py`, `state_db.py`, `pa_cli.py`, `escalation.py`, hooks, `vcs_sync.py`, `models.py`, `memory_grad.py`, `cockpit.py`).
- Do **not** commit gitignored runtime state (`.state/state.db`, `.state/pa-skills.json`, `.state/pa-worker-rules.json`, `.agents/plugins.json`, or `daemon/state/registry.json`).
- Do **not** leave `.agents/plugins.json` or `.state/` on the working tree with host-specific absolute paths after verification.

## 2. Architectural Requirements & Cross-PR Interfaces (Charter — Chief Architect)

### 2.1 Normative Requirements

1. **Workspace Migration Integrity:**
   - Every file previously tracked under `.agents/skills/principal-architect-workspace/` must be moved to `.agents/plugins/principal-architect-workspace/` via `git mv` (exercised by `pa enroll .`), preserving all `charter_hash` and `spec_hash` values across `PR-01`..`PR-05`.
   - `common.workspace_dir(repo_root)` must resolve `<repo_root>/.agents/plugins/principal-architect-workspace`.
2. **Dogfood State Reconciliation (`pa sync` & `pa status --json`):**
   - `pa sync` and `pa status --json` must parse the migrated `.agents/plugins/principal-architect-workspace/` without errors and report `programme.programme_id == "prog-principal-architect-plugin"`, 5 PRs (`PR-01`..`PR-05`), and all committed Work Orders and Audits.
   - `tests/test_state_db_and_sync.py` must include a permanent automated test verifying `pa enroll` + `pa sync` + `pa status --json` + `verify_charter_hash` / `verify_spec_hash` across all PRs (`PR-01`..`PR-05`) in the repository's committed workspace.
3. **Release Metadata & Hygiene (Invariants I1, I2, I10):**
   - `CHANGELOG.md` must follow Keep a Changelog / Semantic Versioning format for `0.1.0` (`2026-10-16`).
   - `pyproject.toml`, `daemon/plugin.json`, and `daemon/workspace-plugin/principal-architect/plugin.json` must all carry `"version": "0.1.0"`.
   - Zero internal identifiers or machine-local paths (`google3`, `/usr/local/google`, `cl/`, `b/`, `go/`, `jetski`, `moma`, or `@google.com`) may appear anywhere in tracked or untracked files under `daemon/`, `scripts/`, `tests/`, `pyproject.toml`, `README.md`, `CHANGELOG.md`, or `.agents/`.

### 2.2 Allowed Modules & Verification Floor

- **Allowed Modules:**
  - `CHANGELOG.md`
  - `README.md`
  - `.gitignore`
  - `pyproject.toml`
  - `daemon/plugin.json`
  - `daemon/workspace-plugin/principal-architect/plugin.json`
  - `.agents/plugins/principal-architect-workspace/`
  - `.agents/skills/principal-architect-workspace/`
  - `tests/test_state_db_and_sync.py`
- **Verification Floor:**
  ```bash
  ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py && ./.venv/bin/ruff check daemon tests
  ```

<!-- PART II — IMPLEMENTATION PLAN & WORK ORDER BREAKDOWN (PRINCIPAL ARCHITECT) -->

## 3. Implementation Plan & Work Order Breakdown (Principal Architect)

*To be completed by the Tier 2 Principal Architect for PR-05.*

<!-- PART III — OUTCOME & SESSION LOG (PRINCIPAL ARCHITECT) -->

## 4. Outcome & Session Log (Principal Architect)

*To be completed by the Tier 2 Principal Architect for PR-05.*
