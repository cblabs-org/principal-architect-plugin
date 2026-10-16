---
schema_version: 1
wo_id: WO-04.3
pr_id: PR-04
title: Host install.sh and uninstall.sh scripts, user-facing README.md, and isolated
  tmp_path installer tests
complexity: mechanical
status: COMPLETED
allowed_files:
- scripts/install.sh
- scripts/uninstall.sh
- README.md
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
spec_hash: 47f83e2d9715c4507a0bb83e8a5a59796acd3b19345ef93de35913f7bd919626
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: rcpt_871745929da7
  commit_sha: fa32b5d2a5035c268dadc296a413c2c1b6a740ef
  files_modified:
  - scripts/install.sh
  - scripts/uninstall.sh
  - README.md
  - tests/test_cockpit_api.py
  verification_summary: "121 passed in 81.82s; ruff check daemon tests: All checks passed!"
  out_of_scope_findings:
  - "pa_cli.py status takes a positional path argument (pa status [path] [--json]) rather than --repo; test_install_and_uninstall_scripts_isolated_tmp_path exercises the positional path contract."
  escalation_request: null
  decisions_made:
  - "Implemented scripts/install.sh and scripts/uninstall.sh honouring PA_DAEMON_HOME and PA_BIN_DIR, backing up and restoring <PA_DAEMON_HOME>/state/ across upgrades, initializing registry.json with both repos and repositories keys, setting executable permissions, and symlinking pa_cli.py to <PA_BIN_DIR>/pa."
  - "Authored comprehensive user-facing README.md covering the 3-tier operating model, Split-Authority Markdown contracts (charter_hash & spec_hash), two-tier installation, dual-mode hooks (R1-R6), local_git vs github VCS bus, external vs builtin memory modes, Cockpit AuxPane UI zones, and CLI reference."
  - "Extended tests/test_cockpit_api.py with test_install_and_uninstall_scripts_isolated_tmp_path verifying isolated tmp_path installation, pa --help, pa enroll, pa status --json, state/registry.json preservation across re-installs, and idempotent uninstallation."
  dead_ends: []
---

# WO-04.3 — Host Installer (`scripts/install.sh`, `scripts/uninstall.sh`), `README.md` & Installer Tests

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-04` (`pr-04-cockpit-auxpane-ui`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T23:01:30Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `scripts/install.sh` and `scripts/uninstall.sh` (`SPEC.md §4.1` & Charter G3/R6), write the complete user-facing `README.md`, and extend `tests/test_cockpit_api.py` with isolated `tmp_path` installation/uninstallation and registry preservation tests.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `scripts/install.sh`
  - `scripts/uninstall.sh`
  - `README.md`
  - `tests/test_cockpit_api.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-04-cockpit-auxpane-ui/wo3-install-uninstall-and-docs/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md` (do NOT modify `cockpit.py` or any Python module in `daemon/`). Do NOT run `pa_cli.py wo verify` directly against this unenrolled workspace repository (as that creates `.state/state.db` in the repo root; instead compute `tree_hash = post_tool_receipt.compute_tree_hash` via Python and commit directly). Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh` on the workspace repository. Commit only on the currently checked-out branch `pr-04-cockpit-auxpane-ui/wo3-install-uninstall-and-docs` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R7):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file, test fixture, or commit message.

## 3. Line-Item Instructions

- [ ] **`scripts/install.sh` (`SPEC.md §4.1` & Charter G3/R6):**
  - Must start with `#!/usr/bin/env bash` and `set -euo pipefail`, and be marked executable (`chmod +x scripts/install.sh`).
  - Honours environment overrides:
    - `PA_DAEMON_HOME="${PA_DAEMON_HOME:-$HOME/.gemini/config/plugins/pa-daemon}"`
    - `PA_BIN_DIR="${PA_BIN_DIR:-$HOME/.local/bin}"`
  - Preserves `<PA_DAEMON_HOME>/state/` (in particular `<PA_DAEMON_HOME>/state/registry.json`) across upgrades/re-installs:
    - Before replacing `<PA_DAEMON_HOME>`, if `<PA_DAEMON_HOME>/state` exists, backs it up to a temporary directory (`mktemp -d`), installs `daemon/` into `<PA_DAEMON_HOME>`, ensures `<PA_DAEMON_HOME>/state` exists, and restores the backed-up `state/` contents (`registry.json`, etc.).
    - If `<PA_DAEMON_HOME>/state/registry.json` does not exist yet, initializes `<PA_DAEMON_HOME>/state/registry.json` with `{"schema_version": 1, "repositories": []}`.
  - Sets `chmod +x` on `<PA_DAEMON_HOME>/workspace-plugin/principal-architect/scripts/*.py` (and `scripts/{enroll,unenroll}.sh` in the repo).
  - Creates `mkdir -p "$PA_BIN_DIR"` and symlinks `ln -sf "$PA_DAEMON_HOME/workspace-plugin/principal-architect/scripts/pa_cli.py" "$PA_BIN_DIR/pa"`.
  - Prints a concise installation summary showing `PA_DAEMON_HOME` and `$PA_BIN_DIR/pa`.

