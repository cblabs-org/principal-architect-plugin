"""Dual-mode escalation engine, structural blocker signatures, and hook I/O helpers.

Implements SPEC §3.2, §7.2, and §7.3:
- `decide(rule, mode, ctx)` across rules R1, R1b, R2, R3, R4, R5, R6 and modes
  `monitored` vs `autonomous`.
- `STRUCTURAL_SIGNATURES` and `is_structural_blocker(text)` for fast-fail detection.
- `record_escalation(db, ...)` and `enqueue_attention(db, ...)` for StateDB persistence.
- `extract_workspace_paths`, `read_hook_input`, and `write_hook_output` for stdlib-only
  sub-millisecond hook entrypoints.

Lazy Import Rule (Charter R1): This module MUST NOT import `pydantic`, `yaml`, or `schemas`
at module top-level.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

import state_db

RULES: tuple[str, ...] = ("R1", "R1b", "R2", "R3", "R4", "R5", "R6")
MODES: tuple[str, ...] = ("monitored", "autonomous")

STRUCTURAL_SIGNATURES: tuple[str, ...] = (
    "hardware is currently tied",
    "exclusive hardware",
    "mcp lock",
    "permissiondecision: deny",
    "permission_denied",
    "blocker_structural",
    "structural_blocker",
    "command not found",
    "no such file or directory: './.venv",
    "modulenotfounderror: no module named 'pydantic'",
    "modulenotfounderror: no module named 'yaml'",
    "address already in use",
)


def is_structural_blocker(text: str | None) -> bool:
    """Return True if `text` contains any known structural/environmental blocker signature."""
    if not text:
        return False
    lowered = text.lower()
    return any(sig in lowered for sig in STRUCTURAL_SIGNATURES)


def decide(
    rule: str,
    mode: str,
    ctx: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a governance rule (`R1`..`R6`) under `monitored` or `autonomous` mode.

    Returns a dictionary containing `permissionDecision`, `decision`, `reason`, `rule`,
    `mode`, `increment_structural_failures`, `auto_approve_plan`, and `escalation`.
    """
    if rule not in RULES:
        raise ValueError(f"Unknown rule: {rule!r}")
    norm_mode = mode.strip().lower() if isinstance(mode, str) else ""
    if norm_mode not in MODES:
        raise ValueError(f"Invalid execution mode: {mode!r}")

    c: dict[str, Any] = dict(ctx) if ctx is not None else {}
    path = str(c.get("path", "<target>"))
    pr_id = str(c.get("pr_id") or "PR-??")
    wo_id = str(c.get("wo_id") or "WO-??")
    head_sha = str(c.get("head_sha") or "HEAD")
    auto_approve_pr_plans = bool(c.get("auto_approve_pr_plans", False))
    plan_valid = bool(c.get("plan_valid", False))
    raw_req = c.get("requested_files")
    if raw_req:
        requested_files = [str(f) for f in raw_req]
    elif path != "<target>":
        requested_files = [path]
    else:
        requested_files = []

    permission_decision = "deny"
    reason = ""
    increment_structural = False
    auto_approve = False
    escalation: dict[str, Any] | None = None

    if rule == "R1":
        if norm_mode == "monitored":
            permission_decision = "ask"
            reason = (
                f"Architect is attempting to edit '{path}' directly instead of dispatching "
                "pa-engineer. Allow one-off edit?"
            )
        else:
            permission_decision = "deny"
            reason = (
                f"Autonomous Mode (R1): Architects cannot edit source file '{path}' inline. "
                "Issue/amend a WORKORDER.md and invoke pa-engineer."
            )

    elif rule == "R1b":
        if norm_mode == "monitored":
            permission_decision = "ask"
            reason = (
                f"Principal Architect is modifying the Chief Architect's locked PR Charter "
                f"({pr_id}) or touching '{path}' outside allowed_modules. Allow Charter amendment?"
            )
        else:
            permission_decision = "deny"
            reason = (
                f"Part I (PR Charter) of PROJECT.md ({pr_id}) is owned by the Chief Architect "
                f"(or '{path}' is outside allowed_modules). Run `pa escalate --to-chief` to "
                "request a scope or interface change."
            )
            escalation = {
                "level": "PA_TO_CHIEF",
                "source_role": "pa",
                "target_role": "chief",
                "pr_id": c.get("pr_id"),
                "wo_id": c.get("wo_id"),
                "blocker_type": "charter",
                "reason_code": "CHARTER_AMENDMENT_NEEDED",
                "requested_files": requested_files,
                "summary": (
                    f"PA attempted to modify locked Charter or file '{path}' outside "
                    f"allowed_modules on {pr_id}."
                ),
                "enqueue_attention": True,
                "attention_kind": "charter_escalation",
                "attention_priority": 20,
                "attention_title": (
                    f"🔴 [Charter Escalation] {pr_id} requested Charter amendment ({path})"
                ),
            }

    elif rule == "R2":
        if norm_mode == "monitored":
            permission_decision = "ask"
            reason = (
                f"Approve PROJECT.md Part II Work Order decomposition for {pr_id} and start "
                "Worker execution?"
            )
        elif auto_approve_pr_plans and plan_valid:
            permission_decision = "allow"
            reason = f"Auto-approved PROJECT.md Part II Work Order decomposition for {pr_id}."
            auto_approve = True
        else:
            permission_decision = "deny"
            reason = (
                f"Autonomous Mode (R2): PROJECT.md status for {pr_id} is not APPROVED. "
                "Enqueued plan approval in Human Attention Needed."
            )
            escalation = {
                "level": "PA_TO_HUMAN",
                "source_role": "pa",
                "target_role": "human",
                "pr_id": c.get("pr_id"),
                "wo_id": c.get("wo_id"),
                "blocker_type": "other",
                "reason_code": "PLAN_APPROVAL_REQUIRED",
                "requested_files": [],
                "summary": f"Plan approval required for {pr_id} before dispatching pa-engineer.",
                "enqueue_attention": True,
                "attention_kind": "plan_approval",
                "attention_priority": 10,
                "attention_title": (
                    f"🟠 [Plan Approval] {pr_id} Part II Work Order decomposition ready"
                ),
            }

    elif rule == "R3":
        if norm_mode == "monitored":
            permission_decision = "ask"
            reason = (
                f"Worker {wo_id} wants to edit '{path}' outside allowed_files (or protected "
                f"spec). Approve and add '{path}' to allowed_files?"
            )
        else:
            permission_decision = "deny"
            reason = (
                f"File '{path}' is outside your allowed_files (or mutates locked Part I of "
                "WORKORDER.md). Record an escalation_request in Part II (Completion Report) "
                "of WORKORDER.md with status: ESCALATED_TO_PA and finish your turn."
            )
            increment_structural = True
            escalation = {
                "level": "WORKER_TO_PA",
                "source_role": "engineer",
                "target_role": "pa",
                "pr_id": c.get("pr_id"),
                "wo_id": c.get("wo_id"),
                "blocker_type": "boundary",
                "reason_code": str(c.get("reason_code") or "BOUNDARY_EXPANSION_NEEDED"),
                "requested_files": requested_files,
                "summary": f"Worker {wo_id} attempted to edit '{path}' outside boundary box.",
                "enqueue_attention": True,
                "attention_kind": "boundary_escalation",
                "attention_priority": 20,
                "attention_title": (
                    f"🔴 [Boundary Escalation] {wo_id} requested access to {path}"
                ),
            }

    elif rule == "R4":
        cmd_str = str(c.get("command", path))
        permission_decision = "deny"
        reason = (
            "Worker git/gh lockdown (R4): pa-engineer is forbidden from executing branch, "
            f"remote, or PR command: {cmd_str}"
        )
        increment_structural = True

    elif rule == "R5":
        cmd_str = str(c.get("command", path))
        permission_decision = "deny"
        reason = (
            "Auditor read-only lockdown (R5): pa-auditor is strictly read-only and cannot "
            f"mutate files or run mutating command: {cmd_str}"
        )

    elif rule == "R6":
        if norm_mode == "monitored":
            permission_decision = "ask"
            reason = (
                f"Cold-Firewall Audit has not approved current HEAD ({head_sha}) for {pr_id}. "
                "Override and allow graduation?"
            )
        else:
            permission_decision = "deny"
            reason = (
                f"Cannot graduate {pr_id}: current HEAD ({head_sha}) lacks an APPROVED "
                "Cold-Firewall Audit verdict."
            )

    return {
        "permissionDecision": permission_decision,
        "decision": permission_decision,
        "reason": reason,
        "rule": rule,
        "mode": norm_mode,
        "increment_structural_failures": increment_structural,
        "auto_approve_plan": auto_approve,
        "escalation": escalation,
    }


