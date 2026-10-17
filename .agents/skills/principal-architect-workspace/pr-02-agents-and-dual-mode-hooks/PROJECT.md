---
schema_version: 1
charter:
  pr_id: PR-02
  programme_id: prog-principal-architect-plugin
  slug: pr-02-agents-and-dual-mode-hooks
  title: "Custom agent definitions, hooks.json, dual-mode PreToolUse/PostToolUse/Stop gates, pa pr approve-plan, pa wo verify"
  branch: feat/pr-02-agents-and-dual-mode-hooks
  base_branch: feat/pr-01-core-schemas-and-enrollment
  depends_on:
    - PR-01
  allowed_modules:
    - daemon/workspace-plugin/principal-architect/hooks.json
    - daemon/workspace-plugin/principal-architect/agents/
    - daemon/workspace-plugin/principal-architect/rules/
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/SKILL.md
    - daemon/workspace-plugin/principal-architect/scripts/pre_invocation.py
    - daemon/workspace-plugin/principal-architect/scripts/pre_tool_gate.py
    - daemon/workspace-plugin/principal-architect/scripts/post_tool_receipt.py
    - daemon/workspace-plugin/principal-architect/scripts/stop_gate.py
    - daemon/workspace-plugin/principal-architect/scripts/escalation.py
    - daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
    - daemon/workspace-plugin/principal-architect/scripts/schemas.py
    - daemon/workspace-plugin/principal-architect/scripts/state_db.py
    - daemon/workspace-plugin/principal-architect/scripts/common.py
    - tests/conftest.py
    - tests/test_hooks_monitored_vs_autonomous.py
  required_skills: []
  verification_floor:
    - "pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py"
  charter_locked: true
  charter_hash: "c4101d401d3bfce795e277df30e49ffc534e9e1d2c835788a433f342d95ddbde"
status: PLANNED
approved_at: null
github_pr: null
work_orders: []
---

# PR-02 — Agents, Capability Scoping & Dual-Mode Hook Engine

| | |
|---|---|
| **Programme** | [`prog-principal-architect-plugin`](../programme-principal-architect-plugin/PROGRAM.md) · [plan](../programme-principal-architect-plugin/PROGRAM-PLAN.md) |
| **Spec** | [`SPEC.md` v1.1](../../../../SPEC.md) §5.1–5.2 (roles & capability scoping), §7.1–7.4 (hook engine), §8 (`pr approve-plan`, `wo verify`, `escalate`), §11.1–11.2, §11.4 |
| **Base → head** | `feat/pr-01-core-schemas-and-enrollment` → `feat/pr-02-agents-and-dual-mode-hooks` (WO branches: `pr-02-agents-and-dual-mode-hooks/woM-<topic>`) |
| **Part I owner** | Tier 1 Chief Architect (locked — amendments only via escalation to the Chief) |
| **Part II / III owner** | Tier 2 Principal Architect for PR-02 |

<!-- ======================================================================
     PART I — PR CHARTER (authored by the Tier 1 Chief Architect; locked via charter_hash)
     ====================================================================== -->

## 1. PR Charter: Scope, Goals, & Non-Goals

### 1.1 Scope

PR-02 turns the prompt-only `principal-architect` methodology into **deterministic mechanical enforcement**: the five custom role agents (`agents/pa-*.md`) with evidence-based capability scoping (`inheritCustomizations: false` + `.state/pa-skills.json` & `.state/pa-worker-rules.json`), the workspace plugin `hooks.json` and all four hook entrypoints (`pre_invocation.py`, `pre_tool_gate.py`, `post_tool_receipt.py`, `stop_gate.py`), the dual-mode escalation engine (`escalation.py`) implementing rules R1–R6 symmetrically across `monitored` and `autonomous` modes, cryptographic `tree_hash` verification receipts, the two-tier retry policy (`max_attempts: 5` vs. `max_structural_failures: 2`), the CLI subcommands `pa pr approve-plan`, `pa wo verify`, and `pa escalate`, and the subprocess + unit test suite `tests/test_hooks_monitored_vs_autonomous.py`.

### 1.2 Goals

