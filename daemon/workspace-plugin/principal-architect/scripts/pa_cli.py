#!/usr/bin/env python3
"""Principal Architect Plugin (`pa`) CLI entrypoint and subcommand dispatcher.

Implements `pa enroll`, `pa unenroll`, `pa status [--json]`, `pa mode`,
`pa pr approve-plan`, `pa wo verify`, and `pa escalate`, plus the
`COMMAND_MODULES` extension list consumed by downstream PR modules.

Lazy Import Rule (Charter R1): This module MUST NOT import `pydantic`, `yaml`,
or `schemas` at module top-level so fast paths (`pa --help`, `pa mode`) remain
sub-millisecond and stdlib-only.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import state_db

COMMAND_MODULES: list[str] = []

DEFAULT_WORKER_RULE_EXCLUDES: tuple[str, ...] = (
    "01-plan-before-execute.md",
    "bug-fixer-*",
)


def _dedup_preserve_order(items: Sequence[str]) -> list[str]:
    """Deduplicate non-empty stripped strings while preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in items:
        val = raw.strip()
        if val and val not in seen:
            seen.add(val)
            result.append(val)
    return result


def _ensure_line_in_file(file_path: Path, line_to_ensure: str) -> None:
    """Ensure `line_to_ensure` is present as a line in `file_path` without duplicating it."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    target = line_to_ensure.strip()
    existing_text = ""
    if file_path.is_file():
        existing_text = file_path.read_text(encoding="utf-8")
        existing_lines = [ln.strip() for ln in existing_text.splitlines()]
        if target in existing_lines:
            return

    prefix = ""
    if existing_text and not existing_text.endswith("\n"):
        prefix = "\n"
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(f"{prefix}{target}\n")


def detect_vcs_mode(
    repo_root: str | Path,
    *,
    runner: common.Runner = common.run,
) -> Literal["github", "local_git"]:
    """Auto-detect VCS mode (`github` if origin is GitHub and `gh auth status` exits 0, else `local_git`)."""
    root = Path(os.path.realpath(repo_root))
    try:
        res_remote = runner(["git", "remote", "get-url", "origin"], cwd=root)
    except (OSError, subprocess.SubprocessError):
        return "local_git"

    if res_remote.returncode != 0 or "github.com" not in res_remote.stdout.lower():
        return "local_git"

    gh_bin = os.environ.get("PA_GH_BIN", "gh").strip() or "gh"
    try:
        res_gh = runner([gh_bin, "auth", "status"], cwd=root)
    except (OSError, subprocess.SubprocessError):
        return "local_git"

    if res_gh.returncode == 0:
        return "github"
    return "local_git"


def detect_memory_mode(repo_root: str | Path) -> Literal["external", "builtin"]:
    """Auto-detect memory mode (`external` if repo-memory-plugin is present/enrolled, else `builtin`)."""
    real_root = os.path.realpath(str(repo_root))
    root = Path(real_root)

    # 1. Direct .memory directory in the repository
    if (root / ".memory").exists():
        return "external"

    # 2. <repo>/.agents/plugins.json entry referencing repo-memory
    plugins_file = root / ".agents" / "plugins.json"
    if plugins_file.is_file():
        try:
            pdata = json.loads(plugins_file.read_text(encoding="utf-8"))
            if isinstance(pdata, dict) and isinstance(pdata.get("entries"), list):
                for entry in pdata["entries"]:
                    if isinstance(entry, dict) and "repo-memory" in str(entry.get("path", "")):
                        return "external"
                    if isinstance(entry, str) and "repo-memory" in entry:
                        return "external"
        except (OSError, json.JSONDecodeError):
            pass

    # 3. Global repo-memory-daemon registry listing this repository
    user_home = Path(os.path.realpath(Path.home()))
    rm_registry = (
        user_home / ".gemini" / "config" / "plugins" / "repo-memory-daemon" / "state" / "registry.json"
    )
    if rm_registry.is_file():
        try:
            rdata = json.loads(rm_registry.read_text(encoding="utf-8"))
            if isinstance(rdata, dict):
                repos_field = rdata.get("repos")
                if isinstance(repos_field, dict):
                    if any(os.path.realpath(str(k)) == real_root for k in repos_field):
                        return "external"
                elif isinstance(repos_field, list):
                    for item in repos_field:
                        candidate = item.get("path", "") if isinstance(item, dict) else str(item)
                        if candidate and os.path.realpath(str(candidate)) == real_root:
                            return "external"
                for k, v in rdata.items():
                    if k in ("schema_version", "repos"):
                        continue
                    if os.path.realpath(str(k)) == real_root:
                        return "external"
                    if isinstance(v, dict) and "path" in v and os.path.realpath(str(v["path"])) == real_root:
                        return "external"
            elif isinstance(rdata, list):
                for item in rdata:
                    candidate = item.get("path", "") if isinstance(item, dict) else str(item)
                    if candidate and os.path.realpath(str(candidate)) == real_root:
                        return "external"
        except (OSError, json.JSONDecodeError):
            pass

    return "builtin"


def _cmd_enroll(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Execute the normative 9-step `pa enroll` sequence (SPEC §4.3, Charter §2.3)."""
    raw_target = Path(args.path).expanduser()
    if not raw_target.exists():
        print(f"Error: Target path does not exist: {args.path}", file=sys.stderr)
        return 2

    target = Path(os.path.realpath(raw_target))
    if target.is_file():
        target = target.parent

    # Step 1: Resolve git root or initialize a local git repository
    repo_root = common.find_repo_root(target, runner=runner)
    if repo_root is None:
        try:
            init_res = runner(["git", "init"], cwd=target)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"Error: Failed to run git init in {target}: {exc}", file=sys.stderr)
            return 2
        if init_res.returncode != 0:
            print(
                f"Error: git init failed in {target}: {init_res.stderr.strip()}",
                file=sys.stderr,
            )
            return 2
        repo_root = Path(os.path.realpath(target))

    # Step 2: Legacy migration check (Charter R8)
    legacy_ws = repo_root / common.LEGACY_WORKSPACE_REL
    new_ws = repo_root / common.NEW_WORKSPACE_REL
    if legacy_ws.exists() and new_ws.exists():
        print(
            "Error: Cannot migrate workspace: both "
            f"{common.LEGACY_WORKSPACE_REL} and {common.NEW_WORKSPACE_REL} exist.",
            file=sys.stderr,
        )
        return 2

    if legacy_ws.exists() and not new_ws.exists():
        new_ws.parent.mkdir(parents=True, exist_ok=True)
        ls_res = runner(
            ["git", "ls-files", "--error-unmatch", str(common.LEGACY_WORKSPACE_REL)],
            cwd=repo_root,
        )
        if ls_res.returncode == 0:
            mv_res = runner(
                ["git", "mv", str(common.LEGACY_WORKSPACE_REL), str(common.NEW_WORKSPACE_REL)],
                cwd=repo_root,
            )
            if mv_res.returncode != 0 or (legacy_ws.exists() and not new_ws.exists()):
                shutil.move(str(legacy_ws), str(new_ws))
        else:
            shutil.move(str(legacy_ws), str(new_ws))

    # Step 3 & 6: Ensure workspace and .state directories exist; open StateDB
    new_ws.mkdir(parents=True, exist_ok=True)
    state_dir = new_ws / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)

    with state_db.StateDB(state_dir / "state.db") as db:
        # Step 3 (cont.): Resolve memory_mode & scaffold builtin memory files if missing
        if args.memory_mode in ("external", "builtin"):
            memory_mode: Literal["external", "builtin"] = args.memory_mode
        else:
            memory_mode = detect_memory_mode(repo_root)

        if memory_mode == "builtin":
            mem_dir = new_ws / "memory"
            mem_dir.mkdir(parents=True, exist_ok=True)
            now_iso = state_db.utc_now_iso()
            for tpl_name, fname in (
                ("MEMORY", "MEMORY.md"),
                ("MODULE_INDEX", "MODULE_INDEX.md"),
                ("PROJECT_INDEX", "PROJECT_INDEX.md"),
            ):
                dest = mem_dir / fname
                if not dest.exists():
                    dest.write_text(
                        common.render_template_file(tpl_name, {"updated_at": now_iso}),
                        encoding="utf-8",
                    )

        # Step 4: Resolve vcs_mode
        if args.vcs_mode in ("github", "local_git"):
            vcs_mode: Literal["github", "local_git"] = args.vcs_mode
        else:
            vcs_mode = detect_vcs_mode(repo_root, runner=runner)

        # Step 5: Resolve extra_skills and exclude_rules (preserving stored values on idempotent re-run)
        if args.extra_skill is not None:
            extra_skills = _dedup_preserve_order(args.extra_skill)
        else:
            stored_extra = db.get_config("extra_skills_json")
            extra_skills = []
            if stored_extra:
                try:
                    parsed_extra = json.loads(stored_extra)
                    if isinstance(parsed_extra, list):
                        extra_skills = _dedup_preserve_order([str(x) for x in parsed_extra])
                except json.JSONDecodeError:
                    extra_skills = []

        if args.exclude_rule is not None:
            exclude_rules = _dedup_preserve_order(args.exclude_rule)
        else:
            stored_exclude = db.get_config("exclude_rules_json")
            exclude_rules = []
            if stored_exclude:
                try:
                    parsed_exclude = json.loads(stored_exclude)
                    if isinstance(parsed_exclude, list):
                        exclude_rules = _dedup_preserve_order([str(x) for x in parsed_exclude])
                except json.JSONDecodeError:
                    exclude_rules = []

        user_config_dir = Path(os.path.realpath(Path.home())) / ".gemini" / "config"
        skills_entries: list[dict[str, Any]] = [
            {"path": str(repo_root / ".agents" / "skills")},
        ]
        if extra_skills:
            skills_entries.append(
                {
                    "path": str(user_config_dir / "skills"),
                    "include_only": extra_skills,
                }
            )
        (state_dir / "pa-skills.json").write_text(
            json.dumps({"entries": skills_entries}, indent=2) + "\n",
            encoding="utf-8",
        )

        combined_excludes = _dedup_preserve_order(
            [*DEFAULT_WORKER_RULE_EXCLUDES, *exclude_rules]
        )
        rules_entries: list[dict[str, Any]] = [
            {
                "path": str(repo_root / ".agents" / "rules"),
                "exclude": combined_excludes,
            }
        ]
        (state_dir / "pa-worker-rules.json").write_text(
            json.dumps({"entries": rules_entries}, indent=2) + "\n",
            encoding="utf-8",
        )

        _ensure_line_in_file(new_ws / ".gitignore", ".state/")

        # Step 6: Persist configuration in StateDB
        existing_exec = db.get_config("execution_mode")
        execution_mode = (
            existing_exec if existing_exec in ("monitored", "autonomous") else "monitored"
        )
        db.set_config("execution_mode", execution_mode)
        db.set_config("memory_mode", memory_mode)
        db.set_config("vcs_mode", vcs_mode)
        db.set_config("extra_skills_json", json.dumps(extra_skills))
        db.set_config("exclude_rules_json", json.dumps(exclude_rules))

    # Step 7: Write/merge <repo>/.agents/plugins.json and add to .git/info/exclude
    wp_path = str(common.daemon_home() / "workspace-plugin")
    plugins_file = repo_root / ".agents" / "plugins.json"
    plugins_file.parent.mkdir(parents=True, exist_ok=True)
    existing_entries: list[dict[str, Any]] = []
    if plugins_file.is_file():
        try:
            pdata = json.loads(plugins_file.read_text(encoding="utf-8"))
            if isinstance(pdata, dict) and isinstance(pdata.get("entries"), list):
                for item in pdata["entries"]:
                    if isinstance(item, dict) and "path" in item:
                        existing_entries.append(dict(item))
        except (OSError, json.JSONDecodeError):
            existing_entries = []

    seen_paths: set[str] = set()
    merged_entries: list[dict[str, Any]] = []
    for item in existing_entries:
        p_val = str(item["path"])
        if p_val not in seen_paths:
            seen_paths.add(p_val)
            merged_entries.append(item)

    if wp_path not in seen_paths:
        merged_entries.append({"path": wp_path})

    plugins_file.write_text(
        json.dumps({"entries": merged_entries}, indent=2) + "\n",
        encoding="utf-8",
    )

    git_dir = repo_root / ".git"
    if git_dir.is_dir():
        _ensure_line_in_file(git_dir / "info" / "exclude", ".agents/plugins.json")

    # Step 8: Register repository in global Registry
    state_db.Registry().register(repo_root, workspace_dir=new_ws)

    # Step 9: Print one-screen summary to stderr and exit 0
    print(
        f"Enrolled repository: {repo_root}\n"
        f"  workspace_dir:  {new_ws}\n"
        f"  vcs_mode:       {vcs_mode}\n"
        f"  memory_mode:    {memory_mode}\n"
        f"  execution_mode: {execution_mode}",
        file=sys.stderr,
    )
    return 0


