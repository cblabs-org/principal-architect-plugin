---
schema_version: 1
wo_id: WO-02.4
pr_id: PR-02
title: "Stop gate implementing two-tier retry ceiling (max_attempts=5 vs max_structural_failures=2) and Case A/B + auditor checks"
complexity: architect
status: PENDING
allowed_files:
  - daemon/workspace-plugin/principal-architect/scripts/stop_gate.py
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
spec_hash: 2e9932eb895dfa79afc92b34a4b4d7c4a74b1803d6c5b3202d83741b247e282a
completion: null
---

# WO-02.4 — `Stop` Gate, Two-Tier Retry Ceiling, and Completion Invariants

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-02` (`pr-02-agents-and-dual-mode-hooks`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T20:05:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/workspace-plugin/principal-architect/scripts/stop_gate.py` (`evaluate_stop` and `main()`) enforcing SPEC §7.4 and PR-02 Charter G5, R1, R2, R4, and R5:
1. `< 1 ms` unenrolled fast-exit (`common.is_repo_enrolled`) with zero top-level imports of `pydantic`, `yaml`, or `schemas`.
2. Two-tier retry ceiling for `pa-engineer`:
   - **Fast-Fail Structural Escalation (`structural_failures >= max_structural_failures` [2] or `>= 3` consecutive `ERROR_MESSAGE` steps in `transcript.jsonl`):** marks Work Order `ESCALATED_TO_PA` (`blocker_type="structural"`), records escalation in `state.db`, and returns `{}` immediately so the Worker stops without burning remaining attempts.
   - **Productive Attempt Ceiling (`attempt_num >= max_attempts` [5] when not completed):** marks Work Order `BLOCKED`, records escalation in `state.db`, enqueues a `pa-debugger` item (`🔬 [Debug <WO-ID>]`) in `attention_queue`, and returns `{}`.
3. Normal completion checks for `pa-engineer`:
   - **Case A (`status` is `ESCALATED_TO_PA` or `BLOCKED`):** verifies `completion.escalation_request` or `completion.verification_summary` explains the blocker, records escalation in `state.db`, and returns `{}`.
   - **Case B (`status` is `COMPLETED` or `IN_PROGRESS` / `PENDING`):** verifies (1) a valid receipt (`valid == 1`) in `verification_receipts` matching `post_tool_receipt.compute_tree_hash(repo_root, allowed_files)`, (2) clean `git status --porcelain` on `allowed_files` + `WORKORDER.md` and latest commit subject starting with `<WO-ID>:`, and (3) valid `CompletionReport` (`status: COMPLETED`, `receipt_id`, `commit_sha`, `files_modified`, `verification_summary`) with intact Part I `spec_hash`. If any check fails and `attempt_num < max_attempts`, increments `attempt_num` in `sessions` (Charter R5 bounded continuation cap) and returns `{"decision": "continue", "reason": "..."}`.
4. Auditor Stop check for `pa-auditor` requiring a valid `AuditReport` (`AUDIT-round-*.md`) matching current `HEAD` SHA, with bounded continuation cap (`max 5` continuations).
5. Comprehensive unit and subprocess tests in `tests/test_hooks_monitored_vs_autonomous.py`.

## 2. Boundary Box & Invariants