| # | Goal | Done when |
|---|---|---|
| **G1** | **`escalation.py` — Pure dual-mode decision engine, structural blocker signatures, and hook I/O helpers.** Implements `decide(rule, mode, ctx) -> dict[str, Any]` for rules `R1`, `R1b`, `R2`, `R3`, `R4`, `R5`, `R6`; `STRUCTURAL_SIGNATURES` and `is_structural_blocker(text) -> bool`; `record_escalation(db, ...)` and `enqueue_attention(db, ...)`; and stdlib-friendly hook JSON stdin/stdout helpers (`read_hook_input`, `write_hook_output`) that always exit `0`. | Every `(rule, mode)` combination has deterministic unit tests in `tests/test_hooks_monitored_vs_autonomous.py`. |
| **G2** | **`hooks.json` & `<1ms` unenrolled fast-exit.** `daemon/workspace-plugin/principal-architect/hooks.json` registers `PreInvocation` (`pre_invocation.py`), `PreToolUse` (`pre_tool_gate.py` with matcher `write_to_file\|write_file\|replace_file_content\|edit_file\|multi_replace_file_content\|run_command\|invoke_subagent`), `PostToolUse` (`post_tool_receipt.py`), and `Stop` (`stop_gate.py`) with `timeout: 10`. Every hook checks `common.is_repo_enrolled(workspace_paths)` before importing `pydantic`/`yaml`/`schemas` and exits `0` in `< 1 ms` when unenrolled. | Subprocess and in-process tests verify unenrolled fast-exit (`< 1 ms` in-process) and zero `pydantic`/`yaml` imports on the unenrolled path. |
| **G3** | **`pre_tool_gate.py` — Rules R1, R1b, R2, R3, R4, R5, R6 + `os.path.realpath` traversal defense.** Resolves all target file paths via `os.path.realpath` relative to `repo_root` before matching against `allowed_files`, `forbidden_files`, or `charter.allowed_modules`. Enforces R1 (Architect no-inline-code), R1b (PA Charter lock on `PROJECT.md` Part I / `charter_hash` and `allowed_modules`), R2 (PA `invoke_subagent` plan approval gate with `auto_approve_pr_plans` support), R3 (Worker `allowed_files` / `forbidden_files` / `WORKORDER.md` Part I `spec_hash` lock), R4 (Worker git/gh lockdown — hard deny in both modes), R5 (Auditor read-only lockdown — hard deny in both modes), and R6 (`pa pr graduate` / `gh pr merge` audit gate). | Full `rule × mode` matrix plus symlink and `../` traversal escape attempts tested via subprocess and direct calls. |
| **G4** | **`post_tool_receipt.py` — Receipt invalidation, deterministic `tree_hash` stamping, and attempt/structural tracking.** Invalidates existing receipts (`db.invalidate_receipts(wo_id)`) whenever `pa-engineer` mutates files or runs a mutating shell command; computes `compute_tree_hash(repo_root, allowed_files)` over the working-tree contents of `allowed_files`; stamps a valid receipt (`valid=1`) in `verification_receipts` when `verification_command` exits `0`; increments `attempt_num` (and `structural_failures` when `is_structural_blocker` matches) on non-zero exit. | Tested for edit -> verify (`valid=1`) -> subsequent edit (`valid=0`) -> failed verify (`attempt_num` + `structural_failures` increment). |
| **G5** | **`stop_gate.py` — Two-tier retry ceiling (`max_attempts: 5` vs. `max_structural_failures: 2`) and completion invariants.** Fast-fails with `ESCALATED_TO_PA` (`blocker_type="structural"`) and allows stop (`{}`) when `structural_failures >= max_structural_failures` (2) or `>= 3` consecutive `ERROR_MESSAGE` steps appear in `transcript.jsonl`; stops with `BLOCKED` and enqueues a `pa-debugger` item (`🔬 [Debug <WO-ID>]`) when `attempt_num >= max_attempts` (5); otherwise enforces Case A (blocker/escalation report recorded) and Case B (valid receipt matching current `tree_hash`, clean git status on `allowed_files` + `WORKORDER.md` with `<WO-ID>:` commit message, and valid `CompletionReport` with intact `spec_hash`), incrementing `attempt_num` on each `"decision": "continue"` response so `Stop` never loops infinitely; for `pa-auditor`, requires an `AuditReport` recorded for current `HEAD`. | Tested across productive retries, structural fast-fail (2 structural failures / 3 consecutive `ERROR_MESSAGE` steps), 5-attempt ceiling, Case A/B completion checks, auditor stop gate, and bounded continuation cap. |
| **G6** | **`pre_invocation.py` — Session role binding, compaction/rewind detection, and persistent `userMessage` injection.** Binds unbound `conversationId` in `sessions` by parsing `PA_ROLE:`, `PR_ID:`, `WO_ID:`, `PROGRAMME_ID:` from the prompt/transcript; detects new `CHECKPOINT` steps or step-count rewind to re-arm injection; emits `{"injectSteps": [{"userMessage": "..."}]}` tailored to the bound role and `memory_mode` (`builtin` injects `MEMORY.md` + matching `MODULE_INDEX.md` sections and Full Distillation mode; `external` omits `memory/` and instructs Succinct Write-Back mode; `engineer` injects bound `WORKORDER.md` Part I summary + `required_skills` paths). | Tested for first-turn subagent binding, `CHECKPOINT` compaction re-injection, step rewind re-injection, and `builtin` vs. `external` memory payload separation. |
| **G7** | **Role agents (`agents/pa-*.md`), rule, skill, and CLI (`pa pr approve-plan`, `pa wo verify`, `pa escalate`).** Five agent markdown files in `daemon/workspace-plugin/principal-architect/agents/`, `rules/00-pa-operating-model.md`, in-plugin `skills/principal-architect/SKILL.md`, and CLI commands `pa pr approve-plan`, `pa wo verify`, and `pa escalate` integrated into `pa_cli.py`. | Agent frontmatter schema test passes; `pa pr approve-plan`, `pa wo verify`, and `pa escalate` pass end-to-end offline tests in `tests/test_hooks_monitored_vs_autonomous.py`. |
| **G8** | **All verification floors green & hygiene clean.** `pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py` passes from `./.venv`; `ruff check daemon tests` clean; zero I10 hygiene violations. | Cold-Firewall audit `APPROVED`. |

