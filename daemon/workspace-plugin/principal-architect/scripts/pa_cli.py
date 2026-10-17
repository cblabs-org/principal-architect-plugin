#!/usr/bin/env python3
"""Principal Architect Plugin (`pa`) CLI entrypoint and subcommand dispatcher.

Implements `pa enroll`, `pa unenroll`, `pa status [--json]`, and `pa mode`, plus
the `COMMAND_MODULES` extension list consumed by downstream PR modules.

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
                    if not commit_sha:
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
                    if not commit_sha:
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
