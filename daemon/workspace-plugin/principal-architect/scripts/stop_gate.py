#!/usr/bin/env python3
"""Principal Architect Plugin (c) 2026 Matt McNeill
https://github.com/matthewmcneill/principal-architect-plugin
SPDX-License-Identifier: Apache-2.0
Module: daemon/workspace-plugin/principal-architect/scripts/stop_gate.py

Stop governance gate enforcing the two-tier retry ceiling and completion invariants.
Plays the session-completion verification role in the Split-Authority enforcement pipeline
(SPEC §7.4 and PR-02 Charter G5, R1, R2, R4, and R5):
- Executes a `< 1 ms` fast-exit when the target workspace is not enrolled in the Registry.
- Enforces the lazy import rule (Charter G2 & R1): `pydantic`, `yaml`, and `schemas` are
  never imported at module top-level or on the unenrolled fast path.
- Enforces the two-tier retry policy for `pa-engineer`:
  * Fast-fail structural escalation (`structural_failures >= max_structural_failures` [2]
    or `>= 3` consecutive `ERROR_MESSAGE` steps in `transcript.jsonl`) marks the Work Order
    `ESCALATED_TO_PA`, records the escalation in `state.db`, and returns `{}` immediately.
  * Productive attempt ceiling (`attempt_num >= max_attempts` [5]) marks the Work Order
    `BLOCKED`, records the escalation in `state.db`, enqueues `pa-debugger`
    (`🔬 [Debug <WO-ID>]`), and returns `{}`.
- Evaluates Case A (explicit blocker/escalation report) and Case B (valid receipt matching
  `compute_tree_hash`, clean git status with `<WO-ID>:` commit, and valid `CompletionReport`
  with intact `spec_hash`) completion invariants, incrementing `attempt_num` on every
  `"decision": "continue"` response so `Stop` continuations are strictly bounded.
- Enforces the Auditor Stop gate requiring a valid `AuditReport` (`AUDIT-round-*.md`) for
  the current `HEAD` commit SHA.

Exported API Summary:
  Constants:
    _SCRIPTS_DIR: Absolute directory path containing the hook script modules.
  Public Functions:
    evaluate_stop(payload, *, repo_root=None, runner=common.run) -> dict[str, Any]:
        Evaluate a Stop hook event for pa-engineer and pa-auditor sessions.
    main(argv=None) -> int:
        CLI entrypoint reading a Stop JSON payload from stdin and writing the hook response.
  Internal Helpers:
    _has_consecutive_error_steps(steps, threshold=3) -> bool:
        Check whether a transcript step sequence has at least threshold consecutive error steps.
    _parse_porcelain_paths(stdout) -> list[str]:
        Parse dirty or untracked repo-relative POSIX paths from git status porcelain output.
    _is_ephemeral_runtime_path(rel_posix) -> bool:
        Check whether a repo-relative POSIX path is an ephemeral runtime file ignored by git checks.
    _check_git_clean_and_committed(
        repo_root, wo_id, allowed_files, wo_rel_posix, *, runner=common.run
    ) -> tuple[bool, list[str]]:
        Verify that allowed_files and WORKORDER.md are clean in git and committed with `<WO-ID>:`.
    _evaluate_engineer_stop(
        *, payload, db, session, conv_id, real_root, ws_dir, runner
    ) -> dict[str, Any]:
        Evaluate Stop completion invariants and two-tier retry bounds for a pa-engineer session.
    _evaluate_auditor_stop(*, db, session, conv_id, real_root, ws_dir, runner) -> dict[str, Any]:
        Evaluate Stop completion invariants for a pa-auditor session.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# Absolute path to the scripts directory, inserted into sys.path for sibling imports.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import escalation
import post_tool_receipt
import pre_tool_gate
import state_db


def _has_consecutive_error_steps(
    steps: Sequence[Mapping[str, Any]],
    threshold: int = 3,
) -> bool:
    """Return True if `steps` contains a run of at least `threshold` consecutive error steps.

    Args:
        steps: Sequence of parsed `transcript.jsonl` step dictionaries.
        threshold: Minimum number of consecutive error steps required to trigger (`3` by default).

    Returns:
        `True` if at least `threshold` consecutive error steps are present, otherwise `False`.
    """
    # --- Step 1: Handle non-positive threshold edge case ---
    if threshold <= 0:
        return True

    # --- Step 2: Scan transcript steps for consecutive error streaks ---
    run_len = 0
    for step in steps:
        if not isinstance(step, Mapping):
            run_len = 0
            continue
        stype = str(step.get("type") or "").strip().upper()
        sstatus = str(step.get("status") or "").strip().upper()
        if stype in ("ERROR_MESSAGE", "CORTEX_STEP_TYPE_ERROR_MESSAGE") or sstatus == "ERROR":
            run_len += 1
            if run_len >= threshold:
                return True
        else:
            run_len = 0
    return False


def _parse_porcelain_paths(stdout: str) -> list[str]:
    """Parse dirty/untracked repo-relative POSIX paths from `git status --porcelain -uall`.

    Args:
        stdout: Raw stdout text from `git status --porcelain -uall`.

    Returns:
        Deduplicated list of repo-relative POSIX file paths in order of appearance.
    """
    paths: list[str] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        if len(line) < 4:
            continue
        raw_entry = line[3:]
        parts = raw_entry.split(" -> ", 1) if " -> " in raw_entry else [raw_entry]
        for part in parts:
            cleaned = part.strip().strip('"').lstrip("./")
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                paths.append(cleaned)
    return paths


def _is_ephemeral_runtime_path(rel_posix: str) -> bool:
    """Return True if `rel_posix` is an ephemeral runtime file ignored by git hygiene checks.

    Args:
        rel_posix: Normalized repo-relative POSIX path.

    Returns:
        `True` if the path points to `.agents/plugins.json` or any `.state/` directory entry.
    """
    norm = rel_posix.strip().lstrip("./")
    if norm == ".agents/plugins.json":
        return True
    return ".state" in norm.split("/")


def _check_git_clean_and_committed(
    repo_root: Path,
    wo_id: str,
    allowed_files: Sequence[str],
    wo_rel_posix: str,
    *,
    runner: common.Runner = common.run,
) -> tuple[bool, list[str]]:
    """Verify `allowed_files` + `WORKORDER.md` are clean in git and committed with `<WO-ID>:`.

    Args:
        repo_root: Canonical path to the repository root.
        wo_id: Work Order identifier (`WO-01`, etc.) expected in the commit subject prefix.
        allowed_files: Sequence of allowed file patterns for the Work Order.
        wo_rel_posix: Repo-relative POSIX path to the Work Order's `WORKORDER.md` file.
        runner: Subprocess runner callable used to invoke git commands.

    Returns:
        A 2-tuple `(is_ok, problems)` where `is_ok` is `True` when `problems` is empty.
    """
    problems: list[str] = []

    # --- Step 1: Check git status for uncommitted changes in allowed_files or WORKORDER.md ---
    try:
        status_res = runner(["git", "status", "--porcelain", "-uall"], cwd=repo_root)
    except (OSError, subprocess.SubprocessError):
        status_res = None

    if status_res is None or status_res.returncode != 0:
        problems.append("git status check failed")
    else:
        dirty_paths = [
            p
            for p in _parse_porcelain_paths(status_res.stdout)
            if not _is_ephemeral_runtime_path(p)
        ]
        dirty_relevant = [
            p
            for p in dirty_paths
            if (wo_rel_posix and p == wo_rel_posix)
            or pre_tool_gate.matches_any_pattern(p, allowed_files)
        ]
        if dirty_relevant:
            problems.append("uncommitted files in allowed_files or WORKORDER.md")

    # --- Step 2: Check recent git log subjects for `<WO-ID>:` commit prefix ---
    try:
        log_res = runner(["git", "log", "-n", "5", "--format=%s"], cwd=repo_root)
    except (OSError, subprocess.SubprocessError):
        log_res = None

    prefix_upper = f"{wo_id.upper()}:"
    has_wo_commit = False
    if log_res is not None and log_res.returncode == 0 and log_res.stdout:
        for line in log_res.stdout.splitlines():
            if line.strip().upper().startswith(prefix_upper):
                has_wo_commit = True
                break

    if not has_wo_commit:
        problems.append(f"missing git commit starting with '{wo_id}:'")

    return len(problems) == 0, problems


def evaluate_stop(
    payload: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Evaluate a `Stop` hook event for `pa-engineer` and `pa-auditor` sessions.

    Executes an immediate `< 1 ms` fast-exit returning `{}` when the workspace is not enrolled
    in the global PA Registry (or local `.state/state.db` when `repo_root` is explicitly passed).

    Args:
        payload: Decoded JSON hook input dictionary for the `Stop` event.
        repo_root: Optional explicit repository root override for testing or CLI invocation.
        runner: Subprocess runner callable used for git status/log/rev-parse checks.

    Returns:
        Hook response dictionary: `{}` to allow the agent to stop, or
        `{"decision": "continue", "reason": "..."}` to resume the agent with remediation guidance.
    """
    # --- Step 1: Fast-exit check for unenrolled workspaces (< 1 ms) ---
    resolved_root: Path | None = None
    if repo_root is None:
        workspace_paths = escalation.extract_workspace_paths(payload)
        if not common.is_repo_enrolled(workspace_paths):
            return {}
        for wp in workspace_paths:
            if common.is_repo_enrolled([wp]):
                cand = common.find_repo_root(wp, runner=runner)
                if cand is not None:
                    resolved_root = cand
                    break
        if resolved_root is None:
            resolved_root = common.find_repo_root(workspace_paths[0], runner=runner)
        if resolved_root is None:
            return {}
    else:
        cand_root = Path(os.path.realpath(repo_root))
        has_local_db = (
            (cand_root / common.NEW_WORKSPACE_REL / ".state" / "state.db").is_file()
            or (cand_root / common.LEGACY_WORKSPACE_REL / ".state" / "state.db").is_file()
        )
        if not has_local_db and not common.is_repo_enrolled([str(cand_root)]):
            return {}
        resolved_root = cand_root

    # --- Step 2: Validate workspace state DB and normal termination reason ---
    real_root = Path(os.path.realpath(resolved_root))
    ws_dir = common.workspace_dir(real_root)
    db_file = ws_dir / ".state" / "state.db"
    if not db_file.is_file():
        return {}

    term_reason = str(
        payload.get("terminationReason") or payload.get("termination_reason") or ""
    ).strip()
    if term_reason and term_reason != "NO_TOOL_CALL":
        return {}

    # --- Step 3: Resolve bound session role and dispatch role-specific Stop evaluator ---
    with state_db.StateDB(db_file) as db:
        conv_id = str(
            payload.get("conversationId") or payload.get("conversation_id") or ""
        ).strip()
        if not conv_id:
            return {}

        session = db.get_session(conv_id)
        if session is None:
            return {}

        role = pre_tool_gate._normalize_role(str(session.get("role") or ""))
        if role not in ("engineer", "auditor"):
            return {}

        if role == "engineer":
            return _evaluate_engineer_stop(
                payload=payload,
                db=db,
                session=session,
                conv_id=conv_id,
                real_root=real_root,
                ws_dir=ws_dir,
                runner=runner,
            )

        return _evaluate_auditor_stop(
            db=db,
            session=session,
            conv_id=conv_id,
            real_root=real_root,
            ws_dir=ws_dir,
            runner=runner,
        )