### 1.3 Non-Goals (explicitly out of scope for PR-02)

- `vcs_sync.py` (`LocalGitBus`, `GitHubBus`, `pa sync`, `pa programme init/charter`, `pa pr start/claim/open-or-sync/post-audit/sync-audit/graduate/restack`, `pa issue create`) — **PR-03**.
- `models.py` (complexity routing helper, retry step-up, Language Server client, `pa wo debug/resolve`) — **PR-03**.
- `memory_grad.py` (`builtin` 5-PR window roll-off and `MODULE_INDEX.md` graduation writer) — **PR-03**.
- `cockpit.py`, `daemon/sidecars/`, `scripts/install.sh`, `scripts/uninstall.sh` — **PR-04**.

## 2. Architectural Requirements, Cross-PR Interfaces, & Required Skills/Tools

### 2.1 Architectural requirements

| # | Requirement |
|---|---|
| **R1** | **Unenrolled fast-exit & lazy imports (I4).** Every hook script (`pre_invocation.py`, `pre_tool_gate.py`, `post_tool_receipt.py`, `stop_gate.py`) must import `common` first, extract `workspace_paths` from the hook JSON payload (`workspacePaths`, `workspaceUris`, `cwd`, or fallback `.`), call `common.is_repo_enrolled(workspace_paths)`, and if `False`, print `{}` and exit `0` without importing `pydantic`, `yaml`, or `schemas`. |
| **R2** | **Hook I/O contract (PROGRAM.md §2.2(6)).** Hooks read one JSON object from `sys.stdin` and write one JSON object to `sys.stdout` followed by exit code `0`. Any uncaught exception or malformed stdin must be caught, logged to `sys.stderr`, and result in a safe JSON output + exit `0` so the harness is never crashed by an unhandled traceback. `PreToolUse` outputs `{"permissionDecision": "allow" \| "ask" \| "deny", "reason": "..."}` (or `{}` for allow). `PreInvocation` outputs `{"injectSteps": [{"userMessage": "..."}]}` when injecting or `{}` when no injection is needed. `Stop` outputs `{}` to allow termination or `{"decision": "continue", "reason": "..."}` to block premature termination. |
| **R3** | **Canonical path resolution & boundary matching (SPEC §11.2).** `pre_tool_gate.py` must resolve every candidate target path via `os.path.realpath` against the real `repo_root` (`common.find_repo_root`). A path that resolves outside `repo_root` (or outside `.agents/` for Architects under R1, or outside `allowed_files` / inside `forbidden_files` for Workers under R3) is rejected according to the active mode. Pattern matching supports exact relative paths, directory prefixes (`dir/` or `dir/**`), and `fnmatch` globs. |
| **R4** | **Deterministic `tree_hash` calculation.** `compute_tree_hash(repo_root: str | Path, allowed_files: Sequence[str]) -> str` resolves all existing files under `repo_root` matching `allowed_files` (excluding `.git/` and `.state/`), sorts them by normalized POSIX relative path, and hashes `<rel_posix_path>\0<len>\0<raw_bytes>\n` with SHA-256. Both `post_tool_receipt.py`, `stop_gate.py`, and `pa wo verify` must call this single shared function so receipt hashes never diverge. |
| **R5** | **Bounded Stop-hook continuations (Risk R6).** Whenever `stop_gate.py` returns `{"decision": "continue", ...}` for an `engineer` or `auditor` session, it must increment `attempt_num` in `sessions` (or track stop-continuation count) so that at most `max_attempts` (5) continuations can ever occur before the ceiling triggers and allows termination with `{}` + an escalation record. |
| **R6** | **Agent frontmatter compliance (SPEC §5.2 & I9).** All five `daemon/workspace-plugin/principal-architect/agents/pa-*.md` files must have valid YAML frontmatter with non-empty `name` and `description`, `model: inherit`, `mainAgent` / `subagent` booleans per SPEC §5.2 table, `tools:` allowlists per SPEC §5.2 table, `inheritCustomizations: false` on `pa-engineer.md` and `pa-auditor.md`, `skills: [.agents/plugins/principal-architect-workspace/.state/pa-skills.json]`, `rules: [.agents/plugins/principal-architect-workspace/.state/pa-worker-rules.json]` (or `<repo>/.agents/rules` for Chief/PA), and `inheritMcp: false` on `pa-auditor.md` (`true` on the other four). |
| **R7** | **CLI subcommands (`pa pr approve-plan`, `pa wo verify`, `pa escalate`).** Registered via `COMMAND_MODULES` (or directly in `pa_cli.py` while keeping `pa_cli.py` top-level stdlib-only). `pa pr approve-plan <PR-ID>` verifies `charter_hash`, validates all `wo*/WORKORDER.md` specs and checks `allowed_files ⊆ charter.allowed_modules`, stamps `spec_hash` on each `WORKORDER.md`, and sets `PROJECT.md` `status: APPROVED` + `approved_at`. `pa wo verify <WO-ID>` checks working-tree scope hygiene + `spec_hash`, runs `verification_command`, stamps a valid `verification_receipts` row in `state.db`, updates `WORKORDER.md` Part II `completion` (`status: COMPLETED`, `receipt_id`, `files_modified`, `verification_summary`), commits `allowed_files` + `WORKORDER.md` with message `<WO-ID>: <title>` and trailers `PA-WorkOrder: <WO-ID>` + `PA-Verified-Hash: <tree_hash>`, and updates `commit_sha` in `WORKORDER.md` and `PROJECT.md`. `pa escalate` records an escalation in `state.db` (`escalations` and, when targeting human or in autonomous mode, `attention_queue`). |
| **R8** | **Additive-only changes to PR-01 modules.** Any helper added to `common.py`, `schemas.py`, `state_db.py`, or `pa_cli.py` must be strictly additive and preserve all PR-01 exported signatures and tests (`tests/test_schemas.py` and `tests/test_state_db_and_sync.py` must stay 100% green). |
| **R9** | **Hygiene (I10).** Zero internal identifiers, machine-specific absolute paths, or personal emails in any committed file, test fixture, or commit message. |