def enqueue_attention(
    db: state_db.StateDB,
    *,
    kind: str,
    title: str,
    priority: int = 10,
    pr_id: str | None = None,
    wo_id: str | None = None,
    action_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert an item into `attention_queue` and return the stored row dictionary."""
    return db.enqueue(
        kind=kind,
        title=title,
        priority=priority,
        pr_id=pr_id,
        wo_id=wo_id,
        action_payload=action_payload,
    )


def record_escalation(
    db: state_db.StateDB,
    *,
    level: str,
    source_role: str,
    target_role: str,
    pr_id: str | None = None,
    wo_id: str | None = None,
    blocker_type: str = "other",
    reason_code: str = "UNSPECIFIED",
    requested_files: Sequence[str] | None = None,
    summary: str = "",
    enqueue_if_needed: bool = False,
    attention_kind: str | None = None,
    attention_title: str | None = None,
    attention_priority: int = 20,
) -> dict[str, Any]:
    """Insert an escalation row in `state.db` and optionally enqueue a linked attention item."""
    req_list = [str(f) for f in (requested_files or [])]
    row = db.insert_escalation(
        level=level,
        source_role=source_role,
        target_role=target_role,
        pr_id=pr_id,
        wo_id=wo_id,
        blocker_type=blocker_type,
        reason_code=reason_code,
        requested_files=req_list,
        summary=summary,
    )
    if enqueue_if_needed or target_role == "human":
        kind_val = attention_kind or f"{blocker_type}_escalation"
        title_val = attention_title or (
            summary or f"Escalation {row['escalation_id']} ({reason_code})"
        )
        payload = {
            "escalation_id": row["escalation_id"],
            "level": level,
            "source_role": source_role,
            "target_role": target_role,
            "blocker_type": blocker_type,
            "reason_code": reason_code,
            "requested_files": req_list,
            "summary": summary,
        }
        enqueue_attention(
            db,
            kind=kind_val,
            title=title_val,
            priority=attention_priority,
            pr_id=pr_id,
            wo_id=wo_id,
            action_payload=payload,
        )
    return row


def extract_workspace_paths(payload: Mapping[str, Any] | None) -> list[str]:
    """Extract deduplicated candidate workspace paths from a hook JSON payload."""
    candidates: list[str] = []
    if isinstance(payload, Mapping):
        for list_key in ("workspacePaths", "workspaceUris"):
            raw_seq = payload.get(list_key)
            if isinstance(raw_seq, Sequence) and not isinstance(raw_seq, (str, bytes)):
                for item in raw_seq:
                    if isinstance(item, str) and item.strip():
                        candidates.append(item.strip())
        for str_key in ("workspaceRoot", "cwd"):
            raw_val = payload.get(str_key)
            if isinstance(raw_val, str) and raw_val.strip():
                candidates.append(raw_val.strip())

    seen: set[str] = set()
    result: list[str] = []
    for path_str in candidates:
        if path_str not in seen:
            seen.add(path_str)
            result.append(path_str)

    if not result:
        return [os.getcwd()]
    return result


def read_hook_input(stream: TextIO | None = None) -> dict[str, Any]:
    """Read and parse one JSON object from `stream` (or `sys.stdin`), returning `{}` on error."""
    src = stream if stream is not None else sys.stdin
    try:
        raw = src.read()
    except OSError as exc:
        print(f"[principal-architect] Failed to read hook stdin: {exc}", file=sys.stderr)
        return {}

    if not raw or not raw.strip():
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[principal-architect] Malformed hook JSON stdin: {exc}", file=sys.stderr)
        return {}

    if not isinstance(parsed, dict):
        print(
            f"[principal-architect] Hook stdin must be a JSON object, got {type(parsed).__name__}",
            file=sys.stderr,
        )
        return {}

    return parsed


def write_hook_output(payload: Mapping[str, Any], stream: TextIO | None = None) -> int:
    """Serialize `payload` as a single JSON line to `stream` (or `sys.stdout`) and return `0`."""
    dst = stream if stream is not None else sys.stdout
    try:
        dst.write(json.dumps(dict(payload), ensure_ascii=False) + "\n")
        dst.flush()
    except OSError as exc:
        print(f"[principal-architect] Failed to write hook stdout: {exc}", file=sys.stderr)
    return 0
