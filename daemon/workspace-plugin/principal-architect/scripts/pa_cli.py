#!/usr/bin/env python3
"""Principal Architect Plugin (c) 2026 Matt McNeill
https://github.com/matthewmcneill/principal-architect-plugin
SPDX-License-Identifier: Apache-2.0
Module: daemon/workspace-plugin/principal-architect/scripts/pa_cli.py

Principal Architect Plugin (`pa`) CLI entrypoint and control-plane subcommand dispatcher.
Orchestrates the three-tier Split-Authority lifecycle across Tier 1 Chief Architect
(`pa programme init`, `pa programme charter`), Tier 2 Principal Architect (`pa pr start`,
`pa pr claim`, `pa pr approve-plan`, `pa pr open-or-sync`, `pa pr post-audit`,
`pa pr sync-audit`, `pa pr graduate`, `pa pr restack`), Tier 3 Execution Worker and
Interactive Debugger (`pa wo verify`, `pa wo debug`, `pa wo resolve`), and repository
administration (`pa enroll`, `pa migrate`, `pa unenroll`, `pa status`, `pa sync`,
`pa mode`, `pa issue create`, `pa escalate`).

Lazy Import Rule (Charter R1 & R6): This module MUST NOT import `pydantic`, `yaml`,
`schemas`, `vcs_sync`, `models`, or `memory_grad` at module top-level so fast paths
(`pa --help`, `pa mode`) remain sub-millisecond and stdlib-only.

Exported API Summary
--------------------
Constants:
  - `_SCRIPTS_DIR`: Absolute directory path containing plugin control-plane scripts.
  - `COMMAND_MODULES`: Extension module names registered dynamically by `build_parser()`.
  - `DEFAULT_WORKER_RULE_EXCLUDES`: Default rule globs excluded for Tier 3 workers.
  - `_GIT_LOG_TRAILER_RE`: Regex matching NUL-delimited `git log` SHA and PA trailers.

Functions:
  - `_dedup_preserve_order(items) -> list[str]`: Deduplicate non-empty strings in order.
  - `_ensure_line_in_file(file_path, line_to_ensure) -> None`: Idempotently append a line.
  - `detect_vcs_mode(repo_root, *, runner=common.run) -> Literal["github", "local_git"]`:
    Auto-detect repository VCS mode (`github` vs `local_git`).
  - `detect_memory_mode(repo_root) -> Literal["external", "builtin"]`:
    Auto-detect repository memory mode (`external` vs `builtin`).
  - `_move_path_git_or_fs(repo_root, src, dst, *, runner=common.run) -> None`:
    Move a path via `git mv` when tracked, falling back to `shutil.move`.
  - `_merge_legacy_into_new_workspace(repo_root, legacy_ws, new_ws, *, runner) -> list[str]`:
    Migrate or merge legacy `.agents/skills/principal-architect-workspace` into the new workspace.
  - `_cleanup_legacy_skill_dir(repo_root, *, runner=common.run) -> bool`:
    Remove legacy `.agents/skills/principal-architect` directory or submodule.
  - `_rewrite_legacy_workspace_paths(new_ws) -> int`:
    Rewrite stale legacy workspace path references in Markdown specs and recompute hashes.
  - `_bridge_repo_memory(repo_root, new_ws, *, runner=common.run) -> dict[str, Any]`:
    Register PA memory in `.agents/memory/config.json` and run `repo-memory` seed/index.
  - `_cmd_migrate(args, *, runner=common.run) -> int`: Handler for `pa migrate`.
  - `_cmd_enroll(args, *, runner=common.run) -> int`: Handler for `pa enroll`.
  - `_cmd_unenroll(args, *, runner=common.run) -> int`: Handler for `pa unenroll`.
  - `_scan_git_trailers(repo_root, *, runner=common.run) -> dict[str, tuple[str, str | None]]`:
    Scan local Git history for `PA-WorkOrder` and `PA-Verified-Hash` commit trailers.
  - `_status_glyph(status) -> str`: Map a status string to a human-readable terminal glyph.
  - `_cmd_status(args, *, runner=common.run) -> int`: Handler for `pa status [--json]`.
  - `_cli_plugin_version() -> str`: Resolve the semantic version of the running `pa_cli.py` bundle.
  - `_installed_daemon_version() -> str | None`: Read the semantic version of the installed `pa-daemon` bundle.
  - `_cmd_doctor(args, *, runner=common.run) -> int`: Handler for `pa doctor [--json]`.
  - `_cmd_mode(args, *, runner=common.run) -> int`: Handler for `pa mode`.
  - `_parse_porcelain_paths(stdout) -> list[str]`: Parse paths from `git status --porcelain`.
  - `_is_ephemeral_runtime_path(rel_posix) -> bool`: Check if a path is an ignored runtime file.
  - `_collect_existing_allowed_files(real_root, allowed_files, forbidden_files, ...) -> list[str]`:
    Enumerate existing repository files matching `allowed_files` and not `forbidden_files`.
  - `_cmd_wo_verify(args, *, runner=common.run) -> int`: Handler for `pa wo verify`.
  - `_cmd_wo_debug(args, *, runner=common.run) -> int`: Handler for `pa wo debug`.
  - `_cmd_wo_resolve(args, *, runner=common.run) -> int`: Handler for `pa wo resolve`.
  - `_is_pattern_within_allowed_modules(pattern, allowed_modules, matches_any_fn) -> bool`:
    Validate that a Work Order `allowed_files` pattern falls within `charter.allowed_modules`.
  - `_cmd_pr_approve_plan(args, *, runner=common.run) -> int`: Handler for `pa pr approve-plan`.
  - `_cmd_escalate(args, *, runner=common.run) -> int`: Handler for `pa escalate`.
  - `_resolve_repo_root_and_ws(path_str, *, runner=common.run) -> tuple[Path, Path] | int`:
    Resolve `(real_root, ws_dir)` from a CLI path argument or return exit code `2`.
  - `_normalize_pr_id(raw_pr_id) -> str`: Normalize a PR identifier to `PR-NN[a-z]`.
  - `_normalize_pr_slug(pr_id_canonical, raw_slug) -> str`: Normalize a PR directory slug.
  - `_cmd_sync(args, *, runner=common.run) -> int`: Handler for `pa sync`.
  - `_cmd_programme_init(args, *, runner=common.run) -> int`: Handler for `pa programme init`.
  - `_scaffold_or_update_project_charter(ws_dir, *, pr_id_raw, ...) -> tuple[Path, Path, Any, str]`:
    Create or update `PROJECT.md` Part I Charter, stamp `charter_hash`, and sync `PROGRAM.md`.
  - `_cmd_programme_charter(args, *, runner=common.run) -> int`: Handler for `pa programme charter`.
  - `_cmd_pr_start(args, *, runner=common.run) -> int`: Handler for `pa pr start`.
  - `_cmd_pr_claim(args, *, runner=common.run) -> int`: Handler for `pa pr claim`.
  - `_cmd_pr_open_or_sync(args, *, runner=common.run) -> int`: Handler for `pa pr open-or-sync`.
  - `_cmd_pr_post_audit(args, *, runner=common.run) -> int`: Handler for `pa pr post-audit`.
  - `_cmd_pr_sync_audit(args, *, runner=common.run) -> int`: Handler for `pa pr sync-audit`.
  - `_sha_matches(sha_a, sha_b) -> bool`: Compare two Git commit SHAs (supporting short prefixes).
  - `_head_matches_audited_sha(real_root, pr_dir, current_head_sha, audited_sha, ...) -> bool`:
    Check whether `current_head_sha` (or `HEAD~1` for audit commits) matches `audited_sha`.
  - `_cmd_pr_graduate(args, *, runner=common.run) -> int`: Handler for `pa pr graduate`.
  - `_cmd_pr_restack(args, *, runner=common.run) -> int`: Handler for `pa pr restack`.
  - `_cmd_issue_create(args, *, runner=common.run) -> int`: Handler for `pa issue create`.
  - `build_parser() -> argparse.ArgumentParser`: Build the root `pa` CLI argument parser.
  - `main(argv=None, *, runner=common.run) -> int`: Main CLI entrypoint.
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

# Absolute directory containing the Principal Architect control-plane scripts.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import state_db

# Registry of optional extension module names dynamically imported by `build_parser()`.
COMMAND_MODULES: list[str] = []

# Default workspace rule patterns excluded for Tier 3 workers to prevent planning loops.
DEFAULT_WORKER_RULE_EXCLUDES: tuple[str, ...] = (
    "01-plan-before-execute.md",
    "bug-fixer-*",
)


def _dedup_preserve_order(items: Sequence[str]) -> list[str]:
    """Deduplicate non-empty stripped strings while preserving first-seen order.

    Args:
        items: Input sequence of raw strings.

    Returns:
        Deduplicated list of non-empty stripped strings.
    """
    seen: set[str] = set()
    result: list[str] = []
    for raw in items:
        val = raw.strip()
        if val and val not in seen:
            seen.add(val)
            result.append(val)
    return result


def _ensure_line_in_file(file_path: Path, line_to_ensure: str) -> None:
    """Ensure `line_to_ensure` is present as a line in `file_path` without duplicating it.

    Args:
        file_path: Target file `Path` (created along with parent directories if missing).
        line_to_ensure: Single line string to append if not already present.
    """
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
    """Auto-detect VCS mode (`github` if origin is GitHub and `gh auth status` succeeds).

    Args:
        repo_root: Target git repository root path.
        runner: Subprocess runner callable (defaults to `common.run`).

    Returns:
        `"github"` when `origin` points to `github.com` and `gh auth status` exits 0;
        otherwise `"local_git"`.
    """
    # --- Step 1: Inspect the `origin` remote URL ---
    root = Path(os.path.realpath(repo_root))
    try:
        res_remote = runner(["git", "remote", "get-url", "origin"], cwd=root)
    except (OSError, subprocess.SubprocessError):
        return "local_git"

    if res_remote.returncode != 0 or "github.com" not in res_remote.stdout.lower():
        return "local_git"

    # --- Step 2: Verify GitHub CLI authentication status ---
    gh_bin = os.environ.get("PA_GH_BIN", "gh").strip() or "gh"
    try:
        res_gh = runner([gh_bin, "auth", "status"], cwd=root)
    except (OSError, subprocess.SubprocessError):
        return "local_git"

    if res_gh.returncode == 0:
        return "github"
    return "local_git"


def detect_memory_mode(repo_root: str | Path) -> Literal["external", "builtin"]:
    """Auto-detect memory mode (`external` if `repo-memory` is enrolled, else `builtin`).

    Args:
        repo_root: Target git repository root path.

    Returns:
        `"external"` if `.memory/`, `.agents/plugins.json`, or the global `repo-memory-daemon`
        registry indicates `repo-memory` enrollment; otherwise `"builtin"`.
    """
    real_root = os.path.realpath(str(repo_root))
    root = Path(real_root)

    # --- Step 1: Check for a direct `.memory` directory in the repository ---
    if (root / ".memory").exists():
        return "external"

    # --- Step 2: Check `<repo>/.agents/plugins.json` for a repo-memory entry ---
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

    # --- Step 3: Check the global repo-memory-daemon registry ---
    user_home = Path(os.path.realpath(Path.home()))
    rm_registry = (
        user_home
        / ".gemini"
        / "config"
        / "plugins"
        / "repo-memory-daemon"
        / "state"
        / "registry.json"
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
                    if (
                        isinstance(v, dict)
                        and "path" in v
                        and os.path.realpath(str(v["path"])) == real_root
                    ):
                        return "external"
            elif isinstance(rdata, list):
                for item in rdata:
                    candidate = item.get("path", "") if isinstance(item, dict) else str(item)
                    if candidate and os.path.realpath(str(candidate)) == real_root:
                        return "external"
        except (OSError, json.JSONDecodeError):
            pass

    return "builtin"


def _move_path_git_or_fs(
    repo_root: Path,
    src: Path,
    dst: Path,
    *,
    runner: common.Runner = common.run,
) -> None:
    """Move `src` to `dst`, preferring `git mv` when `src` is tracked by Git.

    Preserves Git rename history when migrating tracked `.agents/skills/` specifications into
    `.agents/plugins/principal-architect-workspace/`, while seamlessly falling back to
    `shutil.move` for untracked files or partial worktrees.

    Args:
        repo_root: Repository root `Path`.
        src: Source path inside `repo_root`.
        dst: Destination path inside `repo_root`.
        runner: Subprocess runner callable.
    """
    # --- Step 1: Ensure destination parent directory exists and compute repo-relative paths ---
    dst.parent.mkdir(parents=True, exist_ok=True)
    rel_src = src.relative_to(repo_root)
    rel_dst = dst.relative_to(repo_root)

    # --- Step 2: Use `git mv` if tracked in the index; otherwise fall back to filesystem move ---
    ls_res = runner(
        ["git", "ls-files", "--error-unmatch", str(rel_src)],
        cwd=repo_root,
    )
    if ls_res.returncode == 0:
        mv_res = runner(
            ["git", "mv", str(rel_src), str(rel_dst)],
            cwd=repo_root,
        )
        if mv_res.returncode != 0 or (src.exists() and not dst.exists()):
            shutil.move(str(src), str(dst))
    else:
        shutil.move(str(src), str(dst))


def _merge_legacy_into_new_workspace(
    repo_root: Path,
    legacy_ws: Path,
    new_ws: Path,
    *,
    runner: common.Runner = common.run,
) -> list[str]:
    """Move or merge `.agents/skills/principal-architect-workspace` into the new workspace path.

    Args:
        repo_root: Repository root `Path`.
        legacy_ws: Legacy `.agents/skills/principal-architect-workspace` directory `Path`.
        new_ws: Canonical `.agents/plugins/principal-architect-workspace` directory `Path`.
        runner: Subprocess runner callable.

    Returns:
        List of repository-relative POSIX paths moved during migration.
    """
    # --- Step 1: Fast-path whole-directory move when destination does not exist yet ---
    moved: list[str] = []
    if not legacy_ws.exists():
        return moved

    if not new_ws.exists():
        _move_path_git_or_fs(repo_root, legacy_ws, new_ws, runner=runner)
        moved.append(common.NEW_WORKSPACE_REL.as_posix())
        return moved

    # --- Step 2: Merge individual files and subdirectories into existing destination ---
    for item in sorted(legacy_ws.iterdir()):
        if item.name == ".state":
            shutil.rmtree(item, ignore_errors=True)
            continue
        dst_item = new_ws / item.name
        if not dst_item.exists():
            _move_path_git_or_fs(repo_root, item, dst_item, runner=runner)
            moved.append(dst_item.relative_to(repo_root).as_posix())
        elif item.is_dir() and dst_item.is_dir():
            for child in sorted(item.rglob("*")):
                if not child.is_file():
                    continue
                rel_c = child.relative_to(item)
                dst_c = dst_item / rel_c
                dst_c.parent.mkdir(parents=True, exist_ok=True)
                if dst_c.exists():
                    dst_c.unlink()
                _move_path_git_or_fs(repo_root, child, dst_c, runner=runner)
                moved.append(dst_c.relative_to(repo_root).as_posix())
            shutil.rmtree(item, ignore_errors=True)
        elif item.is_file():
            if dst_item.exists():
                dst_item.unlink()
            _move_path_git_or_fs(repo_root, item, dst_item, runner=runner)
            moved.append(dst_item.relative_to(repo_root).as_posix())

    shutil.rmtree(legacy_ws, ignore_errors=True)
    return moved


def _cleanup_legacy_skill_dir(
    repo_root: Path,
    *,
    runner: common.Runner = common.run,
) -> bool:
    """Remove legacy `.agents/skills/principal-architect` directory or submodule if present.

    Args:
        repo_root: Repository root `Path`.
        runner: Subprocess runner callable.

    Returns:
        `True` if the legacy skill path existed and was removed; `False` otherwise.
    """
    legacy_skill = repo_root / ".agents" / "skills" / "principal-architect"
    if not legacy_skill.exists() and not legacy_skill.is_symlink():
        return False

    try:
        runner(
            ["git", "rm", "-rf", ".agents/skills/principal-architect"],
            cwd=repo_root,
        )
    except (OSError, subprocess.SubprocessError):
        pass

    if legacy_skill.is_symlink() or legacy_skill.is_file():
        legacy_skill.unlink(missing_ok=True)
    elif legacy_skill.is_dir():
        shutil.rmtree(legacy_skill, ignore_errors=True)
    return True


def _rewrite_legacy_workspace_paths(new_ws: Path) -> int:
    """Rewrite stale `.agents/skills/principal-architect-workspace` references in `.md` files.

    Args:
        new_ws: Canonical `.agents/plugins/principal-architect-workspace` directory `Path`.

    Returns:
        Count of Markdown files updated and re-hashed.
    """
    if not new_ws.is_dir():
        return 0

    import schemas

    # --- Step 1: Scan workspace Markdown files and replace legacy path references ---
    old_str = common.LEGACY_WORKSPACE_REL.as_posix()
    new_str = common.NEW_WORKSPACE_REL.as_posix()
    updated = 0

    for md_file in sorted(new_ws.rglob("*.md")):
        if ".state" in md_file.parts or not md_file.is_file():
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if old_str not in text:
            continue

        new_text = text.replace(old_str, new_str)
        md_file.write_text(new_text, encoding="utf-8")

        # --- Step 2: Recompute charter_hash or spec_hash on locked specs ---
        try:
            if md_file.name == "PROJECT.md":
                pdoc = schemas.load_project(md_file)
                if pdoc.spec.charter.charter_hash:
                    pdoc.spec.charter.charter_hash = schemas.compute_charter_hash(
                        pdoc.spec.charter, pdoc.sections
                    )
                    md_file.write_text(
                        schemas.dump_document(pdoc.spec, pdoc.sections),
                        encoding="utf-8",
                    )
            elif md_file.name == "WORKORDER.md":
                wdoc = schemas.load_workorder(md_file)
                if wdoc.spec.spec_hash:
                    wdoc.spec.spec_hash = schemas.compute_spec_hash(
                        wdoc.spec, wdoc.sections
                    )
                    md_file.write_text(
                        schemas.dump_document(wdoc.spec, wdoc.sections),
                        encoding="utf-8",
                    )
        except Exception:  # noqa: BLE001, S110
            pass

        updated += 1
    return updated


def _bridge_repo_memory(
    repo_root: Path,
    new_ws: Path,
    *,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Register PA memory in `.agents/memory/config.json` and run `repo-memory` seed/index.

    Args:
        repo_root: Repository root `Path`.
        new_ws: Canonical `.agents/plugins/principal-architect-workspace` directory `Path`.
        runner: Subprocess runner callable.

    Returns:
        Dictionary summarizing `config_updated`, `commands_run`, and `seeded` status.
    """
    # --- Step 1: Update `doc_seeds` in `.agents/memory/config.json` ---
    config_updated = False
    rm_cfg_path = repo_root / ".agents" / "memory" / "config.json"
    new_mem_rel = f"{common.NEW_WORKSPACE_REL.as_posix()}/memory"
    old_mem_rel = f"{common.LEGACY_WORKSPACE_REL.as_posix()}/memory"

    if rm_cfg_path.is_file() and (new_ws / "memory").is_dir():
        try:
            cfg_data = json.loads(rm_cfg_path.read_text(encoding="utf-8"))
            if isinstance(cfg_data, dict):
                raw_seeds = cfg_data.get("doc_seeds")
                seeds = [str(s) for s in raw_seeds] if isinstance(raw_seeds, list) else []
                filtered = [s for s in seeds if s != old_mem_rel]
                if new_mem_rel not in filtered:
                    filtered.append(new_mem_rel)
                if filtered != seeds:
                    cfg_data["doc_seeds"] = filtered
                    rm_cfg_path.write_text(
                        json.dumps(cfg_data, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    config_updated = True
        except (OSError, json.JSONDecodeError):
            pass

    # --- Step 2: Execute `repo-memory seed`, `seed-docs`, and `index` if installed ---
    rm_bin = (
        os.environ.get("PA_REPO_MEMORY_BIN")
        or shutil.which("repo-memory")
        or str(Path.home() / ".local" / "bin" / "repo-memory")
    )
    commands_run: list[str] = []
    seeded = False

    if Path(rm_bin).is_file() or shutil.which(rm_bin) is not None:
        subcmds = ["seed", "seed-docs", "index"]
        for sub in subcmds:
            cmd = [rm_bin, sub, "--repo", str(repo_root)]
            try:
                res = runner(cmd, cwd=repo_root)
            except (OSError, subprocess.SubprocessError):
                continue
            if res.returncode == 0:
                commands_run.append(f"repo-memory {sub}")
                seeded = True

    return {
        "config_updated": config_updated,
        "commands_run": commands_run,
        "seeded": seeded,
    }


def _cmd_migrate(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Migrate legacy workspace paths, synchronize `state.db`, and bridge `repo-memory`.

    Args:
        args: Parsed CLI arguments (`path`, `cleanup_legacy_skill`, `seed_repo_memory`, `as_json`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `2` if target path or git repository is invalid).
    """
    import vcs_sync

    # --- Step 1: Validate target repository root ---
    raw_target = Path(args.path).expanduser()
    if not raw_target.exists():
        print(f"Error: Target path does not exist: {args.path}", file=sys.stderr)
        return 2

    repo_root = common.find_repo_root(raw_target, runner=runner)
    if repo_root is None:
        print(f"Error: Not inside a git repository: {args.path}", file=sys.stderr)
        return 2

    real_root = Path(os.path.realpath(repo_root))
    legacy_ws = real_root / common.LEGACY_WORKSPACE_REL
    new_ws = real_root / common.NEW_WORKSPACE_REL

    # --- Step 2: Merge legacy workspace files, clean up legacy skill, and rewrite paths ---
    moved_paths = _merge_legacy_into_new_workspace(real_root, legacy_ws, new_ws, runner=runner)
    removed_legacy_skill = False
    if getattr(args, "cleanup_legacy_skill", True):
        removed_legacy_skill = _cleanup_legacy_skill_dir(real_root, runner=runner)

    rewritten_files = _rewrite_legacy_workspace_paths(new_ws)

    # --- Step 3: Synchronize VCS state and optionally bridge repo-memory ---
    new_ws.mkdir(parents=True, exist_ok=True)
    (new_ws / ".state").mkdir(parents=True, exist_ok=True)
    bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
    sync_summary = bus.sync_state()

    should_seed_rm = getattr(args, "seed_repo_memory", None)
    if should_seed_rm is None:
        should_seed_rm = detect_memory_mode(real_root) == "external"

    rm_summary: dict[str, Any] = {
        "config_updated": False,
        "commands_run": [],
        "seeded": False,
    }
    if should_seed_rm:
        rm_summary = _bridge_repo_memory(real_root, new_ws, runner=runner)

    # --- Step 4: Format and emit migration summary ---
    result = {
        "repo_root": str(real_root),
        "workspace_dir": str(new_ws),
        "moved_paths": moved_paths,
        "removed_legacy_skill": removed_legacy_skill,
        "rewritten_markdown_files": rewritten_files,
        "sync": sync_summary,
        "repo_memory": rm_summary,
    }

    if getattr(args, "as_json", False):
        print(json.dumps(result, indent=2))
    else:
        cmds_joined = ", ".join(rm_summary["commands_run"]) or "skipped"
        print(
            f"Migrated repository: {real_root}\n"
            f"  workspace_dir:            {new_ws}\n"
            f"  moved_paths:              {len(moved_paths)}\n"
            f"  removed_legacy_skill:     {removed_legacy_skill}\n"
            f"  rewritten_markdown_files: {rewritten_files}\n"
            f"  synced_wos:               {sync_summary.get('synced_wos', 0)}\n"
            f"  synced_receipts:          {sync_summary.get('synced_receipts', 0)}\n"
            f"  synced_audits:            {sync_summary.get('synced_audits', 0)}\n"
            f"  repo_memory_seeded:       {rm_summary['seeded']} ({cmds_joined})"
        )
    return 0


def _cmd_enroll(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Execute the normative 9-step `pa enroll` sequence (SPEC §4.3, Charter §2.3).

    Args:
        args: Parsed CLI arguments for `pa enroll`.
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `2` on invalid path, failed `git init`, or migration conflict).
    """
    raw_target = Path(args.path).expanduser()
    if not raw_target.exists():
        print(f"Error: Target path does not exist: {args.path}", file=sys.stderr)
        return 2

    target = Path(os.path.realpath(raw_target))
    if target.is_file():
        target = target.parent

    # --- Step 1: Resolve git root or initialize a local git repository ---
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

    # --- Step 2: Check and perform legacy workspace migration (Charter R8) ---
    legacy_ws = repo_root / common.LEGACY_WORKSPACE_REL
    new_ws = repo_root / common.NEW_WORKSPACE_REL
    force_migrate = bool(getattr(args, "migrate", False))
    had_legacy = legacy_ws.exists()

    if legacy_ws.exists() and new_ws.exists() and not force_migrate:
        print(
            "Error: Cannot migrate workspace: both "
            f"{common.LEGACY_WORKSPACE_REL} and {common.NEW_WORKSPACE_REL} exist. "
            "Run `pa migrate` or pass `--migrate` to merge.",
            file=sys.stderr,
        )
        return 2

    if legacy_ws.exists():
        _merge_legacy_into_new_workspace(repo_root, legacy_ws, new_ws, runner=runner)

    if had_legacy or force_migrate:
        _cleanup_legacy_skill_dir(repo_root, runner=runner)
        _rewrite_legacy_workspace_paths(new_ws)

    # --- Step 3: Ensure workspace and .state directories exist and resolve memory_mode ---
    new_ws.mkdir(parents=True, exist_ok=True)
    state_dir = new_ws / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)

    with state_db.StateDB(state_dir / "state.db") as db:
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

        # --- Step 4: Resolve vcs_mode ---
        if args.vcs_mode in ("github", "local_git"):
            vcs_mode: Literal["github", "local_git"] = args.vcs_mode
        else:
            vcs_mode = detect_vcs_mode(repo_root, runner=runner)

        # --- Step 5: Write .state/pa-skills.json and .state/pa-worker-rules.json ---
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

        # --- Step 6: Persist configuration in StateDB ---
        req_exec = getattr(args, "execution_mode", None)
        existing_exec = db.get_config("execution_mode")
        if req_exec in ("monitored", "autonomous"):
            execution_mode = req_exec
        else:
            execution_mode = (
                existing_exec if existing_exec in ("monitored", "autonomous") else "monitored"
            )
        db.set_config("execution_mode", execution_mode)
        db.set_config("memory_mode", memory_mode)
        db.set_config("vcs_mode", vcs_mode)
        db.set_config("extra_skills_json", json.dumps(extra_skills))
        db.set_config("exclude_rules_json", json.dumps(exclude_rules))

        req_auto_approve = getattr(args, "auto_approve_pr_plans", None)
        if req_auto_approve is not None:
            db.set_config("auto_approve_pr_plans", "true" if req_auto_approve else "false")

    # --- Step 7: Write/merge <repo>/.agents/plugins.json and update .git/info/exclude ---
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

    # --- Step 8: Register repository in global Registry ---
    state_db.Registry().register(repo_root, workspace_dir=new_ws)

    if (had_legacy or force_migrate) and memory_mode == "external":
        _bridge_repo_memory(repo_root, new_ws, runner=runner)

    # --- Step 9: Print one-screen summary to stderr and exit 0 ---
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
    """Remove the workspace plugin entry and unregister the repository (Charter R9).

    Args:
        args: Parsed CLI arguments (`path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code `0`.
    """
    # --- Step 1: Resolve repository root and remove workspace-plugin from plugins.json ---
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

    # --- Step 2: Unregister repository from global Registry ---
    state_db.Registry().unregister(repo_root)
    print(f"Unenrolled repository: {repo_root}", file=sys.stderr)
    return 0


# Compiled regex parsing NUL-delimited `git log` records: `<sha>\x00<wo_id>\x00<verified_hash>`.
_GIT_LOG_TRAILER_RE = re.compile(
    r"([0-9a-fA-F]{7,40})\x00([^\x00]*)\x00([^\x00\r\n]*)"
)


def _scan_git_trailers(
    repo_root: Path,
    *,
    runner: common.Runner = common.run,
) -> dict[str, tuple[str, str | None]]:
    """Scan local Git commit trailers for `PA-WorkOrder` and `PA-Verified-Hash`.

    Args:
        repo_root: Target git repository root `Path`.
        runner: Subprocess runner callable.

    Returns:
        Mapping `wo_id -> (commit_sha, verified_hash)` for the latest matching commit.
    """
    # --- Step 1: Query git log using NUL-delimited trailer format ---
    # `git log --format` uses `%x00` (ASCII NUL) to separate the commit SHA, the extracted
    # `PA-WorkOrder` trailer value, and the `PA-Verified-Hash` trailer value within each
    # commit line (companion `vcs_sync` queries also use `%x1e` record separators when
    # full multi-line commit bodies are included). Because Git SHAs and trailer values
    # cannot contain NUL bytes, `_GIT_LOG_TRAILER_RE` can unambiguously extract all three
    # fields even when commits lack one or both trailers.
    fmt_arg = (
        "--format=%H%x00"
        "%(trailers:key=PA-WorkOrder,valueonly=true)%x00"
        "%(trailers:key=PA-Verified-Hash,valueonly=true)"
    )
    try:
        res = runner(["git", "log", fmt_arg], cwd=repo_root)
    except (OSError, subprocess.SubprocessError):
        return {}

    if res.returncode != 0 or not res.stdout:
        return {}

    # --- Step 2: Extract first-seen (most recent) trailer tuple per Work Order ID ---
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
    """Return a human-readable status glyph (used ONLY in non-JSON human output).

    Args:
        status: Lifecycle status string (e.g., `"COMPLETED"`, `"IN_PROGRESS"`, `"BLOCKED"`).

    Returns:
        Single-character/emoji glyph representing the status.
    """
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
    """Reconcile committed specs, Git trailers, and `state.db`; output human tree or `--json`.

    Args:
        args: Parsed CLI arguments (`path`, `as_json`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `2` if target path or git repository is invalid).
    """
    import schemas  # Lazy import per Charter R1

    # --- Step 1: Resolve repository root, StateDB config, and git trailers ---
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

    # --- Step 2: Load Programme and Pull Request specifications from workspace ---
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

        # --- Step 3: Reconcile each PR's Work Orders and Audit reports ---
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

    # --- Step 4: Emit JSON payload or formatted human status tree ---
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

    lines: list[str] = [
        f"Principal Architect Status — {repo_root.name}",
        f"Environment: vcs={vcs_mode} | memory={memory_mode} | mode={execution_mode}",
    ]
    if attention_queue:
        lines.append("\n🔔 Human Attention Needed:")
        for item in attention_queue:
            p_num = item.get("priority", 10)
            kind_str = item.get("kind", "info")
            title_str = item.get("title", "")
            lines.append(f"  - [P{p_num}] ({kind_str}) {title_str}")

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
                wo_line = (
                    f"      {wg} {wo['id']} [{wo['complexity']}]: "
                    f"{wo['title']} — {wo['status']}{sha_sfx}"
                )
                lines.append(wo_line)

    print("\n".join(lines))
    return 0


def _cli_plugin_version() -> str:
    """Resolve the semantic version string of the running `pa_cli.py` plugin bundle.

    Reads `workspace-plugin/principal-architect/plugin.json` adjacent to `_SCRIPTS_DIR`,
    falling back to `"0.1.0"` if the manifest file is absent or unreadable.

    Returns:
        Semantic version string from the workspace plugin manifest (e.g., `"0.1.0"`).
    """
    manifest = Path(_SCRIPTS_DIR).parent / "plugin.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version"):
                return str(data["version"]).strip()
        except (OSError, json.JSONDecodeError):
            pass
    return "0.1.0"


def _installed_daemon_version() -> str | None:
    """Read the semantic version string from the installed `pa-daemon/plugin.json` manifest.

    Returns:
        Semantic version string from `common.daemon_home() / "plugin.json"`, or `None`
        if the daemon plugin directory or manifest is not installed.
    """
    manifest = common.daemon_home() / "plugin.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version"):
                return str(data["version"]).strip()
        except (OSError, json.JSONDecodeError):
            pass
    return None