### 2.2 Cross-PR interfaces exported by PR-02 (stability contract)

| Module | Symbol | Contract |
|---|---|---|
| `escalation.py` | `decide`, `STRUCTURAL_SIGNATURES`, `is_structural_blocker`, `record_escalation`, `enqueue_attention`, `read_hook_input`, `write_hook_output` | Pure decision core and hook I/O helpers consumed by all four hooks and PR-03. |
| `pre_tool_gate.py` | `evaluate_pre_tool(payload, *, repo_root=None) -> dict[str, Any]`, `main()` | Enforces R1, R1b, R2, R3, R4, R5, R6 across `monitored` and `autonomous` modes. |
| `post_tool_receipt.py` | `compute_tree_hash(repo_root, allowed_files) -> str`, `evaluate_post_tool(payload, *, repo_root=None) -> dict[str, Any]`, `main()` | Receipt invalidation, deterministic `tree_hash`, receipt stamping, attempt/structural tracking. |
| `stop_gate.py` | `evaluate_stop(payload, *, repo_root=None) -> dict[str, Any]`, `main()` | Two-tier retry ceiling (`max_attempts: 5`, `max_structural_failures: 2`) and Case A/B + auditor completion gates. |
| `pre_invocation.py` | `parse_spawn_header(text) -> dict[str, str]`, `evaluate_pre_invocation(payload, *, repo_root=None) -> dict[str, Any]`, `main()` | Prompt-header role binding, `CHECKPOINT`/rewind detection, memory-mode-aware `userMessage` injection. |
| `pa_cli.py` | `pa pr approve-plan`, `pa wo verify`, `pa escalate` | CLI commands consumed by Architects, Workers, and PR-03 lifecycle commands. |
| `agents/pa-*.md`, `rules/`, `SKILL.md`, `hooks.json` | 5 agent files, operating-model rule, in-plugin skill, hook manifest | Static KV-cache-stable role definitions and hook registrations. |

