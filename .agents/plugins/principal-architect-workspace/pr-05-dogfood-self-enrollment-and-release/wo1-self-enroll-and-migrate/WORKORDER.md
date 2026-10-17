---
schema_version: 1
wo_id: WO-05.1
pr_id: PR-05
title: Self-enrollment and legacy workspace migration (.agents/skills -> .agents/plugins)
complexity: standard
status: COMPLETED
allowed_files:
- .gitignore
- .agents/skills/principal-architect-workspace/
- .agents/plugins/principal-architect-workspace/
- tests/test_state_db_and_sync.py
forbidden_files:
- SPEC.md
- docs/positioning-paper.md
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
spec_hash: 1ad583000245bbe6891d913544c6aac89965f539fd209b14fc8942a23acb0ed7
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: rcpt_0b1f0c3a6d7a
  commit_sha: null
  files_modified:
  - .gitignore
  - .agents/plugins/principal-architect-workspace/
  - tests/test_state_db_and_sync.py
  verification_summary: "121 passed in 54.65s; ruff check daemon tests: All checks passed!; verified 1 PROGRAM.md, 5 PROJECT.md charter_hash locks, 21 WORKORDER.md spec_hash locks, and 4 AUDIT-round-1.md reports under .agents/plugins/principal-architect-workspace"
  out_of_scope_findings: []
  escalation_request: null
  decisions_made:
  - "Executed scripts/install.sh and pa enroll . --memory-mode builtin --vcs-mode local_git in an isolated temporary directory (/tmp/pa-dogfood-pr05) to exercise tracked git mv migration from .agents/skills/principal-architect-workspace/ to .agents/plugins/principal-architect-workspace/ and create .agents/plugins/principal-architect-workspace/.gitignore."
  - "Removed the empty .agents/skills directory and cleaned up untracked .agents/plugins.json, .agents/plugins/principal-architect-workspace/.state/, and /tmp/pa-dogfood-pr05 so zero host-specific paths remain on disk."
  - "Added .agents/plugins/principal-architect-workspace/.state/ to root .gitignore and updated test_workspace_dir_dogfood() in tests/test_state_db_and_sync.py to assert common.workspace_dir(repo_root) == repo_root / common.NEW_WORKSPACE_REL and not (repo_root / common.LEGACY_WORKSPACE_REL).exists()."
  dead_ends: []
---

# WO-05.1 — Self-Enrollment & Legacy Workspace Migration (`.agents/skills` -> `.agents/plugins`)

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-05` (`pr-05-dogfood-self-enrollment-and-release`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T23:58:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Dogfood `scripts/install.sh` and `pa enroll .` on this repository using an isolated temporary daemon/bin root so that `pa enroll` exercises its tracked `git mv` migration from `.agents/skills/principal-architect-workspace/` to `.agents/plugins/principal-architect-workspace/`, creates `.agents/plugins/principal-architect-workspace/.gitignore` (containing `.state/`), adds `.agents/plugins/principal-architect-workspace/.state/` to root `.gitignore`, updates `test_workspace_dir_dogfood` in `tests/test_state_db_and_sync.py`, cleans up all untracked/gitignored runtime artifacts so zero host-specific absolute paths remain on disk, and verifies that all committed `PROGRAM.md`, `PROJECT.md`, `WORKORDER.md`, and `AUDIT-round-1.md` files pass `schemas.verify_charter_hash` and `schemas.verify_spec_hash`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `.gitignore`
  - `.agents/skills/principal-architect-workspace/`
  - `.agents/plugins/principal-architect-workspace/`
  - `tests/test_state_db_and_sync.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (which starts at `.agents/skills/principal-architect-workspace/pr-05-dogfood-self-enrollment-and-release/wo1-self-enroll-and-migrate/WORKORDER.md` and moves to `.agents/plugins/principal-architect-workspace/pr-05-dogfood-self-enrollment-and-release/wo1-self-enroll-and-migrate/WORKORDER.md` after `git mv`).
- **Forbidden:** Do NOT edit any Python runtime module under `daemon/workspace-plugin/principal-architect/scripts/*.py`. Do NOT modify `PROGRAM.md`, any `PROJECT.md`, any `AUDIT-round-1.md`, or Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh`. Commit only on the currently checked-out branch `pr-05-dogfood-self-enrollment-and-release/wo1-self-enroll-and-migrate` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10):** Never leave `.agents/plugins.json`, `.agents/plugins/principal-architect-workspace/.state/`, or `/tmp/pa-dogfood-pr05` on disk after verification, and never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any committed file or commit message.

## 3. Line-Item Instructions

- [ ] **Step 1 — Execute `scripts/install.sh` and `pa enroll .` in an isolated temporary directory:**
  Run:
  ```bash
  PA_DAEMON_HOME=/tmp/pa-dogfood-pr05/pa-daemon PA_BIN_DIR=/tmp/pa-dogfood-pr05/bin bash scripts/install.sh
  PA_DAEMON_HOME=/tmp/pa-dogfood-pr05/pa-daemon PA_BIN_DIR=/tmp/pa-dogfood-pr05/bin /tmp/pa-dogfood-pr05/bin/pa enroll . --memory-mode builtin --vcs-mode local_git
  ```
  Verify that:
  1. `pa enroll .` executed `git mv .agents/skills/principal-architect-workspace .agents/plugins/principal-architect-workspace`.
  2. `.agents/plugins/principal-architect-workspace/.gitignore` exists and contains `.state/`.
  3.Remove the empty `.agents/skills` directory if left behind (`rmdir .agents/skills 2>/dev/null || true`).
  4. Remove the untracked/gitignored runtime files created by `pa enroll` and the temporary install directory so zero machine-specific paths remain on disk:
     ```bash
     rm -rf .agents/plugins.json .agents/plugins/principal-architect-workspace/.state /tmp/pa-dogfood-pr05
     ```

- [ ] **Step 2 — Update root `.gitignore`:**
  Append `.agents/plugins/principal-architect-workspace/.state/` to root `.gitignore` under `# Dynamic configuration & state`.