def _cmd_doctor(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Inspect CLI vs. installed daemon version drift, Python dependencies, and enrolled repos.

    Args:
        args: Parsed CLI arguments (`path`, `as_json`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` when no blocking errors are found, `1` if a critical check fails).
    """
    # --- Step 1: Compare running CLI bundle version against installed pa-daemon version ---
    cli_ver = _cli_plugin_version()
    daemon_dir = common.daemon_home()
    daemon_ver = _installed_daemon_version()
    warnings: list[str] = []
    errors: list[str] = []

    if daemon_ver is None:
        warnings.append(
            f"Global plugin manifest not found at {daemon_dir / 'plugin.json'}. "
            "Run `./scripts/install.sh` or extract `pa-daemon.zip`."
        )
    elif daemon_ver != cli_ver:
        warnings.append(
            f"Installed pa-daemon version ({daemon_ver}) does not match CLI version ({cli_ver}). "
            "Run `./scripts/install.sh` to refresh hooks, sidecar, and skills."
        )

    # --- Step 2: Verify Python runtime version and third-party schema dependencies ---
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if (sys.version_info.major, sys.version_info.minor) < (3, 11):
        errors.append(f"Python >= 3.11 is required (current: {py_ver}).")

    deps_status: dict[str, bool] = {"pydantic": False, "yaml": False}
    for mod_name in ("pydantic", "yaml"):
        try:
            importlib.import_module(mod_name)
            deps_status[mod_name] = True
        except ImportError:
            errors.append(
                f"Missing required Python package '{mod_name}'. "
                "Run `./scripts/dev-bootstrap.sh` or `pip install pydantic pyyaml`."
            )

    # --- Step 3: Inspect registry.json and target repository enrollment pointers ---
    registry_path = daemon_dir / "state" / "registry.json"
    enrolled_count = 0
    if registry_path.is_file():
        try:
            reg_data = json.loads(registry_path.read_text(encoding="utf-8"))
            if isinstance(reg_data, dict) and isinstance(reg_data.get("repos"), dict):
                enrolled_count = len(reg_data["repos"])
        except (OSError, json.JSONDecodeError):
            warnings.append(f"Could not parse {registry_path}.")

    raw_target = Path(getattr(args, "path", ".")).expanduser()
    repo_root = (
        common.find_repo_root(raw_target, runner=runner) if raw_target.exists() else None
    )
    repo_enrolled = False
    if repo_root is not None:
        repo_enrolled = common.is_repo_enrolled([repo_root])

    # --- Step 4: Emit structured JSON or human diagnostic report ---
    ok = len(errors) == 0
    payload: dict[str, Any] = {
        "ok": ok,
        "cli_version": cli_ver,
        "daemon_version": daemon_ver,
        "daemon_home": str(daemon_dir),
        "python_version": py_ver,
        "dependencies": deps_status,
        "enrolled_repos_count": enrolled_count,
        "current_repo_enrolled": repo_enrolled,
        "warnings": warnings,
        "errors": errors,
    }
    if getattr(args, "as_json", False):
        print(json.dumps(payload, indent=2))
        return 0 if ok else 1

    lines = [
        f"Principal Architect Doctor (CLI v{cli_ver})",
        f"  Daemon Home:     {daemon_dir} (version: {daemon_ver or 'not installed'})",
        f"  Python Runtime:  {py_ver} (pydantic={deps_status['pydantic']}, pyyaml={deps_status['yaml']})",
        f"  Enrolled Repos:  {enrolled_count}",
    ]
    for w in warnings:
        lines.append(f"  [WARN] {w}")
    for err in errors:
        lines.append(f"  [ERROR] {err}")
    if ok and not warnings:
        lines.append("  [OK] All installation and runtime checks passed.")
    print("\n".join(lines))
    return 0 if ok else 1


def _cmd_mode(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Get or set repository `execution_mode` (`monitored` | `autonomous`).

    Args:
        args: Parsed CLI arguments (`path`, `mode_value`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` on invalid mode string, `2` on invalid repo path).
    """
    # --- Step 1: Validate target repository and requested mode value ---
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

    # --- Step 2: Query or update execution_mode in StateDB ---
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
    """Parse dirty/untracked repo-relative POSIX paths from `git status --porcelain -uall`.

    Args:
        stdout: Raw stdout string produced by `git status --porcelain -uall`.

    Returns:
        Deduplicated list of repo-relative POSIX paths for modified, staged, or untracked files.
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
    """Return True if `rel_posix` is an ephemeral runtime file ignored by scope hygiene.

    Args:
        rel_posix: Repository-relative POSIX path string.

    Returns:
        `True` if the path is `.agents/plugins.json` or resides inside a `.state` directory.
    """
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
    """Return sorted existing repo-relative POSIX paths matching `allowed_files`.

    Args:
        real_root: Canonical repository root `Path`.
        allowed_files: Allowed path/glob patterns from `WORKORDER.md`.
        forbidden_files: Forbidden path/glob patterns from `WORKORDER.md`.
        matches_any_fn: Pattern-matching callable (`pre_tool_gate.matches_any_pattern`).

    Returns:
        Sorted list of existing repo-relative POSIX file paths within `allowed_files`.
    """
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
    """Verify Work Order scope hygiene, run `verification_command`, stamp receipt, and commit.

    Args:
        args: Parsed CLI arguments (`wo_id`, `path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on verified commit, `1` on verification failure, `2` on repo error).
    """
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

    # --- Step 1: Check spec_hash & git status --porcelain scope hygiene ---
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

    # --- Step 2: Execute verification_command ---
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

    # --- Step 3: Stamp cryptographic receipt in WORKORDER.md Part II and PROJECT.md ---
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

    # --- Step 4: Stage files, commit with PA trailers, and upsert StateDB receipt ---
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
        err_msg = commit_res.stderr.strip() or commit_res.stdout.strip()
        print(f"Error: git commit failed: {err_msg}", file=sys.stderr)
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

    short_sha = new_head_sha[:12] if new_head_sha else "HEAD"
    print(
        f"Verified and committed {wo_doc.spec.wo_id} ({short_sha})\n"
        f"  receipt_id: {receipt_id}\n"
        f"  tree_hash:  {t_hash}",
        file=sys.stderr,
    )
    return 0


def _cmd_wo_debug(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Transition a Work Order to `BLOCKED`, spawn/prepare `pa-debugger`, and record escalation.

    Args:
        args: Parsed CLI arguments (`wo_id`, `path`, `reason`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` if Work Order is missing/invalid, `2` on repo error).
    """
    import escalation
    import models
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

    wo_doc = pre_tool_gate._find_bound_workorder(ws_dir, None, wo_id_arg)
    if wo_doc is None or wo_doc.path is None:
        print(f"Error: Work Order '{wo_id_arg}' not found in {ws_dir}", file=sys.stderr)
        return 1

    if wo_doc.spec.status == schemas.WorkOrderStatus.COMPLETED:
        print(
            f"Error: Cannot debug {wo_doc.spec.wo_id}: Work Order is already COMPLETED.",
            file=sys.stderr,
        )
        return 1

    proj_md = wo_doc.path.parent.parent / "PROJECT.md"
    if proj_md.is_file():
        proj_check = schemas.load_project(proj_md)
        if proj_check.spec.status == schemas.PRState.GRADUATED:
            print(
                f"Error: Cannot debug {wo_doc.spec.wo_id}: parent PR {proj_check.spec.charter.pr_id} is already GRADUATED.",
                file=sys.stderr,
            )
            return 1

    # --- Step 1: Transition WORKORDER.md to BLOCKED and verify spec_hash ---
    wo_doc.spec.status = schemas.WorkOrderStatus.BLOCKED
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
    if proj_md.is_file():
        proj_doc = schemas.load_project(proj_md)
        updated_proj = False
        for row in proj_doc.spec.work_orders:
            if row.id.upper() == wo_doc.spec.wo_id.upper():
                row.status = schemas.WorkOrderStatus.BLOCKED
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

    # --- Step 2: Gather failure context (open escalations, completion summary, git status) ---
    db_file = ws_dir / ".state" / "state.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with state_db.StateDB(db_file) as db:
        open_escs = db.open_escalations(wo_id=wo_doc.spec.wo_id)

    comp_summary = (
        wo_doc.spec.completion.verification_summary.strip()
        if (wo_doc.spec.completion and wo_doc.spec.completion.verification_summary)
        else ""
    )
    reason_arg = str(getattr(args, "reason", None) or "").strip()
    reason_str = (
        reason_arg
        or comp_summary
        or f"Work Order {wo_doc.spec.wo_id} escalated to pa-debugger."
    )

    git_res = runner(["git", "status", "--short"], cwd=real_root)
    git_short = (
        git_res.stdout.strip()
        if (git_res.returncode == 0 and git_res.stdout.strip())
        else "(clean)"
    )

    wo_rel_posix = wo_doc.path.resolve().relative_to(real_root).as_posix()
    esc_lines = [
        f"- [{e.get('reason_code', 'ESC')}] {e.get('summary', '')}"
        for e in open_escs
    ] or ["- (no prior open escalations)"]

    bridge_prompt = (
        f"PA_ROLE: debugger\n"
        f"PR_ID: {wo_doc.spec.pr_id}\n"
        f"WO_ID: {wo_doc.spec.wo_id}\n\n"
        f"You are `pa-debugger` investigating blocked Work Order `{wo_doc.spec.wo_id}` "
        f"({wo_doc.spec.title}).\n\n"
        f"### Context\n"
        f"- **Work Order Spec:** `{wo_rel_posix}`\n"
        f"- **Allowed Files:** {', '.join(wo_doc.spec.allowed_files)}\n"
        f"- **Verification Command:** `{wo_doc.spec.verification_command}`\n"
        f"- **Failure Reason / Summary:** {reason_str}\n\n"
        f"### Open Escalations\n"
        + "\n".join(esc_lines)
        + f"\n\n### Git Status (`git status --short`)\n```text\n{git_short}\n```\n\n"
        f"### Instructions\n"
        f"1. Diagnose and fix the root cause within `allowed_files`.\n"
        f"2. Run `{wo_doc.spec.verification_command}` to confirm all checks pass.\n"
        f"3. Run `pa wo resolve {wo_doc.spec.wo_id} --summary \"<concise root cause and fix>\"`.\n"
    )

    # --- Step 3: Start (and JIT-pin) debugger conversation or fall back to bridge prompt ---
    ls_client = models.LanguageServerClient()
    ls_res = ls_client.start_conversation(
        title=f"🔬 [Debug {wo_doc.spec.wo_id}] {wo_doc.spec.title}",
        prompt=bridge_prompt,
        role="debugger",
        workspace_root=real_root,
        pin=True,
    )
    conv_id = str(ls_res["conversation_id"])

    # --- Step 4: Record debugger session and escalation in state.db ---
    with state_db.StateDB(db_file) as db:
        db.bind_session(
            conv_id,
            role="debugger",
            pr_id=wo_doc.spec.pr_id,
            wo_id=wo_doc.spec.wo_id,
            pinned=1 if ls_res.get("pinned") else 0,
        )
        esc_row = escalation.record_escalation(
            db,
            level="wo_to_pa",
            source_role="engineer",
            target_role="debugger",
            pr_id=wo_doc.spec.pr_id,
            wo_id=wo_doc.spec.wo_id,
            blocker_type="verification",
            reason_code="DEBUG_ESCALATION",
            summary=reason_str[:500],
            enqueue_if_needed=True,
            attention_kind="debugger_escalation",
            attention_title=f"🔬 [Debug {wo_doc.spec.wo_id}] {wo_doc.spec.title}",
            attention_priority=10,
        )

    out_payload = {
        "wo_id": wo_doc.spec.wo_id,
        "pr_id": wo_doc.spec.pr_id,
        "status": wo_doc.spec.status.value,
        "conversation_id": conv_id,
        "connected": bool(ls_res.get("connected")),
        "pinned": bool(ls_res.get("pinned")),
        "model": ls_res.get("model"),
        "escalation_id": esc_row["escalation_id"],
        "bridge_prompt": bridge_prompt,
    }
    print(json.dumps(out_payload, indent=2))
    return 0


def _cmd_wo_resolve(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Verify and resolve a blocked Work Order from `pa-debugger`, unpinning and notifying PA.

    Args:
        args: Parsed CLI arguments (`wo_id`, `summary`, `path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` on missing summary/verification failure, `2` on repo error).
    """
    import models
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
    summary_str = str(getattr(args, "summary", None) or "").strip()
    if not summary_str:
        print("Error: --summary is required for pa wo resolve", file=sys.stderr)
        return 1

    wo_doc = pre_tool_gate._find_bound_workorder(ws_dir, None, wo_id_arg)
    if wo_doc is None or wo_doc.path is None:
        print(f"Error: Work Order '{wo_id_arg}' not found in {ws_dir}", file=sys.stderr)
        return 1

    # --- Step 1: Execute verification_command ---
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

    # --- Step 2: Compute tree_hash and receipt_id ---
    t_hash = post_tool_receipt.compute_tree_hash(real_root, wo_doc.spec.allowed_files)
    receipt_id = f"rcpt_{t_hash[:12]}"
    head_res = runner(["git", "rev-parse", "HEAD"], cwd=real_root)
    head_sha = (
        head_res.stdout.strip()
        if head_res.returncode == 0 and head_res.stdout.strip()
        else None
    )

    files_modified = _collect_existing_allowed_files(
        real_root,
        wo_doc.spec.allowed_files,
        wo_doc.spec.forbidden_files,
        pre_tool_gate.matches_any_pattern,
    )

    # --- Step 3: Update WORKORDER.md and PROJECT.md to COMPLETED ---
    prev_comp = wo_doc.spec.completion
    existing_attempt_num = prev_comp.attempt_num if prev_comp is not None else 1
    prev_decisions = list(prev_comp.decisions_made) if prev_comp else []
    decisions_made = _dedup_preserve_order([*prev_decisions, summary_str])

    wo_doc.spec.status = schemas.WorkOrderStatus.COMPLETED
    wo_doc.spec.completion = schemas.CompletionReport(
        status=schemas.WorkOrderStatus.COMPLETED,
        attempt_num=existing_attempt_num,
        receipt_id=receipt_id,
        commit_sha=head_sha,
        files_modified=files_modified,
        verification_summary=summary_str[:280],
        out_of_scope_findings=list(prev_comp.out_of_scope_findings) if prev_comp else [],
        escalation_request=None,
        decisions_made=decisions_made,
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
    if proj_md.is_file():
        proj_doc = schemas.load_project(proj_md)
        updated_proj = False
        for row in proj_doc.spec.work_orders:
            if row.id.upper() == wo_doc.spec.wo_id.upper():
                row.status = schemas.WorkOrderStatus.COMPLETED
                row.attempts = max(row.attempts, existing_attempt_num)
                if head_sha:
                    row.commit_sha = head_sha
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

    # --- Step 4: Upsert receipt, resolve escalations/attention, unpin debugger, notify PA ---
    db_file = ws_dir / ".state" / "state.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    ls_client = models.LanguageServerClient()
    unpinned_sessions: list[str] = []
    notified_pa_sessions: list[str] = []

    with state_db.StateDB(db_file) as db:
        post_tool_receipt._upsert_receipt(
            db,
            wo_id=wo_doc.spec.wo_id,
            pr_id=wo_doc.spec.pr_id,
            cmd=wo_doc.spec.verification_command,
            exit_code=0,
            tree_hash=t_hash,
            git_head_sha=head_sha,
            valid=1,
            receipt_id=receipt_id,
        )

        for esc in db.open_escalations(wo_id=wo_doc.spec.wo_id):
            db.resolve_escalation(str(esc["escalation_id"]), status="RESOLVED")

        for item in db.list_open():
            if str(item.get("wo_id") or "").upper() == wo_doc.spec.wo_id.upper():
                db.dequeue(str(item["item_id"]), status="RESOLVED")

        cur_dbg = db.conn.execute(
            """
            SELECT conversation_id FROM sessions
            WHERE UPPER(wo_id) = UPPER(?)
              AND LOWER(role) IN ('debugger', 'pa-debugger')
            """,
            (wo_doc.spec.wo_id,),
        )
        for row_dbg in cur_dbg.fetchall():
            dbg_cid = str(row_dbg["conversation_id"])
            ls_client.set_pinned(dbg_cid, False)
            db.update_session(dbg_cid, pinned=0)
            unpinned_sessions.append(dbg_cid)

        cur_pa = db.conn.execute(
            """
            SELECT conversation_id FROM sessions
            WHERE UPPER(pr_id) = UPPER(?)
              AND LOWER(role) IN ('pa', 'pa-principal-architect', 'principal-architect')
            ORDER BY updated_at DESC
            """,
            (wo_doc.spec.pr_id,),
        )
        for row_pa in cur_pa.fetchall():
            pa_cid = str(row_pa["conversation_id"])
            ls_client.send_message(
                pa_cid,
                f"Work Order {wo_doc.spec.wo_id} resolved by pa-debugger: {summary_str}",
            )
            notified_pa_sessions.append(pa_cid)

    out_payload = {
        "wo_id": wo_doc.spec.wo_id,
        "pr_id": wo_doc.spec.pr_id,
        "status": wo_doc.spec.status.value,
        "receipt_id": receipt_id,
        "tree_hash": t_hash,
        "summary": summary_str,
        "unpinned_debugger_sessions": unpinned_sessions,
        "notified_pa_sessions": notified_pa_sessions,
    }
    print(json.dumps(out_payload, indent=2))
    print(
        f"Resolved {wo_doc.spec.wo_id} (receipt_id: {receipt_id})",
        file=sys.stderr,
    )
    return 0


def _is_pattern_within_allowed_modules(
    pattern: str,
    allowed_modules: Sequence[str],
    matches_any_fn: Any,
) -> bool:
    """Return True if Work Order `allowed_files` pattern falls within `charter.allowed_modules`.

    Args:
        pattern: Candidate `allowed_files` path or glob pattern from `WORKORDER.md`.
        allowed_modules: Allowed module prefixes/globs from `PROJECT.md` Part I Charter.
        matches_any_fn: Pattern-matching callable (`pre_tool_gate.matches_any_pattern`).

    Returns:
        `True` if `pattern` (or its directory base) matches at least one `allowed_modules` entry.
    """
    norm = pattern.strip().lstrip("./")
    if not norm:
        return False
    stripped_glob = re.sub(r"/\*+$", "", norm).rstrip("/")
    candidates = [norm, norm.rstrip("/")]
    if stripped_glob:
        candidates.append(stripped_glob)
    return any(matches_any_fn(cand, allowed_modules) for cand in candidates)


def _cmd_pr_approve_plan(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Validate `PROJECT.md` and `wo*/WORKORDER.md` specs, stamp `spec_hash`, and approve PR plan.

    Args:
        args: Parsed CLI arguments (`pr_id`, `path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on approval, `1` on validation/scope failure, `2` on invalid repo path).
    """
    import pre_tool_gate
    import schemas

    # --- Step 1: Locate and validate PROJECT.md and charter_hash ---
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

    # --- Step 2: Load all wo*/WORKORDER.md files and verify allowed_modules subset ---
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
                f"Error: Work Order '{row.id}' listed in PROJECT.md "
                f"has no matching WORKORDER.md in {pr_dir}",
                file=sys.stderr,
            )
            return 1

    # --- Step 3: Stamp spec_hash on each WORKORDER.md and set PROJECT.md status: APPROVED ---
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

    # --- Step 4: Resolve open plan_approval items in StateDB ---
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
    """Record an upward escalation in `state.db` (`escalations` and optional `attention_queue`).

    Args:
        args: Parsed CLI arguments for `pa escalate`.
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on recorded escalation, `1` on missing summary, `2` on invalid repo path).
    """
    import escalation

    # --- Step 1: Validate target repository and resolve escalation level and roles ---
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

    # --- Step 2: Persist escalation and optional attention_queue item in StateDB ---
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


def _resolve_repo_root_and_ws(
    path_str: str,
    *,
    runner: common.Runner = common.run,
) -> tuple[Path, Path] | int:
    """Resolve `(real_root, ws_dir)` from `path_str`, or print error and return exit code `2`.

    Args:
        path_str: Filesystem path string pointing inside the target git repository.
        runner: Subprocess runner callable.

    Returns:
        A 2-tuple `(real_root, ws_dir)` of `Path` objects, or integer `2` on error.
    """
    raw_target = Path(path_str or ".").expanduser()
    if not raw_target.exists():
        print(f"Error: Path does not exist: {path_str}", file=sys.stderr)
        return 2

    repo_root = common.find_repo_root(raw_target, runner=runner)
    if repo_root is None:
        print(f"Error: Not inside a git repository: {path_str}", file=sys.stderr)
        return 2

    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)
    return real_root, ws_dir


def _normalize_pr_id(raw_pr_id: str) -> str:
    """Normalize a PR ID like `'pr-01'` or `'PR-01A'` to `'PR-01'` / `'PR-01a'`.

    Args:
        raw_pr_id: Raw PR identifier or directory slug string.

    Returns:
        Canonical PR ID string (e.g., `"PR-01"` or `"PR-01a"`).
    """
    cleaned = raw_pr_id.strip()
    m = re.match(r"^pr-(\d+)([a-z]?)(?:-[a-z0-9-]+)?$", cleaned, re.IGNORECASE)
    if m:
        return f"PR-{m.group(1)}{m.group(2).lower()}"
    return cleaned.upper()


def _normalize_pr_slug(pr_id_canonical: str, raw_slug: str | None) -> str:
    """Normalize a PR slug so it matches `^pr-\\d+[a-z]?-[a-z0-9-]+$`.

    Args:
        pr_id_canonical: Canonical PR ID (e.g., `"PR-01"`).
        raw_slug: Optional user-supplied folder slug.

    Returns:
        Normalized folder slug prefixed with `pr-NN[a-z]-`.
    """
    pr_prefix = pr_id_canonical.lower()
    if raw_slug is not None and raw_slug.strip():
        s = re.sub(r"[^a-z0-9-]+", "-", raw_slug.strip().lower()).strip("-")
        if re.fullmatch(r"pr-\d+[a-z]?-[a-z0-9-]+", s):
            return s
        if s == pr_prefix:
            return f"{pr_prefix}-feature"
        if s.startswith(f"{pr_prefix}-"):
            return s
        return f"{pr_prefix}-{s}"
    return f"{pr_prefix}-feature"


def _cmd_sync(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Synchronize VCS commit trailers, audit reports, and specs into `.state/state.db`.

    Args:
        args: Parsed CLI arguments (`path`, `path_opt`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `2` on invalid repository path).
    """
    import vcs_sync

    target_path = getattr(args, "path_opt", None) or getattr(args, "path", None) or "."
    resolved = _resolve_repo_root_and_ws(str(target_path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, _ = resolved

    bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
    summary = bus.sync_state()
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_programme_init(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Scaffold `<ws_dir>/programme-<slug>/PROGRAM.md` and bind the Tier 1 Chief conversation.

    Args:
        args: Parsed CLI arguments (`slug`, `title`, `base_branch`, `path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` on invalid slug/title, `2` on invalid repo path).
    """
    import models
    import schemas

    # --- Step 1: Validate repository root, programme slug, and title ---
    resolved = _resolve_repo_root_and_ws(str(args.path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, ws_dir = resolved

    raw_slug = str(args.slug or "").strip().lower()
    clean_slug = re.sub(r"^(programme-|prog-)", "", raw_slug).strip("-")
    if not clean_slug or not re.fullmatch(r"[a-z0-9-]+", clean_slug):
        print(f"Error: Invalid programme slug: '{args.slug}'", file=sys.stderr)
        return 1

    title = str(args.title or "").strip()
    if not title:
        print("Error: --title is required for pa programme init", file=sys.stderr)
        return 1

    # --- Step 2: Scaffold or update `<ws_dir>/programme-<slug>/PROGRAM.md` ---
    base_branch = str(args.base_branch or "main").strip() or "main"
    programme_id = f"prog-{clean_slug}"
    prog_dir = ws_dir / f"programme-{clean_slug}"
    prog_dir.mkdir(parents=True, exist_ok=True)
    prog_md = prog_dir / "PROGRAM.md"

    if not prog_md.is_file():
        rendered = common.render_template_file(
            "PROGRAM.md.tpl",
            {
                "programme_id": programme_id,
                "title": title,
                "base_branch": base_branch,
            },
        )
        prog_md.write_text(rendered, encoding="utf-8")
        prog_doc = schemas.load_program(prog_md)
    else:
        prog_doc = schemas.load_program(prog_md)
        prog_doc.spec.title = title
        prog_doc.spec.base_branch = base_branch
        prog_md.write_text(
            schemas.dump_document(prog_doc.spec, prog_doc.sections),
            encoding="utf-8",
        )
        prog_doc = schemas.load_program(prog_md)

    # --- Step 3: Start and bind the Tier 1 Chief Architect conversation ---
    prog_rel = prog_md.resolve().relative_to(real_root).as_posix()
    chief_prompt = (
        f"PA_ROLE: chief\n"
        f"PROGRAMME_ID: {programme_id}\n\n"
        f"You are the Tier 1 Chief Architect for programme `{programme_id}` ({title}).\n"
        f"- Programme Spec: `{prog_rel}`\n"
        f"- Base Branch: `{base_branch}`\n"
    )
    ls_res = models.LanguageServerClient().start_conversation(
        title=f"🏛️ [Chief] {title}",
        prompt=chief_prompt,
        role="chief",
        workspace_root=real_root,
        pin=True,
    )

    db_file = ws_dir / ".state" / "state.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with state_db.StateDB(db_file) as db:
        db.bind_session(
            str(ls_res["conversation_id"]),
            role="chief",
            programme_id=programme_id,
            pinned=1 if ls_res.get("pinned") else 0,
        )

    out_payload = {
        "programme_id": programme_id,
        "program_md": str(prog_md),
        "conversation_id": ls_res["conversation_id"],
        "pinned": bool(ls_res.get("pinned")),
        "bridge_prompt": ls_res.get("bridge_prompt"),
    }
    print(json.dumps(out_payload, indent=2))
    return 0


def _scaffold_or_update_project_charter(
    ws_dir: Path,
    *,
    pr_id_raw: str,
    slug_arg: str | None = None,
    title_arg: str | None = None,
    branch_arg: str | None = None,
    base_branch_arg: str | None = None,
    allowed_modules_arg: Sequence[str] | None = None,
    verification_floor_arg: Sequence[str] | None = None,
    depends_on_arg: Sequence[str] | None = None,
    required_skills_arg: Sequence[str] | None = None,
    programme_id_arg: str | None = None,
) -> tuple[Path, Path, Any, str]:
    """Create or update `<ws_dir>/<slug>/PROJECT.md` Part I Charter and stamp `charter_hash`.

    Args:
        ws_dir: Active Principal Architect workspace directory `Path`.
        pr_id_raw: Raw Pull Request identifier (e.g., `"PR-01"` or `"pr-01"`).
        slug_arg: Optional PR folder slug override.
        title_arg: Optional PR title override.
        branch_arg: Optional PR head branch override.
        base_branch_arg: Optional PR base branch override.
        allowed_modules_arg: Optional sequence of allowed module path/glob strings.
        verification_floor_arg: Optional sequence of verification floor shell commands.
        depends_on_arg: Optional sequence of upstream PR IDs.
        required_skills_arg: Optional sequence of required skill names.
        programme_id_arg: Optional parent programme ID override.

    Returns:
        A 4-tuple `(pr_dir, proj_md, proj_doc, charter_hash)`.

    Raises:
        ValueError: If `pr_id_raw` does not match the canonical `PR-NN[a-z]` format.
        RuntimeError: If `charter_hash` verification fails after writing `PROJECT.md`.
    """
    import schemas
    import vcs_sync

    # --- Step 1: Normalize PR ID and resolve defaults from any existing PROJECT.md ---
    pr_id_canonical = _normalize_pr_id(pr_id_raw)
    if not re.fullmatch(r"^PR-\d+[a-z]?$", pr_id_canonical):
        raise ValueError(f"Invalid PR ID '{pr_id_raw}' (expected format 'PR-01')")

    existing_dir, existing_doc = vcs_sync._find_pr_dir_and_project(ws_dir, pr_id_canonical)
    if existing_doc is None and slug_arg:
        existing_dir, existing_doc = vcs_sync._find_pr_dir_and_project(ws_dir, slug_arg)

    if existing_doc is not None:
        slug = (
            _normalize_pr_slug(pr_id_canonical, slug_arg)
            if slug_arg
            else existing_doc.spec.charter.slug
        )
    else:
        slug = _normalize_pr_slug(pr_id_canonical, slug_arg)

    title = (
        title_arg.strip()
        if (title_arg and title_arg.strip())
        else (
            existing_doc.spec.charter.title
            if existing_doc is not None
            else f"Charter for {pr_id_canonical}"
        )
    )
    if len(title) < 5:
        title = f"{pr_id_canonical} — {title}"

    branch = (
        branch_arg.strip()
        if (branch_arg and branch_arg.strip())
        else (
            existing_doc.spec.charter.branch
            if existing_doc is not None
            else f"feat/{slug}"
        )
    )
    base_branch = (
        base_branch_arg.strip()
        if (base_branch_arg and base_branch_arg.strip())
        else (
            existing_doc.spec.charter.base_branch
            if existing_doc is not None
            else "main"
        )
    )
    allowed_modules = (
        _dedup_preserve_order(allowed_modules_arg)
        if allowed_modules_arg
        else (
            list(existing_doc.spec.charter.allowed_modules)
            if existing_doc is not None
            else ["src/"]
        )
    )
    verification_floor = (
        _dedup_preserve_order(verification_floor_arg)
        if verification_floor_arg
        else (
            list(existing_doc.spec.charter.verification_floor)
            if existing_doc is not None
            else ["pytest"]
        )
    )
    depends_on = (
        _dedup_preserve_order(depends_on_arg)
        if depends_on_arg is not None
        else (
            list(existing_doc.spec.charter.depends_on)
            if existing_doc is not None
            else []
        )
    )
    required_skills = (
        _dedup_preserve_order(required_skills_arg)
        if required_skills_arg is not None
        else (
            list(existing_doc.spec.charter.required_skills)
            if existing_doc is not None
            else []
        )
    )

    programme_id: str | None = None
    if programme_id_arg and programme_id_arg.strip():
        raw_prog = programme_id_arg.strip().lower()
        programme_id = raw_prog if raw_prog.startswith("prog-") else f"prog-{raw_prog}"
    elif existing_doc is not None and existing_doc.spec.charter.programme_id:
        programme_id = existing_doc.spec.charter.programme_id
    else:
        for cand_prog in sorted(ws_dir.glob("programme-*/PROGRAM.md")):
            try:
                pdoc = schemas.load_program(cand_prog)
                programme_id = pdoc.spec.programme_id
                break
            except Exception:  # noqa: BLE001, S112
                continue
        if programme_id is None:
            programme_id = "prog-default"

    # --- Step 2: Scaffold PROJECT.md from template if missing and lock Part I Charter ---
    pr_dir = (
        existing_dir
        if (existing_doc is not None and existing_dir.is_dir())
        else (ws_dir / slug)
    )
    pr_dir.mkdir(parents=True, exist_ok=True)
    proj_md = pr_dir / "PROJECT.md"

    if not proj_md.is_file():
        rendered = common.render_template_file(
            "PROJECT.md.tpl",
            {
                "pr_id": pr_id_canonical,
                "programme_id": programme_id,
                "slug": slug,
                "title": title,
                "branch": branch,
                "base_branch": base_branch,
                "allowed_module": allowed_modules[0],
                "verification_command": verification_floor[0],
            },
        )
        proj_md.write_text(rendered, encoding="utf-8")

    proj_doc = schemas.load_project(proj_md)
    ch = proj_doc.spec.charter
    ch.pr_id = pr_id_canonical
    ch.programme_id = programme_id
    ch.slug = slug
    ch.title = title
    ch.branch = branch
    ch.base_branch = base_branch
    ch.depends_on = depends_on
    ch.allowed_modules = allowed_modules
    ch.required_skills = required_skills
    ch.verification_floor = verification_floor
    ch.charter_locked = True

    c_hash = schemas.compute_charter_hash(proj_doc)
    ch.charter_hash = c_hash
    proj_md.write_text(
        schemas.dump_document(proj_doc.spec, proj_doc.sections),
        encoding="utf-8",
    )
    if not schemas.verify_charter_hash(proj_md):
        raise RuntimeError(f"Failed to verify stamped charter_hash on {proj_md}")

    # --- Step 3: Upsert corresponding PRNodeSpec in any matching PROGRAM.md ---
    for prog_md in sorted(ws_dir.glob("programme-*/PROGRAM.md")):
        try:
            prog_doc = schemas.load_program(prog_md)
        except Exception:  # noqa: BLE001, S112
            continue
        if (
            programme_id_arg
            and prog_doc.spec.programme_id.lower() != str(programme_id).lower()
        ):
            continue

        matched_node = None
        for node in prog_doc.spec.prs:
            if (
                node.id.upper() == pr_id_canonical.upper()
                or node.slug.lower() == slug.lower()
            ):
                matched_node = node
                break

        if matched_node is not None:
            matched_node.id = pr_id_canonical
            matched_node.slug = slug
            matched_node.title = title[:140]
            matched_node.branch = branch
            matched_node.base_branch = base_branch
            matched_node.depends_on = depends_on
            matched_node.allowed_modules = allowed_modules
            matched_node.required_skills = required_skills
        else:
            prog_doc.spec.prs.append(
                schemas.PRNodeSpec(
                    id=pr_id_canonical,
                    slug=slug,
                    title=title[:140],
                    branch=branch,
                    base_branch=base_branch,
                    depends_on=depends_on,
                    allowed_modules=allowed_modules,
                    required_skills=required_skills,
                    status=proj_doc.spec.status,
                    github_pr=proj_doc.spec.github_pr,
                )
            )
        prog_md.write_text(
            schemas.dump_document(prog_doc.spec, prog_doc.sections),
            encoding="utf-8",
        )

    return pr_dir, proj_md, proj_doc, c_hash


def _cmd_programme_charter(
    args: argparse.Namespace,
    *,
    runner: common.Runner = common.run,
) -> int:
    """Author or update Part I (`PR Charter`) of `PROJECT.md` and lock `charter_hash`.

    Args:
        args: Parsed CLI arguments for `pa programme charter`.
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` on charter/VCS error, `2` on invalid repo path).
    """
    import vcs_sync

    # --- Step 1: Scaffold or update PROJECT.md Part I Charter ---
    resolved = _resolve_repo_root_and_ws(str(args.path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, ws_dir = resolved

    try:
        _, proj_md, proj_doc, c_hash = _scaffold_or_update_project_charter(
            ws_dir,
            pr_id_raw=str(args.pr_id),
            slug_arg=args.slug,
            title_arg=args.title,
            branch_arg=args.branch,
            base_branch_arg=args.base_branch,
            allowed_modules_arg=args.allowed_module,
            verification_floor_arg=args.verification_command,
            depends_on_arg=args.depends_on,
            required_skills_arg=args.required_skill,
            programme_id_arg=args.programme_id,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # --- Step 2: Optionally checkout branch and open draft PR ---
    ch = proj_doc.spec.charter
    draft_res: dict[str, Any] | None = None
    if getattr(args, "open_draft", False):
        try:
            bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
            bus.create_or_checkout_branch(ch.branch, ch.base_branch)
            draft_res = bus.open_or_sync_pr(ch.pr_id, draft=True)
        except (ValueError, RuntimeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    out_payload: dict[str, Any] = {
        "pr_id": ch.pr_id,
        "slug": ch.slug,
        "project_md": str(proj_md),
        "charter_hash": c_hash,
        "charter_locked": True,
    }
    if draft_res is not None:
        out_payload["draft_pr"] = draft_res
    print(json.dumps(out_payload, indent=2))
    return 0


def _cmd_pr_start(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Create/checkout stacked PR branch, verify `PROJECT.md`, and start/pin Tier 2 PA session.

    Args:
        args: Parsed CLI arguments for `pa pr start`.
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` on charter/branch error, `2` on invalid repo path).
    """
    import models
    import schemas
    import vcs_sync

    # --- Step 1: Locate or scaffold PROJECT.md and verify charter_hash ---
    resolved = _resolve_repo_root_and_ws(str(args.path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, ws_dir = resolved

    pr_id_canonical = _normalize_pr_id(str(args.pr_id))
    pr_dir, proj_doc = vcs_sync._find_pr_dir_and_project(ws_dir, str(args.pr_id))

    if proj_doc is None:
        if args.title or args.slug or args.allowed_module or args.branch:
            try:
                pr_dir, _, proj_doc, _ = _scaffold_or_update_project_charter(
                    ws_dir,
                    pr_id_raw=str(args.pr_id),
                    slug_arg=args.slug,
                    title_arg=args.title,
                    branch_arg=args.branch,
                    base_branch_arg=args.base_branch,
                    allowed_modules_arg=args.allowed_module,
                    verification_floor_arg=args.verification_command,
                )
            except (ValueError, RuntimeError) as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
        else:
            print(
                f"Error: PROJECT.md for '{args.pr_id}' not found in {ws_dir} "
                f"(pass --title to scaffold a standalone PR).",
                file=sys.stderr,
            )
            return 1
    elif (
        args.title
        or args.branch
        or args.base_branch
        or args.allowed_module
        or args.verification_command
    ):
        try:
            pr_dir, _, proj_doc, _ = _scaffold_or_update_project_charter(
                ws_dir,
                pr_id_raw=proj_doc.spec.charter.pr_id,
                slug_arg=args.slug or proj_doc.spec.charter.slug,
                title_arg=args.title,
                branch_arg=args.branch,
                base_branch_arg=args.base_branch,
                allowed_modules_arg=args.allowed_module,
                verification_floor_arg=args.verification_command,
            )
        except (ValueError, RuntimeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    proj_md = pr_dir / "PROJECT.md"
    if proj_doc.spec.charter.charter_locked and not schemas.verify_charter_hash(proj_md):
        print(
            f"Error: PROJECT.md Part I charter_hash verification failed "
            f"for {proj_doc.spec.charter.pr_id}.",
            file=sys.stderr,
        )
        return 1

    # --- Step 2: Create or checkout the stacked PR branch ---
    ch = proj_doc.spec.charter
    pr_id_canonical = ch.pr_id
    bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
    try:
        head_sha = bus.create_or_checkout_branch(ch.branch, ch.base_branch)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # --- Step 3: Start (and JIT-pin) Tier 2 Principal Architect session ---
    proj_rel = proj_md.resolve().relative_to(real_root).as_posix()
    pa_prompt = (
        f"PA_ROLE: pa\n"
        f"PR_ID: {pr_id_canonical}\n\n"
        f"You are the Tier 2 Principal Architect for `{pr_id_canonical}` ({ch.title}).\n"
        f"- Project Spec: `{proj_rel}`\n"
        f"- Branch: `{ch.branch}` (base: `{ch.base_branch}`)\n"
        f"- Allowed Modules: {', '.join(ch.allowed_modules)}\n"
    )
    ls_res = models.LanguageServerClient().start_conversation(
        title=f"📐 [{pr_id_canonical}] {ch.title}",
        prompt=pa_prompt,
        role="pa",
        workspace_root=real_root,
        pin=True,
    )

    db_file = ws_dir / ".state" / "state.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with state_db.StateDB(db_file) as db:
        db.bind_session(
            str(ls_res["conversation_id"]),
            role="pa",
            programme_id=ch.programme_id,
            pr_id=pr_id_canonical,
            pinned=1 if ls_res.get("pinned") else 0,
        )

    out_payload = {
        "pr_id": pr_id_canonical,
        "branch": ch.branch,
        "base_branch": ch.base_branch,
        "head_sha": head_sha,
        "conversation_id": ls_res["conversation_id"],
        "pinned": bool(ls_res.get("pinned")),
        "bridge_prompt": ls_res["bridge_prompt"],
    }
    print(json.dumps(out_payload, indent=2))
    return 0


def _cmd_pr_claim(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int:
    """Sync state, checkout PR branch, and output Tier 2 PA continuation prompt.

    Args:
        args: Parsed CLI arguments (`pr_id`, `path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` if PR not found or checkout fails, `2` on repo error).
    """
    import schemas
    import vcs_sync

    # --- Step 1: Sync VCS state and locate PROJECT.md ---
    resolved = _resolve_repo_root_and_ws(str(args.path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, ws_dir = resolved

    bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
    sync_res = bus.sync_state()

    pr_dir, proj_doc = vcs_sync._find_pr_dir_and_project(ws_dir, str(args.pr_id))
    if proj_doc is None:
        print(f"Error: PROJECT.md for '{args.pr_id}' not found in {ws_dir}", file=sys.stderr)
        return 1

    # --- Step 2: Checkout PR branch, re-sync trailers, and build continuation prompt ---
    ch = proj_doc.spec.charter
    try:
        bus.create_or_checkout_branch(ch.branch, ch.base_branch)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    sync_res = bus.sync_state()
    proj_md = pr_dir / "PROJECT.md"
    proj_doc = schemas.load_project(proj_md)
    ch = proj_doc.spec.charter
    pr_id_canonical = ch.pr_id

    completed_wos = [
        row.id
        for row in proj_doc.spec.work_orders
        if row.status == schemas.WorkOrderStatus.COMPLETED
    ]
    pending_wos = [
        row.id
        for row in proj_doc.spec.work_orders
        if row.status != schemas.WorkOrderStatus.COMPLETED
    ]
    prompt = (
        f"PA_ROLE: pa\n"
        f"PR_ID: {pr_id_canonical}\n\n"
        f"Resuming Principal Architect session for `{pr_id_canonical}` ({ch.title}) "
        f"on branch `{ch.branch}`.\n"
        f"- Completed Work Orders: {', '.join(completed_wos) if completed_wos else 'none'}\n"
        f"- Remaining Work Orders: {', '.join(pending_wos) if pending_wos else 'none'}\n"
    )
    out_payload = {
        "pr_id": pr_id_canonical,
        "branch": ch.branch,
        "completed_wos": completed_wos,
        "pending_wos": pending_wos,
        "continuation_prompt": prompt,
        "sync": sync_res,
    }
    print(json.dumps(out_payload, indent=2))
    return 0


def _cmd_pr_open_or_sync(
    args: argparse.Namespace,
    *,
    runner: common.Runner = common.run,
) -> int:
    """Transition `<pr_id>` to `STAGED_FOR_AUDIT` and open/update GitHub PR in `github` mode.

    Args:
        args: Parsed CLI arguments (`pr_id`, `draft`, `path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` on missing receipts/PR error, `2` on repo error).
    """
    import vcs_sync

    resolved = _resolve_repo_root_and_ws(str(args.path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, _ = resolved

    bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
    try:
        res = bus.open_or_sync_pr(str(args.pr_id), draft=bool(args.draft))
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(res, indent=2))
    return 0


def _cmd_pr_post_audit(
    args: argparse.Namespace,
    *,
    runner: common.Runner = common.run,
) -> int:
    """Validate and record `<audit.md>` into `AUDIT-round-<K>.md` and optional GitHub review.

    Args:
        args: Parsed CLI arguments (`pr_id`, `file`, `no_commit`, `path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` on validation or VCS failure, `2` on repo error).
    """
    import vcs_sync

    resolved = _resolve_repo_root_and_ws(str(args.path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, _ = resolved

    if not args.file:
        print("Error: --file is required for pa pr post-audit", file=sys.stderr)
        return 1

    audit_file = Path(str(args.file)).expanduser()
    bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
    try:
        res = bus.post_audit(
            str(args.pr_id),
            audit_file,
            commit=not bool(getattr(args, "no_commit", False)),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(res, indent=2))
    return 0


def _cmd_pr_sync_audit(
    args: argparse.Namespace,
    *,
    runner: common.Runner = common.run,
) -> int:
    """Sync the latest Cold-Firewall `AuditReport` for `<pr_id>` into `.state/state.db`.

    Args:
        args: Parsed CLI arguments (`pr_id`, `path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` when an audit report is synced, `1` if missing/error, `2` on repo error).
    """
    import vcs_sync

    resolved = _resolve_repo_root_and_ws(str(args.path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, _ = resolved

    bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
    try:
        res = bus.sync_audit(str(args.pr_id))
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if res is None:
        print(
            f"Error: No Cold-Firewall Audit report found for '{args.pr_id}'.",
            file=sys.stderr,
        )
        return 1

    print(json.dumps(res, indent=2))
    return 0


def _sha_matches(sha_a: str, sha_b: str) -> bool:
    """Return True if two Git commit SHAs match (supporting >=7-char short SHA prefixes).

    Args:
        sha_a: First hex commit SHA string.
        sha_b: Second hex commit SHA string.

    Returns:
        `True` if both SHAs are at least 7 characters and one is a prefix of the other.
    """
    a = sha_a.strip().lower()
    b = sha_b.strip().lower()
    if len(a) < 7 or len(b) < 7:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def _head_matches_audited_sha(
    real_root: Path,
    pr_dir: Path,
    current_head_sha: str,
    audited_sha: str,
    *,
    runner: common.Runner,
) -> bool:
    """Verify `audited_sha` matches `current_head_sha` (or `HEAD~1` when `HEAD` is audit commit).

    In `local_git` mode (and default `pa pr post-audit` runs), recording the Cold-Firewall
    `AuditReport` creates a new commit on top of the very `HEAD` SHA (`audited_sha`) that the
    auditor evaluated. To prevent that audit-recording commit from invalidating its own
    `head_sha` match during `pa pr graduate` (Rule R6), this function accepts `HEAD~1 ==
    audited_sha` if and only if the diff between `HEAD~1` and `HEAD` touches exclusively
    `AUDIT-round-<K>.md` and/or `PROJECT.md` inside `pr_dir`.

    Args:
        real_root: Canonical repository root `Path`.
        pr_dir: Pull Request workspace directory `Path`.
        current_head_sha: Current `git rev-parse HEAD` commit SHA.
        audited_sha: `head_sha` recorded inside the latest `AuditReport`.
        runner: Subprocess runner callable.

    Returns:
        `True` if `current_head_sha` matches `audited_sha` directly or via an audit-only commit.
    """
    # --- Step 1: Check direct SHA match against current HEAD ---
    if _sha_matches(current_head_sha, audited_sha):
        return True

    # --- Step 2: Check if HEAD~1 matches audited_sha and HEAD only touched audit/project docs ---
    parent_res = runner(["git", "rev-parse", "HEAD~1"], cwd=real_root)
    if parent_res.returncode != 0 or not parent_res.stdout.strip():
        return False

    parent_sha = parent_res.stdout.strip()
    if not _sha_matches(parent_sha, audited_sha):
        return False

    diff_res = runner(
        ["git", "diff", "--name-only", parent_sha, current_head_sha],
        cwd=real_root,
    )
    if diff_res.returncode != 0:
        return False

    changed_files = [ln.strip() for ln in diff_res.stdout.splitlines() if ln.strip()]
    if not changed_files:
        return True

    pr_dir_rel = pr_dir.resolve().relative_to(real_root).as_posix()
    allowed_audit_re = re.compile(rf"^{re.escape(pr_dir_rel)}/AUDIT-round-\d+\.md$")
    proj_rel = f"{pr_dir_rel}/PROJECT.md"
    return all(cf == proj_rel or bool(allowed_audit_re.match(cf)) for cf in changed_files)


def _cmd_pr_graduate(
    args: argparse.Namespace,
    *,
    runner: common.Runner = common.run,
) -> int:
    """Verify Rule R6 (`APPROVED` audit on current `HEAD` + `verification_floor`) and graduate PR.

    Args:
        args: Parsed CLI arguments (`pr_id`, `skip_floor`, `completed_date`, `path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on graduation, `1` on audit/floor gate failure, `2` on repo error).
    """
    import memory_grad
    import models
    import vcs_sync

    # --- Step 1: Resolve PR specification and verify APPROVED Cold-Firewall Audit on HEAD ---
    resolved = _resolve_repo_root_and_ws(str(args.path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, ws_dir = resolved

    pr_dir, proj_doc = vcs_sync._find_pr_dir_and_project(ws_dir, str(args.pr_id))
    if proj_doc is None:
        print(f"Error: PROJECT.md for '{args.pr_id}' not found in {ws_dir}", file=sys.stderr)
        return 1

    pr_id_canonical = proj_doc.spec.charter.pr_id
    proj_md = pr_dir / "PROJECT.md"

    head_res = runner(["git", "rev-parse", "HEAD"], cwd=real_root)
    if head_res.returncode != 0 or not head_res.stdout.strip():
        print("Error: Failed to resolve current git HEAD.", file=sys.stderr)
        return 1
    current_head_sha = head_res.stdout.strip()

    bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
    audit_meta = bus.sync_audit(pr_id_canonical)
    audited_sha = str((audit_meta or {}).get("head_sha") or "").strip()

    if (
        audit_meta is None
        or str(audit_meta.get("verdict") or "").upper() != "APPROVED"
        or not _head_matches_audited_sha(
            real_root,
            pr_dir,
            current_head_sha,
            audited_sha,
            runner=runner,
        )
    ):
        print(
            f"Error: Cannot graduate {pr_id_canonical}: current HEAD ({current_head_sha}) "
            f"lacks an APPROVED Cold-Firewall Audit verdict.",
            file=sys.stderr,
        )
        return 1

    # --- Step 2: Execute charter.verification_floor commands unless --skip-floor ---
    if not getattr(args, "skip_floor", False):
        for floor_cmd in proj_doc.spec.charter.verification_floor:
            cmd_str = str(floor_cmd).strip()
            if not cmd_str:
                continue
            v_res = runner(["/bin/sh", "-c", cmd_str], cwd=real_root, timeout=300.0)
            if v_res.returncode != 0:
                if v_res.stdout:
                    print(
                        v_res.stdout,
                        file=sys.stderr,
                        end="" if v_res.stdout.endswith("\n") else "\n",
                    )
                if v_res.stderr:
                    print(
                        v_res.stderr,
                        file=sys.stderr,
                        end="" if v_res.stderr.endswith("\n") else "\n",
                    )
                print(
                    f"Error: Cannot graduate {pr_id_canonical}: verification_floor command "
                    f"'{cmd_str}' failed with exit code {v_res.returncode}.",
                    file=sys.stderr,
                )
                return 1

    # --- Step 3: Graduate PR memory and update PROJECT.md / PROGRAM.md ---
    grad_res = memory_grad.graduate(
        real_root,
        pr_id_canonical,
        completed_date=getattr(args, "completed_date", None),
    )

    # --- Step 4: Unpin PA session, notify Chief session, and commit graduated artifacts ---
    db_file = ws_dir / ".state" / "state.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    ls_client = models.LanguageServerClient()
    unpinned_pa: list[str] = []
    notified_chief: list[str] = []

    with state_db.StateDB(db_file) as db:
        cur_pa = db.conn.execute(
            """
            SELECT conversation_id FROM sessions
            WHERE UPPER(pr_id) = UPPER(?)
              AND LOWER(role) IN ('pa', 'pa-principal-architect', 'principal-architect')
            """,
            (pr_id_canonical,),
        )
        for row_pa in cur_pa.fetchall():
            pa_cid = str(row_pa["conversation_id"])
            ls_client.set_pinned(pa_cid, False)
            db.update_session(pa_cid, pinned=0)
            unpinned_pa.append(pa_cid)

        cur_chief = db.conn.execute(
            """
            SELECT conversation_id FROM sessions
            WHERE LOWER(role) IN ('chief', 'pa-chief-architect', 'chief-architect')
            ORDER BY updated_at DESC
            """
        )
        for row_chief in cur_chief.fetchall():
            chief_cid = str(row_chief["conversation_id"])
            ls_client.send_message(
                chief_cid,
                f"PR {pr_id_canonical} graduated ({grad_res['memory_mode']} mode).",
            )
            notified_chief.append(chief_cid)

        for item in db.list_open(pr_id=pr_id_canonical):
            db.dequeue(str(item["item_id"]), status="RESOLVED")

    paths_to_stage: list[str] = [proj_md.resolve().relative_to(real_root).as_posix()]
    for prog_md in sorted(ws_dir.glob("programme-*/PROGRAM.md")):
        if prog_md.is_file():
            paths_to_stage.append(prog_md.resolve().relative_to(real_root).as_posix())
    for mf in grad_res.get("memory_files_touched", []):
        mf_path = Path(str(mf))
        if mf_path.is_file():
            paths_to_stage.append(mf_path.resolve().relative_to(real_root).as_posix())

    paths_to_stage = _dedup_preserve_order(paths_to_stage)
    if paths_to_stage:
        add_res = runner(["git", "add", "--", *paths_to_stage], cwd=real_root)
        if add_res.returncode == 0:
            vcs_sync._git_commit_with_fallback(
                real_root,
                f"chore({pr_id_canonical.lower()}): graduate {pr_id_canonical}",
                runner=runner,
            )

    post_head = runner(["git", "rev-parse", "HEAD"], cwd=real_root)
    grad_res["commit_sha"] = (
        post_head.stdout.strip()
        if post_head.returncode == 0 and post_head.stdout.strip()
        else current_head_sha
    )
    grad_res["unpinned_pa_sessions"] = unpinned_pa
    grad_res["notified_chief_sessions"] = notified_chief

    print(json.dumps(grad_res, indent=2))
    return 0


def _cmd_pr_restack(
    args: argparse.Namespace,
    *,
    runner: common.Runner = common.run,
) -> int:
    """Rebase stacked PR branches (`git rebase --update-refs`) and retarget GitHub PR bases.

    Args:
        args: Parsed CLI arguments (`pr_id`, `pr_id_pos`, `onto`, `path`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` on rebase/VCS failure, `2` on repo error).
    """
    import vcs_sync

    resolved = _resolve_repo_root_and_ws(str(args.path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, _ = resolved

    pr_id_val = getattr(args, "pr_id", None) or getattr(args, "pr_id_pos", None)
    bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
    try:
        res = bus.restack_branches(pr_id=pr_id_val, onto_branch=args.onto)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(res, indent=2))
    return 0


def _cmd_issue_create(
    args: argparse.Namespace,
    *,
    runner: common.Runner = common.run,
) -> int:
    """Record a deferred out-of-scope finding in `DEFERRED_BACKLOG.md` or GitHub Issues.

    Args:
        args: Parsed CLI arguments (`title`, `summary`, `pr_id`, `wo_id`, `file_path`, `label`).
        runner: Subprocess runner callable.

    Returns:
        Exit code (`0` on success, `1` on missing title or VCS failure, `2` on repo error).
    """
    import vcs_sync

    resolved = _resolve_repo_root_and_ws(str(args.path), runner=runner)
    if isinstance(resolved, int):
        return resolved
    real_root, _ = resolved

    title = str(args.title or "").strip()
    if not title:
        print("Error: --title is required for pa issue create", file=sys.stderr)
        return 1

    bus = vcs_sync.get_vcs_bus(real_root, runner=runner)
    try:
        res = bus.create_deferred_issue(
            title=title,
            summary=str(args.summary or ""),
            pr_id=args.pr_id,
            wo_id=args.wo_id,
            labels=args.label or ("pa:deferred",),
            file_path=args.file_path,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(res, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the root `pa` ArgumentParser and register all `COMMAND_MODULES`.

    Returns:
        Configured `argparse.ArgumentParser` instance for the `pa` CLI.
    """
    parser = argparse.ArgumentParser(
        prog="pa",
        description="Principal Architect Plugin CLI control plane.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pa {_cli_plugin_version()}",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # --- Step 1: Register repository enrollment and migration commands ---
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
    p_enroll.add_argument(
        "--execution-mode",
        choices=["monitored", "autonomous"],
        default=None,
        help="Execution mode to configure ('monitored' or 'autonomous').",
    )
    p_enroll.add_argument(
        "--auto-approve-pr-plans",
        dest="auto_approve_pr_plans",
        action="store_true",
        default=None,
        help="Automatically approve valid PR Work Order plans in autonomous mode.",
    )
    p_enroll.add_argument(
        "--no-auto-approve-pr-plans",
        dest="auto_approve_pr_plans",
        action="store_false",
        help="Require human approval for PR Work Order plans even in autonomous mode.",
    )
    p_enroll.add_argument(
        "--migrate",
        action="store_true",
        help=(
            "Merge/migrate legacy .agents/skills/principal-architect-workspace, "
            "rewrite stale paths, clean up legacy skill, and seed repo-memory."
        ),
    )
    p_enroll.set_defaults(_handler=_cmd_enroll)

    p_migrate = subparsers.add_parser(
        "migrate",
        help=(
            "Migrate legacy .agents/skills/principal-architect-workspace, "
            "sync state.db, and bridge repo-memory."
        ),
    )
    p_migrate.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_migrate.add_argument(
        "--seed-repo-memory",
        dest="seed_repo_memory",
        action="store_true",
        default=None,
        help="Force seeding repo-memory from PA WORKORDER.md and memory/ files.",
    )
    p_migrate.add_argument(
        "--no-seed-repo-memory",
        dest="seed_repo_memory",
        action="store_false",
        help="Skip seeding repo-memory during migration.",
    )
    p_migrate.add_argument(
        "--no-cleanup-legacy-skill",
        dest="cleanup_legacy_skill",
        action="store_false",
        default=True,
        help="Do not remove .agents/skills/principal-architect directory/submodule.",
    )
    p_migrate.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON migration summary to stdout.",
    )
    p_migrate.set_defaults(_handler=_cmd_migrate)

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

    # --- Step 2: Register workspace inspection and mode commands (status, sync, mode) ---
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

    p_doctor = subparsers.add_parser(
        "doctor",
        help="Check CLI vs. installed daemon version drift, Python dependencies, and repo health.",
    )
    p_doctor.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_doctor.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON diagnostics to stdout.",
    )
    p_doctor.set_defaults(_handler=_cmd_doctor)

    p_sync = subparsers.add_parser(
        "sync",
        help="Synchronize VCS commit trailers, audit reports, and specs into .state/state.db.",
    )
    p_sync.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_sync.add_argument(
        "--path",
        dest="path_opt",
        default=None,
        help="Path to the target repository.",
    )
    p_sync.set_defaults(_handler=_cmd_sync)

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

    # --- Step 3: Register Tier 1 Programme subcommands (programme init, charter) ---
    p_programme = subparsers.add_parser(
        "programme",
        help="Programme lifecycle commands (init, charter).",
    )
    prog_subparsers = p_programme.add_subparsers(
        dest="programme_command",
        metavar="<subcommand>",
    )

    p_prog_init = prog_subparsers.add_parser(
        "init",
        help="Scaffold programme-<slug>/PROGRAM.md and bind Tier 1 Chief Architect session.",
    )
    p_prog_init.add_argument(
        "slug",
        help="Programme slug (e.g., alpha or prog-alpha).",
    )
    p_prog_init.add_argument(
        "--title",
        required=True,
        help="Human-readable programme title.",
    )
    p_prog_init.add_argument(
        "--base-branch",
        default="main",
        help="Base branch for the programme (default: main).",
    )
    p_prog_init.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_prog_init.set_defaults(_handler=_cmd_programme_init)

    p_prog_charter = prog_subparsers.add_parser(
        "charter",
        help="Author or update Part I (PR Charter) of PROJECT.md and lock charter_hash.",
    )
    p_prog_charter.add_argument(
        "pr_id",
        help="Pull Request ID (e.g., PR-01).",
    )
    p_prog_charter.add_argument(
        "--slug",
        default=None,
        help="PR folder slug (e.g., pr-01-alpha).",
    )
    p_prog_charter.add_argument(
        "--title",
        default=None,
        help="PR title.",
    )
    p_prog_charter.add_argument(
        "--branch",
        default=None,
        help="PR head branch (default: feat/<slug>).",
    )
    p_prog_charter.add_argument(
        "--base-branch",
        default=None,
        help="PR base branch (default: main).",
    )
    p_prog_charter.add_argument(
        "--allowed-module",
        action="append",
        default=None,
        metavar="MODULE",
        help="Allowed module path or glob (repeatable).",
    )
    p_prog_charter.add_argument(
        "--verification-command",
        action="append",
        default=None,
        metavar="CMD",
        help="Verification floor command (repeatable).",
    )
    p_prog_charter.add_argument(
        "--depends-on",
        action="append",
        default=None,
        metavar="PR_ID",
        help="Upstream PR dependency (repeatable).",
    )
    p_prog_charter.add_argument(
        "--required-skill",
        action="append",
        default=None,
        metavar="SKILL",
        help="Required domain skill (repeatable).",
    )
    p_prog_charter.add_argument(
        "--programme-id",
        default=None,
        help="Parent programme ID (e.g., prog-alpha).",
    )
    p_prog_charter.add_argument(
        "--open-draft",
        action="store_true",
        help="Create/checkout the PR branch and open a draft PR.",
    )
    p_prog_charter.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_prog_charter.set_defaults(_handler=_cmd_programme_charter)

    # --- Step 4: Register Tier 3 Work Order subcommands (wo verify, debug, resolve) ---
    p_wo = subparsers.add_parser(
        "wo",
        help="Work Order lifecycle commands.",
    )
    wo_subparsers = p_wo.add_subparsers(dest="wo_command", metavar="<subcommand>")

    p_wo_verify = wo_subparsers.add_parser(
        "verify",
        help=(
            "Verify Work Order scope hygiene, run verification_command, "
            "stamp receipt, and commit."
        ),
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

    p_wo_debug = wo_subparsers.add_parser(
        "debug",
        help="Transition Work Order to BLOCKED and spawn/prepare a pinned pa-debugger session.",
    )
    p_wo_debug.add_argument(
        "wo_id",
        help="Work Order ID (e.g., WO-03.4).",
    )
    p_wo_debug.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_wo_debug.add_argument(
        "--reason",
        default=None,
        help="Optional failure reason or context summary.",
    )
    p_wo_debug.set_defaults(_handler=_cmd_wo_debug)

    p_wo_resolve = wo_subparsers.add_parser(
        "resolve",
        help=(
            "Verify and resolve a blocked Work Order from pa-debugger, "
            "unpinning and notifying PA."
        ),
    )
    p_wo_resolve.add_argument(
        "wo_id",
        help="Work Order ID (e.g., WO-03.4).",
    )
    p_wo_resolve.add_argument(
        "--summary",
        default=None,
        help="Concise root-cause and fix summary (required).",
    )
    p_wo_resolve.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_wo_resolve.set_defaults(_handler=_cmd_wo_resolve)

    # --- Step 5: Register Tier 2 Pull Request subcommands (pr start, claim, approve-plan, ...) ---
    p_pr = subparsers.add_parser(
        "pr",
        help="Pull Request lifecycle commands.",
    )
    pr_subparsers = p_pr.add_subparsers(dest="pr_command", metavar="<subcommand>")

    p_pr_start = pr_subparsers.add_parser(
        "start",
        help=(
            "Create/checkout stacked branch, verify/scaffold PROJECT.md, "
            "and start/pin PA session."
        ),
    )
    p_pr_start.add_argument(
        "pr_id",
        help="Pull Request ID (e.g. PR-01).",
    )
    p_pr_start.add_argument(
        "--slug",
        default=None,
        help="PR folder slug for standalone scaffolding.",
    )
    p_pr_start.add_argument(
        "--title",
        default=None,
        help="PR title for standalone scaffolding.",
    )
    p_pr_start.add_argument(
        "--branch",
        default=None,
        help="PR head branch override.",
    )
    p_pr_start.add_argument(
        "--base-branch",
        default=None,
        help="PR base branch override.",
    )
    p_pr_start.add_argument(
        "--allowed-module",
        action="append",
        default=None,
        metavar="MODULE",
        help="Allowed module path or glob (repeatable).",
    )
    p_pr_start.add_argument(
        "--verification-command",
        action="append",
        default=None,
        metavar="CMD",
        help="Verification floor command (repeatable).",
    )
    p_pr_start.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_pr_start.set_defaults(_handler=_cmd_pr_start)

    p_pr_claim = pr_subparsers.add_parser(
        "claim",
        help="Sync state, checkout PR branch, and output Tier 2 PA continuation prompt.",
    )
    p_pr_claim.add_argument(
        "pr_id",
        help="Pull Request ID (e.g. PR-01) or folder slug.",
    )
    p_pr_claim.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_pr_claim.set_defaults(_handler=_cmd_pr_claim)

    p_pr_approve = pr_subparsers.add_parser(
        "approve-plan",
        help=(
            "Validate PROJECT.md and wo*/WORKORDER.md specs, "
            "stamp spec_hash, and set status: APPROVED."
        ),
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

    p_pr_open = pr_subparsers.add_parser(
        "open-or-sync",
        help="Transition PR to STAGED_FOR_AUDIT and open/update GitHub PR in github mode.",
    )
    p_pr_open.add_argument(
        "pr_id",
        help="Pull Request ID (e.g. PR-01) or folder slug.",
    )
    p_pr_open.add_argument(
        "--draft",
        action="store_true",
        help="Open GitHub PR as a draft.",
    )
    p_pr_open.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_pr_open.set_defaults(_handler=_cmd_pr_open_or_sync)

    p_pr_post_audit = pr_subparsers.add_parser(
        "post-audit",
        help=(
            "Validate and record Cold-Firewall Audit report "
            "(and post gh pr review --comment in github mode)."
        ),
    )
    p_pr_post_audit.add_argument(
        "pr_id",
        help="Pull Request ID (e.g. PR-01).",
    )
    p_pr_post_audit.add_argument(
        "--file",
        required=True,
        help="Path to the AuditReport Markdown file.",
    )
    p_pr_post_audit.add_argument(
        "--no-commit",
        action="store_true",
        help="Write AUDIT-round-K.md without creating a local git commit.",
    )
    p_pr_post_audit.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_pr_post_audit.set_defaults(_handler=_cmd_pr_post_audit)

    p_pr_sync_audit = pr_subparsers.add_parser(
        "sync-audit",
        help=(
            "Sync latest AuditReport from AUDIT-round-K.md "
            "or GitHub PR review into .state/state.db."
        ),
    )
    p_pr_sync_audit.add_argument(
        "pr_id",
        help="Pull Request ID (e.g. PR-01).",
    )
    p_pr_sync_audit.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_pr_sync_audit.set_defaults(_handler=_cmd_pr_sync_audit)

    p_pr_graduate = pr_subparsers.add_parser(
        "graduate",
        help="Verify APPROVED audit for current HEAD + verification_floor and graduate PR memory.",
    )
    p_pr_graduate.add_argument(
        "pr_id",
        help="Pull Request ID (e.g. PR-01).",
    )
    p_pr_graduate.add_argument(
        "--skip-floor",
        action="store_true",
        help="Skip executing charter.verification_floor commands.",
    )
    p_pr_graduate.add_argument(
        "--completed-date",
        default=None,
        help="Override YYYY-MM-DD graduation date.",
    )
    p_pr_graduate.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_pr_graduate.set_defaults(_handler=_cmd_pr_graduate)

    p_pr_restack = pr_subparsers.add_parser(
        "restack",
        help="Rebase stacked PR branches onto base branches (git rebase --update-refs).",
    )
    p_pr_restack.add_argument(
        "pr_id_pos",
        nargs="?",
        default=None,
        help="Optional Pull Request ID or branch to restack.",
    )
    p_pr_restack.add_argument(
        "--pr-id",
        default=None,
        help="Optional Pull Request ID or branch to restack.",
    )
    p_pr_restack.add_argument(
        "--onto",
        default=None,
        help="Override target base branch for rebase.",
    )
    p_pr_restack.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_pr_restack.set_defaults(_handler=_cmd_pr_restack)

    # --- Step 6: Register deferred issue and escalation commands (issue create, escalate) ---
    p_issue = subparsers.add_parser(
        "issue",
        help="Deferred issue and out-of-scope finding commands.",
    )
    issue_subparsers = p_issue.add_subparsers(
        dest="issue_command",
        metavar="<subcommand>",
    )

    p_issue_create = issue_subparsers.add_parser(
        "create",
        help="Create a pa:deferred GitHub issue or append to DEFERRED_BACKLOG.md.",
    )
    p_issue_create.add_argument(
        "--title",
        required=True,
        help="Issue / deferred finding title.",
    )
    p_issue_create.add_argument(
        "--summary",
        default="",
        help="Issue / finding summary.",
    )
    p_issue_create.add_argument(
        "--pr-id",
        default=None,
        help="Associated PR ID (e.g. PR-03).",
    )
    p_issue_create.add_argument(
        "--wo-id",
        default=None,
        help="Associated Work Order ID (e.g. WO-03.5).",
    )
    p_issue_create.add_argument(
        "--file-path",
        default=None,
        help="Associated file path.",
    )
    p_issue_create.add_argument(
        "--label",
        action="append",
        default=None,
        metavar="LABEL",
        help="Issue label (repeatable; 'pa:deferred' always included).",
    )
    p_issue_create.add_argument(
        "--path",
        default=".",
        help="Path to the target repository (default: current directory).",
    )
    p_issue_create.set_defaults(_handler=_cmd_issue_create)

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

    # --- Step 7: Load and register any dynamic COMMAND_MODULES extensions ---
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
    """CLI entrypoint returning exit code (`0` = success, `1` = usage/validation, `2` = env).

    Args:
        argv: Optional sequence of command-line arguments (defaults to `sys.argv[1:]`).
        runner: Subprocess runner callable (defaults to `common.run`).

    Returns:
        Process exit code (`0`, `1`, or `2`).
    """
    # --- Step 1: Build ArgumentParser and parse CLI arguments ---
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

    # --- Step 2: Dispatch parsed subcommand to registered `_handler` or `func` ---
    handler = getattr(args, "_handler", None)
    if callable(handler):
        return int(handler(args, runner=runner))

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