### 2.3 Required skills & tools

| Kind | Item | Notes |
|---|---|---|
| Runtime | `./.venv/bin/python` (Python 3.11+, `pydantic>=2,<3`, `pyyaml>=6`) | Provisioned by `scripts/dev-bootstrap.sh` from PR-01. |
| Test / lint | `./.venv/bin/pytest`, `./.venv/bin/ruff` | Verification floor runs both PR-01 and PR-02 test modules. |
| CLI | `git` | Used in `pa wo verify` and boundary/status tests inside `tmp_repo`. |

### 2.4 Delivery constraints for the Tier 2 PA

- Decompose into **sequential, single-writer Work Orders** (expected 5–6, following `PROGRAM-PLAN.md` §4 PR-02 guidance), each with a tight `allowed_files` subset of `allowed_modules` and the verification floor `pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py`.
- Spawn **exactly one Tier 3 Execution Worker per `WORKORDER.md`**; never execute Work Orders inline.
- Record the user's standing programme approval of Part II in this file (`status: APPROVED`, `approved_at`, and a dated line in §4) before spawning the first Worker.
- At Step 6A: fast-forward `feat/pr-02-agents-and-dual-mode-hooks` to the final WO tip, push to `origin`, open the GitHub PR with `--base feat/pr-01-core-schemas-and-enrollment --head feat/pr-02-agents-and-dual-mode-hooks`, record `github_pr` in `PROJECT.md`, and pause for the Cold-Firewall audit.

<!-- ======================================================================
     PART II — IMPLEMENTATION PLAN & WORK ORDER BREAKDOWN (authored by the Tier 2 Principal Architect)
     ====================================================================== -->

## 3. Implementation Plan & Work Order Breakdown

_To be authored by the Tier 2 Principal Architect for PR-02 after file-level discovery. Ledger rows must link to each `woM-<topic>/WORKORDER.md`._

<!-- ======================================================================
     PART III — OUTCOME & GRADUATION SUMMARY (authored by the Tier 2 Principal Architect)
     ====================================================================== -->

## 4. Outcome & Session Log

_To be authored by the Tier 2 Principal Architect. memory_mode is `builtin`: record full architectural distillation (decisions, dead ends, surfaced findings, audit rounds, final head_sha)._