- [ ] **Step 3 — Update `test_workspace_dir_dogfood` in `tests/test_state_db_and_sync.py`:**
  In `tests/test_state_db_and_sync.py` (around line 102), update `test_workspace_dir_dogfood()` so it verifies that `common.workspace_dir(repo_root)` resolves to the migrated `.agents/plugins/principal-architect-workspace` directory:
  ```python
  def test_workspace_dir_dogfood() -> None:
      """Verify workspace_dir on this repository resolves to the migrated plugins workspace."""
      repo_root = common.find_repo_root(Path(__file__).resolve())
      assert repo_root is not None
      ws = common.workspace_dir(repo_root)
      assert ws.exists()
      assert ws == repo_root / common.NEW_WORKSPACE_REL
      assert not (repo_root / common.LEGACY_WORKSPACE_REL).exists()
  ```

- [ ] **Step 4 — Verify `common.workspace_dir` and all committed `charter_hash` & `spec_hash` locks:**
  Run a Python one-liner from `./.venv/bin/python` verifying that:
  - `common.workspace_dir(repo_root) == repo_root / ".agents/plugins/principal-architect-workspace"`
  - `PROGRAM.md` loads via `schemas.load_program`
  - Every `pr-*/PROJECT.md` (`PR-01`..`PR-05`) loads via `schemas.load_project` and passes `schemas.verify_charter_hash(p) is True`
  - Every `pr-*/wo*/WORKORDER.md` (including `WO-05.1`) loads via `schemas.load_workorder` and passes `schemas.verify_spec_hash(w) is True`
  - Every `pr-*/AUDIT-round-1.md` (`PR-01`..`PR-04`) loads via `schemas.load_audit`

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the full verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py && ./.venv/bin/ruff check daemon tests
   ```
2. Confirm that `.agents/plugins.json` and `.agents/plugins/principal-architect-workspace/.state/` do NOT exist on disk.
3. Compute `tree_hash = post_tool_receipt.compute_tree_hash(repo_root, doc.spec.allowed_files)` via Python, then update `.agents/plugins/principal-architect-workspace/pr-05-dogfood-self-enrollment-and-release/wo1-self-enroll-and-migrate/WORKORDER.md` frontmatter (`status: COMPLETED`, `completion:`) and Part II `## Completion Report` (leaving Part I untouched so `spec_hash` remains valid), stage all changes (`git add -A`), and commit on `pr-05-dogfood-self-enrollment-and-release/wo1-self-enroll-and-migrate` with commit message:
   ```text
   WO-05.1: Self-enrollment and legacy workspace migration (.agents/skills -> .agents/plugins)

   PA-WorkOrder: WO-05.1
   PA-Verified-Hash: <tree_hash>
   ```
4. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report rather than filing issues directly.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

- **Status:** `COMPLETED` (attempt 1)
- **Receipt ID:** `rcpt_0b1f0c3a6d7a`
- **Tree Hash (`allowed_files`):** `0b1f0c3a6d7a2434e50f02a5f6da8bd357b1c88ab6d7d3f7075adce88dc92eee`
- **Files Modified:**
  - `.gitignore`
  - `.agents/plugins/principal-architect-workspace/` (migrated via `git mv` from `.agents/skills/principal-architect-workspace/`)
  - `tests/test_state_db_and_sync.py`
- **Verification Summary:**
  - `common.workspace_dir(repo_root)` resolves `.agents/plugins/principal-architect-workspace`; verified 1 `PROGRAM.md`, 5 `PROJECT.md` `charter_hash` locks (`PR-01`..`PR-05`), 21 `WORKORDER.md` `spec_hash` locks, and 4 `AUDIT-round-1.md` reports (`PR-01`..`PR-04`)
  - `./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py` -> `121 passed in 54.65s`
  - `./.venv/bin/ruff check daemon tests` -> `All checks passed!`
- **Decisions Made:**
  - Executed `scripts/install.sh` and `pa enroll . --memory-mode builtin --vcs-mode local_git` in an isolated temporary directory (`/tmp/pa-dogfood-pr05`) to exercise the tracked `git mv` migration from `.agents/skills/principal-architect-workspace/` to `.agents/plugins/principal-architect-workspace/` and create `.agents/plugins/principal-architect-workspace/.gitignore` (containing `.state/`).
  - Removed the empty `.agents/skills` directory and cleaned up untracked `.agents/plugins.json`, `.agents/plugins/principal-architect-workspace/.state/`, and `/tmp/pa-dogfood-pr05` so zero machine-specific paths remain on disk.
  - Added `.agents/plugins/principal-architect-workspace/.state/` to root `.gitignore` and updated `test_workspace_dir_dogfood()` in `tests/test_state_db_and_sync.py` to assert `ws == repo_root / common.NEW_WORKSPACE_REL` and `not (repo_root / common.LEGACY_WORKSPACE_REL).exists()`.
- **Out-of-Scope Findings:** None.
- **Dead Ends:** None.