- **Allowed Files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/stop_gate.py`
  - `tests/test_hooks_monitored_vs_autonomous.py`
- **Forbidden Files (`forbidden_files`):**
  - `SPEC.md`, `docs/positioning-paper.md`, `PROJECT.md`, `PROGRAM.md`, and any file outside `allowed_files` (except Part II of this `WORKORDER.md`).
- **Architectural Invariants:**
  - **Lazy Imports & `< 1 ms` Fast-Exit (Charter R1):** `stop_gate.py` MUST NOT import `pydantic`, `yaml`, or `schemas` at module top-level. Import `schemas` lazily inside functions only after confirming the repository is enrolled.
  - **Shared `compute_tree_hash` (Charter R4):** Call `post_tool_receipt.compute_tree_hash(real_root, wo_doc.spec.allowed_files)` directly — do not duplicate tree-hashing logic.
  - **Bounded Stop-Hook Continuations (Charter R5):** Every time `stop_gate.py` returns `{"decision": "continue", ...}`, it MUST increment `attempt_num` in `sessions` so that a session can never be continued infinitely (capping at `max_attempts`, default 5).
  - **Hook I/O Contract (Charter R2):** Always output a single JSON object (`{}` or `{"decision": "continue", "reason": "..."}`) and exit `0`. Catch any unexpected exception, log to `sys.stderr`, and output `{}` with exit `0`.

## 3. Concrete Implementation Checklist

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/stop_gate.py`:**
  - Top-level imports: stdlib (`os`, `re`, `subprocess`, `sys`, `collections.abc`, `pathlib.Path`, `typing.Any`) plus `common`, `escalation`, `state_db`, `pre_tool_gate`, and `post_tool_receipt` (NO top-level `pydantic`, `yaml`, or `schemas`!).
  - Helper `_has_consecutive_error_steps(steps: Sequence[Mapping[str, Any]], threshold: int = 3) -> bool`:
    - Inspects `steps` from `common.read_transcript`: a step is an error step if `str(step.get("type") or "").upper() in ("ERROR_MESSAGE", "CORTEX_STEP_TYPE_ERROR_MESSAGE")` or `str(step.get("status") or "").upper() == "ERROR"`.
    - Returns `True` if there are `>= threshold` consecutive error steps at the end of `steps` (or any run of `>= threshold` consecutive error steps in `steps`).
  - Helper `_check_git_clean_and_committed(repo_root: Path, wo_id: str, allowed_files: Sequence[str], wo_rel_posix: str, *, runner: common.Runner = common.run) -> tuple[bool, list[str]]`:
    - Runs `runner(["git", "status", "--porcelain", "-uall"], cwd=repo_root)`.
    - Checks if any dirty/untracked file in porcelain output matches `wo_rel_posix` or `pre_tool_gate.matches_any_pattern(rel_p, allowed_files)` (ignoring `/.state/` and `.agents/plugins.json`). If any such file is dirty/untracked, appends `"uncommitted files in allowed_files or WORKORDER.md"`.
    - Runs `runner(["git", "log", "-n", "5", "--format=%s"], cwd=repo_root)`. Checks whether the latest commit subject (or a recent commit subject on the branch) starts with `f"{wo_id}:"` (case-insensitive prefix match `subj.upper().startswith(f"{wo_id.upper()}:")`). If not, appends `f"missing git commit starting with '{wo_id}:'"`.
    - Returns `(len(problems) == 0, problems)`.
  - **`evaluate_stop(payload: Mapping[str, Any], *, repo_root: Path | str | None = None, runner: common.Runner = common.run) -> dict[str, Any]`:**
    - **1. Unenrolled Fast-Exit:**
      - If `repo_root is None`:
        - `workspace_paths = escalation.extract_workspace_paths(payload)`
        - If `not common.is_repo_enrolled(workspace_paths)`: return `{}` immediately!
        - Resolve `resolved_root` via `common.find_repo_root`. If `None`: return `{}`.
      - Else:
        - Check local `state.db` or `common.is_repo_enrolled([str(repo_root)])` (same pattern as `post_tool_receipt.py`).
      - `real_root = Path(os.path.realpath(resolved_root))`
      - `ws_dir = common.workspace_dir(real_root)`
      - `db_file = ws_dir / ".state" / "state.db"`
      - If `not db_file.is_file()`: return `{}`.
    - **2. Termination Reason Check:**
      - `term_reason = str(payload.get("terminationReason") or payload.get("termination_reason") or "").strip()`
      - If `term_reason` and `term_reason != "NO_TOOL_CALL"`: return `{}`.
    - **3. Session & Role Lookup:**
      - Open `state_db.StateDB(db_file) as db`:
        - `conv_id = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()`
        - If `not conv_id`: return `{}`.
        - `session = db.get_session(conv_id)`
        - If `session is None`: return `{}`.
        - `role = pre_tool_gate._normalize_role(str(session.get("role") or ""))`
        - If `role not in ("engineer", "auditor")`: return `{}`.
    - **4. `role == "engineer"` (`pa-engineer` Stop Gate):**
      - Lazily import `schemas`.
      - `wo_id = str(session.get("wo_id") or "").strip()`
      - `pr_id = str(session.get("pr_id") or "").strip()`
      - `wo_doc = pre_tool_gate._find_bound_workorder(ws_dir, pr_id or None, wo_id or None)`
      - If `wo_doc is None`: return `{}`.
      - `resolved_wo_id = wo_doc.spec.wo_id`
      - `resolved_pr_id = wo_doc.spec.pr_id`
      - `max_attempts = int(wo_doc.spec.max_attempts)`
      - `max_structural = int(wo_doc.spec.max_structural_failures)`
      - `attempt_num = int(session.get("attempt_num") or 1)`
      - `structural_failures = int(session.get("structural_failures") or 0)`
      - Read transcript steps if `transcriptPath` / `transcript_path` is present in `payload`:
        - `t_path = payload.get("transcriptPath") or payload.get("transcript_path")`
        - `steps = common.read_transcript(common._strip_file_uri(str(t_path))) if t_path else []`
        - `has_3_errors = _has_consecutive_error_steps(steps, threshold=3)`
      - **Step 4A — Fast-Fail Structural Escalation (`structural_failures >= max_structural` or `has_3_errors`):**
        - Update `wo_doc.spec.status = schemas.WorkOrderStatus.ESCALATED_TO_PA`.
        - If `wo_doc.spec.completion is None` or `wo_doc.spec.completion.status not in (schemas.WorkOrderStatus.ESCALATED_TO_PA, schemas.WorkOrderStatus.BLOCKED)`:
          - Set `wo_doc.spec.completion = schemas.CompletionReport(status=schemas.WorkOrderStatus.ESCALATED_TO_PA, attempt_num=min(max(attempt_num, 1), 5), verification_summary="Fast-fail structural escalation triggered by Stop gate.", escalation_request=schemas.EscalationRequest(blocker_type="structural", reason_code="STRUCTURAL_FAST_FAIL", requested_files=[], summary=f"Fast-fail structural escalation on {resolved_wo_id} (structural_failures={structural_failures}, consecutive_errors={has_3_errors})."))`
        - Write `wo_doc.path` via `schemas.dump_document(wo_doc.spec, wo_doc.sections)` if `wo_doc.path.is_file()`.
        - Record escalation in `state.db`:
          `escalation.record_escalation(db, level="wo_to_pa", source_role="engineer", target_role="pa", pr_id=resolved_pr_id, wo_id=resolved_wo_id, blocker_type="structural", reason_code="STRUCTURAL_FAST_FAIL", summary=f"Work Order {resolved_wo_id} fast-failed on structural blocker (structural_failures={structural_failures}/{max_structural}, consecutive_errors={has_3_errors}).", enqueue_if_needed=True, attention_kind="escalation", attention_title=f"Structural blocker on {resolved_wo_id}", attention_priority=20)`
        - Return `{}`.
      - **Step 4B — Case A: Explicit Blocker / Escalation (`wo_doc.spec.status in (ESCALATED_TO_PA, BLOCKED)` or `(wo_doc.spec.completion and wo_doc.spec.completion.status in (ESCALATED_TO_PA, BLOCKED))`):**
        - Check if `wo_doc.spec.completion is not None` and (`wo_doc.spec.completion.escalation_request is not None` or `bool(wo_doc.spec.completion.verification_summary.strip())`) and (`not wo_doc.spec.spec_hash` or `schemas.verify_spec_hash(wo_doc.path)`):
          - Extract `esc_req = wo_doc.spec.completion.escalation_request`.
          - `b_type = esc_req.blocker_type if esc_req is not None else "scope"`
          - `r_code = esc_req.reason_code if esc_req is not None else wo_doc.spec.status.value`
          - `req_files = list(esc_req.requested_files) if esc_req is not None else []`
          - `summary_txt = esc_req.summary if esc_req is not None else wo_doc.spec.completion.verification_summary`
          - Record escalation in `state.db`:
            `escalation.record_escalation(db, level="wo_to_pa", source_role="engineer", target_role="pa", pr_id=resolved_pr_id, wo_id=resolved_wo_id, blocker_type=b_type, reason_code=r_code, requested_files=req_files, summary=summary_txt)`
          - Return `{}` (allow clean return to PA).
        - If `completion` is missing or lacks explanation (and `attempt_num < max_attempts`):
          - `db.update_session(conv_id, attempt_num=attempt_num + 1)`
          - Return `{"decision": "continue", "reason": f"Work Order {resolved_wo_id} (attempt {attempt_num}/{max_attempts}) is marked {wo_doc.spec.status.value} but lacks a valid CompletionReport/escalation_request explaining the blocker."}`.
      - **Step 4C — Case B: Normal Completion Invariants (`status == COMPLETED` or `IN_PROGRESS` / `PENDING`):**
        - Evaluate all 3 completion invariants:
          1. **Receipt check:** `current_tree_hash = post_tool_receipt.compute_tree_hash(real_root, wo_doc.spec.allowed_files)`, `receipt = db.latest_valid_receipt(resolved_wo_id, tree_hash=current_tree_hash)`. Missing if `receipt is None`.
          2. **Git clean & `<WO-ID>:` commit check:** `wo_rel_posix = wo_doc.path.resolve().relative_to(real_root).as_posix()`, `git_ok, git_problems = _check_git_clean_and_committed(real_root, resolved_wo_id, wo_doc.spec.allowed_files, wo_rel_posix, runner=runner)`.
          3. **CompletionReport & `spec_hash` check:**
             - `comp = wo_doc.spec.completion`
             - Valid iff `wo_doc.spec.status == schemas.WorkOrderStatus.COMPLETED`, `comp is not None`, `comp.status == schemas.WorkOrderStatus.COMPLETED`, `bool(comp.receipt_id)`, `bool(comp.commit_sha)`, `bool(comp.verification_summary and comp.verification_summary.strip())`, and (`not wo_doc.spec.spec_hash` or `schemas.verify_spec_hash(wo_doc.path)`).
        - If all 3 invariants pass:
          - Return `{}`!
        - If any invariant fails:
          - **Productive Attempt Ceiling Check (`attempt_num >= max_attempts` [5]):**
            - Update `wo_doc.spec.status = schemas.WorkOrderStatus.BLOCKED`.
            - If `wo_doc.spec.completion is None` or `wo_doc.spec.completion.status != schemas.WorkOrderStatus.BLOCKED`:
              - Set `wo_doc.spec.completion = schemas.CompletionReport(status=schemas.WorkOrderStatus.BLOCKED, attempt_num=min(max(attempt_num, 1), 5), verification_summary=f"Blocked after reaching max_attempts ({max_attempts}).")`
            - Write `wo_doc.path` via `schemas.dump_document(wo_doc.spec, wo_doc.sections)` if `wo_doc.path.is_file()`.
            - Record escalation in `state.db`:
              `escalation.record_escalation(db, level="wo_to_pa", source_role="engineer", target_role="debugger", pr_id=resolved_pr_id, wo_id=resolved_wo_id, blocker_type="verification_ceiling", reason_code="MAX_ATTEMPTS_EXCEEDED", summary=f"Work Order {resolved_wo_id} exhausted {max_attempts} verification attempts; escalating to pa-debugger.", enqueue_if_needed=True, attention_kind="debugger_escalation", attention_title=f"🔬 [Debug {resolved_wo_id}] {wo_doc.spec.title}", attention_priority=10)`
            - Return `{}` (allow Worker to stop with `BLOCKED` and `pa-debugger` enqueued!).
          - **Otherwise (`attempt_num < max_attempts`):**
            - Increment `attempt_num` in `sessions`: `db.update_session(conv_id, attempt_num=attempt_num + 1)` (Charter R5).
            - Build clear reason string listing the failing invariant(s) (`missing verification receipt`, `uncommitted files`, `incomplete Completion Report`, `spec_hash mismatch`, etc.):
              `f"Work Order {resolved_wo_id} (attempt {attempt_num}/{max_attempts}) cannot complete yet: [{', '.join(missing_reasons)}]. Run \`pa wo verify {resolved_wo_id}\` to verify, stamp the receipt, and commit."`
            - Return `{"decision": "continue", "reason": reason_str}`.
    - **5. `role == "auditor"` (`pa-auditor` Stop Gate — SPEC §7.4.3):**
      - Lazily import `schemas`.
      - `pr_id = str(session.get("pr_id") or "").strip()`
      - `head_sha = post_tool_receipt._get_current_head_sha(real_root, runner=runner) or ""`
      - Check if any `AUDIT-round-*.md` file in `ws_dir` (for `pr_id` if specified) loads via `schemas.load_audit` and has `head_sha` matching `head_sha` (exact match or prefix match `head_sha.startswith(audit_doc.spec.head_sha)` / `audit_doc.spec.head_sha.startswith(head_sha)` when `head_sha` is non-empty).
      - If found: return `{}`.
      - If not found:
        - `attempt_num = int(session.get("attempt_num") or 1)`
        - If `attempt_num >= 5`:
          - `escalation.record_escalation(db, level="pa_to_chief", source_role="auditor", target_role="pa", pr_id=pr_id or None, blocker_type="audit_missing", reason_code="AUDITOR_STOP_TIMEOUT", summary=f"Auditor failed to publish AuditReport for {pr_id or 'PR'} after 5 Stop continuations.")`
          - Return `{}`.
        - `db.update_session(conv_id, attempt_num=attempt_num + 1)`
        - `target_pr = pr_id or "<PR-ID>"`
        - Return `{"decision": "continue", "reason": f"Publish your audit findings via `pa pr post-audit {target_pr} --file <path>` before finishing."}`.
  - **`main() -> int`:**
    - Reads hook payload via `escalation.read_hook_input()`, calls `evaluate_stop(payload)`, writes output via `escalation.write_hook_output(res)`, catches any unexpected exception to `sys.stderr` and outputs `{}` with exit `0`.
