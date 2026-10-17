#!/usr/bin/env python3
"""PreToolUse governance gate enforcing rules R1, R1b, R2, R3, R4, R5, and R6.

Implements SPEC §7.2 and §11.2:
- `< 1 ms` fast-exit when the target workspace is not enrolled in Registry.
- Lazy import rule (Charter G2 & R1): `pydantic`, `yaml`, and `schemas` are NEVER imported
  at module top-level or on the unenrolled fast path.
- Canonical path resolution (`os.path.realpath`) preventing `../` path traversal and
  symlink escapes outside `repo_root`, `allowed_files`, or `.agents/`.
- Symmetric `monitored` (`ask`) vs `autonomous` (`deny` + StateDB escalation) enforcement
  via `escalation.decide`.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import escalation
import state_db

FILE_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        "write_to_file",
        "write_file",
        "replace_file_content",
        "edit_file",
        "multi_replace_file_content",
    }
)

_PATH_ARG_KEYS: tuple[str, ...] = (
    "TargetFile",
    "Path",
    "file_path",
    "path",
    "FilePath",
    "TargetPath",
)

_CMD_ARG_KEYS: tuple[str, ...] = (
    "CommandLine",
    "command",
    "cmd",
    "Command",
)

_R6_GRADUATE_RE = re.compile(
    r"\b(?:pa(?:\s+|_cli\.py\s+)pr\s+graduate|gh\s+pr\s+merge)\b"
)
_PR_ID_TOKEN_RE = re.compile(r"\b(PR-\d+[a-z]?)\b", re.IGNORECASE)

_R4_FORBIDDEN_GIT_GH_RE = re.compile(
    r"\b(?:"
    r"git\s+(?:push|checkout|switch|branch|rebase|merge)\b"
    r"|git\s+reset\s+--hard\b"
    r"|gh\s+(?:pr|issue)\b"
    r")"
)

_R5_AUDITOR_MUTATING_CMD_RE = re.compile(
    r"\b(?:"
    r"git\s+(?:commit|push|checkout|switch|branch|rebase|merge|reset|clean|mv|rm|tag|stash|add|apply|cherry-pick|revert)\b"
    r"|gh\s+(?:pr\s+(?:create|merge|close|edit|ready|reopen)|issue\s+(?:create|close|edit|delete|reopen)|repo\s+(?:create|delete|edit|fork))\b"
    r"|(?:rm|mv|cp|touch|mkdir|rmdir|chmod|chown|dd|tee|truncate|install)\b"
    r"|sed\s+(?:-[a-zA-Z]*i|--in-place)\b"
    r")"
)

_SAFE_REDIRECT_STRIP_RE = re.compile(
    r"(?:\d*>&\d+|\d*>{1,2}\s*/dev/null\b|&>{1,2}\s*/dev/null\b)"
)
_FILE_REDIRECT_RE = re.compile(r"(?:^|[^0-9<>])>{1,2}\s*(\S+)")
_COMMIT_MSG_QUOTED_RE = re.compile(
    r"(?:-m|--message)\s+(?:\"[^\"]*\"|'[^']*')"
)


def resolve_repo_rel_path(repo_root: Path | str, raw_path: str) -> tuple[bool, str, Path]:
    """Resolve `raw_path` via `os.path.realpath` against `repo_root`.

    Returns `(inside_repo, rel_posix_or_raw, real_target)`:
    - `inside_repo` is True iff `real_target` is equal to or inside `real_root`.
    - When `inside_repo` is True, the second element is the normalized POSIX path
      relative to `real_root` (or `"."` if equal to `real_root`).
    - When `inside_repo` is False (e.g. `../` traversal or symlink pointing outside
      `real_root`), returns `(False, str(raw_path), real_target)`.
    """
    cleaned = common._strip_file_uri(str(raw_path).strip())
    real_root = Path(os.path.realpath(repo_root))
    cand_path = Path(cleaned)
    if not cand_path.is_absolute():
        cand_path = real_root / cand_path

    real_target = Path(os.path.realpath(cand_path))
    if real_target == real_root:
        return True, ".", real_target
    if real_root in real_target.parents:
        return True, real_target.relative_to(real_root).as_posix(), real_target
    return False, str(raw_path), real_target


def matches_pattern(rel_posix: str, pattern: str) -> bool:
    """Check whether repo-relative POSIX path `rel_posix` matches `pattern`.

    Supports exact paths, directory prefixes (`dir/` or `dir/**`), and `fnmatch` globs.
    """
    norm_rel = rel_posix.strip().lstrip("./")
    pat = pattern.strip().lstrip("./")
    if not pat or not norm_rel:
        return False

    if norm_rel == pat.rstrip("/"):
        return True

    if pat.endswith("/**"):
        prefix = pat[:-3].rstrip("/")
        if norm_rel == prefix or norm_rel.startswith(prefix + "/"):
            return True

    if pat.endswith("/"):
        prefix = pat.rstrip("/")
        if norm_rel == prefix or norm_rel.startswith(prefix + "/"):
            return True

    if norm_rel.startswith(pat.rstrip("/") + "/"):
        return True

    return fnmatch.fnmatch(norm_rel, pat)


def matches_any_pattern(rel_posix: str, patterns: Sequence[str]) -> bool:
    """Return True if `rel_posix` matches at least one pattern in `patterns`."""
    return any(matches_pattern(rel_posix, pat) for pat in patterns)


def simulate_file_edit(
    existing_text: str,
    tool_name: str,
    args: Mapping[str, Any],
) -> str | None:
    """Simulate the resulting file text from a file mutation tool call, or None if invalid."""
    if tool_name in ("write_to_file", "write_file"):
        if "CodeContent" in args:
            content = args.get("CodeContent")
        elif "Content" in args:
            content = args.get("Content")
        else:
            content = args.get("content")
        if not isinstance(content, str):
            return None
        if args.get("Append") is True:
            return existing_text + content
        return content

    if tool_name in ("replace_file_content", "edit_file"):
        chunks = args.get("ReplacementChunks")
        if isinstance(chunks, list):
            return _apply_replacement_chunks(existing_text, chunks)
        target = args.get("TargetContent") if "TargetContent" in args else args.get("Target")
        replacement = (
            args.get("ReplacementContent")
            if "ReplacementContent" in args
            else args.get("Replacement")
        )
        if not isinstance(target, str) or not isinstance(replacement, str):
            return None
        if target not in existing_text:
            return None
        return existing_text.replace(target, replacement)

    if tool_name == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks")
        if not isinstance(chunks, list) or not chunks:
            return None
        return _apply_replacement_chunks(existing_text, chunks)

    return None


def _apply_replacement_chunks(existing_text: str, chunks: Sequence[Any]) -> str | None:
    text = existing_text
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            return None
        target = chunk.get("TargetContent") if "TargetContent" in chunk else chunk.get("Target")
        replacement = (
            chunk.get("ReplacementContent")
            if "ReplacementContent" in chunk
            else chunk.get("Replacement")
        )
        if not isinstance(target, str) or not isinstance(replacement, str):
            return None
        if target not in text:
            return None
        text = text.replace(target, replacement)
    return text


def _extract_tool_name_and_args(payload: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    tool_call = payload.get("toolCall")
    tc_map = tool_call if isinstance(tool_call, Mapping) else {}

    tool_name = str(
        tc_map.get("name")
        or tc_map.get("toolName")
        or payload.get("toolName")
        or payload.get("tool_name")
        or payload.get("name")
        or ""
    ).strip()

    raw_args: Any = None
    for src in (tc_map, payload):
        for key in ("args", "arguments", "input", "toolArgs", "toolInput", "tool_input"):
            if key in src and src[key] is not None:
                raw_args = src[key]
                break
        if raw_args is not None:
            break

    if isinstance(raw_args, Mapping):
        return tool_name, dict(raw_args)
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, Mapping):
                return tool_name, dict(parsed)
        except json.JSONDecodeError:
            pass
    return tool_name, {}


def _extract_target_path(args: Mapping[str, Any]) -> str:
    for key in _PATH_ARG_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_command_str(args: Mapping[str, Any]) -> str:
    for key in _CMD_ARG_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _normalize_role(raw_role: str | None) -> str:
    if not raw_role:
        return ""
    r = raw_role.strip().lower()
    if r in ("pa-chief-architect", "chief-architect", "chief"):
        return "chief"
    if r in ("pa-principal-architect", "principal-architect", "pa"):
        return "pa"
    if r in ("pa-engineer", "engineer", "worker"):
        return "engineer"
    if r in ("pa-auditor", "auditor"):
        return "auditor"
    if r in ("pa-debugger", "debugger"):
        return "debugger"
    return r


def _finalize_decision(
    db: state_db.StateDB,
    session: dict[str, Any] | None,
    decision_dict: dict[str, Any],
) -> dict[str, Any]:
    if decision_dict.get("increment_structural_failures") and session is not None:
        conv_id = str(session.get("conversation_id") or "")
        if conv_id:
            new_val = int(session.get("structural_failures") or 0) + 1
            updated = db.update_session(conv_id, structural_failures=new_val)
            if updated is not None:
                session.update(updated)

    esc = decision_dict.get("escalation")
    if isinstance(esc, Mapping):
        recorded = escalation.record_escalation(
            db,
            level=str(esc["level"]),
            source_role=str(esc["source_role"]),
            target_role=str(esc["target_role"]),
            pr_id=esc.get("pr_id"),
            wo_id=esc.get("wo_id"),
            blocker_type=str(esc.get("blocker_type") or "other"),
            reason_code=str(esc.get("reason_code") or "UNSPECIFIED"),
            requested_files=esc.get("requested_files"),
            summary=str(esc.get("summary") or ""),
            enqueue_if_needed=bool(esc.get("enqueue_attention")),
            attention_kind=esc.get("attention_kind"),
            attention_title=esc.get("attention_title"),
            attention_priority=int(esc.get("attention_priority", 20)),
        )
        decision_dict["escalation_row"] = recorded

    return decision_dict


def _is_auditor_mutating_command(cmd_str: str) -> bool:
    if not cmd_str:
        return False
    if _R5_AUDITOR_MUTATING_CMD_RE.search(cmd_str):
        return True
    scrubbed = _SAFE_REDIRECT_STRIP_RE.sub("", cmd_str)
    return bool(_FILE_REDIRECT_RE.search(scrubbed))


def _architect_cmd_mutates_outside_agents(cmd_str: str) -> str | None:
    if not cmd_str:
        return None
    scrubbed = _SAFE_REDIRECT_STRIP_RE.sub("", cmd_str)
    redirs = _FILE_REDIRECT_RE.findall(scrubbed)
    for target in redirs:
        cleaned = target.strip("'\"")
        if cleaned and not cleaned.startswith(".agents/"):
            return cleaned

    mut_match = re.search(
        r"\b(?:rm|mv|cp|touch|tee)\s+(?:-[a-zA-Z]+\s+)*([^\s;|>&]+)",
        scrubbed,
    )
    if mut_match:
        target = mut_match.group(1).strip("'\"")
        if target and not target.startswith(".agents/") and not target.startswith("/dev/null"):
            return target
    return None


def _workspace_subpath(rel_posix: str, real_root: Path, ws_dir: Path) -> str | None:
    prefixes: list[str] = []
    if ws_dir.is_relative_to(real_root):
        prefixes.append(ws_dir.relative_to(real_root).as_posix())
    for p in (common.NEW_WORKSPACE_REL.as_posix(), common.LEGACY_WORKSPACE_REL.as_posix()):
        if p not in prefixes:
            prefixes.append(p)

    for pfx in prefixes:
        if rel_posix == pfx:
            return ""
        if rel_posix.startswith(pfx + "/"):
            return rel_posix[len(pfx) + 1 :]
    return None


def _find_project_doc(ws_dir: Path, pr_id: str | None) -> Any | None:
    import schemas

    candidates = sorted(ws_dir.glob("pr-*/PROJECT.md"))
    loaded: list[Any] = []
    for path in candidates:
        try:
            doc = schemas.load_project(path)
        except Exception:  # noqa: BLE001, S112
            continue
        if pr_id and doc.spec.charter.pr_id.upper() == pr_id.upper():
            return doc
        loaded.append(doc)

    if pr_id is None and len(loaded) == 1:
        return loaded[0]
    return None


def _find_bound_workorder(ws_dir: Path, pr_id: str | None, wo_id: str | None) -> Any | None:
    import schemas

    candidates = sorted(ws_dir.glob("pr-*/wo*/WORKORDER.md"))
    loaded: list[Any] = []
    for path in candidates:
        try:
            doc = schemas.load_workorder(path)
        except Exception:  # noqa: BLE001, S112
            continue
        if (
            wo_id
            and doc.spec.wo_id.upper() == wo_id.upper()
            and (not pr_id or doc.spec.pr_id.upper() == pr_id.upper())
        ):
            return doc
        loaded.append(doc)

    if wo_id is None and len(loaded) == 1:
        return loaded[0]
    return None


def _check_r6_graduation_gate(
    cmd_str: str,
    real_root: Path,
    ws_dir: Path,
    pr_id: str | None,
    mode: str,
    db: state_db.StateDB,
    session: dict[str, Any] | None,
    runner: common.Runner,
) -> dict[str, Any] | None:
    import schemas

    res = runner(["git", "rev-parse", "HEAD"], cwd=real_root)
    head_sha = res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else "HEAD"

    m = _PR_ID_TOKEN_RE.search(cmd_str)
    target_pr_id = m.group(1).upper() if m else pr_id
    if not target_pr_id:
        proj_doc = _find_project_doc(ws_dir, None)
        if proj_doc is not None:
            target_pr_id = proj_doc.spec.charter.pr_id

    for audit_path in sorted(ws_dir.glob("pr-*/AUDIT-round-*.md")):
        try:
            audit_doc = schemas.load_audit(audit_path)
        except Exception:  # noqa: BLE001, S112
            continue
        report = audit_doc.spec
        if target_pr_id and report.pr_id.upper() != target_pr_id.upper():
            continue
        if (
            report.verdict == "APPROVED"
            and head_sha != "HEAD"
            and (head_sha.startswith(report.head_sha) or report.head_sha.startswith(head_sha))
        ):
            return None

    return _finalize_decision(
        db,
        session,
        escalation.decide(
            "R6",
            mode,
            {"pr_id": target_pr_id or "PR-??", "head_sha": head_sha[:12]},
        ),
    )


def _check_architect_file_gates(
    role: str,
    tool_name: str,
    args: Mapping[str, Any],
    raw_path: str,
    real_root: Path,
    ws_dir: Path,
    pr_id: str | None,
    mode: str,
    db: state_db.StateDB,
    session: dict[str, Any] | None,
) -> dict[str, Any] | None:
    inside_repo, rel_posix, real_target = resolve_repo_rel_path(real_root, raw_path)
    ws_sub = _workspace_subpath(rel_posix, real_root, ws_dir) if inside_repo else None
    if not inside_repo or ws_sub is None:
        return _finalize_decision(
            db,
            session,
            escalation.decide(
                "R1",
                mode,
                {"path": rel_posix if inside_repo else raw_path, "pr_id": pr_id},
            ),
        )

    target_name = Path(ws_sub).name
    if role == "chief":
        if target_name == "WORKORDER.md":
            return _finalize_decision(
                db,
                session,
                escalation.decide("R1", mode, {"path": rel_posix, "pr_id": pr_id}),
            )
        return None

    # role == "pa"
    import schemas

    if target_name == "PROGRAM.md":
        return _finalize_decision(
            db,
            session,
            escalation.decide("R1b", mode, {"path": rel_posix, "pr_id": pr_id}),
        )

    if target_name == "PROJECT.md" and real_target.is_file():
        try:
            existing_proj = schemas.load_project(real_target)
        except Exception:  # noqa: BLE001
            existing_proj = None

        if existing_proj is not None and existing_proj.spec.charter.charter_locked:
            existing_text = real_target.read_text(encoding="utf-8")
            proposed_text = simulate_file_edit(existing_text, tool_name, args)
            charter_intact = False
            if proposed_text is not None:
                try:
                    fm_data, proposed_sections = schemas.parse_document(proposed_text)
                    proposed_spec = schemas.ProjectSpec.model_validate(fm_data)
                    if proposed_spec.charter == existing_proj.spec.charter:
                        new_hash = schemas.compute_charter_hash(
                            proposed_spec.charter, proposed_sections
                        )
                        if new_hash == existing_proj.spec.charter.charter_hash:
                            charter_intact = True
                except Exception:  # noqa: BLE001
                    charter_intact = False

            if not charter_intact:
                return _finalize_decision(
                    db,
                    session,
                    escalation.decide(
                        "R1b",
                        mode,
                        {
                            "path": rel_posix,
                            "pr_id": existing_proj.spec.charter.pr_id,
                        },
                    ),
                )

    if target_name == "WORKORDER.md":
        existing_text = real_target.read_text(encoding="utf-8") if real_target.is_file() else ""
        proposed_text = simulate_file_edit(existing_text, tool_name, args)
        if proposed_text is not None:
            try:
                fm_data, _ = schemas.parse_document(proposed_text)
                wo_spec = schemas.WorkOrderSpec.model_validate(fm_data)
            except Exception:  # noqa: BLE001
                wo_spec = None

            if wo_spec is not None:
                proj_path = real_target.parent.parent / "PROJECT.md"
                proj_doc = None
                if proj_path.is_file():
                    try:
                        proj_doc = schemas.load_project(proj_path)
                    except Exception:  # noqa: BLE001
                        proj_doc = None
                if proj_doc is None:
                    proj_doc = _find_project_doc(ws_dir, wo_spec.pr_id or pr_id)

                if proj_doc is not None:
                    allowed_mods = proj_doc.spec.charter.allowed_modules
                    for af in wo_spec.allowed_files:
                        if not (
                            matches_any_pattern(af, allowed_mods)
                            or matches_any_pattern(af.rstrip("/"), allowed_mods)
                        ):
                            return _finalize_decision(
                                db,
                                session,
                                escalation.decide(
                                    "R1b",
                                    mode,
                                    {
                                        "path": af,
                                        "pr_id": proj_doc.spec.charter.pr_id,
                                        "wo_id": wo_spec.wo_id,
                                        "requested_files": [af],
                                    },
                                ),
                            )

    return None


def _check_r2_plan_approval_gate(
    args: Mapping[str, Any],
    ws_dir: Path,
    pr_id: str | None,
    mode: str,
    db: state_db.StateDB,
    session: dict[str, Any] | None,
) -> dict[str, Any] | None:
    sub_type = str(
        args.get("TypeName") or args.get("subagent_type") or args.get("type_name") or ""
    ).strip()
    sub_role = str(args.get("Role") or args.get("role") or "").strip()
    sub_prompt = str(args.get("Prompt") or args.get("prompt") or "").strip()

    if "auditor" in sub_type.lower() or "auditor" in sub_role.lower():
        return None

    is_worker_spawn = (
        sub_type == "pa-engineer"
        or "engineer" in sub_role.lower()
        or "worker" in sub_role.lower()
        or "pa_role: engineer" in sub_prompt.lower()
    )
    if not is_worker_spawn:
        return None

    import schemas

    target_pr_id = pr_id
    if not target_pr_id:
        m = _PR_ID_TOKEN_RE.search(sub_prompt)
        if m:
            target_pr_id = m.group(1).upper()

    proj_doc = _find_project_doc(ws_dir, target_pr_id)
    if proj_doc is None or proj_doc.spec.status != schemas.PRState.PLANNED:
        return None

    auto_approve = (
        db.get_config("auto_approve_pr_plans", "false") or "false"
    ).strip().lower() in ("true", "1", "yes")

    plan_valid = False
    proj_path = proj_doc.path
    if (
        proj_path is not None
        and schemas.verify_charter_hash(proj_doc)
        and len(proj_doc.spec.work_orders) >= 1
    ):
        wo_paths = sorted(proj_path.parent.glob("wo*/WORKORDER.md"))
        if len(wo_paths) >= len(proj_doc.spec.work_orders):
            all_wos_ok = True
            allowed_mods = proj_doc.spec.charter.allowed_modules
            loaded_wos: list[Any] = []
            for wp in wo_paths:
                try:
                    wdoc = schemas.load_workorder(wp)
                except Exception:  # noqa: BLE001
                    all_wos_ok = False
                    break
                for af in wdoc.spec.allowed_files:
                    if not (
                        matches_any_pattern(af, allowed_mods)
                        or matches_any_pattern(af.rstrip("/"), allowed_mods)
                    ):
                        all_wos_ok = False
                        break
                if not all_wos_ok:
                    break
                loaded_wos.append(wdoc)
            plan_valid = all_wos_ok
    else:
        loaded_wos = []

    decision = escalation.decide(
        "R2",
        mode,
        {
            "pr_id": proj_doc.spec.charter.pr_id,
            "auto_approve_pr_plans": auto_approve,
            "plan_valid": plan_valid,
        },
    )

    if decision.get("auto_approve_plan") and proj_path is not None:
        proj_doc.spec.status = schemas.PRState.APPROVED
        proj_doc.spec.approved_at = datetime.now(UTC)
        for wdoc in loaded_wos:
            if not wdoc.spec.spec_hash and wdoc.path is not None:
                wdoc.spec.spec_hash = schemas.compute_spec_hash(wdoc)
                wdoc.path.write_text(
                    schemas.dump_document(wdoc.spec, wdoc.sections),
                    encoding="utf-8",
                )
        proj_path.write_text(
            schemas.dump_document(proj_doc.spec, proj_doc.sections),
            encoding="utf-8",
        )

    return _finalize_decision(db, session, decision)


def _check_worker_gates(
    tool_name: str,
    args: Mapping[str, Any],
    raw_path: str,
    cmd_str: str,
    real_root: Path,
    ws_dir: Path,
    pr_id: str | None,
    wo_id: str | None,
    mode: str,
    db: state_db.StateDB,
    session: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if tool_name == "run_command":
        scrubbed_cmd = _COMMIT_MSG_QUOTED_RE.sub("", cmd_str)
        if _R4_FORBIDDEN_GIT_GH_RE.search(scrubbed_cmd):
            return _finalize_decision(
                db,
                session,
                escalation.decide(
                    "R4",
                    mode,
                    {"command": cmd_str, "pr_id": pr_id, "wo_id": wo_id},
                ),
            )
        return None

    if tool_name not in FILE_MUTATION_TOOLS:
        return None

    inside_repo, rel_posix, real_target = resolve_repo_rel_path(real_root, raw_path)
    if not inside_repo:
        return _finalize_decision(
            db,
            session,
            escalation.decide(
                "R3",
                mode,
                {
                    "path": raw_path,
                    "pr_id": pr_id,
                    "wo_id": wo_id,
                    "reason_code": "PATH_TRAVERSAL_BLOCKED",
                },
            ),
        )

    import schemas

    wo_doc = _find_bound_workorder(ws_dir, pr_id, wo_id)
    if wo_doc is None or wo_doc.path is None:
        return None

    wo_md_path = Path(os.path.realpath(wo_doc.path))
    eff_pr_id = pr_id or wo_doc.spec.pr_id
    eff_wo_id = wo_id or wo_doc.spec.wo_id

    if real_target == wo_md_path:
        if wo_doc.spec.spec_hash:
            existing_text = wo_md_path.read_text(encoding="utf-8")
            proposed_text = simulate_file_edit(existing_text, tool_name, args)
            spec_intact = False
            if proposed_text is not None:
                try:
                    fm_data, proposed_sections = schemas.parse_document(proposed_text)
                    proposed_spec = schemas.WorkOrderSpec.model_validate(fm_data)
                    if (
                        proposed_spec.spec_hash == wo_doc.spec.spec_hash
                        and schemas.verify_spec_hash(proposed_spec, proposed_sections)
                    ):
                        spec_intact = True
                except Exception:  # noqa: BLE001
                    spec_intact = False

            if not spec_intact:
                return _finalize_decision(
                    db,
                    session,
                    escalation.decide(
                        "R3",
                        mode,
                        {
                            "path": rel_posix,
                            "pr_id": eff_pr_id,
                            "wo_id": eff_wo_id,
                            "reason_code": "SPEC_LOCK_VIOLATION",
                        },
                    ),
                )
        return None

    if matches_any_pattern(rel_posix, wo_doc.spec.forbidden_files) or not matches_any_pattern(
        rel_posix, wo_doc.spec.allowed_files
    ):
        return _finalize_decision(
            db,
            session,
            escalation.decide(
                "R3",
                mode,
                {
                    "path": rel_posix,
                    "pr_id": eff_pr_id,
                    "wo_id": eff_wo_id,
                    "reason_code": "BOUNDARY_EXPANSION_NEEDED",
                },
            ),
        )

    return None


def evaluate_pre_tool(
    payload: Mapping[str, Any],
    *,
    repo_root: str | Path | None = None,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Evaluate a `PreToolUse` hook event against rules R1..R6.

    Executes an immediate `<1ms` fast-exit returning `{}` when the workspace is not
    enrolled in the global PA Registry (or local `.state/state.db` when `repo_root` is
    explicitly passed).
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
    db_path = ws_dir / ".state" / "state.db"

    tool_name, args = _extract_tool_name_and_args(payload)
    if not tool_name:
        return {"permissionDecision": "allow", "decision": "allow", "reason": "No tool specified"}

    raw_path = _extract_target_path(args)
    cmd_str = _extract_command_str(args)

    with state_db.StateDB(db_path) as db:
        raw_mode = (db.get_config("execution_mode", "monitored") or "monitored").strip().lower()
        mode = raw_mode if raw_mode in ("monitored", "autonomous") else "monitored"

        conversation_id = str(
            payload.get("conversationId") or payload.get("conversation_id") or ""
        ).strip()
        session = db.get_session(conversation_id) if conversation_id else None

        raw_role = (session.get("role") if session else None) or payload.get("role")
        role = _normalize_role(str(raw_role) if raw_role is not None else None)
        pr_id = (
            (session.get("pr_id") if session else None)
            or payload.get("prId")
            or payload.get("pr_id")
        )
        wo_id = (
            (session.get("wo_id") if session else None)
            or payload.get("woId")
            or payload.get("wo_id")
        )

        # Rule R6: Graduation Audit Gate (applies regardless of role)
        if tool_name == "run_command" and _R6_GRADUATE_RE.search(cmd_str):
            r6_res = _check_r6_graduation_gate(
                cmd_str, real_root, ws_dir, pr_id, mode, db, session, runner
            )
            if r6_res is not None:
                return r6_res

        # Rule R5: Auditor Read-Only Lockdown
        if role == "auditor":
            if tool_name in FILE_MUTATION_TOOLS or tool_name == "invoke_subagent":
                target_desc = raw_path or tool_name
                return _finalize_decision(
                    db,
                    session,
                    escalation.decide(
                        "R5", mode, {"path": target_desc, "command": target_desc}
                    ),
                )
            if tool_name == "run_command" and _is_auditor_mutating_command(cmd_str):
                return _finalize_decision(
                    db,
                    session,
                    escalation.decide("R5", mode, {"command": cmd_str, "path": cmd_str}),
                )

        # Rules R1 & R1b: Architect No-Inline-Code & Charter Lock
        if role in ("chief", "pa"):
            if tool_name in FILE_MUTATION_TOOLS and raw_path:
                arch_res = _check_architect_file_gates(
                    role,
                    tool_name,
                    args,
                    raw_path,
                    real_root,
                    ws_dir,
                    pr_id,
                    mode,
                    db,
                    session,
                )
                if arch_res is not None:
                    return arch_res
            elif tool_name == "run_command":
                offending = _architect_cmd_mutates_outside_agents(cmd_str)
                if offending is not None:
                    return _finalize_decision(
                        db,
                        session,
                        escalation.decide("R1", mode, {"path": offending, "pr_id": pr_id}),
                    )

        # Rule R2: Plan Approval Gate on PA invoke_subagent
        if role == "pa" and tool_name == "invoke_subagent":
            r2_res = _check_r2_plan_approval_gate(args, ws_dir, pr_id, mode, db, session)
            if r2_res is not None:
                return r2_res

        # Rules R3 & R4: Worker Boundary Box, Spec Lock & Git/GH Lockdown
        if role == "engineer":
            worker_res = _check_worker_gates(
                tool_name,
                args,
                raw_path,
                cmd_str,
                real_root,
                ws_dir,
                pr_id,
                wo_id,
                mode,
                db,
                session,
            )
            if worker_res is not None:
                return worker_res

    return {
        "permissionDecision": "allow",
        "decision": "allow",
        "reason": "Allowed by pre_tool_gate",
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `PreToolUse` hook (`pre_tool_gate.py`)."""
    _ = argv
    payload = escalation.read_hook_input()
    try:
        res = evaluate_pre_tool(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[principal-architect] pre_tool_gate error: {exc}", file=sys.stderr)
        res = {}
    out: dict[str, Any] = {}
    if isinstance(res, Mapping) and res.get("decision"):
        dec = str(res["decision"])
        out["decision"] = "force_ask" if dec == "ask" else dec
        if res.get("reason"):
            out["reason"] = str(res["reason"])
    return escalation.write_hook_output(out)


if __name__ == "__main__":
    raise SystemExit(main())