- [ ] **`scripts/uninstall.sh` (`SPEC.md §4.1` & Charter G3/R6):**
  - Must start with `#!/usr/bin/env bash` and `set -euo pipefail`, and be marked executable (`chmod +x scripts/uninstall.sh`).
  - Honours environment overrides:
    - `PA_DAEMON_HOME="${PA_DAEMON_HOME:-$HOME/.gemini/config/plugins/pa-daemon}"`
    - `PA_BIN_DIR="${PA_BIN_DIR:-$HOME/.local/bin}"`
  - Removes `$PA_BIN_DIR/pa` if it exists (or is a symlink) and removes `$PA_DAEMON_HOME` if it exists (`rm -rf "$PA_DAEMON_HOME"`).
  - Idempotent: exits `0` even if already uninstalled.

- [ ] **`README.md` (Charter G3):**
  - Update `README.md` into the complete, authoritative user-facing guide for `principal-architect-plugin` covering:
    1. **Overview & 3-Tier Operating Model:** Tier 1 Chief Architect (`pa-chief`), Tier 2 Principal Architect (`pa-architect`), Tier 3 Execution Worker (`pa-engineer`), Cold-Firewall Auditor (`pa-auditor`), and Adversarial Plan Critic (`pa-critic`), plus Split-Authority Markdown (`charter_hash` & `spec_hash`).
    2. **Two-Tier Installation (`SPEC.md §4.1`):**
       - Tier 1 Global Host Daemon (`./scripts/install.sh` -> `~/.gemini/config/plugins/pa-daemon` and `~/.local/bin/pa`, plus `./scripts/uninstall.sh`).
       - Tier 2 Per-Repo Opt-In Enrollment (`pa enroll [path] [--execution-mode monitored|autonomous]` / `./scripts/enroll.sh` and `pa unenroll` / `./scripts/unenroll.sh`).
    3. **Dual Execution Modes & Hook Enforcement (`SPEC.md §6–§7`):**
       - `monitored` vs. `autonomous` mode across R1–R6 triggers.
       - The 4 fast-exit (`<1ms` on unenrolled repos) hooks: `pre_invocation.py`, `pre_tool_gate.py`, `post_tool_receipt.py`, `stop_gate.py`.
    4. **Local-Git Floor + GitHub Multi-Machine Bus (`SPEC.md §8`):**
       - Stacked branches (`feat/pr-NN-<slug>` and `pr-NN-<slug>/woM-<topic>`), commit trailers (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`), `AUDIT-round-<K>.md`, `DEFERRED_BACKLOG.md`, `pa sync`, and `pa pr restack`.
    5. **Mutually Exclusive Memory Modes (`SPEC.md §9`):**
       - `external` mode (`cblabs-org/repo-memory-plugin` compatibility with zero mutations to `memory/`) vs. `builtin` mode (5-PR rolling window in `MEMORY.md`, `PROJECT_INDEX.md`, `MODULE_INDEX.md`).
    6. **Principal Architect Cockpit AuxPane UI (`SPEC.md §10`):**
       - Zone 1 (Header, environment badges, Sync, Monitored/Autonomous toggle, Architect Model selector), Zone 2 (`🔔 Human Attention Needed` inbox), and Zone 3 (Programme -> Stacked PR -> Work Order DAG with `window.sidecar.ui.toggleConversation` jump links).
    7. **Complete CLI Reference & Verification Floor:**
       - All `pa` subcommands (`enroll`, `unenroll`, `status`, `mode`, `sync`, `programme`, `pr`, `wo`, `escalate`, `issue`) and running the 6 pytest verification suites + `ruff check`.

- [ ] **Extend `tests/test_cockpit_api.py` (Charter G3 & R6):**
  Keep all existing `WO-04.1` and `WO-04.2` tests intact and add a new test function (e.g. `test_install_and_uninstall_scripts_isolated_tmp_path`) that:
  1. Runs `bash scripts/install.sh` with `PA_DAEMON_HOME=tmp_path / "pa-daemon"` and `PA_BIN_DIR=tmp_path / "bin"`.
  2. Verifies `pa-daemon/plugin.json`, `pa-daemon/sidecars/pa_cockpit/sidecar.json`, `pa-daemon/sidecars/pa_cockpit/ui/index.html`, `pa-daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`, `pa-daemon/state/registry.json`, and the symlink `bin/pa` all exist and `bin/pa` is executable.
  3. Invokes `<tmp_path>/bin/pa --help` and `<tmp_path>/bin/pa status --repo <enrolled_tmp_repo> --json` (using `PA_DAEMON_HOME`) and verifies exit code `0` and valid JSON output.
  4. Enrolls `tmp_repo` into `pa-daemon/state/registry.json`, then re-runs `bash scripts/install.sh` and verifies that `pa-daemon/state/registry.json` **preserves** the enrolled repository across the upgrade/re-install.
  5. Runs `bash scripts/uninstall.sh` (twice to verify idempotency) and verifies both `bin/pa` and `pa-daemon/` are removed cleanly.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the full verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute `tree_hash = post_tool_receipt.compute_tree_hash(repo_root, doc.spec.allowed_files)`, update `WORKORDER.md` frontmatter (`status: COMPLETED`, `completion:`) and Part II `## Completion Report` (leaving Part I untouched so `spec_hash` remains valid), and commit on `pr-04-cockpit-auxpane-ui/wo3-install-uninstall-and-docs` with trailers `PA-WorkOrder: WO-04.3` and `PA-Verified-Hash: <tree_hash>`.
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report rather than filing issues directly.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

- **Status:** `COMPLETED` (attempt 1)
- **Receipt ID:** `rcpt_871745929da7`
- **Tree Hash (`allowed_files`):** `871745929da78c115d13bc8b0ae37af5ef6fdba4f486554179119011d63dd7d1`
- **Files Modified:**
  - `scripts/install.sh`
  - `scripts/uninstall.sh`
  - `README.md`
  - `tests/test_cockpit_api.py`
- **Verification Summary:**
  - `./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py tests/test_cockpit_api.py` -> `121 passed in 81.82s`
  - `./.venv/bin/ruff check daemon tests` -> `All checks passed!`
- **Decisions Made:**
  - Authored `scripts/install.sh` and `scripts/uninstall.sh` (`chmod +x`) honouring `PA_DAEMON_HOME` and `PA_BIN_DIR`, backing up and restoring `<PA_DAEMON_HOME>/state/` across upgrades, initializing `registry.json` with both `repos` and `repositories` keys when absent, setting executable permissions on `scripts/*.py` and `scripts/{enroll,unenroll}.sh`, and symlinking `pa_cli.py` to `<PA_BIN_DIR>/pa`.
  - Authored the complete user-facing `README.md` covering the 3-tier operating model, Split-Authority Markdown contracts (`charter_hash` & `spec_hash`), two-tier installation, dual-mode hooks (`R1`–`R6`), `local_git` vs. `github` VCS bus, `external` vs. `builtin` memory modes, Cockpit AuxPane UI zones, and CLI reference.
  - Extended `tests/test_cockpit_api.py` with `test_install_and_uninstall_scripts_isolated_tmp_path` verifying isolated `tmp_path` installation, `pa --help`, `pa enroll`, `pa status --json`, `state/registry.json` preservation across re-installs, and idempotent uninstallation.
- **Out-of-Scope Findings:**
  - `pa_cli.py status` takes a positional `path` argument (`pa status [path] [--json]`) rather than `--repo`; `test_install_and_uninstall_scripts_isolated_tmp_path` exercises the positional `path` contract.
- **Dead Ends:** None.