- [ ] **`tests/test_hooks_monitored_vs_autonomous.py`:**
  - Add unit and subprocess tests for `stop_gate.py`:
    1. **Unenrolled fast-exit & import purity test for `stop_gate.py` (Charter G2 & R1):**
       - Subprocess call on unenrolled directory outputs `{}` and exits `0`.
       - In-process timing `< 1.0 ms` and subprocess `sys.modules` check confirms `pydantic`, `yaml`, and `schemas` are NOT imported on the unenrolled path.
    2. **Two-tier retry ceiling tests (Charter G5, SPEC §7.4.1):**
       - **Fast-fail on `structural_failures >= 2`:** When `structural_failures == 2` (even at `attempt_num == 1`), `evaluate_stop` returns `{}` immediately, transitions `WORKORDER.md` to `ESCALATED_TO_PA`, and records a `STRUCTURAL_FAST_FAIL` escalation in `state.db`.
       - **Fast-fail on `>= 3` consecutive `ERROR_MESSAGE` steps in `transcript.jsonl`:** Even when `structural_failures == 0` and `attempt_num == 1`, a transcript with 3 consecutive `ERROR_MESSAGE` steps triggers fast-fail structural escalation and returns `{}`.
       - **Productive retry (`attempt_num < 5`, `structural_failures < 2`) vs. 5-attempt ceiling (`attempt_num >= 5`):**
         - At `attempt_num == 2` with missing receipt, returns `{"decision": "continue", ...}` and increments `attempt_num` to `3`.
         - At `attempt_num == 5` with missing receipt, returns `{}`, transitions `WORKORDER.md` to `BLOCKED`, records `MAX_ATTEMPTS_EXCEEDED` escalation, and enqueues `🔬 [Debug <WO-ID>]` in `attention_queue`.
    3. **Bounded Stop-hook continuation loop test (Charter R5):**
       - Calling `evaluate_stop` repeatedly on an incomplete `engineer` session starting at `attempt_num == 1` returns `"decision": "continue"` at most 4 times (`1->2`, `2->3`, `3->4`, `4->5`) and on the 5th call (`attempt_num == 5`) terminates with `{}` and `BLOCKED`.
    4. **Case A & Case B completion invariant tests (SPEC §7.4.2):**
       - **Case A:** Worker marks `WORKORDER.md` `ESCALATED_TO_PA` with a valid `escalation_request` -> `evaluate_stop` records escalation in `state.db` and returns `{}`.
       - **Case B failure modes:** (a) valid commit and `CompletionReport` but stale/invalid receipt (`tree_hash` mismatch after post-verify edit) -> `"continue"`; (b) valid receipt but uncommitted file in `allowed_files` -> `"continue"`; (c) valid receipt and clean git status but incomplete `CompletionReport` (`receipt_id: null`) -> `"continue"`.
       - **Case B success:** After `pa wo verify <WO-ID>` succeeds, `evaluate_stop` returns `{}`!
    5. **Auditor Stop gate tests (SPEC §7.4.3):**
       - `pa-auditor` session without `AUDIT-round-1.md` for current `HEAD` returns `{"decision": "continue", "reason": "Publish your audit findings via `pa pr post-audit ...`"}` and increments `attempt_num`.
       - Once `AUDIT-round-1.md` matching current `HEAD` SHA is present, `evaluate_stop` returns `{}`.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 hash over `allowed_files` (or run `pa wo verify WO-02.4`), update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-02-agents-and-dual-mode-hooks/wo4-stop-gate-two-tier-retry` with message:
   ```text
   WO-02.4: Stop gate enforcing two-tier retry ceiling and Case A/B completion invariants

   PA-WorkOrder: WO-02.4
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->
