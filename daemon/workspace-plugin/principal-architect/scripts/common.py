"""Principal Architect Plugin (c) 2026 Matt McNeill
https://github.com/matthewmcneill/principal-architect-plugin
SPDX-License-Identifier: Apache-2.0
Module: daemon/workspace-plugin/principal-architect/scripts/common.py

Standard-library-only foundation helpers for the Principal Architect Split-Authority
runtime. Provides subprocess execution wrappers, git repository root discovery,
workspace and daemon directory resolution, sub-millisecond repository enrollment
checks, JSONL transcript checkpoint inspection, and Markdown template rendering.

This module MUST NOT import any third-party dependencies (specifically `pydantic`
or `yaml`) so that hot-path hook entrypoints such as `is_repo_enrolled` execute
in under 1 ms.

Exported API Summary:
- NEW_WORKSPACE_REL: Repository-relative path to the active plugin workspace directory.
- LEGACY_WORKSPACE_REL: Repository-relative path to the legacy skill workspace directory.
- Runner: Callable type alias for subprocess execution functions compatible with `run`.
- run: Execute a subprocess command with string stdout/stderr capture and timeout control.
- _strip_file_uri: Strip a leading `file://` URI scheme and unquote URL-encoded characters.
- find_repo_root: Locate the enclosing git repository root directory for a filesystem path.
- workspace_dir: Resolve the active `principal-architect-workspace` path for a repository root.
- daemon_home: Resolve the base directory for `pa-daemon` global state and configuration.
- is_repo_enrolled: Fast-exit check (< 1 ms) determining if any path belongs to an enrolled repo.
- read_transcript: Parse a JSONL conversation transcript file into a list of step dictionaries.
- latest_checkpoint_step: Find the highest checkpoint step index in a sequence of transcript steps.
- templates_dir: Return the absolute path to the Markdown document templates directory.
- render_template: Substitute `{{name}}` placeholders in a template string from a value mapping.
- render_template_file: Load a named template file from `templates_dir()` and render it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

# Repository-relative directory path for modern Principal Architect workspaces.
NEW_WORKSPACE_REL = Path(".agents/plugins/principal-architect-workspace")

# Repository-relative directory path for legacy skill-based Principal Architect workspaces.
LEGACY_WORKSPACE_REL = Path(".agents/skills/principal-architect-workspace")

# Callable signature for injectable subprocess runners returning text CompletedProcess results.
Runner = Callable[..., subprocess.CompletedProcess[str]]


def run(
    cmd: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a subprocess command with string stdout/stderr capture without raising on non-zero.

    Args:
        cmd: Sequence of command-line program and argument strings.
        cwd: Optional working directory for the child process.
        env: Optional environment variable mapping for the child process.
        timeout: Maximum execution time in seconds before raising `subprocess.TimeoutExpired`.
        input_text: Optional UTF-8 text payload written to the child process's stdin.

    Returns:
        CompletedProcess[str] containing the exit code, captured stdout, and captured stderr.

    Raises:
        subprocess.TimeoutExpired: If the subprocess does not finish within `timeout` seconds.
        OSError: If the executable cannot be launched.
    """
    # --- Step 1: Normalize arguments and invoke subprocess.run with text capture ---
    return subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _strip_file_uri(path_str: str) -> str:
    """Strip a leading `file://` URI scheme and URL-unquote the resulting filesystem path.

    Args:
        path_str: Raw filesystem path or `file://` URI string.

    Returns:
        Plain filesystem path string with percent-encoded sequences decoded.
    """
    if path_str.startswith("file://"):
        parsed = urllib.parse.urlparse(path_str)
        # On POSIX systems, urlparse("file:///foo/bar").path yields "/foo/bar".
        return urllib.parse.unquote(parsed.path)
    return path_str


