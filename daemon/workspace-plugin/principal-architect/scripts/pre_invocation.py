#!/usr/bin/env python3
"""PreInvocation hook for session role binding, compaction/rewind detection, and context injection.

Implements SPEC §7.1 & §9.1–9.2 and PR-02 Charter G6, R1, and R2:
- `< 1 ms` fast-exit when the target workspace is not enrolled in Registry.
- Lazy import rule (Charter G2 & R1): `pydantic`, `yaml`, and `schemas` are NEVER imported
  at module top-level or on the unenrolled fast path.
- `parse_spawn_header(text)` parsing `PA_ROLE:`, `PR_ID:`, `WO_ID:`, and `PROGRAMME_ID:`
  from subagent spawn prompts and transcript steps.
- Automatic Turn 1 session binding in `.state/state.db` (`sessions` table) for unbound
  `conversationId` instances.
- Compaction (`CHECKPOINT` step) and step-rewind detection on `transcript.jsonl` to
  re-arm context injection after context window compaction or user rewind.
- Role-specific persistent `{"injectSteps": [{"userMessage": "..."}]}` payload generation
  enforcing the strict `memory_mode` boundary (`builtin` vs `external`).
"""

from __future__ import annotations

import os
import re
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

_SPAWN_HEADER_LINE_RE = re.compile(
    r"^\s*(?:[>\-*]+\s*)?[\*_`]*\b(PA_ROLE|PR_ID|WO_ID|PROGRAMME_ID)\b[\*_`]*\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)


def parse_spawn_header(text: str) -> dict[str, str]:
    """Parse `PA_ROLE:`, `PR_ID:`, `WO_ID:`, and `PROGRAMME_ID:` lines from `text`.

    Normalizes `PA_ROLE` via `pre_tool_gate._normalize_role` into `"role"` and returns
    a dictionary of non-empty parsed fields (`"role"`, `"pr_id"`, `"wo_id"`, `"programme_id"`).
    """
    if not text or not isinstance(text, str):
        return {}

    parsed: dict[str, str] = {}
    for line in text.splitlines():
        m = _SPAWN_HEADER_LINE_RE.match(line)
        if not m:
            continue
        raw_key = m.group(1).upper()
        raw_val = m.group(2).strip().strip("`'\"*")
        if not raw_val or raw_val.lower() in ("null", "none"):
            continue

        if raw_key == "PA_ROLE":
            norm_role = pre_tool_gate._normalize_role(raw_val)
            if norm_role and "role" not in parsed:
                parsed["role"] = norm_role
        elif raw_key == "PR_ID":
            if "pr_id" not in parsed:
                parsed["pr_id"] = raw_val
        elif raw_key == "WO_ID":
            if "wo_id" not in parsed:
                parsed["wo_id"] = raw_val
        elif raw_key == "PROGRAMME_ID":
            if "programme_id" not in parsed:
                parsed["programme_id"] = raw_val

    return parsed


def _extract_spawn_headers_from_payload_and_steps(
    payload: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Collect candidate prompt strings from `payload` and `steps` and merge spawn headers."""
    candidates: list[str] = []
    for key in ("prompt", "userMessage", "message", "initialPrompt"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            candidates.append(val)

    for step in steps:
        if not isinstance(step, Mapping):
            continue
        content = step.get("content")
        if isinstance(content, str) and content.strip():
            candidates.append(content)

    merged: dict[str, str] = {}
    for text in candidates:
        hdr = parse_spawn_header(text)
        for k, v in hdr.items():
            if k not in merged and v:
                merged[k] = v
        if "role" in merged and "pr_id" in merged and "wo_id" in merged and "programme_id" in merged:
            break
    return merged


def _extract_matching_module_index_sections(
    module_index_text: str,
    allowed_modules: Sequence[str],
) -> str:
    """Filter H2 sections of `MODULE_INDEX.md` matching `allowed_modules` (or full text fallback)."""
    stripped_full = module_index_text.strip()
    if not stripped_full or not allowed_modules:
        return stripped_full

    chunks = re.split(r"(?m)^(?=## )", stripped_full)
    h2_sections = [c.strip() for c in chunks if c.strip().startswith("## ")]
    if not h2_sections:
        return stripped_full

    search_tokens: list[str] = []
    for mod in allowed_modules:
        raw_mod = str(mod).strip()
        if not raw_mod:
            continue
        cleaned = raw_mod.strip("/").lower()
        if cleaned and cleaned not in search_tokens:
            search_tokens.append(cleaned)
        base_name = Path(cleaned).name.lower() if cleaned else ""
        if base_name and len(base_name) >= 3 and base_name not in search_tokens:
            search_tokens.append(base_name)

    if not search_tokens:
        return stripped_full

    matched: list[str] = []
    for sec in h2_sections:
        sec_lower = sec.lower()
        if any(tok in sec_lower for tok in search_tokens):
            matched.append(sec)

    if matched:
        return "\n\n".join(matched)
    return stripped_full


def _resolve_skill_paths(repo_root: Path, required_skills: Sequence[str]) -> list[str]:
    """Resolve explicit `SKILL.md` paths on disk for each skill slug in `required_skills`.

    Searches in precedence order:
    1. Repo-local `<repo>/.agents/skills/<slug>/SKILL.md`
    2. Bundled PA workspace plugin skills
    3. User global `~/.gemini/config/skills/<slug>/SKILL.md`
    4. Installed global plugin skills `~/.gemini/config/plugins/*/skills/<slug>/SKILL.md`
    5. Built-in skills `~/.gemini/jetski/builtin/skills/<slug>/SKILL.md`
    """
    real_root = Path(os.path.realpath(repo_root))
    d_home = common.daemon_home()
    user_home = Path(os.path.realpath(Path.home()))
    plugins_root = user_home / ".gemini" / "config" / "plugins"

    resolved: list[str] = []
    for raw_skill in required_skills:
        slug = str(raw_skill).strip()
        if not slug:
            continue
        plugin_skill_candidates = (
            sorted(plugins_root.glob(f"*/skills/{slug}/SKILL.md"))
            if plugins_root.is_dir()
            else []
        )
        candidates = (
            real_root / ".agents" / "skills" / slug / "SKILL.md",
            d_home / "workspace-plugin" / "principal-architect" / "skills" / slug / "SKILL.md",
            user_home / ".gemini" / "config" / "skills" / slug / "SKILL.md",
            *plugin_skill_candidates,
            user_home / ".gemini" / "jetski" / "builtin" / "skills" / slug / "SKILL.md",
            user_home / ".gemini" / "jetski" / "builtin" / "contrib" / "skills" / slug / "SKILL.md",
        )
        chosen: Path | None = None
        for cand in candidates:
            if cand.is_file():
                chosen = cand
                break
        if chosen is not None:
            resolved.append(str(chosen))
        else:
            resolved.append(str(real_root / ".agents" / "skills" / slug / "SKILL.md"))
    return resolved


def _find_active_project_doc(ws_dir: Path, pr_id: str | None) -> Any | None:
    """Locate the active `PROJECT.md` matching `pr_id` or fallback to the first `pr-*/PROJECT.md`."""
    import schemas

    doc = pre_tool_gate._find_project_doc(ws_dir, pr_id)
    if doc is not None:
        return doc

    for path in sorted(ws_dir.glob("pr-*/PROJECT.md")):
        try:
            return schemas.load_project(path)
        except Exception:  # noqa: BLE001, S112
            continue
    return None


def _find_active_program_doc(ws_dir: Path, programme_id: str | None) -> Any | None:
    """Locate the active `PROGRAM.md` matching `programme_id` or first `programme-*/PROGRAM.md`."""
    import schemas

    candidates = sorted(ws_dir.glob("programme-*/PROGRAM.md"))
    loaded: list[Any] = []
    for path in candidates:
        try:
            doc = schemas.load_program(path)
        except Exception:  # noqa: BLE001, S112
            continue
        if programme_id and doc.spec.programme_id.lower() == programme_id.lower():
            return doc
        loaded.append(doc)
    return loaded[0] if loaded else None


def _build_architect_injection(
    *,
    role: str,
    session: Mapping[str, Any],
    ws_dir: Path,
    db: state_db.StateDB,
    execution_mode: str,
    memory_mode: str,
) -> str:
    """Build the persistent `userMessage` context block for `chief` or `pa` roles."""
    pr_id = str(session.get("pr_id") or "").strip() or None
    programme_id = str(session.get("programme_id") or "").strip() or None

    lines: list[str] = [
        f"## Principal Architect Active Context (`role={role}`, `execution_mode={execution_mode}`, `memory_mode={memory_mode}`)"
    ]

    prog_doc = _find_active_program_doc(ws_dir, programme_id)
    if prog_doc is not None:
        pspec = prog_doc.spec
        lines.append(
            f"- **Programme:** `{pspec.programme_id}` — {pspec.title} "
            f"(`status: {pspec.status}`, `base_branch: {pspec.base_branch}`)"
        )

    proj_doc = _find_active_project_doc(ws_dir, pr_id)
    allowed_modules: list[str] = []
    resolved_pr_id = pr_id
    if proj_doc is not None:
        cspec = proj_doc.spec.charter
        resolved_pr_id = cspec.pr_id
        allowed_modules = list(cspec.allowed_modules)
        lines.append(
            f"- **Active PR:** `{cspec.pr_id}` ({cspec.slug}) — {cspec.title}\n"
            f"  - Status: `{proj_doc.spec.status.value}` | Branch: `{cspec.branch}` -> `{cspec.base_branch}` "
            f"| Charter Locked: `{cspec.charter_locked}`\n"
            f"  - Allowed Modules: `{', '.join(allowed_modules)}`\n"
            f"  - Verification Floor: `{'; '.join(cspec.verification_floor) or 'none'}`"
        )
        if proj_doc.spec.work_orders:
            wo_bits = [
                f"{row.id} ({row.status.value}, {row.complexity.value})"
                for row in proj_doc.spec.work_orders
            ]
            lines.append(f"  - Work Orders: {', '.join(wo_bits)}")

    open_escs = db.open_escalations(target_role=role)
    if not open_escs and resolved_pr_id:
        open_escs = db.open_escalations(pr_id=resolved_pr_id)
    if open_escs:
        lines.append("### Open Escalations")
        for esc in open_escs:
            lines.append(
                f"- `{esc['escalation_id']}` [{esc['level']}] `{esc['reason_code']}` "
                f"(PR={esc.get('pr_id') or '-'}, WO={esc.get('wo_id') or '-'}): {esc.get('summary') or ''}"
            )

    if memory_mode == "external":
        lines.append(
            "Memory Mode: external — Use Succinct Write-Back Mode (defer codebase memory to "
            "repo-memory-plugin; record only mechanical status, WO table, and cross-PR notes in "
            "PROJECT.md Part III)."
        )
    else:
        lines.append(
            "Memory Mode: builtin — Use Full Distillation Mode (update MEMORY.md, "
            "MODULE_INDEX.md, and Outcome & Session Log)."
        )
        mem_file = ws_dir / "memory" / "MEMORY.md"
        if mem_file.is_file():
            mem_text = mem_file.read_text(encoding="utf-8").strip()
            if mem_text:
                lines.append(f"### Builtin Memory (MEMORY.md)\n{mem_text}")

        mod_index_file = ws_dir / "memory" / "MODULE_INDEX.md"
        if mod_index_file.is_file():
            mod_text = mod_index_file.read_text(encoding="utf-8")
            extracted = _extract_matching_module_index_sections(mod_text, allowed_modules)
            if extracted:
                lines.append(f"### Module Index (MODULE_INDEX.md)\n{extracted}")

    return "\n\n".join(lines)


def _build_engineer_injection(
    *,
    session: Mapping[str, Any],
    real_root: Path,
    ws_dir: Path,
    execution_mode: str,
    memory_mode: str,
) -> str:
    """Build the persistent `userMessage` contract block for `pa-engineer`."""
    import schemas

    pr_id = str(session.get("pr_id") or "").strip() or None
    wo_id = str(session.get("wo_id") or "").strip() or None
    attempt_num = int(session.get("attempt_num") or 1)
    structural_failures = int(session.get("structural_failures") or 0)

    wo_doc = pre_tool_gate._find_bound_workorder(ws_dir, pr_id, wo_id)
    if wo_doc is None:
        write_back_line = (
            "Write-Back Mode: Succinct Mode (memory_mode=external) — keep Completion Report strictly mechanical."
            if memory_mode == "external"
            else "Write-Back Mode: Full Distillation Mode (memory_mode=builtin) — populate decisions_made and dead_ends in Completion Report while prompt cache is warm."
        )
        return (
            f"## Worker Execution Contract (`role=engineer`, `wo_id={wo_id or 'unbound'}`, "
            f"`pr_id={pr_id or 'unbound'}`, `execution_mode={execution_mode}`)\n\n"
            f"- Retry Budget: attempt {attempt_num} (structural_failures: {structural_failures})\n"
            f"- {write_back_line}"
        )

    wspec = wo_doc.spec
    skill_paths = _resolve_skill_paths(real_root, wspec.required_skills)
    part1_sections = schemas._part1_workorder_sections(wo_doc.sections)
    part1_headings = ", ".join(s.heading for s in part1_sections if s.heading)

    lines: list[str] = [
        (
            f"## Worker Execution Contract (`WO_ID={wspec.wo_id}`, `PR_ID={wspec.pr_id}`, "
            f"`complexity={wspec.complexity.value}`, `execution_mode={execution_mode}`)"
        ),
        f"- **Title:** {wspec.title}",
        (
            f"- **Retry Budget:** attempt {attempt_num} of {wspec.max_attempts} "
            f"(structural_failures: {structural_failures}/{wspec.max_structural_failures})"
        ),
        f"- **Allowed Files (`allowed_files`):** {', '.join(wspec.allowed_files)}",
        f"- **Forbidden Files (`forbidden_files`):** {', '.join(wspec.forbidden_files) or 'none'}",
        f"- **Verification Command (`verification_command`):** `{wspec.verification_command}`",
    ]
    if part1_headings:
        lines.append(f"- **Part I Spec Sections:** {part1_headings}")
    if skill_paths:
        lines.append(f"- **Required Skills (`SKILL.md` paths):** {', '.join(skill_paths)}")
    else:
        lines.append("- **Required Skills (`SKILL.md` paths):** none")

    if memory_mode == "external":
        lines.append(
            "Write-Back Mode: Succinct Mode (memory_mode=external) — keep Completion Report "
            "strictly mechanical (status, attempt_num, receipt_id, commit_sha, files_modified, "
            "1-line verification_summary <= 280 chars; omit narrative decisions_made/dead_ends "
            "unless escalating)."
        )
    else:
        lines.append(
            "Write-Back Mode: Full Distillation Mode (memory_mode=builtin) — populate "
            "decisions_made and dead_ends in Completion Report while prompt cache is warm."
        )

    return "\n".join(lines)


def evaluate_pre_invocation(
    payload: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Evaluate a `PreInvocation` hook event for role binding, compaction/rewind, and injection.

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

    conv_id = str(
        payload.get("conversationId") or payload.get("conversation_id") or ""
    ).strip()
    if not conv_id:
        return {}

    t_path = payload.get("transcriptPath") or payload.get("transcript_path")
    steps = common.read_transcript(common._strip_file_uri(str(t_path))) if t_path else []
    latest_cp = common.latest_checkpoint_step(steps)
    step_watermark = latest_cp if latest_cp is not None else len(steps)

    with state_db.StateDB(db_file) as db:
        session = db.get_session(conv_id)
        should_inject = False

        if session is None:
            parsed = _extract_spawn_headers_from_payload_and_steps(payload, steps)
            role_val = parsed.get("role", "")
            if not role_val:
                return {}
            session = db.bind_session(
                conv_id,
                role=role_val,
                programme_id=parsed.get("programme_id"),
                pr_id=parsed.get("pr_id"),
                wo_id=parsed.get("wo_id"),
                attempt_num=1,
                structural_failures=0,
                pinned=0,
                last_checkpoint_step=step_watermark,
            )
            should_inject = True
        else:
            parsed = _extract_spawn_headers_from_payload_and_steps(payload, steps)
            missing_updates: dict[str, Any] = {}
            for field_key in ("programme_id", "pr_id", "wo_id"):
                if not session.get(field_key) and parsed.get(field_key):
                    missing_updates[field_key] = parsed[field_key]
            if missing_updates:
                session = db.update_session(conv_id, **missing_updates) or session

            prev_cp = session.get("last_checkpoint_step")
            inv_num = (
                payload.get("invocationNum")
                if "invocationNum" in payload
                else payload.get("invocation_num")
            )
            should_inject = bool(
                prev_cp is None
                or inv_num == 1
                or (latest_cp is not None and int(latest_cp) > int(prev_cp))
                or (steps and step_watermark < int(prev_cp))
            )

            if should_inject or (steps and step_watermark != prev_cp):
                session = (
                    db.update_session(conv_id, last_checkpoint_step=step_watermark)
                    or session
                )

        if not should_inject:
            return {}

        memory_mode = (db.get_config("memory_mode") or "builtin").strip().lower()
        if memory_mode not in ("builtin", "external"):
            memory_mode = "builtin"
        execution_mode = (db.get_config("execution_mode") or "monitored").strip().lower()
        if execution_mode not in ("monitored", "autonomous"):
            execution_mode = "monitored"

        role = pre_tool_gate._normalize_role(str(session.get("role") or ""))
        if role in ("chief", "pa"):
            msg_text = _build_architect_injection(
                role=role,
                session=session,
                ws_dir=ws_dir,
                db=db,
                execution_mode=execution_mode,
                memory_mode=memory_mode,
            )
        elif role == "engineer":
            msg_text = _build_engineer_injection(
                session=session,
                real_root=real_root,
                ws_dir=ws_dir,
                execution_mode=execution_mode,
                memory_mode=memory_mode,
            )
        else:
            pr_id_str = str(session.get("pr_id") or "-")
            wo_id_str = str(session.get("wo_id") or "-")
            msg_text = (
                f"## Principal Architect Session Reminder (`role={role}`, "
                f"`pr_id={pr_id_str}`, `wo_id={wo_id_str}`, "
                f"`execution_mode={execution_mode}`, `memory_mode={memory_mode}`)"
            )

        return {"injectSteps": [{"userMessage": msg_text}]}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for `PreInvocation` hook (`pre_invocation.py`)."""
    _ = argv
    payload = escalation.read_hook_input()
    try:
        res = evaluate_pre_invocation(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[principal-architect] pre_invocation error: {exc}", file=sys.stderr)
        res = {}
    return escalation.write_hook_output(res)


if __name__ == "__main__":
    raise SystemExit(main())