def _evaluate_engineer_stop(
    *,
    payload: Mapping[str, Any],
    db: state_db.StateDB,
    session: Mapping[str, Any],
    conv_id: str,
    real_root: Path,
    ws_dir: Path,
    runner: common.Runner,
) -> dict[str, Any]:
    """Evaluate `Stop` completion invariants and two-tier retry bounds for `pa-engineer`.

    Args:
        payload: Raw `Stop` hook input dictionary.
        db: Open `StateDB` connection for the workspace.
        session: Active session row mapping from `state.db`.
        conv_id: Bound conversation UUID string.
        real_root: Canonical path to the repository root.
        ws_dir: Canonical path to the `principal-architect-workspace` workspace directory.
        runner: Subprocess runner callable used for git hygiene verification.

    Returns:
        `{}` when completion or escalation terminates the session, or
        `{"decision": "continue", "reason": "..."}` when retries remain.
    """
    # --- Step 1: Load bound WorkOrder document and session retry counters ---
    import schemas

    wo_id = str(session.get("wo_id") or "").strip()
    pr_id = str(session.get("pr_id") or "").strip()
    wo_doc = pre_tool_gate._find_bound_workorder(ws_dir, pr_id or None, wo_id or None)
    if wo_doc is None:
        return {}

    resolved_wo_id = wo_doc.spec.wo_id
    resolved_pr_id = wo_doc.spec.pr_id
    max_attempts = int(wo_doc.spec.max_attempts)
    max_structural = int(wo_doc.spec.max_structural_failures)
    attempt_num = int(session.get("attempt_num") or 1)
    structural_failures = int(session.get("structural_failures") or 0)

    t_path = payload.get("transcriptPath") or payload.get("transcript_path")
    steps = common.read_transcript(common._strip_file_uri(str(t_path))) if t_path else []
    has_3_errors = _has_consecutive_error_steps(steps, threshold=3)

    # --- Step 2: Fast-fail structural escalation check (SPEC §7.4 Step 4A) ---
    if structural_failures >= max_structural or has_3_errors:
        wo_doc.spec.status = schemas.WorkOrderStatus.ESCALATED_TO_PA
        if wo_doc.spec.completion is None or wo_doc.spec.completion.status not in (
            schemas.WorkOrderStatus.ESCALATED_TO_PA,
            schemas.WorkOrderStatus.BLOCKED,
        ):
            wo_doc.spec.completion = schemas.CompletionReport(
                status=schemas.WorkOrderStatus.ESCALATED_TO_PA,
                attempt_num=min(max(attempt_num, 1), 5),
                verification_summary="Fast-fail structural escalation triggered by Stop gate.",
                escalation_request=schemas.EscalationRequest(
                    blocker_type="structural",
                    reason_code="STRUCTURAL_FAST_FAIL",
                    target_role="pa",
                    requested_files=[],
                    summary=(
                        f"Fast-fail structural escalation on {resolved_wo_id} "
                        f"(structural_failures={structural_failures}, "
                        f"consecutive_errors={has_3_errors})."
                    ),
                ),
            )
        if wo_doc.path is not None and wo_doc.path.is_file():
            wo_doc.path.write_text(
                schemas.dump_document(wo_doc.spec, wo_doc.sections),
                encoding="utf-8",
            )
        escalation.record_escalation(
            db,
            level="wo_to_pa",
            source_role="engineer",
            target_role="pa",
            pr_id=resolved_pr_id,
            wo_id=resolved_wo_id,
            blocker_type="structural",
            reason_code="STRUCTURAL_FAST_FAIL",
            summary=(
                f"Work Order {resolved_wo_id} fast-failed on structural blocker "
                f"(structural_failures={structural_failures}/{max_structural}, "
                f"consecutive_errors={has_3_errors})."
            ),
            enqueue_if_needed=True,
            attention_kind="escalation",
            attention_title=f"Structural blocker on {resolved_wo_id}",
            attention_priority=20,
        )
        return {}

    # --- Step 3: Case A check for explicit blocker or escalation report (SPEC §7.4 Step 4B) ---
    is_case_a = wo_doc.spec.status in (
        schemas.WorkOrderStatus.ESCALATED_TO_PA,
        schemas.WorkOrderStatus.BLOCKED,
    ) or (
        wo_doc.spec.completion is not None
        and wo_doc.spec.completion.status
        in (schemas.WorkOrderStatus.ESCALATED_TO_PA, schemas.WorkOrderStatus.BLOCKED)
    )
    if is_case_a:
        comp = wo_doc.spec.completion
        spec_hash_ok = not wo_doc.spec.spec_hash or (
            wo_doc.path is not None and schemas.verify_spec_hash(wo_doc.path)
        )
        if (
            comp is not None
            and (comp.escalation_request is not None or bool(comp.verification_summary.strip()))
            and spec_hash_ok
        ):
            esc_req = comp.escalation_request
            b_type = esc_req.blocker_type if esc_req is not None else "scope"
            r_code = esc_req.reason_code if esc_req is not None else wo_doc.spec.status.value
            req_files = list(esc_req.requested_files) if esc_req is not None else []
            summary_txt = esc_req.summary if esc_req is not None else comp.verification_summary
            escalation.record_escalation(
                db,
                level="wo_to_pa",
                source_role="engineer",
                target_role="pa",
                pr_id=resolved_pr_id,
                wo_id=resolved_wo_id,
                blocker_type=b_type,
                reason_code=r_code,
                requested_files=req_files,
                summary=summary_txt,
            )
            return {}

        if attempt_num < max_attempts:
            db.update_session(conv_id, attempt_num=attempt_num + 1)
            return {
                "decision": "continue",
                "reason": (
                    f"Work Order {resolved_wo_id} (attempt {attempt_num}/{max_attempts}) is "
                    f"marked {wo_doc.spec.status.value} but lacks a valid "
                    "CompletionReport/escalation_request explaining the blocker."
                ),
            }

    # --- Step 4: Case B check for normal completion invariants (SPEC §7.4 Step 4C) ---
    missing_reasons: list[str] = []

    current_tree_hash = post_tool_receipt.compute_tree_hash(
        real_root, wo_doc.spec.allowed_files
    )
    receipt = db.latest_valid_receipt(resolved_wo_id, tree_hash=current_tree_hash)
    if receipt is None:
        missing_reasons.append("missing verification receipt")

    wo_rel_posix = (
        wo_doc.path.resolve().relative_to(real_root).as_posix()
        if wo_doc.path is not None
        else ""
    )
    git_ok, git_problems = _check_git_clean_and_committed(
        real_root,
        resolved_wo_id,
        wo_doc.spec.allowed_files,
        wo_rel_posix,
        runner=runner,
    )
    if not git_ok:
        missing_reasons.extend(git_problems)

    comp = wo_doc.spec.completion
    comp_valid = (
        wo_doc.spec.status == schemas.WorkOrderStatus.COMPLETED
        and comp is not None
        and comp.status == schemas.WorkOrderStatus.COMPLETED
        and bool(comp.receipt_id)
        and bool(comp.commit_sha)
        and bool(comp.verification_summary and comp.verification_summary.strip())
    )
    if not comp_valid:
        missing_reasons.append("incomplete Completion Report")

    if wo_doc.spec.spec_hash and (
        wo_doc.path is None or not schemas.verify_spec_hash(wo_doc.path)
    ):
        missing_reasons.append("spec_hash mismatch")

    if not missing_reasons:
        return {}

    # --- Step 5: Enforce productive attempt ceiling or issue bounded continuation ---
    if attempt_num >= max_attempts:
        wo_doc.spec.status = schemas.WorkOrderStatus.BLOCKED
        if (
            wo_doc.spec.completion is None
            or wo_doc.spec.completion.status != schemas.WorkOrderStatus.BLOCKED
        ):
            wo_doc.spec.completion = schemas.CompletionReport(
                status=schemas.WorkOrderStatus.BLOCKED,
                attempt_num=min(max(attempt_num, 1), 5),
                verification_summary=f"Blocked after reaching max_attempts ({max_attempts}).",
            )
        if wo_doc.path is not None and wo_doc.path.is_file():
            wo_doc.path.write_text(
                schemas.dump_document(wo_doc.spec, wo_doc.sections),
                encoding="utf-8",
            )
        escalation.record_escalation(
            db,
            level="wo_to_pa",
            source_role="engineer",
            target_role="debugger",
            pr_id=resolved_pr_id,
            wo_id=resolved_wo_id,
            blocker_type="verification_ceiling",
            reason_code="MAX_ATTEMPTS_EXCEEDED",
            summary=(
                f"Work Order {resolved_wo_id} exhausted {max_attempts} verification attempts; "
                "escalating to pa-debugger."
            ),
            enqueue_if_needed=True,
            attention_kind="debugger_escalation",
            attention_title=f"🔬 [Debug {resolved_wo_id}] {wo_doc.spec.title}",
            attention_priority=10,
        )
        return {}

    db.update_session(conv_id, attempt_num=attempt_num + 1)
    reason_str = (
        f"Work Order {resolved_wo_id} (attempt {attempt_num}/{max_attempts}) cannot complete yet: "
        f"[{', '.join(missing_reasons)}]. Run `pa wo verify {resolved_wo_id}` to verify, "
        "stamp the receipt, and commit."
    )
    return {"decision": "continue", "reason": reason_str}


