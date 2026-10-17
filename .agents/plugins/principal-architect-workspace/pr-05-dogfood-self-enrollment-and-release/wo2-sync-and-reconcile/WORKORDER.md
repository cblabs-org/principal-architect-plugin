---
schema_version: 1
wo_id: WO-05.2
pr_id: PR-05
title: Live state reconciliation (pa sync & pa status --json) and automated dogfood
  suite
complexity: standard
status: PENDING
allowed_files:
- tests/test_state_db_and_sync.py
forbidden_files:
- SPEC.md
- docs/positioning-paper.md
- .agents/plugins/principal-architect-workspace/pr-05-dogfood-self-enrollment-and-release/PROJECT.md
- .agents/plugins/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
- daemon/workspace-plugin/principal-architect/scripts/common.py
- daemon/workspace-plugin/principal-architect/scripts/schemas.py
- daemon/workspace-plugin/principal-architect/scripts/state_db.py
- daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
- daemon/workspace-plugin/principal-architect/scripts/escalation.py
- daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py
- daemon/workspace-plugin/principal-architect/scripts/models.py
- daemon/workspace-plugin/principal-architect/scripts/memory_grad.py
- daemon/workspace-plugin/principal-architect/scripts/cockpit.py
required_skills: []
verification_command: ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py
  tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py
  tests/test_memory_modes.py tests/test_cockpit_api.py && ./.venv/bin/ruff check daemon
  tests
max_attempts: 5
max_structural_failures: 2
spec_hash: 9f0007935a96e583ea2bf13b967116992ef7485781cf8a55e0cf145e0c127627
completion: null
---

# WO-05.2 — Live State Reconciliation (`pa sync` & `pa status --json`) and Automated Dogfood Suite

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-05` (`pr-05-dogfood-self-enrollment-and-release`) — decomposition approved (`PROJECT.md` `status: IN_PROGRESS`, `approved_at: 2026-10-16T23:58:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Verify live state reconciliation (`pa enroll . --vcs-mode local_git`, `pa sync`, and `pa status --json`) against this repository's migrated `.agents/plugins/principal-architect-workspace/` (under an isolated temporary `PA_DAEMON_HOME`, cleaning up untracked runtime files afterward) and add a permanent automated dogfood test `test_dogfood_self_enroll_sync_and_status_on_repo_workspace` in `tests/test_state_db_and_sync.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `tests/test_state_db_and_sync.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/plugins/principal-architect-workspace/pr-05-dogfood-self-enrollment-and-release/wo2-sync-and-reconcile/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and Part II of this `WORKORDER.md`. Note: if running `pa sync` against the live repository updates `commit_sha` in any `pr-*/PROJECT.md`, restore those `PROJECT.md` files (`git checkout -- .agents/plugins/principal-architect-workspace/pr-*/PROJECT.md`) and remove `.agents/plugins.json`, `.agents/plugins/principal-architect-workspace/.state/`, and `/tmp/pa-dogfood-pr05-wo2` before running the test floor and committing. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md`.
- **Git & Shell constraints:** Do NOT run `git checkout` (to switch branches), `git switch`, `git branch`, `git push`, `git rebase`, or `gh`. Commit only on the currently checked-out branch `pr-05-dogfood-self-enrollment-and-release/wo2-sync-and-reconcile` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10):** Never leave `.agents/plugins.json` or `.agents/plugins/principal-architect-workspace/.state/` on disk after verification, and never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any committed file or commit message.

## 3. Line-Item Instructions

