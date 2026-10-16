#!/usr/bin/env python3
"""PostToolUse verification receipt engine and deterministic tree_hash calculator.

Implements SPEC §7.3 and PR-02 Charter G4 & R4:
- `< 1 ms` fast-exit when the target workspace is not enrolled in Registry.
- Lazy import rule (Charter G2 & R1): `pydantic`, `yaml`, and `schemas` are NEVER imported
  at module top-level or on the unenrolled fast path.
- `compute_tree_hash(repo_root, allowed_files) -> str` computing the canonical SHA-256 over
  sorted existing files matching `allowed_files` (excluding `.git/` and `.state/`).
- Receipt invalidation (`valid = 0`) when `pa-engineer` mutates files or runs mutating shell
  commands, receipt stamping (`valid = 1`) when `verification_command` exits `0`, and
  `attempt_num` / `structural_failures` tracking on non-zero verification exit.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import escalation
import pre_tool_gate
import state_db

_PA_WO_VERIFY_RE = re.compile(r"\bpa(?:\s+|_cli\.py\s+)wo\s+verify\b")
_EXIT_CODE_TEXT_RE = re.compile(r"Command exited with code (-?\d+)")

_WORKER_MUTATING_CMD_RE = re.compile(
    r"\b(?:"
    r"git\s+(?:add|reset|checkout|switch|clean|restore|mv|rm|stash|apply|cherry-pick|revert)\b"
    r"|(?:rm|mv|cp|touch|mkdir|rmdir|chmod|chown|dd|tee|truncate|install)\b"
    r"|sed\s+(?:-[a-zA-Z]*i|--in-place)\b"
    r"|perl\s+-[a-zA-Z]*i\b"
    r")"
)


def compute_tree_hash(repo_root: str | Path, allowed_files: Sequence[str]) -> str:
    """Compute the deterministic SHA-256 `tree_hash` over existing files matching `allowed_files`.

    Excludes `.git/` and `.state/` directories, sorts matched files by normalized POSIX
    path relative to `repo_root`, and hashes `<rel_posix_path>\\0<len>\\0<raw_bytes>\\n`.
    """
    real_root = Path(os.path.realpath(repo_root))
    matched: list[tuple[str, Path]] = []

    if real_root.is_dir() and allowed_files:
        for dirpath, dirnames, filenames in os.walk(real_root):
            dirnames[:] = [d for d in dirnames if d not in (".git", ".state")]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                try:
                    if not fpath.is_file():
                        continue
                    rel_posix = fpath.relative_to(real_root).as_posix()
                except OSError:
                    continue
                parts = rel_posix.split("/")
                if ".git" in parts or ".state" in parts:
                    continue
                if pre_tool_gate.matches_any_pattern(rel_posix, allowed_files):
                    matched.append((rel_posix, fpath))

    matched.sort(key=lambda item: item[0])
    hasher = hashlib.sha256()
    for rel_posix, fpath in matched:
        raw_bytes = fpath.read_bytes()
        header = f"{rel_posix}\0{len(raw_bytes)}\0".encode()
        hasher.update(header)
        hasher.update(raw_bytes)
        hasher.update(b"\n")

    return hasher.hexdigest()


def _get_current_head_sha(
    repo_root: Path,
    *,
    runner: common.Runner = common.run,
) -> str | None:
    """Return the current `HEAD` commit SHA for `repo_root`, or None if unavailable."""
    try:
        res = runner(["git", "rev-parse", "HEAD"], cwd=repo_root)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    return None


def _is_mutating_worker_command(cmd_str: str) -> bool:
    """Return True if `cmd_str` mutates working-tree or index state."""
    if not cmd_str:
        return False
    scrubbed_msg = pre_tool_gate._COMMIT_MSG_QUOTED_RE.sub("", cmd_str)
    if _WORKER_MUTATING_CMD_RE.search(scrubbed_msg):
        return True
    scrubbed_redir = pre_tool_gate._SAFE_REDIRECT_STRIP_RE.sub("", scrubbed_msg)
    return bool(pre_tool_gate._FILE_REDIRECT_RE.search(scrubbed_redir))


def _extract_command_outcome(payload: Mapping[str, Any]) -> tuple[int | None, str, str]:
    """Extract `(exit_code, error_str, combined_output_text)` from a PostToolUse payload."""
    tr_raw = payload.get("toolResult")
    if not isinstance(tr_raw, Mapping):
        tr_raw = payload.get("tool_result")
    tr: Mapping[str, Any] = tr_raw if isinstance(tr_raw, Mapping) else {}

    exit_code: int | None = None
    for src in (payload, tr):
        for key in ("exitCode", "exit_code", "returncode", "returnCode"):
            val = src.get(key)
            if isinstance(val, int) and not isinstance(val, bool):
                exit_code = val
                break
            if isinstance(val, str) and val.strip().lstrip("-").isdigit():
                exit_code = int(val.strip())
                break
        if exit_code is not None:
            break

    error_parts: list[str] = []
    for src in (payload, tr):
        for key in ("error", "toolError", "tool_error"):
            val = src.get(key)
            if isinstance(val, str) and val.strip():
                error_parts.append(val.strip())
    error_val = "\n".join(error_parts)

    output_parts: list[str] = []
    for src in (payload, tr):
        for key in (
            "output",
            "toolOutput",
            "tool_output",
            "result",
            "stdout",
            "stderr",
            "content",
        ):
            val = src.get(key)
            if isinstance(val, str) and val.strip():
                output_parts.append(val.strip())
    if error_val:
        output_parts.append(error_val)
    output_text = "\n".join(output_parts)

    if exit_code is None and output_text:
        m = _EXIT_CODE_TEXT_RE.search(output_text)
        if m:
            exit_code = int(m.group(1))

    return exit_code, error_val, output_text


def _upsert_receipt(
    db: state_db.StateDB,
    *,
    wo_id: str,
    pr_id: str,
    cmd: str,
    exit_code: int,
    tree_hash: str,
    git_head_sha: str | None,
    valid: int,
    receipt_id: str,
) -> dict[str, Any]:
    """Invalidate prior receipts for `wo_id` and insert/replace `receipt_id` cleanly."""
    db.invalidate_receipts(wo_id)
    with db.conn:
        db.conn.execute(
            "DELETE FROM verification_receipts WHERE receipt_id = ?",
            (receipt_id,),
        )
    return db.insert_receipt(
        wo_id=wo_id,
        pr_id=pr_id,
        cmd=cmd,
        exit_code=exit_code,
        tree_hash=tree_hash,
        git_head_sha=git_head_sha,
        valid=valid,
        receipt_id=receipt_id,
    )


def evaluate_post_tool(
    payload: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Evaluate a `PostToolUse` hook event for receipt invalidation, stamping, and retry counters.

    Executes an immediate `< 1 ms` fast-exit returning `{}` when the workspace is not enrolled
    in the global PA Registry (or local `.state/state.db` when `repo_root` is explicitly passed).
    """
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

    real_root = Path(os.path.realpath(resolved_root))
    ws_dir = common.workspace_dir(real_root)
    db_file = ws_dir / ".state" / "state.db"
    if not db_file.is_file():
        return {}

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
        if role != "engineer":
            return {}

        wo_id = str(session.get("wo_id") or "").strip()
        pr_id = str(session.get("pr_id") or "").strip()
        tool_name, args = pre_tool_gate._extract_tool_name_and_args(payload)

        # 1. File Mutation Tool -> Invalidate Receipts (SPEC §7.3.1)
        if tool_name in pre_tool_gate.FILE_MUTATION_TOOLS:
            if not wo_id:
                wo_doc = pre_tool_gate._find_bound_workorder(ws_dir, pr_id or None, None)
                if wo_doc is not None:
                    wo_id = wo_doc.spec.wo_id
            if wo_id:
                db.invalidate_receipts(wo_id)
            return {}

        # 2. run_command Tool -> Stamp Receipt / Track Failures / Invalidate on Mutating Command
        if tool_name == "run_command":
            cmd_str = pre_tool_gate._extract_command_str(args)
            if not cmd_str:
                return {}

            if _PA_WO_VERIFY_RE.search(cmd_str):
                return {}

            wo_doc = pre_tool_gate._find_bound_workorder(
                ws_dir, pr_id or None, wo_id or None
            )
            ver_cmd = wo_doc.spec.verification_command.strip() if wo_doc is not None else ""

            if wo_doc is not None and ver_cmd and ver_cmd in cmd_str:
                exit_code, error_val, output_text = _extract_command_outcome(payload)
                if exit_code is not None:
                    succeeded = (int(exit_code) == 0) and not bool(error_val.strip())
                else:
                    succeeded = not bool(error_val.strip())

                resolved_wo_id = wo_id or wo_doc.spec.wo_id
                resolved_pr_id = pr_id or wo_doc.spec.pr_id

                if succeeded:
                    t_hash = compute_tree_hash(real_root, wo_doc.spec.allowed_files)
                    git_head = _get_current_head_sha(real_root, runner=runner)
                    receipt_id = f"rcpt_{t_hash[:12]}"
                    _upsert_receipt(
                        db,
                        wo_id=resolved_wo_id,
                        pr_id=resolved_pr_id,
                        cmd=wo_doc.spec.verification_command,
                        exit_code=0,
                        tree_hash=t_hash,
                        git_head_sha=git_head,
                        valid=1,
                        receipt_id=receipt_id,
                    )
                    return {}

                db.invalidate_receipts(resolved_wo_id)
                max_att = int(wo_doc.spec.max_attempts)
                cur_att = int(session.get("attempt_num") or 0)
                new_att = min(cur_att + 1, max_att) if cur_att < max_att else cur_att
                cur_struct = int(session.get("structural_failures") or 0)
                new_struct = (
                    cur_struct + 1
                    if escalation.is_structural_blocker(output_text)
                    else cur_struct
                )
                db.update_session(
                    conv_id,
                    attempt_num=new_att,
                    structural_failures=new_struct,
                )
                return {}

            if _is_mutating_worker_command(cmd_str):
                resolved_wo_id = wo_id or (wo_doc.spec.wo_id if wo_doc is not None else "")
                if resolved_wo_id:
                    db.invalidate_receipts(resolved_wo_id)
            return {}

    return {}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `PostToolUse` hook (`post_tool_receipt.py`)."""
    _ = argv
    payload = escalation.read_hook_input()
    try:
        res = evaluate_post_tool(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[principal-architect] post_tool_receipt error: {exc}", file=sys.stderr)
        res = {}
    return escalation.write_hook_output(res)


if __name__ == "__main__":
    raise SystemExit(main())