def _evaluate_auditor_stop(
    *,
    db: state_db.StateDB,
    session: Mapping[str, Any],
    conv_id: str,
    real_root: Path,
    ws_dir: Path,
    runner: common.Runner,
) -> dict[str, Any]:
    """Evaluate `Stop` completion invariants for a `pa-auditor` session.

    Verifies that a schema-valid `AUDIT-round-*.md` file matching the current `HEAD`
    commit SHA has been published for the active PR, or issues a bounded continuation
    up to 5 attempts.

    Args:
        db: Open `StateDB` connection for the workspace.
        session: Active session row mapping from `state.db`.
        conv_id: Bound conversation UUID string.
        real_root: Canonical path to the repository root.
        ws_dir: Canonical path to the `principal-architect-workspace` workspace directory.
        runner: Subprocess runner callable used to query `git rev-parse HEAD`.

    Returns:
        `{}` if a matching `AuditReport` exists or the 5-attempt ceiling is reached,
        otherwise `{"decision": "continue", "reason": "..."}`.
    """
    # --- Step 1: Check for an existing AuditReport matching the current HEAD SHA ---
    import schemas

    pr_id = str(session.get("pr_id") or "").strip()
    head_sha = post_tool_receipt._get_current_head_sha(real_root, runner=runner) or ""

    for audit_path in sorted(ws_dir.glob("pr-*/AUDIT-round-*.md")):
        try:
            audit_doc = schemas.load_audit(audit_path)
        except Exception:  # noqa: BLE001, S112
            continue
        report = audit_doc.spec
        if pr_id and report.pr_id.upper() != pr_id.upper():
            continue
        if head_sha and common.head_matches_audited_sha(
            real_root,
            audit_path.parent,
            head_sha,
            report.head_sha,
            runner=runner,
        ):
            return {}

    # --- Step 2: Enforce 5-attempt auditor continuation ceiling or continue ---
    attempt_num = int(session.get("attempt_num") or 1)
    if attempt_num >= 5:
        escalation.record_escalation(
            db,
            level="pa_to_chief",
            source_role="auditor",
            target_role="pa",
            pr_id=pr_id or None,
            blocker_type="audit_missing",
            reason_code="AUDITOR_STOP_TIMEOUT",
            summary=(
                f"Auditor failed to publish AuditReport for {pr_id or 'PR'} "
                "after 5 Stop continuations."
            ),
        )
        return {}

    db.update_session(conv_id, attempt_num=attempt_num + 1)
    target_pr = pr_id or "<PR-ID>"
    return {
        "decision": "continue",
        "reason": (
            f"Publish your audit findings via `pa pr post-audit {target_pr} --file <path>` "
            "before finishing."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `Stop` hook (`stop_gate.py`).

    Args:
        argv: Optional command-line argument sequence (unused; hook reads JSON from stdin).

    Returns:
        Process exit code (`0` after writing the JSON hook response to stdout).
    """
    _ = argv
    payload = escalation.read_hook_input()
    try:
        res = evaluate_stop(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[principal-architect] stop_gate error: {exc}", file=sys.stderr)
        res = {}
    return escalation.write_hook_output(res)


if __name__ == "__main__":
    raise SystemExit(main())