- [ ] **Step 1 — Execute live dogfood `pa enroll`, `pa sync`, and `pa status --json` against this repository:**
  1. Using an isolated `PA_DAEMON_HOME=/tmp/pa-dogfood-pr05-wo2/pa-daemon`, run:
     ```bash
     PA_DAEMON_HOME=/tmp/pa-dogfood-pr05-wo2/pa-daemon ./.venv/bin/python daemon/workspace-plugin/principal-architect/scripts/pa_cli.py enroll . --vcs-mode local_git --memory-mode builtin
     PA_DAEMON_HOME=/tmp/pa-dogfood-pr05-wo2/pa-daemon ./.venv/bin/python daemon/workspace-plugin/principal-architect/scripts/pa_cli.py sync .
     PA_DAEMON_HOME=/tmp/pa-dogfood-pr05-wo2/pa-daemon ./.venv/bin/python daemon/workspace-plugin/principal-architect/scripts/pa_cli.py status . --json
     ```
  2. Verify from the JSON output that:
     - `programmes[0]["programme_id"] == "prog-principal-architect-plugin"`
     - All 5 PRs (`PR-01`..`PR-05`) are present in `prs`
     - All Work Order commit trailers (`PA-WorkOrder`, `PA-Verified-Hash`) and Cold-Firewall audit commits (`PA-Audit-Verdict` + `AUDIT-round-1.md` for `PR-01`..`PR-04`) are reconciled into `.state/state.db`
  3. Clean up all untracked/gitignored runtime files and restore any `PROJECT.md` touched by `pa sync` so only `tests/test_state_db_and_sync.py` and this `WORKORDER.md` are modified:
     ```bash
     git checkout -- .agents/plugins/principal-architect-workspace/pr-*/PROJECT.md
     rm -rf .agents/plugins.json .agents/plugins/principal-architect-workspace/.state /tmp/pa-dogfood-pr05-wo2
     ```

- [ ] **Step 2 — Add `test_dogfood_self_enroll_sync_and_status_on_repo_workspace` in `tests/test_state_db_and_sync.py`:**
  Append `test_dogfood_self_enroll_sync_and_status_on_repo_workspace` to `tests/test_state_db_and_sync.py`:
  1. Locate `this_repo = Path(__file__).resolve().parent.parent` and `repo_ws = common.workspace_dir(this_repo)`. Assert `repo_ws == this_repo / common.NEW_WORKSPACE_REL`.
  2. Copy `repo_ws` into `tmp_repo / common.NEW_WORKSPACE_REL` via `shutil.copytree(repo_ws, tmp_repo / common.NEW_WORKSPACE_REL, ignore=shutil.ignore_patterns(".state"))`.
  3. Run `pa_cli.main(["enroll", str(tmp_repo), "--vcs-mode", "local_git", "--memory-mode", "builtin"]) == 0`.
  4. Run `pa_cli.main(["sync", str(tmp_repo)]) == 0` and capture the JSON summary from stdout (`synced_receipts >= 18`, `synced_audits >= 4`, `synced_wos >= 18`).
  5. Run `pa_cli.main(["status", str(tmp_repo), "--json"]) == 0` and parse the JSON payload:
     - Assert `payload["programmes"][0]["programme_id"] == "prog-principal-architect-plugin"`.
     - Assert `[p["pr_id"] for p in payload["prs"]] == ["PR-01", "PR-02", "PR-03", "PR-04", "PR-05"]`.
     - Assert that for `PR-01` through `PR-04`, `p["status"] == "GRADUATED"`, `p["charter_locked"] is True`, and `p["latest_audit"]["verdict"] == "APPROVED"`.
     - Assert that for `PR-05`, `p["charter_locked"] is True` and `len(p["work_orders"]) == 3`.
  6. Iterate over all committed `pr-*/PROJECT.md` files in `tmp_repo / common.NEW_WORKSPACE_REL` (`PR-01`..`PR-05`) and assert `schemas.verify_charter_hash(proj_md) is True`.
  7. Iterate over all committed `pr-*/wo*/WORKORDER.md` files in `tmp_repo / common.NEW_WORKSPACE_REL` (`PR-01`..`PR-05`) and assert `schemas.verify_spec_hash(wo_md) is True`.
  8. Also run `pa_cli.main(["status", str(this_repo), "--json"]) == 0` directly against `this_repo` and assert `[p["pr_id"] for p in live_payload["prs"]] == ["PR-01", "PR-02", "PR-03", "PR-04", "PR-05"]` and that `(repo_ws / ".state" / "state.db").exists() is False`.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the full verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute `tree_hash = post_tool_receipt.compute_tree_hash(repo_root, doc.spec.allowed_files)`, update `WORKORDER.md` frontmatter (`status: COMPLETED`, `completion:`) and Part II `## Completion Report` (leaving Part I untouched so `spec_hash` remains valid), and commit `tests/test_state_db_and_sync.py` and `WORKORDER.md` on `pr-05-dogfood-self-enrollment-and-release/wo2-sync-and-reconcile` with trailers `PA-WorkOrder: WO-05.2` and `PA-Verified-Hash: <tree_hash>`.
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report rather than filing issues directly.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

_Pending execution._