def _cmd_unenroll(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Remove the workspace plugin entry and unregister the repository (Charter R9)."""
    raw_target = Path(args.path).expanduser()
    repo_root = common.find_repo_root(raw_target, runner=runner) or Path(
        os.path.realpath(raw_target)
    )

    wp_path = str(common.daemon_home() / "workspace-plugin")
    plugins_file = repo_root / ".agents" / "plugins.json"
    if plugins_file.is_file():
        try:
            pdata = json.loads(plugins_file.read_text(encoding="utf-8"))
            if isinstance(pdata, dict) and isinstance(pdata.get("entries"), list):
                filtered: list[Any] = []
                for item in pdata["entries"]:
                    if isinstance(item, dict):
                        p_str = str(item.get("path", "")).rstrip("/")
                        if p_str == wp_path.rstrip("/") or p_str.endswith(
                            (
                                "/pa-daemon/workspace-plugin",
                                "/workspace-plugin/principal-architect",
                            )
                        ):
                            continue
                    filtered.append(item)
                plugins_file.write_text(
                    json.dumps({"entries": filtered}, indent=2) + "\n",
                    encoding="utf-8",
                )
        except (OSError, json.JSONDecodeError):
            pass

    state_db.Registry().unregister(repo_root)
    print(f"Unenrolled repository: {repo_root}", file=sys.stderr)
    return 0


_GIT_LOG_TRAILER_RE = re.compile(
    r"([0-9a-fA-F]{7,40})\x00([^\x00]*)\x00([^\x00\r\n]*)"
)


def _scan_git_trailers(
    repo_root: Path,
    *,
    runner: common.Runner = common.run,
) -> dict[str, tuple[str, str | None]]:
    """Scan local git commit trailers for `PA-WorkOrder` and `PA-Verified-Hash`.

    Returns a mapping `wo_id -> (commit_sha, verified_hash)` for the latest matching commit.
    """
    try:
        res = runner(
            [
                "git",
                "log",
                "--format=%H%x00%(trailers:key=PA-WorkOrder,valueonly=true)%x00%(trailers:key=PA-Verified-Hash,valueonly=true)",
            ],
            cwd=repo_root,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    if res.returncode != 0 or not res.stdout:
        return {}

    trailers: dict[str, tuple[str, str | None]] = {}
    for match in _GIT_LOG_TRAILER_RE.finditer(res.stdout):
        sha = match.group(1).strip()
        wo_raw = match.group(2).strip()
        hash_raw = match.group(3).strip()
        if not wo_raw:
            continue
        # Handle multiple trailer lines if present; take first non-empty token
        wo_id = wo_raw.splitlines()[0].strip()
        v_hash = hash_raw.splitlines()[0].strip() if hash_raw else None
        if wo_id and wo_id not in trailers:
            trailers[wo_id] = (sha, v_hash)
    return trailers


def _status_glyph(status: str) -> str:
    """Return a human-readable status glyph (used ONLY in non-JSON human output)."""
    mapping = {
        "COMPLETED": "✅",
        "GRADUATED": "✅",
        "AUDIT_APPROVED": "✅",
        "APPROVED": "🟢",
        "IN_PROGRESS": "⚡",
        "ACTIVE": "⚡",
        "STAGED_FOR_AUDIT": "📤",
        "CHANGES_REQUESTED": "🔴",
        "BLOCKED": "🔴",
        "ESCALATED_TO_PA": "🔴",
        "PLANNED": "⏳",
        "PENDING": "⏳",
        "DRAFT": "⏳",
        "ARCHIVED": "📦",
    }
    return mapping.get(status, "•")


def _cmd_status(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Reconcile committed specs, git trailers, and state.db; output human tree or `--json`."""
    import schemas  # Lazy import per Charter R1

    raw_target = Path(args.path).expanduser()
    if not raw_target.exists():
        print(f"Error: Path does not exist: {args.path}", file=sys.stderr)
        return 2

    repo_root = common.find_repo_root(raw_target, runner=runner)
    if repo_root is None:
        print(f"Error: Not inside a git repository: {args.path}", file=sys.stderr)
        return 2

    ws_dir = common.workspace_dir(repo_root)
    db_file = ws_dir / ".state" / "state.db"

    if db_file.is_file():
        with state_db.StateDB(db_file) as db:
            vcs_mode = db.get_config("vcs_mode") or detect_vcs_mode(repo_root, runner=runner)
            memory_mode = db.get_config("memory_mode") or detect_memory_mode(repo_root)
            execution_mode = db.get_config("execution_mode") or "monitored"
            attention_queue = db.list_open()
    else:
        vcs_mode = detect_vcs_mode(repo_root, runner=runner)
        memory_mode = detect_memory_mode(repo_root)
        execution_mode = "monitored"
        attention_queue = []

    git_trailers = _scan_git_trailers(repo_root, runner=runner)

    programmes: list[dict[str, Any]] = []
    prs: list[dict[str, Any]] = []

    if ws_dir.is_dir():
        for prog_dir in sorted(ws_dir.glob("programme-*")):
            prog_md = prog_dir / "PROGRAM.md"
            if not prog_md.is_file():
                continue
            prog_doc = schemas.load_program(prog_md)
            programmes.append(
                {
                    "programme_id": prog_doc.spec.programme_id,
                    "title": prog_doc.spec.title,
                    "base_branch": prog_doc.spec.base_branch,
                    "status": prog_doc.spec.status,
                    "prs": [p.model_dump(mode="json") for p in prog_doc.spec.prs],
                }
            )

        for pr_dir in sorted(ws_dir.glob("pr-*")):
            proj_md = pr_dir / "PROJECT.md"
            if not proj_md.is_file():
                continue
            proj_doc = schemas.load_project(proj_md)

            # Load individual WORKORDER.md files in this PR directory
            wo_docs: dict[str, tuple[str, schemas.Document[schemas.WorkOrderSpec]]] = {}
            for wo_dir in sorted(pr_dir.glob("wo*")):
                wo_md = wo_dir / "WORKORDER.md"
                if wo_md.is_file():
                    wo_doc = schemas.load_workorder(wo_md)
                    wo_docs[wo_doc.spec.wo_id] = (wo_dir.name, wo_doc)

            reconciled_wos: list[dict[str, Any]] = []
            seen_wo_ids: set[str] = set()

            for row in proj_doc.spec.work_orders:
                seen_wo_ids.add(row.id)
                wo_status = row.status.value
                attempts = row.attempts
                commit_sha = row.commit_sha
                receipt_id: str | None = None
                verified_hash: str | None = None

                if row.id in wo_docs:
                    _, wdoc = wo_docs[row.id]
                    if (
                        wdoc.spec.status == schemas.WorkOrderStatus.COMPLETED
                        or wo_status == "PENDING"
                    ):
                        wo_status = wdoc.spec.status.value
                    if wdoc.spec.completion is not None:
                        attempts = max(attempts, wdoc.spec.completion.attempt_num)
                        if wdoc.spec.completion.commit_sha:
                            commit_sha = wdoc.spec.completion.commit_sha
                        if wdoc.spec.completion.receipt_id:
                            receipt_id = wdoc.spec.completion.receipt_id

                if row.id in git_trailers:
                    t_sha, t_hash = git_trailers[row.id]
                    if t_sha:
                        commit_sha = t_sha
                    if t_hash:
                        verified_hash = t_hash

                reconciled_wos.append(
                    {
                        "id": row.id,
                        "wo_id": row.id,
                        "slug": row.slug,
                        "title": row.title,
                        "complexity": row.complexity.value,
                        "status": wo_status,
                        "attempts": attempts,
                        "commit_sha": commit_sha,
                        "receipt_id": receipt_id,
                        "verified_hash": verified_hash,
                    }
                )

            for wo_id, (wo_slug, wdoc) in wo_docs.items():
                if wo_id in seen_wo_ids:
                    continue
                commit_sha = (
                    wdoc.spec.completion.commit_sha if wdoc.spec.completion else None
                )
                receipt_id = (
                    wdoc.spec.completion.receipt_id if wdoc.spec.completion else None
                )
                attempts = (
                    wdoc.spec.completion.attempt_num if wdoc.spec.completion else 0
                )
                verified_hash = None
                if wo_id in git_trailers:
                    t_sha, t_hash = git_trailers[wo_id]
                    if t_sha:
                        commit_sha = t_sha
                    if t_hash:
                        verified_hash = t_hash

                reconciled_wos.append(
                    {
                        "id": wo_id,
                        "wo_id": wo_id,
                        "slug": wo_slug,
                        "title": wdoc.spec.title,
                        "complexity": wdoc.spec.complexity.value,
                        "status": wdoc.spec.status.value,
                        "attempts": attempts,
                        "commit_sha": commit_sha,
                        "receipt_id": receipt_id,
                        "verified_hash": verified_hash,
                    }
                )

            # Inspect AUDIT-round-*.md files
            latest_audit: dict[str, Any] | None = None
            audit_docs: list[schemas.Document[schemas.AuditReport]] = []
            for audit_md in sorted(pr_dir.glob("AUDIT-round-*.md")):
                if audit_md.is_file():
                    audit_docs.append(schemas.load_audit(audit_md))
            if audit_docs:
                audit_docs.sort(key=lambda d: d.spec.audit_round)
                top_audit = audit_docs[-1].spec
                latest_audit = {
                    "audit_round": top_audit.audit_round,
                    "head_sha": top_audit.head_sha,
                    "verdict": top_audit.verdict,
                    "auditor_harness": top_audit.auditor_harness,
                    "findings_count": len(top_audit.findings),
                }

            pr_entry: dict[str, Any] = {
                "pr_id": proj_doc.spec.charter.pr_id,
                "slug": proj_doc.spec.charter.slug,
                "title": proj_doc.spec.charter.title,
                "status": proj_doc.spec.status.value,
                "branch": proj_doc.spec.charter.branch,
                "base_branch": proj_doc.spec.charter.base_branch,
                "github_pr": proj_doc.spec.github_pr,
                "charter_locked": proj_doc.spec.charter.charter_locked,
                "work_orders": reconciled_wos,
            }
            if latest_audit is not None:
                pr_entry["latest_audit"] = latest_audit
            prs.append(pr_entry)

    payload: dict[str, Any] = {
        "env": {
            "vcs_mode": vcs_mode,
            "memory_mode": memory_mode,
            "execution_mode": execution_mode,
            "workspace_dir": str(ws_dir),
        },
        "programmes": programmes,
        "prs": prs,
        "attention_queue": attention_queue,
    }

    if args.as_json:
        print(json.dumps(payload, indent=2))
        return 0

    # Human-readable tree output (glyphs allowed here)
    lines: list[str] = [
        f"Principal Architect Status — {repo_root.name}",
        f"Environment: vcs={vcs_mode} | memory={memory_mode} | mode={execution_mode}",
    ]
    if attention_queue:
        lines.append("\n🔔 Human Attention Needed:")
        for item in attention_queue:
            lines.append(
                f"  - [P{item.get('priority', 10)}] ({item.get('kind', 'info')}) {item.get('title', '')}"
            )

    if programmes:
        lines.append("\nProgrammes:")
        for prog in programmes:
            g = _status_glyph(str(prog["status"]))
            lines.append(f"  {g} {prog['programme_id']}: {prog['title']} [{prog['status']}]")

    if prs:
        lines.append("\nPull Requests:")
        for pr in prs:
            g = _status_glyph(str(pr["status"]))
            lock_glyph = " 🔒" if pr.get("charter_locked") else ""
            lines.append(
                f"  {g} {pr['pr_id']} ({pr['slug']}): {pr['title']} [{pr['status']}]{lock_glyph}"
            )
            for wo in pr["work_orders"]:
                wg = _status_glyph(str(wo["status"]))
                sha_sfx = f" ({str(wo['commit_sha'])[:7]})" if wo.get("commit_sha") else ""
                lines.append(
                    f"      {wg} {wo['id']} [{wo['complexity']}]: {wo['title']} — {wo['status']}{sha_sfx}"
                )

    print("\n".join(lines))
    return 0


def _cmd_mode(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Get or set repository `execution_mode` (`monitored` | `autonomous`)."""
    raw_target = Path(args.path).expanduser()
    if not raw_target.exists():
        print(f"Error: Path does not exist: {args.path}", file=sys.stderr)
        return 2

    repo_root = common.find_repo_root(raw_target, runner=runner)
    if repo_root is None:
        print(f"Error: Not inside a git repository: {args.path}", file=sys.stderr)
        return 2

    mode_val: str | None = args.mode_value
    if mode_val is not None and mode_val not in ("monitored", "autonomous"):
        print(
            f"Error: Invalid execution mode '{mode_val}'. Expected 'monitored' or 'autonomous'.",
            file=sys.stderr,
        )
        return 1

    ws_dir = common.workspace_dir(repo_root)
    db_file = ws_dir / ".state" / "state.db"

    if mode_val is None:
        if db_file.is_file():
            with state_db.StateDB(db_file) as db:
                current = db.get_config("execution_mode", "monitored") or "monitored"
        else:
            current = "monitored"
        print(current)
        return 0

    with state_db.StateDB(db_file) as db:
        db.set_config("execution_mode", mode_val)
    print(mode_val)
    return 0


def _parse_porcelain_paths(stdout: str) -> list[str]:
    """Parse dirty/untracked repo-relative POSIX paths from `git status --porcelain -uall`."""
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
    """Return True if `rel_posix` is an ephemeral runtime file ignored by scope hygiene."""
    norm = rel_posix.strip().lstrip("./")
    if norm == ".agents/plugins.json":
        return True
    return ".state" in norm.split("/")


def _collect_existing_allowed_files(
    real_root: Path,
    allowed_files: Sequence[str],
    forbidden_files: Sequence[str],
    matches_any_fn: Any,
) -> list[str]:
    """Return sorted existing repo-relative POSIX paths matching `allowed_files` and not `forbidden_files`."""
    collected: list[str] = []
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
            if not matches_any_fn(rel_posix, forbidden_files) and matches_any_fn(
                rel_posix, allowed_files
            ):
                collected.append(rel_posix)
    collected.sort()
    return collected


def _cmd_wo_verify(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Verify Work Order scope hygiene, run `verification_command`, stamp receipt, and commit."""
    import post_tool_receipt
    import pre_tool_gate
    import schemas

    raw_target = Path(args.path).expanduser()
    if not raw_target.exists():
        print(f"Error: Path does not exist: {args.path}", file=sys.stderr)
        return 2

    repo_root = common.find_repo_root(raw_target, runner=runner)
    if repo_root is None:
        print(f"Error: Not inside a git repository: {args.path}", file=sys.stderr)
        return 2

    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)
    wo_id_arg = str(args.wo_id).strip()

    git_dir = real_root / ".git"
    if git_dir.is_dir():
        _ensure_line_in_file(git_dir / "info" / "exclude", ".agents/plugins.json")
        _ensure_line_in_file(
            git_dir / "info" / "exclude",
            f"{common.NEW_WORKSPACE_REL.as_posix()}/.state/",
        )
        _ensure_line_in_file(
            git_dir / "info" / "exclude",
            f"{common.LEGACY_WORKSPACE_REL.as_posix()}/.state/",
        )

    wo_doc = pre_tool_gate._find_bound_workorder(ws_dir, None, wo_id_arg)
    if wo_doc is None or wo_doc.path is None:
        print(f"Error: Work Order '{wo_id_arg}' not found in {ws_dir}", file=sys.stderr)
        return 1

    # Step 1: Check spec_hash & git status --porcelain scope hygiene
    if wo_doc.spec.spec_hash and not schemas.verify_spec_hash(wo_doc.path):
        print(
            f"Error: WORKORDER.md Part I spec_hash verification failed for {wo_doc.spec.wo_id}.",
            file=sys.stderr,
        )
        return 1

    status_res = runner(["git", "status", "--porcelain", "-uall"], cwd=real_root)
    if status_res.returncode != 0:
        print(
            f"Error: git status failed: {status_res.stderr.strip()}",
            file=sys.stderr,
        )
        return 1

    wo_rel_posix = wo_doc.path.resolve().relative_to(real_root).as_posix()
    dirty_paths = [
        p
        for p in _parse_porcelain_paths(status_res.stdout)
        if not _is_ephemeral_runtime_path(p)
    ]

    out_of_scope: list[str] = []
    for rel_p in dirty_paths:
        if rel_p == wo_rel_posix:
            continue
        if pre_tool_gate.matches_any_pattern(
            rel_p, wo_doc.spec.forbidden_files
        ) or not pre_tool_gate.matches_any_pattern(rel_p, wo_doc.spec.allowed_files):
            out_of_scope.append(rel_p)

    if out_of_scope:
        print(
            f"Error: Scope hygiene check failed for {wo_doc.spec.wo_id}; "
            f"modified or untracked files outside allowed_files: {', '.join(out_of_scope)}",
            file=sys.stderr,
        )
        return 1

    # Step 2: Execute verification_command
    ver_res = runner(
        ["/bin/sh", "-c", wo_doc.spec.verification_command],
        cwd=real_root,
        timeout=300.0,
    )
    if ver_res.returncode != 0:
        if ver_res.stdout:
            print(
                ver_res.stdout,
                file=sys.stderr,
                end="" if ver_res.stdout.endswith("\n") else "\n",
            )
        if ver_res.stderr:
            print(
                ver_res.stderr,
                file=sys.stderr,
                end="" if ver_res.stderr.endswith("\n") else "\n",
            )
        print(
            f"Error: verification_command failed with exit code {ver_res.returncode}.",
            file=sys.stderr,
        )
        return 1

    # Step 3: Stamp cryptographic receipt in WORKORDER.md Part II (and PROJECT.md if present)
    t_hash = post_tool_receipt.compute_tree_hash(real_root, wo_doc.spec.allowed_files)
    receipt_id = f"rcpt_{t_hash[:12]}"
    pre_head_res = runner(["git", "rev-parse", "HEAD"], cwd=real_root)
    pre_head_sha = (
        pre_head_res.stdout.strip()
        if pre_head_res.returncode == 0 and pre_head_res.stdout.strip()
        else None
    )

    files_modified = sorted(
        p
        for p in dirty_paths
        if p != wo_rel_posix
        and not pre_tool_gate.matches_any_pattern(p, wo_doc.spec.forbidden_files)
        and pre_tool_gate.matches_any_pattern(p, wo_doc.spec.allowed_files)
    )
    if not files_modified:
        files_modified = _collect_existing_allowed_files(
            real_root,
            wo_doc.spec.allowed_files,
            wo_doc.spec.forbidden_files,
            pre_tool_gate.matches_any_pattern,
        )

    prev_comp = wo_doc.spec.completion
    existing_attempt_num = prev_comp.attempt_num if prev_comp is not None else 1
    db_file = ws_dir / ".state" / "state.db"
    if prev_comp is None and db_file.is_file():
        with state_db.StateDB(db_file) as db:
            cur = db.conn.execute(
                "SELECT MAX(attempt_num) FROM sessions WHERE wo_id = ?",
                (wo_doc.spec.wo_id,),
            )
            row_max = cur.fetchone()
            if row_max is not None and row_max[0] is not None:
                existing_attempt_num = max(1, min(int(row_max[0]), 5))

    if prev_comp is not None and prev_comp.verification_summary.strip():
        summary_str = prev_comp.verification_summary.strip()[:280]
    else:
        non_empty = [ln.strip() for ln in (ver_res.stdout or "").splitlines() if ln.strip()]
        if non_empty:
            summary_str = f"{wo_doc.spec.verification_command}: {non_empty[-1]}"[:280]
        else:
            summary_str = f"{wo_doc.spec.verification_command} exited 0"[:280]

    wo_doc.spec.status = schemas.WorkOrderStatus.COMPLETED
    wo_doc.spec.completion = schemas.CompletionReport(
        status=schemas.WorkOrderStatus.COMPLETED,
        attempt_num=existing_attempt_num,
        receipt_id=receipt_id,
        commit_sha=pre_head_sha,
        files_modified=files_modified,
        verification_summary=summary_str,
        out_of_scope_findings=list(prev_comp.out_of_scope_findings) if prev_comp else [],
        escalation_request=prev_comp.escalation_request if prev_comp else None,
        decisions_made=list(prev_comp.decisions_made) if prev_comp else [],
        dead_ends=list(prev_comp.dead_ends) if prev_comp else [],
    )
    wo_doc.path.write_text(
        schemas.dump_document(wo_doc.spec, wo_doc.sections),
        encoding="utf-8",
    )
    if wo_doc.spec.spec_hash and not schemas.verify_spec_hash(wo_doc.path):
        print(
            f"Error: Internal spec_hash check failed after updating {wo_doc.path}",
            file=sys.stderr,
        )
        return 1

    proj_md = wo_doc.path.parent.parent / "PROJECT.md"
    proj_rel_posix: str | None = None
    if proj_md.is_file():
        proj_doc = schemas.load_project(proj_md)
        updated_proj = False
        for row in proj_doc.spec.work_orders:
            if row.id.upper() == wo_doc.spec.wo_id.upper():
                row.status = schemas.WorkOrderStatus.COMPLETED
                row.attempts = max(row.attempts, existing_attempt_num)
                row.commit_sha = pre_head_sha
                updated_proj = True
                break
        if updated_proj:
            proj_md.write_text(
                schemas.dump_document(proj_doc.spec, proj_doc.sections),
                encoding="utf-8",
            )
            if proj_doc.spec.charter.charter_locked and not schemas.verify_charter_hash(proj_md):
                print(
                    f"Error: PROJECT.md charter_hash verification failed after update: {proj_md}",
                    file=sys.stderr,
                )
                return 1
            proj_rel_posix = proj_md.resolve().relative_to(real_root).as_posix()

    # Step 4: Commit allowed_files + WORKORDER.md (and PROJECT.md if updated) and record receipt
    paths_to_stage = _dedup_preserve_order(
        [
            *files_modified,
            wo_rel_posix,
            *([proj_rel_posix] if proj_rel_posix is not None else []),
        ]
    )
    add_res = runner(["git", "add", "--", *paths_to_stage], cwd=real_root)
    if add_res.returncode != 0:
        print(f"Error: git add failed: {add_res.stderr.strip()}", file=sys.stderr)
        return 1

    commit_msg = (
        f"{wo_doc.spec.wo_id}: {wo_doc.spec.title}\n\n"
        f"PA-WorkOrder: {wo_doc.spec.wo_id}\n"
        f"PA-Verified-Hash: {t_hash}"
    )
    commit_res = runner(["git", "commit", "-m", commit_msg], cwd=real_root)
    if commit_res.returncode != 0:
        print(
            f"Error: git commit failed: {commit_res.stderr.strip() or commit_res.stdout.strip()}",
            file=sys.stderr,
        )
        return 1

    head_res = runner(["git", "rev-parse", "HEAD"], cwd=real_root)
    new_head_sha = (
        head_res.stdout.strip()
        if head_res.returncode == 0 and head_res.stdout.strip()
        else pre_head_sha
    )

    with state_db.StateDB(db_file) as db:
        post_tool_receipt._upsert_receipt(
            db,
            wo_id=wo_doc.spec.wo_id,
            pr_id=wo_doc.spec.pr_id,
            cmd=wo_doc.spec.verification_command,
            exit_code=0,
            tree_hash=t_hash,
            git_head_sha=new_head_sha,
            valid=1,
            receipt_id=receipt_id,
        )

    print(
        f"Verified and committed {wo_doc.spec.wo_id} ({new_head_sha[:12] if new_head_sha else 'HEAD'})\n"
        f"  receipt_id: {receipt_id}\n"
        f"  tree_hash:  {t_hash}",
        file=sys.stderr,
    )
    return 0


def _is_pattern_within_allowed_modules(
    pattern: str,
    allowed_modules: Sequence[str],
    matches_any_fn: Any,
) -> bool:
    """Return True if Work Order `allowed_files` pattern falls within `charter.allowed_modules`."""
    norm = pattern.strip().lstrip("./")
    if not norm:
        return False
    stripped_glob = re.sub(r"/\*+$", "", norm).rstrip("/")
    candidates = [norm, norm.rstrip("/")]
    if stripped_glob:
        candidates.append(stripped_glob)
    return any(matches_any_fn(cand, allowed_modules) for cand in candidates)


def _cmd_pr_approve_plan(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Validate `PROJECT.md` and `wo*/WORKORDER.md` specs, stamp `spec_hash`, and approve PR plan."""
    import pre_tool_gate
    import schemas

    raw_target = Path(args.path).expanduser()
    if not raw_target.exists():
        print(f"Error: Path does not exist: {args.path}", file=sys.stderr)
        return 2

    repo_root = common.find_repo_root(raw_target, runner=runner)
    if repo_root is None:
        print(f"Error: Not inside a git repository: {args.path}", file=sys.stderr)
        return 2

    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)
    pr_id_arg = str(args.pr_id).strip()
    if not pr_id_arg:
        print("Error: pr_id is required for pa pr approve-plan", file=sys.stderr)
        return 1

    proj_md: Path | None = None
    proj_doc: schemas.Document[schemas.ProjectSpec] | None = None
    for cand_md in sorted(ws_dir.glob("pr-*/PROJECT.md")):
        pr_dir_name = cand_md.parent.name
        try:
            cand_doc = schemas.load_project(cand_md)
        except Exception as exc:  # noqa: BLE001
            if pr_dir_name.lower() == pr_id_arg.lower():
                print(
                    f"Error: Invalid PROJECT.md at {cand_md}: {exc}",
                    file=sys.stderr,
                )
                return 1
            continue
        if (
            cand_doc.spec.charter.pr_id.upper() == pr_id_arg.upper()
            or pr_dir_name.lower() == pr_id_arg.lower()
        ):
            proj_md = cand_md
            proj_doc = cand_doc
            break

    if proj_md is None or proj_doc is None:
        print(
            f"Error: PROJECT.md for '{pr_id_arg}' not found in {ws_dir}",
            file=sys.stderr,
        )
        return 1

    pr_dir = proj_md.parent
    pr_id_canonical = proj_doc.spec.charter.pr_id

    if proj_doc.spec.charter.charter_locked and not schemas.verify_charter_hash(proj_md):
        print(
            f"Error: PROJECT.md Part I charter_hash verification failed for {pr_id_canonical}.",
            file=sys.stderr,
        )
        return 1

    if len(proj_doc.spec.work_orders) < 1:
        print(
            f"Error: PROJECT.md for {pr_id_canonical} has no work_orders entries.",
            file=sys.stderr,
        )
        return 1

    wo_paths = sorted(pr_dir.glob("wo*/WORKORDER.md"))
    if not wo_paths:
        print(
            f"Error: No wo*/WORKORDER.md files found in {pr_dir}",
            file=sys.stderr,
        )
        return 1

    allowed_modules = proj_doc.spec.charter.allowed_modules
    loaded_wos: list[tuple[Path, schemas.Document[schemas.WorkOrderSpec]]] = []
    loaded_by_id: dict[str, schemas.Document[schemas.WorkOrderSpec]] = {}

    for wo_md in wo_paths:
        try:
            wo_doc = schemas.load_workorder(wo_md)
        except Exception as exc:  # noqa: BLE001
            print(
                f"Error: Invalid WORKORDER.md at {wo_md}: {exc}",
                file=sys.stderr,
            )
            return 1

        if wo_doc.spec.pr_id.upper() != pr_id_canonical.upper():
            print(
                f"Error: WORKORDER.md {wo_doc.spec.wo_id} declares pr_id='{wo_doc.spec.pr_id}' "
                f"(expected '{pr_id_canonical}').",
                file=sys.stderr,
            )
            return 1

        for af in wo_doc.spec.allowed_files:
            if not _is_pattern_within_allowed_modules(
                af, allowed_modules, pre_tool_gate.matches_any_pattern
            ):
                print(
                    f"Error: Work Order {wo_doc.spec.wo_id} allowed_files pattern '{af}' "
                    f"falls outside charter.allowed_modules for {pr_id_canonical}.",
                    file=sys.stderr,
                )
                return 1

        loaded_wos.append((wo_md, wo_doc))
        loaded_by_id[wo_doc.spec.wo_id.upper()] = wo_doc

    for row in proj_doc.spec.work_orders:
        if row.id.upper() not in loaded_by_id:
            print(
                f"Error: Work Order '{row.id}' listed in PROJECT.md has no matching WORKORDER.md in {pr_dir}",
                file=sys.stderr,
            )
            return 1

    for wo_md, wo_doc in loaded_wos:
        h = schemas.compute_spec_hash(wo_doc)
        wo_doc.spec.spec_hash = h
        wo_md.write_text(
            schemas.dump_document(wo_doc.spec, wo_doc.sections),
            encoding="utf-8",
        )
        if not schemas.verify_spec_hash(wo_md):
            print(
                f"Error: Failed to verify stamped spec_hash on {wo_md}",
                file=sys.stderr,
            )
            return 1

    proj_doc.spec.status = schemas.PRState.APPROVED
    if proj_doc.spec.approved_at is None:
        proj_doc.spec.approved_at = datetime.now(UTC)

    proj_md.write_text(
        schemas.dump_document(proj_doc.spec, proj_doc.sections),
        encoding="utf-8",
    )
    if (
        proj_doc.spec.charter.charter_locked
        and proj_doc.spec.charter.charter_hash
        and not schemas.verify_charter_hash(proj_md)
    ):
        print(
            f"Error: PROJECT.md charter_hash check failed after approval write: {proj_md}",
            file=sys.stderr,
        )
        return 1

    db_file = ws_dir / ".state" / "state.db"
    if db_file.is_file():
        with state_db.StateDB(db_file) as db:
            for item in db.list_open(pr_id=pr_id_canonical):
                if item.get("kind") == "plan_approval":
                    db.dequeue(str(item["item_id"]), status="RESOLVED")
            for esc in db.open_escalations(pr_id=pr_id_canonical):
                if esc.get("reason_code") == "PLAN_APPROVAL_REQUIRED":
                    db.resolve_escalation(str(esc["escalation_id"]), status="RESOLVED")

    print(
        f"Approved plan for {pr_id_canonical} ({len(loaded_wos)} Work Orders stamped).",
        file=sys.stderr,
    )
    return 0


def _cmd_escalate(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Record an upward escalation in `state.db` (`escalations` and optional `attention_queue`)."""
    import escalation

    raw_target = Path(args.path).expanduser()
    if not raw_target.exists():
        print(f"Error: Path does not exist: {args.path}", file=sys.stderr)
        return 2

    repo_root = common.find_repo_root(raw_target, runner=runner)
    if repo_root is None:
        print(f"Error: Not inside a git repository: {args.path}", file=sys.stderr)
        return 2

    if args.to_human or args.level == "chief_to_human":
        level = "chief_to_human"
        source_role = args.source_role or "chief"
        target_role = args.target_role or "human"
    elif args.to_chief or args.level == "pa_to_chief":
        level = "pa_to_chief"
        source_role = args.source_role or "pa"
        target_role = args.target_role or "chief"
    else:
        level = "wo_to_pa"
        source_role = args.source_role or "engineer"
        target_role = args.target_role or "pa"

    summary_str = str(args.summary or args.summary_pos or "").strip()
    if not summary_str:
        print("Error: --summary is required for pa escalate", file=sys.stderr)
        return 1

    ws_dir = common.workspace_dir(repo_root)
    db_file = ws_dir / ".state" / "state.db"
    with state_db.StateDB(db_file) as db:
        exec_mode = (db.get_config("execution_mode") or "monitored").strip().lower()
        enqueue = (target_role == "human") or (exec_mode == "autonomous")
        row = escalation.record_escalation(
            db,
            level=level,
            source_role=source_role,
            target_role=target_role,
            pr_id=args.pr_id,
            wo_id=args.wo_id,
            blocker_type=args.blocker_type,
            reason_code=args.reason_code,
            requested_files=args.requested_file or [],
            summary=summary_str,
            enqueue_if_needed=enqueue,
            attention_kind="escalation",
            attention_title=(
                f"Escalation ({args.reason_code}): {args.wo_id or args.pr_id or level}"
            ),
            attention_priority=15 if target_role == "human" else 20,
        )

    print(row["escalation_id"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the root `pa` ArgumentParser and register all `COMMAND_MODULES`."""
    parser = argparse.ArgumentParser(
        prog="pa",
        description="Principal Architect Plugin CLI control plane.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # 1. pa enroll
    p_enroll = subparsers.add_parser(
        "enroll",
        help="Enroll a repository into principal-architect-plugin.",
    )
    p_enroll.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_enroll.add_argument(
        "--memory-mode",
        choices=["auto", "external", "builtin"],
        default="auto",
        help="Memory management mode (default: auto).",
    )
    p_enroll.add_argument(
        "--vcs-mode",
        choices=["auto", "github", "local_git"],
        default="auto",
        help="VCS synchronization mode (default: auto).",
    )
    p_enroll.add_argument(
        "--extra-skill",
        action="append",
        default=None,
        metavar="NAME",
        help="Global domain skill name to include in .state/pa-skills.json (repeatable).",
    )
    p_enroll.add_argument(
        "--exclude-rule",
        action="append",
        default=None,
        metavar="PATTERN",
        help="Rule glob pattern to exclude in .state/pa-worker-rules.json (repeatable).",
    )
    p_enroll.set_defaults(_handler=_cmd_enroll)

    # 2. pa unenroll
    p_unenroll = subparsers.add_parser(
        "unenroll",
        help="Unenroll a repository from principal-architect-plugin.",
    )
    p_unenroll.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_unenroll.set_defaults(_handler=_cmd_unenroll)

    # 3. pa status
    p_status = subparsers.add_parser(
        "status",
        help="Reconcile and display Programme, PR, and Work Order status.",
    )
    p_status.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_status.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON status to stdout.",
    )
    p_status.set_defaults(_handler=_cmd_status)

    # 4. pa mode
    p_mode = subparsers.add_parser(
        "mode",
        help="Get or set the repository execution mode (monitored or autonomous).",
    )
    p_mode.add_argument(
        "mode_value",
        nargs="?",
        default=None,
        metavar="monitored|autonomous",
        help="Execution mode to set ('monitored' or 'autonomous'). Omit to query.",
    )
    p_mode.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_mode.set_defaults(_handler=_cmd_mode)

    # 5. pa wo <subcommand>
    p_wo = subparsers.add_parser(
        "wo",
        help="Work Order lifecycle commands.",
    )
    wo_subparsers = p_wo.add_subparsers(dest="wo_command", metavar="<subcommand>")

    p_wo_verify = wo_subparsers.add_parser(
        "verify",
        help="Verify Work Order scope hygiene, run verification_command, stamp receipt, and commit.",
    )
    p_wo_verify.add_argument(
        "wo_id",
        help="Work Order ID (e.g., WO-02.3).",
    )
    p_wo_verify.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_wo_verify.set_defaults(_handler=_cmd_wo_verify)

    # 6. pa pr <subcommand>
    p_pr = subparsers.add_parser(
        "pr",
        help="Pull Request lifecycle commands.",
    )
    pr_subparsers = p_pr.add_subparsers(dest="pr_command", metavar="<subcommand>")

    p_pr_approve = pr_subparsers.add_parser(
        "approve-plan",
        help="Validate PROJECT.md and wo*/WORKORDER.md specs, stamp spec_hash, and set status: APPROVED.",
    )
    p_pr_approve.add_argument(
        "pr_id",
        help="Pull Request ID (e.g. PR-02) or folder slug.",
    )
    p_pr_approve.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_pr_approve.set_defaults(_handler=_cmd_pr_approve_plan)

    # 7. pa escalate
    p_escalate = subparsers.add_parser(
        "escalate",
        help="Record an upward hierarchical escalation in state.db.",
    )
    p_escalate.add_argument(
        "--level",
        choices=["wo_to_pa", "pa_to_chief", "chief_to_human"],
        default=None,
        help="Explicit escalation level.",
    )
    p_escalate.add_argument(
        "--to-pa",
        action="store_true",
        help="Escalate from Tier 3 Worker to Tier 2 Principal Architect.",
    )
    p_escalate.add_argument(
        "--to-chief",
        action="store_true",
        help="Escalate from Tier 2 Principal Architect to Tier 1 Chief Architect.",
    )
    p_escalate.add_argument(
        "--to-human",
        action="store_true",
        help="Escalate to the Human Attention Needed queue.",
    )
    p_escalate.add_argument(
        "--source-role",
        default=None,
        help="Override source role (default inferred from level).",
    )
    p_escalate.add_argument(
        "--target-role",
        default=None,
        help="Override target role (default inferred from level).",
    )
    p_escalate.add_argument(
        "--pr-id",
        default=None,
        help="Pull Request ID (e.g. PR-02).",
    )
    p_escalate.add_argument(
        "--wo-id",
        default=None,
        help="Work Order ID (e.g. WO-02.6).",
    )
    p_escalate.add_argument(
        "--blocker-type",
        default="scope",
        help="Blocker category (default: scope).",
    )
    p_escalate.add_argument(
        "--reason-code",
        default="MANUAL_ESCALATION",
        help="Reason code (default: MANUAL_ESCALATION).",
    )
    p_escalate.add_argument(
        "--requested-file",
        action="append",
        default=None,
        metavar="PATH",
        help="File or module path requested by the escalation (repeatable).",
    )
    p_escalate.add_argument(
        "--summary",
        default=None,
        help="Concise escalation summary.",
    )
    p_escalate.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_escalate.add_argument(
        "summary_pos",
        nargs="?",
        default=None,
        help="Optional positional escalation summary.",
    )
    p_escalate.set_defaults(_handler=_cmd_escalate)

    # Extension hook for downstream PR modules
    for mod_name in COMMAND_MODULES:
        mod = importlib.import_module(mod_name)
        register_fn = getattr(mod, "register", None)
        if callable(register_fn):
            register_fn(subparsers)

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: common.Runner = common.run,
) -> int:
    """CLI entrypoint returning exit code (0 = success, 1 = usage/validation, 2 = environment)."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    try:
        args = parser.parse_args(args_list)
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        return 1

    if getattr(args, "command", None) is None:
        parser.print_help(sys.stderr)
        return 1

    handler = getattr(args, "_handler", None)
    if callable(handler):
        return int(handler(args, runner=runner))

    # Fallback for COMMAND_MODULES setting `func`
    func = getattr(args, "func", None)
    if callable(func):
        try:
            return int(func(args, runner=runner))
        except TypeError:
            return int(func(args))

    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
