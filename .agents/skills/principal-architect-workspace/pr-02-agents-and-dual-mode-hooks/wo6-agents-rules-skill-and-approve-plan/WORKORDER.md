---
schema_version: 1
wo_id: WO-02.6
pr_id: PR-02
title: "Five custom agent definitions (agents/pa-*.md), operating-model rule, in-plugin SKILL.md, pa pr approve-plan, and pa escalate"
complexity: standard
status: COMPLETED
allowed_files:
  - daemon/workspace-plugin/principal-architect/agents/**
  - daemon/workspace-plugin/principal-architect/rules/**
  - daemon/workspace-plugin/principal-architect/skills/principal-architect/SKILL.md
  - daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
  - tests/test_hooks_monitored_vs_autonomous.py
forbidden_files:
  - SPEC.md
  - docs/positioning-paper.md
  - .agents/skills/principal-architect-workspace/pr-02-agents-and-dual-mode-hooks/PROJECT.md
  - .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: "./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests"
max_attempts: 5
max_structural_failures: 2
spec_hash: 72c40ab174373449f4d60f0436cab3c337fa55a8cc6a99392828cbba6a3e1dda
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: rcpt_b620400d70e1
  commit_sha: 1f0d1f96c84019e78c03e7ebe36e7d3103a4b4ab
  files_modified:
    - daemon/workspace-plugin/principal-architect/agents/pa-auditor.md
    - daemon/workspace-plugin/principal-architect/agents/pa-chief-architect.md
    - daemon/workspace-plugin/principal-architect/agents/pa-debugger.md
    - daemon/workspace-plugin/principal-architect/agents/pa-engineer.md
    - daemon/workspace-plugin/principal-architect/agents/pa-principal-architect.md
    - daemon/workspace-plugin/principal-architect/rules/00-pa-operating-model.md
    - daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/SKILL.md
    - tests/test_hooks_monitored_vs_autonomous.py
  verification_summary: "85 passed in 16.02s; ruff check daemon tests: All checks passed!"
  out_of_scope_findings: []
  escalation_request: null
  decisions_made:
    - "Defined _is_pattern_within_allowed_modules in pa_cli.py wrapping pre_tool_gate.matches_any_pattern so glob/directory patterns in allowed_files are validated against charter.allowed_modules without mutating pre_tool_gate.py."
    - "Kept pa_cli.py top-level imports stdlib-only and lazy-imported schemas, pre_tool_gate, and escalation inside _cmd_pr_approve_plan and _cmd_escalate."
  dead_ends: []
---

# WO-02.6 — Custom Agent Definitions (`agents/pa-*.md`), Operating-Model Rule, `SKILL.md`, `pa pr approve-plan`, and `pa escalate`

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-02` (`pr-02-agents-and-dual-mode-hooks`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T20:05:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Deliver the final slice of PR-02 (SPEC §5.2 & §8, Charter G7, R6, R7, R8):
1. Author the five custom role agent markdown files in `daemon/workspace-plugin/principal-architect/agents/`:
   - `pa-chief-architect.md`
   - `pa-principal-architect.md`
   - `pa-engineer.md`
   - `pa-auditor.md`
   - `pa-debugger.md`
2. Author `daemon/workspace-plugin/principal-architect/rules/00-pa-operating-model.md` (no YAML frontmatter, `< 8 KB`).
3. Author `daemon/workspace-plugin/principal-architect/skills/principal-architect/SKILL.md`.
4. Implement `pa pr approve-plan <PR-ID>` and `pa escalate` in `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`.
5. Add comprehensive unit, CLI, and dogfood verification tests in `tests/test_hooks_monitored_vs_autonomous.py`.

## 2. Boundary Box & Invariants

- **Allowed Files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/agents/**`
  - `daemon/workspace-plugin/principal-architect/rules/**`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/SKILL.md`
  - `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`
  - `tests/test_hooks_monitored_vs_autonomous.py`
- **Forbidden Files (`forbidden_files`):**
  - `SPEC.md`, `docs/positioning-paper.md`, `PROJECT.md`, `PROGRAM.md`, and any file outside `allowed_files` (except Part II of this `WORKORDER.md`).
- **Architectural Invariants:**
  - **Agent Frontmatter Compliance (SPEC §5.2, Charter R6, Invariant I9):**
    - Every `agents/pa-*.md` file MUST have valid YAML frontmatter with non-empty `name` and `description`, `model: inherit`, `excludeDefaultComponents: false`, and exact `mainAgent`, `subagent`, `inheritCustomizations`, `tools`, `skills`, `rules`, and `inheritMcp` fields matching SPEC §5.2:
      - `pa-chief-architect.md`: `mainAgent: true`, `subagent: true`, `tools: [view_file, read_file, write_to_file, write_file, replace_file_content, edit_file, list_dir, grep_search, find_by_name, code_search, run_command, invoke_subagent, ask_question, send_message]`, `skills: [.agents/plugins/principal-architect-workspace/.state/pa-skills.json]`, `rules: [.agents/rules]`, `inheritMcp: true`.
      - `pa-principal-architect.md`: `mainAgent: true`, `subagent: true`, `tools: [view_file, read_file, write_to_file, write_file, replace_file_content, edit_file, list_dir, grep_search, find_by_name, code_search, run_command, invoke_subagent, ask_question, send_message]`, `skills: [.agents/plugins/principal-architect-workspace/.state/pa-skills.json]`, `rules: [.agents/rules]`, `inheritMcp: true`.
      - `pa-engineer.md`: `mainAgent: false`, `subagent: true`, `inheritCustomizations: false`, `tools: [view_file, read_file, write_to_file, write_file, replace_file_content, edit_file, list_dir, grep_search, find_by_name, code_search, run_command, send_message]` (MUST OMIT `invoke_subagent`, `ask_question`, `search_web`, `search_marketplace`), `skills: [.agents/plugins/principal-architect-workspace/.state/pa-skills.json]`, `rules: [.agents/plugins/principal-architect-workspace/.state/pa-worker-rules.json]`, `inheritMcp: true`.
      - `pa-auditor.md`: `mainAgent: true`, `subagent: true`, `inheritCustomizations: false`, `tools: [view_file, read_file, list_dir, grep_search, find_by_name, code_search, run_command, send_message]` (MUST OMIT all file-write tools and `invoke_subagent`), `skills: [.agents/plugins/principal-architect-workspace/.state/pa-skills.json]`, `rules: [.agents/plugins/principal-architect-workspace/.state/pa-worker-rules.json]`, `inheritMcp: false`.
      - `pa-debugger.md`: `mainAgent: true`, `subagent: true`, `tools: [view_file, read_file, write_to_file, write_file, replace_file_content, edit_file, list_dir, grep_search, find_by_name, code_search, run_command, ask_question, send_message]`, `skills: [.agents/plugins/principal-architect-workspace/.state/pa-skills.json]`, `rules: [.agents/plugins/principal-architect-workspace/.state/pa-worker-rules.json]`, `inheritMcp: true`.
  - **Rule File Compliance:** `daemon/workspace-plugin/principal-architect/rules/00-pa-operating-model.md` MUST NOT have YAML frontmatter and must be `< 8 KB`.
  - **Lazy Imports in `pa_cli.py` (Charter R1 & R8):** Keep `pa_cli.py` stdlib-only at module top-level; lazy-import `schemas`, `pre_tool_gate`, and `escalation` inside `_cmd_pr_approve_plan` and `_cmd_escalate`.

## 3. Concrete Implementation Checklist

- [ ] **`daemon/workspace-plugin/principal-architect/agents/{pa-chief-architect,pa-principal-architect,pa-engineer,pa-auditor,pa-debugger}.md`:**
  - Create all 5 agent files with exact YAML frontmatter per SPEC §5.2 / Charter R6 and clear, KV-cache-stable Markdown role instructions covering:
    - Split-Authority ownership (`PROGRAM.md`, `PROJECT.md` Part I vs. Part II/III, `WORKORDER.md` Part I vs. Part II, `AUDIT-round-<K>.md`).
    - Spawn header protocol (`PA_ROLE:`, `PR_ID:`, `WO_ID:`, `PROGRAMME_ID:`).
    - Verification, receipt stamping (`pa wo verify <WO-ID>`), audit publishing (`pa pr post-audit <PR-ID> --file <path>`), and upward escalation (`pa escalate`).
- [ ] **`daemon/workspace-plugin/principal-architect/rules/00-pa-operating-model.md`:**
  - Author the canonical operating-model rule (no YAML frontmatter, `< 8 KB`) establishing the three-tier authorization model (`Chief Architect -> Principal Architect -> Engineer / Auditor / Debugger`), the plan gate binding at the human -> Architect boundary, verification of committed `PROJECT.md` `status: APPROVED` provenance, and Strict Boundary Box rules.
- [ ] **`daemon/workspace-plugin/principal-architect/skills/principal-architect/SKILL.md`:**
  - Author the in-plugin `SKILL.md` with valid YAML frontmatter (`name: principal-architect`, `description: ...`) and concise reference instructions for the 3-tier Split-Authority workflow, stacked Git branch topology, `pa` CLI commands (`enroll`, `unenroll`, `status`, `mode`, `pr approve-plan`, `wo verify`, `escalate`), model routing (`flash_lite`, `flash`, `inherit`), and Step 6A/6B Cold-Firewall Audit & Graduation gates.
- [ ] **`pa pr approve-plan <PR-ID>` and `pa escalate` in `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`:**
  - **1. `pa pr approve-plan <PR-ID> [--path <repo_path>]`:**
    - In `build_parser()`, add a `pr` subcommand group (`p_pr = subparsers.add_parser("pr", help="Pull Request lifecycle commands.")`, `pr_subparsers = p_pr.add_subparsers(dest="pr_command", metavar="<subcommand>")`) and register `approve-plan`:
      - Positional `pr_id` (`help="Pull Request ID (e.g. PR-02) or folder slug."`)
      - Optional `--path` (`default="."`, `help="Path to the target repository (default: current directory)."`)
    - Implement `_cmd_pr_approve_plan(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int`:
      - Lazy-import `schemas` and `pre_tool_gate`.
      - Resolve `repo_root = common.find_repo_root(Path(args.path).expanduser(), runner=runner)`. If `None`, print error to `sys.stderr` and return `2`.
      - Locate the matching `pr-*/PROJECT.md` in `ws_dir = common.workspace_dir(repo_root)` (matching `proj_doc.spec.charter.pr_id.upper() == args.pr_id.strip().upper()` or `pr_dir.name == args.pr_id.strip()`). If not found or invalid, print error to `sys.stderr` and return `1`.
      - Verify `charter_hash` if `proj_doc.spec.charter.charter_locked` (and `proj_doc.spec.charter.charter_hash` is set): if `not schemas.verify_charter_hash(proj_md)`, print error to `sys.stderr` and return `1`.
      - Verify `len(proj_doc.spec.work_orders) >= 1`: if empty, print error to `sys.stderr` and return `1`.
      - Load all `wo*/WORKORDER.md` files in `pr_dir` (`sorted(pr_dir.glob("wo*/WORKORDER.md"))`). Verify at least one `WORKORDER.md` exists and every `row.id` in `proj_doc.spec.work_orders` has a matching `WORKORDER.md`.
      - For each `wo_md`:
        - Load `wo_doc = schemas.load_workorder(wo_md)` (catching any validation error, printing to `sys.stderr`, and returning `1`).
        - Verify `wo_doc.spec.pr_id.upper() == proj_doc.spec.charter.pr_id.upper()`.
        - Verify every pattern `af` in `wo_doc.spec.allowed_files` is within `proj_doc.spec.charter.allowed_modules` via `pre_tool_gate._is_pattern_within_allowed_modules(af, proj_doc.spec.charter.allowed_modules)`. If any `af` is outside `allowed_modules`, print error to `sys.stderr` and return `1`.
      - Stamp `spec_hash` on each `wo_md`:
        - Compute `h = schemas.compute_spec_hash(wo_md)`.
        - Set `wo_doc.spec.spec_hash = h` and write `wo_md` via `schemas.dump_document(wo_doc.spec, wo_doc.sections)`.
        - Assert `schemas.verify_spec_hash(wo_md)` is `True`.
      - Update `PROJECT.md`:
        - Set `proj_doc.spec.status = schemas.PRState.APPROVED`.
        - If `proj_doc.spec.approved_at is None`: set `proj_doc.spec.approved_at = state_db.utc_now_iso()`.
        - Write `proj_md` via `schemas.dump_document(proj_doc.spec, proj_doc.sections)`.
        - If `proj_doc.spec.charter.charter_locked` and `proj_doc.spec.charter.charter_hash`: assert `schemas.verify_charter_hash(proj_md)` is `True`.
      - If `(ws_dir / ".state" / "state.db").is_file()`:
        - Resolve any open `plan_approval` items for `proj_doc.spec.charter.pr_id` in `attention_queue`.
      - Print confirmation to `sys.stderr` and return `0`.
  - **2. `pa escalate`:**
    - In `build_parser()`, register `escalate`:
      - `--level`: choices `["wo_to_pa", "pa_to_chief", "chief_to_human"]`, default `None`.
      - `--to-pa`: `action="store_true"`
      - `--to-chief`: `action="store_true"`
      - `--to-human`: `action="store_true"`
      - `--source-role`: default `None`
      - `--target-role`: default `None`
      - `--pr-id`: default `None`
      - `--wo-id`: default `None`
      - `--blocker-type`: default `"scope"`
      - `--reason-code`: default `"MANUAL_ESCALATION"`
      - `--requested-file`: `action="append"`, default `None`
      - `--summary`: default `None`
      - `--path`: default `"."`
      - Optional positional `summary_pos` (`nargs="?"`, default `None`) so either `pa escalate --to-chief --pr-id PR-02 --summary "Need module X"` or `pa escalate --to-chief "Need module X"` works seamlessly.
    - Implement `_cmd_escalate(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int`:
      - Lazy-import `escalation`.
      - Resolve `repo_root = common.find_repo_root(Path(args.path).expanduser(), runner=runner)`. Return `2` if not a git repo.
      - Determine `(level, source_role, target_role)`:
        - If `args.to_human` or `args.level == "chief_to_human"`: `("chief_to_human", args.source_role or "chief", args.target_role or "human")`
        - Else if `args.to_chief` or `args.level == "pa_to_chief"`: `("pa_to_chief", args.source_role or "pa", args.target_role or "chief")`
        - Else: `("wo_to_pa", args.source_role or "engineer", args.target_role or "pa")`
      - `summary_str = (args.summary or args.summary_pos or "").strip()`
      - If `not summary_str`: print error (`"Error: --summary is required for pa escalate"`) to `sys.stderr` and return `1`.
      - Open `state_db.StateDB(common.workspace_dir(repo_root) / ".state" / "state.db") as db`:
        - `exec_mode = db.get_config("execution_mode") or "monitored"`
        - `enqueue = (target_role == "human") or (exec_mode == "autonomous")`
        - `row = escalation.record_escalation(db, level=level, source_role=source_role, target_role=target_role, pr_id=args.pr_id, wo_id=args.wo_id, blocker_type=args.blocker_type, reason_code=args.reason_code, requested_files=args.requested_file or [], summary=summary_str, enqueue_if_needed=enqueue, attention_kind="escalation", attention_title=f"Escalation ({args.reason_code}): {args.wo_id or args.pr_id or level}", attention_priority=15 if target_role == "human" else 20)`
        - Print `row["escalation_id"]` to `sys.stdout` and return `0`.
- [ ] **`tests/test_hooks_monitored_vs_autonomous.py`:**
  - Add unit and integration tests for `WO-02.6`:
    1. **Agent frontmatter, rule, and skill validation test (Charter G7 & R6, SPEC §5.2):**
       - Parses all 5 `daemon/workspace-plugin/principal-architect/agents/pa-*.md` files and verifies:
         - Non-empty `name` and `description`, `model == "inherit"`, `excludeDefaultComponents is False`.
         - `pa-engineer.md` and `pa-auditor.md` have `inheritCustomizations is False`, `skills == [".agents/plugins/principal-architect-workspace/.state/pa-skills.json"]`, `rules == [".agents/plugins/principal-architect-workspace/.state/pa-worker-rules.json"]`.
         - `pa-engineer.md` has `mainAgent is False`, `subagent is True`, `inheritMcp is True`, and omits `invoke_subagent`, `ask_question`, `search_web`, `search_marketplace` from `tools`.
         - `pa-auditor.md` has `inheritMcp is False` and omits all file-write tools (`write_to_file`, `write_file`, `replace_file_content`, `edit_file`, `multi_replace_file_content`) and `invoke_subagent` from `tools`.
         - `pa-chief-architect.md` and `pa-principal-architect.md` have `mainAgent is True`, `subagent is True`, `inheritMcp is True`, and `rules == [".agents/rules"]`.
       - Verifies `daemon/workspace-plugin/principal-architect/rules/00-pa-operating-model.md` exists, does NOT start with `---` (no YAML frontmatter), and is `< 8192` bytes.
       - Verifies `daemon/workspace-plugin/principal-architect/skills/principal-architect/SKILL.md` exists and has valid YAML frontmatter with `name == "principal-architect"` and non-empty `description`.
    2. **`pa pr approve-plan <PR-ID>` CLI test (Charter G7 & R7, SPEC §8):**
       - Rejects (exit `1`) when a Work Order's `allowed_files` falls outside `charter.allowed_modules`.
       - Rejects (exit `1`) when `PROJECT.md` Part I `charter_hash` has been tampered with (`charter_locked: true`).
       - Succeeds (exit `0`) when valid: stamps `spec_hash` on all `wo*/WORKORDER.md` files (`schemas.verify_spec_hash` is `True`), sets `PROJECT.md` `status: APPROVED` and `approved_at`, preserves `charter_hash`, and resolves any open `plan_approval` item in `attention_queue`.
    3. **`pa escalate` CLI test (Charter G7 & R7, SPEC §8):**
       - Verifies `pa escalate --to-pa`, `pa escalate --to-chief`, and `pa escalate --to-human` record rows in `state.db` `escalations` with the expected `level`, `source_role`, `target_role`, `requested_files_json`, and `summary`, and enqueue into `attention_queue` when targeting `human` or in `autonomous` mode.
    4. **PR-02 Dogfood Workspace Validation Test:**
       - Loads this repository's own `.agents/skills/principal-architect-workspace/pr-02-agents-and-dual-mode-hooks/PROJECT.md` and `WO-02.1`..`WO-02.6` `WORKORDER.md` files via `schemas.load_project` and `schemas.load_workorder`, verifying `schemas.verify_charter_hash` and `schemas.verify_spec_hash` pass on every single file!

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 hash over `allowed_files` (or run `pa wo verify WO-02.6`), update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-02-agents-and-dual-mode-hooks/wo6-agents-rules-skill-and-approve-plan` with message:
   ```text
   WO-02.6: custom role agents, operating rule, SKILL.md, pa pr approve-plan, and pa escalate

   PA-WorkOrder: WO-02.6
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

- **Status:** `COMPLETED` (attempt 1 of 5)
- **Receipt ID:** `rcpt_b620400d70e1` (`tree_hash`: `b620400d70e1e92efa9ba535e5b52822335abd4508c6283a8e84caed1c21247b`)
- **Files Created / Modified:**
  - `daemon/workspace-plugin/principal-architect/agents/pa-chief-architect.md`
  - `daemon/workspace-plugin/principal-architect/agents/pa-principal-architect.md`
  - `daemon/workspace-plugin/principal-architect/agents/pa-engineer.md`
  - `daemon/workspace-plugin/principal-architect/agents/pa-auditor.md`
  - `daemon/workspace-plugin/principal-architect/agents/pa-debugger.md`
  - `daemon/workspace-plugin/principal-architect/rules/00-pa-operating-model.md`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/SKILL.md`
  - `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`
  - `tests/test_hooks_monitored_vs_autonomous.py`
- **Verification Summary:** `./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests` — `85 passed in 16.02s`, `All checks passed!`.
- **Out-of-Scope Findings:** None.

