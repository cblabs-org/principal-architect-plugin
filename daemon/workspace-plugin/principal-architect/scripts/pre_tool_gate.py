#!/usr/bin/env python3
"""Principal Architect Plugin (c) 2026 Matt McNeill
https://github.com/matthewmcneill/principal-architect-plugin
SPDX-License-Identifier: Apache-2.0
Module: daemon/workspace-plugin/principal-architect/scripts/pre_tool_gate.py

PreToolUse governance gate enforcing Split-Authority rules R1, R1b, R2, R3, R4, R5, and R6.
Plays the pre-execution boundary-enforcement role in the Split-Authority enforcement pipeline
(SPEC §7.2 and §11.2):
- Executes a `< 1 ms` fast-exit when the target workspace is not enrolled in the Registry.
- Enforces the lazy import rule (Charter G2 & R1): `pydantic`, `yaml`, and `schemas` are
  never imported at module top-level or on the unenrolled fast path.
- Performs canonical path resolution (`os.path.realpath`) preventing `../` path traversal
  and symlink escapes outside `repo_root`, `allowed_files`, or `.agents/`.
- Enforces symmetric `monitored` (`ask`) vs `autonomous` (`deny` + StateDB escalation)
  governance decisions via `escalation.decide` across all agent tiers:
  * R1 / R1b: Architect (`chief` / `pa`) no-inline-code restriction and PR Charter lock.
  * R2: Principal Architect (`pa`) plan approval gate prior to spawning `pa-engineer`.
  * R3 / R4: Worker (`engineer`) `allowed_files` boundary box, Part I `spec_hash` lock,
    and forbidden git/GitHub CLI command lockdown.
  * R5: Cold-Firewall Auditor (`auditor`) strict read-only lockdown.
  * R6: Graduation audit gate requiring an `APPROVED` `AuditReport` for current `HEAD`.

Exported API Summary:
  Constants & Compiled Regexes:
    _SCRIPTS_DIR: Absolute directory path containing the hook script modules.
    FILE_MUTATION_TOOLS: Frozenset of host tool names that create or mutate files on disk.
    _PATH_ARG_KEYS: Ordered tuple of tool argument keys inspected to extract a target file path.
    _CMD_ARG_KEYS: Ordered tuple of tool argument keys inspected to extract a shell command string.
    _R6_GRADUATE_RE: Regex matching `pa pr graduate` or `gh pr merge` graduation commands.
    _PR_ID_TOKEN_RE: Regex matching canonical Pull Request identifiers (`PR-01`, `PR-02a`, etc.).
    _R4_FORBIDDEN_GIT_GH_RE: Regex matching git branch/history, gh, and pa lifecycle commands forbidden to workers.
    _PA_FORBIDDEN_LIFECYCLE_CMD_RE: Regex matching Tier 1/human lifecycle commands forbidden to Tier 2 PAs.
    _R5_AUDITOR_MUTATING_CMD_RE: Regex matching mutating commands forbidden to auditors.
    _SAFE_REDIRECT_STRIP_RE: Regex matching benign fd-duplication and `/dev/null` redirections.
    _FILE_REDIRECT_RE: Regex matching shell output redirection operators (`>` / `>>`) and target.
    _COMMIT_MSG_QUOTED_RE: Regex matching quoted `-m` / `--message` flags in git commit commands.
    _CANONICAL_PROGRAM_SUBPATH_RE: Regex matching canonical `programme-<slug>/PROGRAM.md` workspace subpath.
    _CANONICAL_PROJECT_SUBPATH_RE: Regex matching canonical `pr-<XX>-<slug>/PROJECT.md` workspace subpath.
    _CANONICAL_WORKORDER_SUBPATH_RE: Regex matching canonical `pr-<XX>-<slug>/wo<M>-<slug>/WORKORDER.md` subpath.
  Public Functions:
    resolve_repo_rel_path(repo_root, raw_path) -> tuple[bool, str, Path]:
        Resolve raw_path via os.path.realpath against repo_root and check containment.
    matches_pattern(rel_posix, pattern) -> bool:
        Check whether a repo-relative POSIX path matches an exact path, prefix, or glob pattern.
    matches_any_pattern(rel_posix, patterns) -> bool:
        Return True if rel_posix matches at least one pattern in patterns.
    simulate_file_edit(existing_text, tool_name, args) -> str | None:
        Simulate the resulting file text produced by a file mutation tool call.
    evaluate_pre_tool(payload, *, repo_root=None, runner=common.run) -> dict[str, Any]:
        Evaluate a PreToolUse hook event against Split-Authority governance rules R1 through R6.
    main(argv=None) -> int:
        CLI entrypoint reading a PreToolUse JSON payload from stdin and writing the hook response.
  Internal Helpers:
    _apply_replacement_chunks(existing_text, chunks) -> str | None:
        Sequentially apply ReplacementChunks target/replacement pairs to existing_text.
    _extract_tool_name_and_args(payload) -> tuple[str, dict[str, Any]]:
        Extract the normalized tool name and parsed argument dictionary from a PreToolUse payload.
    _extract_target_path(args) -> str:
        Extract the target file path string from a tool call's arguments mapping.
    _extract_command_str(args) -> str:
        Extract the shell command string from a run_command tool call's arguments mapping.
    _normalize_role(raw_role) -> str:
        Normalize an agent role identifier to its canonical short name.
    _finalize_decision(db, session, decision_dict) -> dict[str, Any]:
        Persist structural failure increments and StateDB escalation rows for a governance decision.
    _is_auditor_mutating_command(cmd_str) -> bool:
        Determine whether a shell command violates the R5 auditor read-only lockdown.
    _architect_cmd_mutates_outside_agents(cmd_str) -> str | None:
        Return the offending path if an architect shell command mutates files outside `.agents/`.
    _cmd_mutates_protected_specs(role, cmd_str) -> str | None:
        Return the offending spec path if a shell command mutates protected PA specs or hashes.
    _workspace_subpath(rel_posix, real_root, ws_dir) -> str | None:
        Return the path relative to the PA workspace directory if rel_posix resides inside it.
    _find_project_doc(ws_dir, pr_id) -> Any | None:
        Load the PROJECT.md document matching pr_id (or the sole PROJECT.md when pr_id is None).
    _find_bound_workorder(ws_dir, pr_id, wo_id) -> Any | None:
        Load the WORKORDER.md document matching wo_id and pr_id.
    _check_r6_graduation_gate(
        cmd_str, real_root, ws_dir, pr_id, mode, db, session, runner
    ) -> dict[str, Any] | None:
        Enforce Rule R6 requiring an APPROVED AuditReport matching current HEAD before graduation.
    _check_architect_file_gates(
        role, tool_name, args, raw_path, real_root, ws_dir, pr_id, mode, db, session
    ) -> dict[str, Any] | None:
        Enforce Rules R1 and R1b on file mutations performed by chief or pa roles.
    _check_r2_plan_approval_gate(args, ws_dir, pr_id, mode, db, session) -> dict[str, Any] | None:
        Enforce Rule R2 requiring PR plan approval before spawning a pa-engineer subagent.
    _check_worker_gates(
        tool_name, args, raw_path, cmd_str, real_root, ws_dir, pr_id, wo_id, mode, db, session
    ) -> dict[str, Any] | None:
        Enforce Rules R3 and R4 on file mutations and shell commands executed by pa-engineer.
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

# Absolute path to the scripts directory, inserted into sys.path for sibling imports.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import escalation
import state_db

# Host tool names that create, overwrite, or edit files on disk.
FILE_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        "write_to_file",
        "write_file",
        "replace_file_content",
        "edit_file",
        "multi_replace_file_content",
        "sed_file",
        "notebook_edit",
    }
)

# Candidate argument dictionary keys used across host tool schemas to specify a target file path.
_PATH_ARG_KEYS: tuple[str, ...] = (
    "TargetFile",
    "Path",
    "NotebookPath",
    "file_path",
    "path",
    "FilePath",
    "TargetPath",
)

# Candidate argument dictionary keys used across host tool schemas to specify a shell command line.
_CMD_ARG_KEYS: tuple[str, ...] = (
    "CommandLine",
    "command",
    "cmd",
    "Command",
)

# Matches PR graduation or merge commands (`pa pr graduate`, `gh pr merge`, etc.).
_R6_GRADUATE_RE = re.compile(
    r"\b(?:pa(?:\s+|_cli\.py\s+)pr\s+graduate|gh\s+pr\s+merge)\b"
)

# Matches canonical Pull Request identifiers such as `PR-01` or `PR-02a`.
_PR_ID_TOKEN_RE = re.compile(r"\b(PR-\d+[a-z]?)\b", re.IGNORECASE)

# Matches git history/branch manipulation, GitHub CLI, and PA lifecycle commands forbidden under Rule R4.
_R4_FORBIDDEN_GIT_GH_RE = re.compile(
    r"\b(?:"
    r"git\s+(?:push|checkout|switch|branch|rebase|merge)\b"
    r"|git\s+reset\s+--hard\b"
    r"|gh\s+(?:pr|issue)\b"
    r"|pa(?:\s+|_cli\.py\s+)(?:programme|pr)\b"
    r")"
)

# Matches Tier 1 / human lifecycle commands forbidden to Tier 2 `pa` sessions (`pa pr start`, `pa programme init|charter`).
_PA_FORBIDDEN_LIFECYCLE_CMD_RE = re.compile(
    r"\bpa(?:\s+|_cli\.py\s+)(?:programme\s+(?:init|charter)|pr\s+start)\b"
)

# Matches mutating git, gh, filesystem, or in-place sed commands forbidden under Rule R5.
_R5_AUDITOR_MUTATING_CMD_RE = re.compile(
    r"\b(?:"
    r"git\s+(?:commit|push|checkout|switch|branch|rebase|merge|reset|clean"
    r"|mv|rm|tag|stash|add|apply|cherry-pick|revert)\b"
    r"|gh\s+(?:pr\s+(?:create|merge|close|edit|ready|reopen)"
    r"|issue\s+(?:create|close|edit|delete|reopen)"
    r"|repo\s+(?:create|delete|edit|fork))\b"
    r"|(?:rm|mv|cp|touch|mkdir|rmdir|chmod|chown|dd|tee|truncate|install)\b"
    r"|sed\s+(?:-[a-zA-Z]*i|--in-place)\b"
    r")"
)

# Matches safe fd duplications (`2>&1`) and `/dev/null` redirects prior to file-redirect checks.
_SAFE_REDIRECT_STRIP_RE = re.compile(
    r"(?:\d*>&\d+|\d*>{1,2}\s*/dev/null\b|&>{1,2}\s*/dev/null\b)"
)

# Matches shell output redirection operators (`>` or `>>`) and captures the target path token.
_FILE_REDIRECT_RE = re.compile(r"(?:^|[^0-9<>])>{1,2}\s*(\S+)")

# Matches quoted commit message flags (`-m "..."` or `--message '...'`) before keyword checks.
_COMMIT_MSG_QUOTED_RE = re.compile(
    r"(?:-m|--message)\s+(?:\"[^\"]*\"|'[^']*')"
)

# Matches canonical `programme-<slug>/PROGRAM.md` workspace subpath.
_CANONICAL_PROGRAM_SUBPATH_RE = re.compile(r"^programme-[a-z0-9-]+/PROGRAM\.md$")

# Matches canonical `pr-<XX>-<slug>/PROJECT.md` workspace subpath directly under workspace root.
_CANONICAL_PROJECT_SUBPATH_RE = re.compile(r"^pr-\d+[a-z]?-[a-z0-9-]+/PROJECT\.md$")

# Matches canonical `pr-<XX>-<slug>/wo<M>-<slug>/WORKORDER.md` workspace subpath.
_CANONICAL_WORKORDER_SUBPATH_RE = re.compile(
    r"^pr-\d+[a-z]?-[a-z0-9-]+/wo\d+[a-z]?-[a-z0-9-]+/WORKORDER\.md$"
)


def resolve_repo_rel_path(repo_root: Path | str, raw_path: str) -> tuple[bool, str, Path]:
    """Resolve `raw_path` via `os.path.realpath` against `repo_root`.

    Args:
        repo_root: Repository root directory path.
        raw_path: Raw target file path (absolute, repo-relative, or `file://` URI).

    Returns:
        A 3-tuple `(inside_repo, rel_posix_or_raw, real_target)`:
        - `inside_repo` is `True` iff `real_target` is equal to or inside `real_root`.
        - When `inside_repo` is `True`, the second element is the normalized POSIX path
          relative to `real_root` (or `"."` if equal to `real_root`).
        - When `inside_repo` is `False` (e.g. `../` traversal or symlink pointing outside
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

    Args:
        rel_posix: Normalized repo-relative POSIX path to test.
        pattern: Allowed or forbidden file pattern string.

    Returns:
        `True` if `rel_posix` matches `pattern`, otherwise `False`.
    """
    # --- Step 1: Normalize leading `./` and reject empty inputs ---
    norm_rel = rel_posix.strip().lstrip("./")
    pat = pattern.strip().lstrip("./")
    if not pat or not norm_rel:
        return False

    # --- Step 2: Check exact path and recursive directory prefix matches ---
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

    # --- Step 3: Fallback to fnmatch wildcard matching ---
    return fnmatch.fnmatch(norm_rel, pat)


def matches_any_pattern(rel_posix: str, patterns: Sequence[str]) -> bool:
    """Return True if `rel_posix` matches at least one pattern in `patterns`.

    Args:
        rel_posix: Normalized repo-relative POSIX path to test.
        patterns: Sequence of pattern strings to check against.

    Returns:
        `True` if any pattern in `patterns` matches `rel_posix`, otherwise `False`.
    """
    return any(matches_pattern(rel_posix, pat) for pat in patterns)


def simulate_file_edit(
    existing_text: str,
    tool_name: str,
    args: Mapping[str, Any],
) -> str | None:
    """Simulate the resulting file text from a file mutation tool call, or None if invalid.

    Args:
        existing_text: Current UTF-8 text content of the target file on disk.
        tool_name: Name of the file mutation tool being invoked.
        args: Tool call arguments dictionary.

    Returns:
        Simulated post-edit file content string, or `None` if the edit arguments are
        malformed or a target substring does not match `existing_text`.
    """
    # --- Step 1: Simulate full-file write or append tools ---
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

    # --- Step 2: Simulate single or chunked replacement tools ---
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

    # --- Step 3: Simulate multi-chunk replacement tools ---
    if tool_name == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks")
        if not isinstance(chunks, list) or not chunks:
            return None
        return _apply_replacement_chunks(existing_text, chunks)

    return None


def _apply_replacement_chunks(existing_text: str, chunks: Sequence[Any]) -> str | None:
    """Apply a sequence of replacement chunk dictionaries to `existing_text`.

    Args:
        existing_text: Starting file content string.
        chunks: Sequence of chunk mappings containing `TargetContent`/`Target` and
            `ReplacementContent`/`Replacement` keys.

    Returns:
        Updated file content string after applying all chunks sequentially, or `None`
        if any chunk is invalid or its target substring is missing.
    """
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
    """Extract the tool name and argument dictionary from a `PreToolUse` hook payload.

    Args:
        payload: Raw `PreToolUse` hook event mapping from the host runtime.

    Returns:
        A 2-tuple `(tool_name, args_dict)` with normalized string tool name and parsed
        arguments dictionary (empty dict if arguments are absent or unparseable).
    """
    # --- Step 1: Extract tool name from nested toolCall or top-level payload keys ---
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

    # --- Step 2: Locate raw tool arguments mapping or JSON string ---
    raw_args: Any = None
    for src in (tc_map, payload):
        for key in ("args", "arguments", "input", "toolArgs", "toolInput", "tool_input"):
            if key in src and src[key] is not None:
                raw_args = src[key]
                break
        if raw_args is not None:
            break

    # --- Step 3: Normalize arguments into a plain dictionary ---
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
    """Extract the target file path string from a tool call's arguments mapping.

    Args:
        args: Parsed tool arguments mapping.

    Returns:
        Stripped file path string from the first matching key in `_PATH_ARG_KEYS`, or `""`.
    """
    for key in _PATH_ARG_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_command_str(args: Mapping[str, Any]) -> str:
    """Extract the shell command string from a `run_command` tool call's arguments mapping.

    Args:
        args: Parsed tool arguments mapping.

    Returns:
        Stripped command line string from the first matching key in `_CMD_ARG_KEYS`, or `""`.
    """
    for key in _CMD_ARG_KEYS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _normalize_role(raw_role: str | None) -> str:
    """Normalize an agent role identifier to its canonical short role name.

    Args:
        raw_role: Raw role string from session state, spawn headers, or hook payload.

    Returns:
        Canonical role string (`"chief"`, `"pa"`, `"engineer"`, `"auditor"`, `"debugger"`),
        the lowercased input if unrecognized, or `""` when `raw_role` is empty/None.
    """
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
    """Persist structural failure increments and escalation rows for a governance decision.

    Args:
        db: Open `StateDB` connection for the workspace.
        session: Active session dictionary from `state.db`, or `None` if unbound.
        decision_dict: Decision payload returned by `escalation.decide`.

    Returns:
        The `decision_dict` enriched with `"escalation_row"` when an escalation was recorded.
    """
    # --- Step 1: Increment session structural_failures counter if requested ---
    if decision_dict.get("increment_structural_failures") and session is not None:
        conv_id = str(session.get("conversation_id") or "")
        if conv_id:
            new_val = int(session.get("structural_failures") or 0) + 1
            updated = db.update_session(conv_id, structural_failures=new_val)
            if updated is not None:
                session.update(updated)

    # --- Step 2: Record escalation row and optional human attention item in StateDB ---
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
    """Return True if `cmd_str` violates the Rule R5 auditor read-only lockdown.

    Args:
        cmd_str: Raw shell command string executed by `pa-auditor`.

    Returns:
        `True` if the command invokes mutating git/gh/filesystem verbs or redirects to a file.
    """
    if not cmd_str:
        return False
    if _R5_AUDITOR_MUTATING_CMD_RE.search(cmd_str):
        return True
    scrubbed = _SAFE_REDIRECT_STRIP_RE.sub("", cmd_str)
    return bool(_FILE_REDIRECT_RE.search(scrubbed))


def _architect_cmd_mutates_outside_agents(cmd_str: str) -> str | None:
    """Detect whether an architect shell command mutates files outside `.agents/`.

    Args:
        cmd_str: Raw shell command string executed by `chief` or `pa`.

    Returns:
        The offending target file path string if a redirection or file-mutation command
        targets a path outside `.agents/`, or `None` if the command is compliant.
    """
    # --- Step 1: Strip safe fd/devnull redirects and check file redirection targets ---
    if not cmd_str:
        return None
    # Strip benign `2>&1` and `>/dev/null` redirections first so heredoc or command
    # pipelines using standard stream suppression do not falsely trigger `_FILE_REDIRECT_RE`.
    scrubbed = _SAFE_REDIRECT_STRIP_RE.sub("", cmd_str)
    redirs = _FILE_REDIRECT_RE.findall(scrubbed)
    for target in redirs:
        cleaned = target.strip("'\"")
        if cleaned and not cleaned.startswith(".agents/"):
            return cleaned

    # --- Step 2: Check direct filesystem mutation verbs (rm, mv, cp, touch, tee, sed -i) ---
    mut_match = re.search(
        r"\b(?:rm|mv|cp|touch|tee)\s+(?:-[a-zA-Z]+\s+)*([^\s;|>&]+)",
        scrubbed,
    )
    if mut_match:
        target = mut_match.group(1).strip("'\"")
        if target and not target.startswith(".agents/") and not target.startswith("/dev/null"):
            return target
    sed_match = re.search(
        r"\bsed\s+(?:-[a-zA-Z]*i|--in-place)(?:=\S+)?\s+(?:'[^']*'|\"[^\"]*\"|\S+)\s+([^\s;|>&]+)",
        scrubbed,
    )
    if sed_match:
        target = sed_match.group(1).strip("'\"")
        if target and not target.startswith(".agents/") and not target.startswith("/dev/null"):
            return target
    return None


def _cmd_mutates_protected_specs(role: str, cmd_str: str) -> str | None:
    """Detect shell commands that bypass `FILE_MUTATION_TOOLS` to mutate protected PA specs or hashes.

    Prevents agents from using `rm`, `mv`, `cp`, `tee`, `truncate`, `sed -i`, file redirections,
    or inline Python scripts (`compute_charter_hash` / `compute_spec_hash`) inside `run_command`
    to bypass `Rule R1`, `Rule R1b`, or `Rule R3` hash/schema verification gates.

    Args:
        role: Normalized caller role (`"chief"`, `"pa"`, or `"engineer"`).
        cmd_str: Raw shell command string executed via `run_command`.

    Returns:
        The offending target artifact path/description if a forbidden shell mutation is detected,
        or `None` if the command is compliant.
    """
    # --- Step 1: Reject direct charter_hash / spec_hash forgery in subordinate shells ---
    if not cmd_str:
        return None
    if role == "pa" and re.search(r"\bcompute_charter_hash\b", cmd_str):
        return "PROJECT.md (charter_hash forgery via run_command)"
    if role == "engineer" and re.search(r"\b(?:compute_spec_hash|compute_charter_hash)\b", cmd_str):
        return "WORKORDER.md (spec_hash forgery via run_command)"

    # --- Step 2: Determine protected spec filenames for the caller's Split-Authority tier ---
    scrubbed = _SAFE_REDIRECT_STRIP_RE.sub("", cmd_str)
    if role == "chief":
        protected_names = ("WORKORDER.md",)
    elif role == "pa":
        protected_names = ("PROGRAM.md", "PROJECT.md")
    elif role == "engineer":
        protected_names = ("PROGRAM.md", "PROJECT.md", "WORKORDER.md")
    else:
        return None

    # --- Step 3: Check shell redirects, destructive verbs, and in-place sed targeting specs ---
    for target in _FILE_REDIRECT_RE.findall(scrubbed):
        cleaned = target.strip("'\"")
        for pname in protected_names:
            if cleaned == pname or cleaned.endswith("/" + pname):
                return cleaned

    for pname in protected_names:
        escaped = re.escape(pname)
        if re.search(
            rf"\b(?:rm|mv|cp|tee|truncate)\b[^\n;|]*\b{escaped}\b"
            rf"|\bsed\s+(?:-[a-zA-Z]*i|--in-place)\b[^\n;|]*\b{escaped}\b",
            scrubbed,
        ):
            return pname

    # Also block `pa` or `engineer` from deleting entire `pr-*` or `programme-*` directories via `rm`
    if role in ("pa", "engineer"):
        rm_ws_match = re.search(
            r"\brm\s+(?:-[a-zA-Z]+\s+)*([^\s;|>&]*(?:programme-|pr-\d+)[^\s;|>&]*)",
            scrubbed,
        )
        if rm_ws_match:
            return rm_ws_match.group(1).strip("'\"")

    return None


def _workspace_subpath(rel_posix: str, real_root: Path, ws_dir: Path) -> str | None:
    """Return the subpath inside the PA workspace directory if `rel_posix` is within it.

    Args:
        rel_posix: Repo-relative POSIX path to inspect.
        real_root: Canonical path to the repository root.
        ws_dir: Canonical path to the active PA workspace directory (`principal-architect-workspace`).

    Returns:
        Workspace-relative POSIX subpath string (or `""` for the workspace root itself),
        or `None` if `rel_posix` is outside the PA workspace directory.
    """
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
    """Locate and load the `PROJECT.md` document for `pr_id` inside `ws_dir`.

    Args:
        ws_dir: Path to the `principal-architect-workspace` workspace directory.
        pr_id: Target Pull Request identifier (`PR-01`, etc.), or `None` to match a sole PR.

    Returns:
        Loaded `ParsedDocument[ProjectSpec]` instance, or `None` if not found or ambiguous.
    """
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
    """Locate and load the bound `WORKORDER.md` document for `(pr_id, wo_id)` inside `ws_dir`.

    Args:
        ws_dir: Path to the `principal-architect-workspace` workspace directory.
        pr_id: Optional Pull Request identifier (`PR-01`, etc.).
        wo_id: Target Work Order identifier (`WO-01`, etc.), or `None` to match a sole WO.

    Returns:
        Loaded `ParsedDocument[WorkOrderSpec]` instance, or `None` if not found or ambiguous.
    """
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
    """Enforce Rule R6 requiring an `APPROVED` `AuditReport` for current `HEAD` before graduation.

    Args:
        cmd_str: Raw shell command string matching `_R6_GRADUATE_RE`.
        real_root: Canonical path to the repository root.
        ws_dir: Path to the `principal-architect-workspace` workspace directory.
        pr_id: Session-bound Pull Request identifier, if any.
        mode: Active execution mode (`"monitored"` or `"autonomous"`).
        db: Open `StateDB` connection for the workspace.
        session: Active session row mapping from `state.db`, or `None`.
        runner: Subprocess runner callable used to query `git rev-parse HEAD`.

    Returns:
        `None` if a valid `APPROVED` audit report matches `HEAD`, otherwise the finalized
        R6 governance decision dictionary.
    """
    # --- Step 1: Filter out quoted strings or --help lookups and resolve current git HEAD SHA ---
    unquoted_cmd = re.sub(r"(?:\"[^\"]*\"|'[^']*')", "", cmd_str)
    active_grad_segments = [
        seg.strip()
        for seg in re.split(r"(?:&&|\|\||[;|\n])", unquoted_cmd)
        if _R6_GRADUATE_RE.search(seg)
        and not re.search(r"(?:^|\s)(?:--help|-h)(?:\s|$)", seg)
    ]
    if not active_grad_segments:
        return None

    import schemas

    res = runner(["git", "rev-parse", "HEAD"], cwd=real_root)
    head_sha = res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else "HEAD"

    m = _PR_ID_TOKEN_RE.search(" ".join(active_grad_segments))
    target_pr_id = m.group(1).upper() if m else pr_id
    if not target_pr_id:
        proj_doc = _find_project_doc(ws_dir, None)
        if proj_doc is not None:
            target_pr_id = proj_doc.spec.charter.pr_id

    # --- Step 2: Scan AUDIT-round-*.md files for an APPROVED verdict matching HEAD (or audit commit) ---
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
            and common.head_matches_audited_sha(
                real_root,
                audit_path.parent,
                head_sha,
                report.head_sha,
                runner=runner,
            )
        ):
            return None

    # --- Step 3: Escalate or block when no matching APPROVED AuditReport exists ---
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
    """Enforce Rules R1 and R1b on file mutations performed by `chief` or `pa` roles.

    Args:
        role: Normalized architect role (`"chief"` or `"pa"`).
        tool_name: Name of the file mutation tool being invoked.
        args: Tool call arguments mapping.
        raw_path: Target file path extracted from `args`.
        real_root: Canonical path to the repository root.
        ws_dir: Path to the `principal-architect-workspace` workspace directory.
        pr_id: Session-bound Pull Request identifier, if any.
        mode: Active execution mode (`"monitored"` or `"autonomous"`).
        db: Open `StateDB` connection for the workspace.
        session: Active session row mapping from `state.db`, or `None`.

    Returns:
        `None` if the file edit is permitted, or a finalized R1/R1b decision dictionary.
    """
    # --- Step 1: Verify target path resolves inside the PA workspace directory (Rule R1) ---
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

    # --- Step 2: Enforce canonical workspace paths and Chief Architect schema/scope rules ---
    import schemas

    target_name = Path(ws_sub).name
    if role == "chief" and target_name == "WORKORDER.md":
        return _finalize_decision(
            db,
            session,
            escalation.decide("R1", mode, {"path": rel_posix, "pr_id": pr_id}),
        )

    if target_name == "PROGRAM.md" and not _CANONICAL_PROGRAM_SUBPATH_RE.fullmatch(ws_sub):
        return {
            "permissionDecision": "deny",
            "decision": "deny",
            "rule": "R1",
            "mode": mode,
            "reason": (
                f"Invalid PROGRAM.md path '{rel_posix}'. PROGRAM.md must reside at "
                f"'.agents/plugins/principal-architect-workspace/programme-<slug>/PROGRAM.md' "
                f"(use 'pa programme init <slug> --title \"...\"')."
            ),
        }
    if target_name == "PROJECT.md" and not _CANONICAL_PROJECT_SUBPATH_RE.fullmatch(ws_sub):
        return {
            "permissionDecision": "deny",
            "decision": "deny",
            "rule": "R1",
            "mode": mode,
            "reason": (
                f"Invalid PROJECT.md path '{rel_posix}'. PROJECT.md must reside directly under "
                f"'.agents/plugins/principal-architect-workspace/pr-<XX>-<slug>/PROJECT.md' "
                f"(never nested inside programme-<slug>/; use 'pa programme charter <PR-ID> "
                f"--slug <slug> --title \"...\"')."
            ),
        }
    if target_name == "WORKORDER.md" and not _CANONICAL_WORKORDER_SUBPATH_RE.fullmatch(ws_sub):
        return {
            "permissionDecision": "deny",
            "decision": "deny",
            "rule": "R1",
            "mode": mode,
            "reason": (
                f"Invalid WORKORDER.md path '{rel_posix}'. WORKORDER.md must reside at "
                f"'.agents/plugins/principal-architect-workspace/pr-<XX>-<slug>/wo<M>-<slug>/WORKORDER.md'."
            ),
        }

    if role == "chief":
        if target_name in ("PROGRAM.md", "PROJECT.md"):
            existing_text = (
                real_target.read_text(encoding="utf-8") if real_target.is_file() else ""
            )
            proposed_text = simulate_file_edit(existing_text, tool_name, args)
            if proposed_text is not None:
                try:
                    fm_data, _ = schemas.parse_document(proposed_text)
                    if target_name == "PROGRAM.md":
                        schemas.ProgramSpec.model_validate(fm_data)
                    else:
                        schemas.ProjectSpec.model_validate(fm_data)
                except Exception as exc:  # noqa: BLE001
                    cli_hint = (
                        "pa programme init <slug> --title \"...\""
                        if target_name == "PROGRAM.md"
                        else "pa programme charter <PR-ID> --slug <slug> --title \"...\""
                    )
                    return {
                        "permissionDecision": "deny",
                        "decision": "deny",
                        "rule": "R1",
                        "mode": mode,
                        "reason": (
                            f"Invalid {target_name} frontmatter schema at '{rel_posix}': {exc}. "
                            f"Always scaffold and lock {target_name} using '{cli_hint}'."
                        ),
                    }
        return None

    # --- Step 3: Enforce PA restrictions on PROGRAM.md and locked Charters (Rule R1b) ---
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

    # --- Step 4: Verify WORKORDER.md allowed_files match Charter allowed_modules (Rule R1b) ---
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
    """Enforce Rule R2 requiring PR plan approval prior to spawning a `pa-engineer` worker.

    Args:
        args: `invoke_subagent` tool call arguments mapping.
        ws_dir: Path to the `principal-architect-workspace` workspace directory.
        pr_id: Session-bound Pull Request identifier, if any.
        mode: Active execution mode (`"monitored"` or `"autonomous"`).
        db: Open `StateDB` connection for the workspace.
        session: Active session row mapping from `state.db`, or `None`.

    Returns:
        `None` if the subagent spawn is not a worker or the PR is already past `PLANNED`,
        otherwise the finalized R2 governance decision dictionary.
    """
    # --- Step 1: Identify whether the subagent invocation targets a pa-engineer worker ---
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

    # --- Step 2: Load target PROJECT.md and check if status is still PLANNED ---
    import schemas

    target_pr_id = pr_id
    if not target_pr_id:
        m = _PR_ID_TOKEN_RE.search(sub_prompt)
        if m:
            target_pr_id = m.group(1).upper()

    proj_doc = _find_project_doc(ws_dir, target_pr_id)
    if proj_doc is None or proj_doc.spec.status != schemas.PRState.PLANNED:
        return None

    # --- Step 3: Validate charter_hash and all Work Order allowed_files for auto-approval ---
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

    # --- Step 4: Evaluate R2 decision and persist auto-approval state if granted ---
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
    """Enforce Rules R3 and R4 on file mutations and shell commands executed by `pa-engineer`.

    Args:
        tool_name: Name of the tool being invoked by the worker.
        args: Tool call arguments mapping.
        raw_path: Target file path extracted from `args`.
        cmd_str: Shell command string extracted from `args`.
        real_root: Canonical path to the repository root.
        ws_dir: Path to the `principal-architect-workspace` workspace directory.
        pr_id: Session-bound Pull Request identifier, if any.
        wo_id: Session-bound Work Order identifier, if any.
        mode: Active execution mode (`"monitored"` or `"autonomous"`).
        db: Open `StateDB` connection for the workspace.
        session: Active session row mapping from `state.db`, or `None`.

    Returns:
        `None` if the tool call is permitted, or a finalized R3/R4 decision dictionary.
    """
    # --- Step 1: Enforce Rule R4 git/gh command lockdown and R3 spec lock on run_command calls ---
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
        spec_mut = _cmd_mutates_protected_specs("engineer", cmd_str)
        if spec_mut is not None:
            return _finalize_decision(
                db,
                session,
                escalation.decide(
                    "R3",
                    mode,
                    {
                        "path": spec_mut,
                        "pr_id": pr_id,
                        "wo_id": wo_id,
                        "reason_code": "SPEC_LOCK_VIOLATION",
                    },
                ),
            )
        return None

    # --- Step 2: Resolve canonical path and block traversal outside repo_root (Rule R3) ---
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

    # --- Step 3: Load bound WORKORDER.md and verify Part I spec_hash integrity on self-edits ---
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

    # --- Step 4: Enforce forbidden_files and allowed_files boundary box (Rule R3) ---
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

    Args:
        payload: Decoded JSON hook input dictionary for the `PreToolUse` event.
        repo_root: Optional explicit repository root override for testing or CLI invocation.
        runner: Subprocess runner callable used for git queries.

    Returns:
        Governance decision dictionary containing `permissionDecision`, `decision`, and `reason`
        (or `{}` on unenrolled fast-exit).
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

    # --- Step 2: Extract tool call metadata and open workspace StateDB ---
    real_root = Path(os.path.realpath(resolved_root))
    ws_dir = common.workspace_dir(real_root)
    db_path = ws_dir / ".state" / "state.db"

    tool_name, args = _extract_tool_name_and_args(payload)
    if not tool_name:
        return {"permissionDecision": "allow", "decision": "allow", "reason": "No tool specified"}

    raw_path = _extract_target_path(args)
    cmd_str = _extract_command_str(args)

    # --- Step 3: Resolve session role and evaluate rules R6, R5, R1/R1b, R2, and R3/R4 ---
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
                if role == "pa" and _PA_FORBIDDEN_LIFECYCLE_CMD_RE.search(cmd_str):
                    return {
                        "permissionDecision": "deny",
                        "decision": "deny",
                        "rule": "R1b",
                        "mode": mode,
                        "reason": (
                            "Principal Architect (role=pa) cannot run 'pa pr start', "
                            "'pa programme init', or 'pa programme charter' (which spawn "
                            "duplicate architect conversations or overwrite locked Part I "
                            "Charters). Use 'pa pr claim <PR-ID>' to check out the PR branch, "
                            "'pa pr approve-plan <PR-ID>' to lock Work Orders, or "
                            "'pa escalate --to-chief' if Part I Charter changes are needed."
                        ),
                    }
                spec_mut = _cmd_mutates_protected_specs(role, cmd_str)
                if spec_mut is not None:
                    rule_id = "R1b" if role == "pa" else "R1"
                    return _finalize_decision(
                        db,
                        session,
                        escalation.decide(rule_id, mode, {"path": spec_mut, "pr_id": pr_id}),
                    )
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
    """CLI entrypoint for `PreToolUse` hook (`pre_tool_gate.py`).

    Args:
        argv: Optional command-line argument sequence (unused; hook reads JSON from stdin).

    Returns:
        Process exit code (`0` after writing the sanitized JSON hook response to stdout).
    """
    _ = argv
    payload = escalation.read_hook_input()
    try:
        res = evaluate_pre_tool(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[principal-architect] pre_tool_gate error: {exc}", file=sys.stderr)
        res = {}
    # The host runtime's strict protobuf JSON unmarshaler rejects unknown top-level keys
    # such as `permissionDecision`, `rule`, or `escalation_row`, and expects `"force_ask"`
    # rather than internal `"ask"` when prompting the human in monitored mode.
    out: dict[str, Any] = {}
    if isinstance(res, Mapping) and res.get("decision"):
        dec = str(res["decision"])
        out["decision"] = "force_ask" if dec == "ask" else dec
        if res.get("reason"):
            out["reason"] = str(res["reason"])
    return escalation.write_hook_output(out)


if __name__ == "__main__":
    raise SystemExit(main())