def find_repo_root(path: str | Path = ".", *, runner: Runner = run) -> Path | None:
    """Find the canonical root directory of the git repository enclosing `path`.

    Walks upward from `path` looking for a `.git` directory or worktree pointer file
    before falling back to `git rev-parse --show-toplevel`.

    Args:
        path: Starting file or directory path (or `file://` URI) to inspect.
        runner: Subprocess runner callable used for the `git rev-parse` fallback.

    Returns:
        Resolved `Path` to the enclosing git repository root, or `None` if not inside a repo.
    """
    # --- Step 1: Strip URI prefix, resolve symlinks, and normalize to a directory ---
    p_str = _strip_file_uri(str(path))
    real_p = os.path.realpath(p_str)
    cur = Path(real_p)
    if cur.is_file():
        cur = cur.parent

    # --- Step 2: Walk ancestor directories for a .git directory or git worktree file ---
    candidates = [cur, *cur.parents]
    for d in candidates:
        git_entry = d / ".git"
        if git_entry.exists():
            return Path(os.path.realpath(d))

    # --- Step 3: Fall back to git rev-parse --show-toplevel for bare or custom git setups ---
    try:
        res = runner(["git", "rev-parse", "--show-toplevel"], cwd=cur)
        if res.returncode == 0 and res.stdout.strip():
            return Path(os.path.realpath(res.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        return None

    return None


def workspace_dir(repo_root: str | Path) -> Path:
    """Resolve the active `principal-architect-workspace` directory for a repository root.

    Prefers `.agents/plugins/principal-architect-workspace` when present, falls back to
    the legacy `.agents/skills/principal-architect-workspace` if it already exists on disk,
    and otherwise defaults to the new plugin workspace location.

    Args:
        repo_root: Root directory path of the git repository.

    Returns:
        Absolute `Path` to the repository's Principal Architect workspace directory.
    """
    root = Path(os.path.realpath(repo_root))
    if (root / NEW_WORKSPACE_REL).exists():
        return root / NEW_WORKSPACE_REL
    if (root / LEGACY_WORKSPACE_REL).exists():
        return root / LEGACY_WORKSPACE_REL
    return root / NEW_WORKSPACE_REL


def daemon_home() -> Path:
    """Resolve the base directory for the `pa-daemon` plugin global state and configuration.

    Honors the `PA_DAEMON_HOME` environment variable when set and non-empty; otherwise
    defaults to `~/.gemini/config/plugins/pa-daemon`.

    Returns:
        Canonical `Path` to the `pa-daemon` home directory.
    """
    env_val = os.environ.get("PA_DAEMON_HOME")
    if env_val and env_val.strip():
        return Path(os.path.realpath(os.path.expanduser(env_val.strip())))
    return Path(os.path.realpath(Path.home())) / ".gemini" / "config" / "plugins" / "pa-daemon"


def is_repo_enrolled(workspace_paths: Sequence[str | Path]) -> bool:
    """Perform a fast-exit check (< 1 ms) determining if any path belongs to an enrolled repo.

    Uses strictly standard-library JSON and path operations against `registry.json`
    without importing `pydantic` or `yaml` or spawning subprocesses.

    Args:
        workspace_paths: Sequence of candidate filesystem paths or `file://` URIs.

    Returns:
        `True` if at least one candidate path (or one of its parent directories) matches
        an enrolled repository root in `registry.json`; `False` otherwise.
    """
    # --- Step 1: Validate input paths and check that the global registry file exists ---
    if not workspace_paths:
        return False

    registry_path = daemon_home() / "state" / "registry.json"
    if not registry_path.is_file():
        return False

    # --- Step 2: Load and validate the JSON structure of registry.json ---
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False

    if not isinstance(data, dict):
        return False

    repos = data.get("repos")
    if not isinstance(repos, dict):
        return False

    enrolled_roots = {os.path.realpath(k) for k in repos}
    if not enrolled_roots:
        return False

    # --- Step 3: Walk each candidate path and its parent chain against enrolled roots ---
    for wp in workspace_paths:
        p_str = _strip_file_uri(str(wp))
        real_p = os.path.realpath(p_str)
        # Check if real_p itself or any ancestor directory is registered in enrolled_roots.
        cur: str | None = real_p
        while cur:
            if cur in enrolled_roots:
                return True
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent

    return False


def read_transcript(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL conversation transcript file into a list of step dictionaries.

    Gracefully ignores missing files, blank lines, non-object JSON values, and
    truncated or malformed JSON lines.

    Args:
        path: Filesystem path to the `.jsonl` transcript file.

    Returns:
        Ordered list of parsed JSON object dictionaries representing transcript steps.
    """
    # --- Step 1: Verify the transcript file exists on disk ---
    p = Path(path)
    if not p.is_file():
        return []

    # --- Step 2: Stream and parse JSONL lines while skipping blank or malformed entries ---
    steps: list[dict[str, Any]] = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    obj = json.loads(line_str)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    steps.append(obj)
    except OSError:
        return []

    return steps


def latest_checkpoint_step(steps: Sequence[Mapping[str, Any]]) -> int | None:
    """Find the highest checkpoint step index from a sequence of transcript steps.

    Inspects steps whose `type` is `"CHECKPOINT"` or `"CORTEX_STEP_TYPE_CHECKPOINT"`,
    falling back to the 0-based enumeration index if `step_index` is absent or non-integer.

    Args:
        steps: Sequence of transcript step dictionaries as returned by `read_transcript`.

    Returns:
        Highest integer checkpoint step index found, or `None` if no checkpoint step exists.
    """
    # --- Step 1: Scan all steps for checkpoint markers and track the maximum index ---
    max_idx: int | None = None
    for idx, step in enumerate(steps):
        stype = step.get("type")
        if stype in ("CHECKPOINT", "CORTEX_STEP_TYPE_CHECKPOINT"):
            # --- Step 2: Resolve explicit step_index or fall back to enumeration offset ---
            raw_idx = step.get("step_index")
            if raw_idx is not None:
                try:
                    val = int(raw_idx)
                except (ValueError, TypeError):
                    val = idx
            else:
                val = idx
            if max_idx is None or val > max_idx:
                max_idx = val
    return max_idx


def templates_dir() -> Path:
    """Return the absolute path to the Principal Architect Markdown templates directory.

    Returns:
        Resolved `Path` to `skills/principal-architect/templates` inside the workspace plugin.
    """
    return Path(__file__).resolve().parent.parent / "skills" / "principal-architect" / "templates"


def render_template(template_text: str, values: Mapping[str, Any]) -> str:
    """Replace `{{name}}` placeholders in `template_text` with stringified values from `values`.

    Args:
        template_text: Raw template string containing `{{identifier}}` placeholders.
        values: Mapping of placeholder names to replacement values.

    Returns:
        Rendered string with all `{{name}}` tokens substituted.

    Raises:
        KeyError: If any placeholder key in `template_text` is missing from `values`.
    """
    # Match Mustache-style {{ identifier }} tokens with optional inner whitespace.
    pattern = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Template placeholder '{key}' not found in values")
        return str(values[key])

    return pattern.sub(_repl, template_text)


def render_template_file(template_name: str, values: Mapping[str, Any] | None = None) -> str:
    """Read a template file from `templates_dir()` and render it with `values`.

    Appends `.md.tpl` automatically if `template_name` does not already end with `.tpl`.

    Args:
        template_name: Template filename or stem (e.g., `"PROJECT"` or `"PROJECT.md.tpl"`).
        values: Optional mapping of placeholder keys to replacement values.

    Returns:
        Rendered Markdown document text.

    Raises:
        FileNotFoundError: If the resolved template file does not exist in `templates_dir()`.
        KeyError: If the template references a placeholder key absent from `values`.
    """
    name = str(template_name)
    if not name.endswith(".tpl"):
        name = f"{name}.md.tpl"
    p = templates_dir() / name
    if not p.is_file():
        raise FileNotFoundError(f"Template file not found: {p}")
    text = p.read_text(encoding="utf-8")
    return render_template(text, values or {})
