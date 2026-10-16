---
schema_version: 1
wo_id: WO-02.1
pr_id: PR-02
title: Dual-mode escalation engine (decide R1-R6), structural blocker signatures,
  hook I/O helpers, and hooks.json
complexity: architect
status: PENDING
allowed_files:
- daemon/workspace-plugin/principal-architect/scripts/escalation.py
- daemon/workspace-plugin/principal-architect/hooks.json
- tests/test_hooks_monitored_vs_autonomous.py
forbidden_files:
- SPEC.md
- docs/positioning-paper.md
- .agents/skills/principal-architect-workspace/pr-02-agents-and-dual-mode-hooks/PROJECT.md
- .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py
  tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests
max_attempts: 5
max_structural_failures: 2
spec_hash: aa1072b4b8176cd14e4bbec5a2bfde3a44a4e276f767aa146e90b26e5b1dc20c
completion: null
---

# WO-02.1 — Dual-Mode Escalation Engine, Structural Signatures, Hook I/O & `hooks.json`

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-02` (`pr-02-agents-and-dual-mode-hooks`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T20:05:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/workspace-plugin/principal-architect/scripts/escalation.py` (the pure dual-mode decision engine `decide(rule, mode, ctx)` covering rules `R1`, `R1b`, `R2`, `R3`, `R4`, `R5`, `R6` symmetrically across `monitored` and `autonomous` modes, `STRUCTURAL_SIGNATURES` and `is_structural_blocker`, `record_escalation`, `enqueue_attention`, and hook stdin/stdout helpers `extract_workspace_paths`, `read_hook_input`, `write_hook_output`), author `daemon/workspace-plugin/principal-architect/hooks.json` registering `PreInvocation`, `PreToolUse`, `PostToolUse`, and `Stop`, and implement initial unit tests in `tests/test_hooks_monitored_vs_autonomous.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/escalation.py`
  - `daemon/workspace-plugin/principal-architect/hooks.json`
  - `tests/test_hooks_monitored_vs_autonomous.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-02-agents-and-dual-mode-hooks/wo1-escalation-engine-and-hook-io/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Stdlib-Only Requirement:** `escalation.py` MUST NOT import `pydantic`, `yaml`, or `schemas` at module top-level so hook fast-paths remain sub-millisecond and stdlib-only (importing only stdlib modules, `common`, and `state_db`).
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh`. Commit only on the currently checked-out branch `pr-02-agents-and-dual-mode-hooks/wo1-escalation-engine-and-hook-io` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R9):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/escalation.py`:**
  1. **Constants & Structural Blocker Detection (Charter G1 & SPEC §3.2, §7.3):**
     - Define `RULES: tuple[str, ...] = ("R1", "R1b", "R2", "R3", "R4", "R5", "R6")`.
     - Define `MODES: tuple[str, ...] = ("monitored", "autonomous")`.
     - Define `STRUCTURAL_SIGNATURES: tuple[str, ...]` containing lowercase substring patterns for structural/environmental blockers where retrying the identical command is futile:
       - `"hardware is currently tied"`
       - `"exclusive hardware"`
       - `"mcp lock"`
       - `"permissiondecision: deny"`
       - `"permission_denied"`
       - `"blocker_structural"`
       - `"structural_blocker"`
       - `"command not found"`
       - `"no such file or directory: './.venv"`
       - `"modulenotfounderror: no module named 'pydantic'"`
       - `"modulenotfounderror: no module named 'yaml'"`
       - `"address already in use"`
     - Implement `is_structural_blocker(text: str | None) -> bool`: returns `True` if `text` is non-empty and any pattern in `STRUCTURAL_SIGNATURES` appears in `text.lower()`, else `False`.
  2. **Pure Dual-Mode Decision Engine (`decide(rule: str, mode: str, ctx: Mapping[str, Any] | None = None) -> dict[str, Any]`, Charter G1 & SPEC §7.2):**
     - Validate `rule in RULES` (raise `ValueError(f"Unknown rule: {rule!r}")` if invalid) and normalize/validate `mode` (`"monitored"` or `"autonomous"`; raise `ValueError(f"Invalid execution mode: {mode!r}")` if not in `MODES`).
     - Extract optional context fields from `ctx or {}`: `path = str(c.get("path", "<target>"))`, `pr_id = str(c.get("pr_id") or "PR-??")`, `wo_id = str(c.get("wo_id") or "WO-??")`, `head_sha = str(c.get("head_sha") or "HEAD")`, `role = str(c.get("role") or "")`, `auto_approve_pr_plans = bool(c.get("auto_approve_pr_plans", False))`, `plan_valid = bool(c.get("plan_valid", False))`, `requested_files = list(c.get("requested_files") or ([path] if path != "<target>" else []))`.
     - Return a dictionary containing:
       - `"permissionDecision": "allow" | "ask" | "deny"`
       - `"decision": "allow" | "ask" | "deny"` (mirrors `"permissionDecision"` for direct harness compatibility)
       - `"reason": str`
       - `"rule": rule`
       - `"mode": mode`
       - `"increment_structural_failures": bool`
       - `"auto_approve_plan": bool`
       - `"escalation": dict[str, Any] | None` (structured metadata when an escalation or attention queue item should be persisted by the caller)
     - Implement the exact 7 rules × 2 modes of SPEC §7.2:
       - **`R1` (Architect No-Inline-Code Gate):**
         - `monitored`: `permissionDecision = "ask"`, `reason = f"Architect is attempting to edit '{path}' directly instead of dispatching pa-engineer. Allow one-off edit?"`, `escalation = None`, `increment_structural_failures = False`.
         - `autonomous`: `permissionDecision = "deny"`, `reason = f"Autonomous Mode (R1): Architects cannot edit source file '{path}' inline. Issue/amend a WORKORDER.md and invoke pa-engineer."`, `escalation = None`, `increment_structural_failures = False`.
       - **`R1b` (Fractal `PROJECT.md` Charter Lock & `allowed_modules`):**
         - `monitored`: `permissionDecision = "ask"`, `reason = f"Principal Architect is modifying the Chief Architect's locked PR Charter ({pr_id}) or touching '{path}' outside allowed_modules. Allow Charter amendment?"`, `escalation = None`, `increment_structural_failures = False`.
         - `autonomous`: `permissionDecision = "deny"`, `reason = f"Part I (PR Charter) of PROJECT.md ({pr_id}) is owned by the Chief Architect (or '{path}' is outside allowed_modules). Run `pa escalate --to-chief` to request a scope or interface change."`, `increment_structural_failures = False`, `escalation = {"level": "PA_TO_CHIEF", "source_role": "pa", "target_role": "chief", "pr_id": c.get("pr_id"), "wo_id": c.get("wo_id"), "blocker_type": "charter", "reason_code": "CHARTER_AMENDMENT_NEEDED", "requested_files": requested_files, "summary": f"PA attempted to modify locked Charter or file '{path}' outside allowed_modules on {pr_id}.", "enqueue_attention": True, "attention_kind": "charter_escalation", "attention_priority": 20, "attention_title": f"🔴 [Charter Escalation] {pr_id} requested Charter amendment ({path})"}`.
       - **`R2` (Plan Approval Gate on `invoke_subagent`):**
         - `monitored`: `permissionDecision = "ask"`, `reason = f"Approve PROJECT.md Part II Work Order decomposition for {pr_id} and start Worker execution?"`, `escalation = None`, `increment_structural_failures = False`, `auto_approve_plan = False`.
         - `autonomous`:
           - If `auto_approve_pr_plans and plan_valid`: `permissionDecision = "allow"`, `reason = f"Auto-approved PROJECT.md Part II Work Order decomposition for {pr_id}."`, `escalation = None`, `increment_structural_failures = False`, `auto_approve_plan = True`.
           - Else: `permissionDecision = "deny"`, `reason = f"Autonomous Mode (R2): PROJECT.md status for {pr_id} is not APPROVED. Enqueued plan approval in Human Attention Needed."`, `increment_structural_failures = False`, `auto_approve_plan = False`, `escalation = {"level": "PA_TO_HUMAN", "source_role": "pa", "target_role": "human", "pr_id": c.get("pr_id"), "wo_id": c.get("wo_id"), "blocker_type": "other", "reason_code": "PLAN_APPROVAL_REQUIRED", "requested_files": [], "summary": f"Plan approval required for {pr_id} before dispatching pa-engineer.", "enqueue_attention": True, "attention_kind": "plan_approval", "attention_priority": 10, "attention_title": f"🟠 [Plan Approval] {pr_id} Part II Work Order decomposition ready"}`.
       - **`R3` (Worker Strict Boundary Box & Spec Lock Gate):**
         - `monitored`: `permissionDecision = "ask"`, `reason = f"Worker {wo_id} wants to edit '{path}' outside allowed_files (or protected spec). Approve and add '{path}' to allowed_files?"`, `escalation = None`, `increment_structural_failures = False`.
         - `autonomous`: `permissionDecision = "deny"`, `reason = f"File '{path}' is outside your allowed_files (or mutates locked Part I of WORKORDER.md). Record an escalation_request in Part II (Completion Report) of WORKORDER.md with status: ESCALATED_TO_PA and finish your turn."`, `increment_structural_failures = True`, `escalation = {"level": "WORKER_TO_PA", "source_role": "engineer", "target_role": "pa", "pr_id": c.get("pr_id"), "wo_id": c.get("wo_id"), "blocker_type": "boundary", "reason_code": str(c.get("reason_code") or "BOUNDARY_EXPANSION_NEEDED"), "requested_files": requested_files, "summary": f"Worker {wo_id} attempted to edit '{path}' outside boundary box.", "enqueue_attention": True, "attention_kind": "boundary_escalation", "attention_priority": 20, "attention_title": f"🔴 [Boundary Escalation] {wo_id} requested access to {path}"}`.
       - **`R4` (Worker Git/GitHub Lockdown — Mode-Independent Hard Deny):**
         - Both `monitored` and `autonomous`: `permissionDecision = "deny"`, `reason = f"Worker git/gh lockdown (R4): pa-engineer is forbidden from executing branch, remote, or PR command: {c.get('command', path)}"`, `increment_structural_failures = True`, `escalation = None`.
       - **`R5` (Auditor Read-Only Lockdown — Mode-Independent Hard Deny):**
         - Both `monitored` and `autonomous`: `permissionDecision = "deny"`, `reason = f"Auditor read-only lockdown (R5): pa-auditor is strictly read-only and cannot mutate files or run mutating command: {c.get('command', path)}"`, `increment_structural_failures = False`, `escalation = None`.
       - **`R6` (Graduation Audit Gate):**
         - `monitored`: `permissionDecision = "ask"`, `reason = f"Cold-Firewall Audit has not approved current HEAD ({head_sha}) for {pr_id}. Override and allow graduation?"`, `escalation = None`, `increment_structural_failures = False`.
         - `autonomous`: `permissionDecision = "deny"`, `reason = f"Cannot graduate {pr_id}: current HEAD ({head_sha}) lacks an APPROVED Cold-Firewall Audit verdict."`, `escalation = None`, `increment_structural_failures = False`.
  3. **Database Escalation & Attention Helpers (`record_escalation` & `enqueue_attention`, Charter G1 & §2.2):**
     - `record_escalation(db: state_db.StateDB, *, level: str, source_role: str, target_role: str, pr_id: str | None = None, wo_id: str | None = None, blocker_type: str = "other", reason_code: str = "UNSPECIFIED", requested_files: Sequence[str] | None = None, summary: str = "", enqueue_if_needed: bool = False, attention_kind: str | None = None, attention_title: str | None = None, attention_priority: int = 20) -> dict[str, Any]`:
       - Calls `db.insert_escalation(...)` and, if `enqueue_if_needed` or `target_role == "human"`, also calls `enqueue_attention(db, ...)` linking `"escalation_id": row["escalation_id"]` in `action_payload`. Returns the inserted escalation row dict.
     - `enqueue_attention(db: state_db.StateDB, *, kind: str, title: str, priority: int = 10, pr_id: str | None = None, wo_id: str | None = None, action_payload: Mapping[str, Any] | None = None) -> dict[str, Any]`:
       - Calls `db.enqueue(...)` and returns the inserted attention queue row dict.
  4. **Hook Stdin/Stdout & Workspace Extraction Helpers (`extract_workspace_paths`, `read_hook_input`, `write_hook_output`, Charter G1, R1, R2):**
     - `extract_workspace_paths(payload: Mapping[str, Any] | None) -> list[str]`:
       - Inspects `payload` (if a dict) for `"workspacePaths"` (list of strings), `"workspaceUris"` (list of strings), `"workspaceRoot"` (string), `"cwd"` (string), and if none yield non-empty strings, falls back to `[os.getcwd()]`. Returns deduplicated list of strings.
     - `read_hook_input(stream: TextIO | None = None) -> dict[str, Any]`:
       - Reads from `stream or sys.stdin`. If empty/whitespace, returns `{}`. Parses with `json.loads`; if `JSONDecodeError` or not a `dict`, logs a concise warning to `sys.stderr` and returns `{}`.
     - `write_hook_output(payload: Mapping[str, Any], stream: TextIO | None = None) -> int`:
       - Writes `json.dumps(dict(payload), ensure_ascii=False) + "\n"` to `stream or sys.stdout`, flushes the stream, and returns `0`.
- [ ] **`daemon/workspace-plugin/principal-architect/hooks.json` (Charter G2 & SPEC §7):**
  - Create valid JSON matching Antigravity's plugin `hooks.json` schema with top-level key `"principal-architect"`:
    ```json
    {
      "principal-architect": {
        "enabled": true,
        "PreInvocation": [
          {
            "type": "command",
            "command": "python3 ${PLUGIN_ROOT}/scripts/pre_invocation.py",
            "timeout": 10
          }
        ],
        "PreToolUse": [
          {
            "matcher": "write_to_file|write_file|replace_file_content|edit_file|multi_replace_file_content|run_command|invoke_subagent",
            "hooks": [
              {
                "type": "command",
                "command": "python3 ${PLUGIN_ROOT}/scripts/pre_tool_gate.py",
                "timeout": 10
              }
            ]
          }
        ],
        "PostToolUse": [
          {
            "matcher": "*",
            "hooks": [
              {
                "type": "command",
                "command": "python3 ${PLUGIN_ROOT}/scripts/post_tool_receipt.py",
                "timeout": 10
              }
            ]
          }
        ],
        "Stop": [
          {
            "type": "command",
            "command": "python3 ${PLUGIN_ROOT}/scripts/stop_gate.py",
            "timeout": 10
          }
        ]
      }
    }
    ```
- [ ] **`tests/test_hooks_monitored_vs_autonomous.py`:**
  - Add thorough unit tests covering:
    1. Every `(rule, mode)` combination (`R1`, `R1b`, `R2` with `auto_approve_pr_plans=False` and `True`, `R3`, `R4`, `R5`, `R6`) across `"monitored"` and `"autonomous"`, asserting `permissionDecision`, `decision`, `reason`, `increment_structural_failures`, `auto_approve_plan`, and `escalation` metadata.
    2. Invalid `rule` or `mode` raising `ValueError`.
    3. `STRUCTURAL_SIGNATURES` and `is_structural_blocker` matching known lock/hook/env blockers and returning `False` on normal assertion/test failures (`AssertionError: assert 1 == 2`, `FAILED tests/test_foo.py`).
    4. `record_escalation` and `enqueue_attention` persisting rows into `StateDB` (`tmp_path / "state.db"`).
    5. `extract_workspace_paths`, `read_hook_input` (valid JSON, empty stdin, malformed JSON logging to stderr and returning `{}`), and `write_hook_output` returning `0`.
    6. `hooks.json` schema validation test: verifies `daemon/workspace-plugin/principal-architect/hooks.json` exists, parses as valid JSON, defines `PreInvocation`, `PreToolUse` (with the exact 7-tool matcher and `timeout: 10`), `PostToolUse`, and `Stop` pointing to `${PLUGIN_ROOT}/scripts/<hook>.py`.
    7. Import purity check: importing `escalation` does not import `pydantic`, `yaml`, or `schemas`.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 hash over `allowed_files`, update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block — using strictly valid `CompletionReport` keys: `status`, `attempt_num`, `receipt_id`, `commit_sha`, `files_modified`, `verification_summary`, `out_of_scope_findings`, `escalation_request`, `decisions_made`, `dead_ends`) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-02-agents-and-dual-mode-hooks/wo1-escalation-engine-and-hook-io` with message:
   ```text
   WO-02.1: dual-mode escalation engine, hook I/O helpers, and hooks.json

   PA-WorkOrder: WO-02.1
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

_Pending execution._
