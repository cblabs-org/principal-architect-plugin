"""Standard-library-only foundations for principal-architect-plugin.

This module MUST NOT import any third-party dependencies (specifically pydantic
or yaml). Fast paths such as `is_repo_enrolled` must execute in < 1 ms.
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

NEW_WORKSPACE_REL = Path(".agents/plugins/principal-architect-workspace")
LEGACY_WORKSPACE_REL = Path(".agents/skills/principal-architect-workspace")

Runner = Callable[..., subprocess.CompletedProcess[str]]


def run(
    cmd: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a subprocess command with string stdout/stderr capture."""
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
    """Strip file:// scheme and unquote URL-encoded path."""
    if path_str.startswith("file://"):
        parsed = urllib.parse.urlparse(path_str)
        # On Linux/Unix, urlparse("file:///foo/bar").path is "/foo/bar"
        return urllib.parse.unquote(parsed.path)
    return path_str


def find_repo_root(path: str | Path = ".", *, runner: Runner = run) -> Path | None:
    """Find the root directory of the git repository enclosing path, or None."""
    p_str = _strip_file_uri(str(path))
    real_p = os.path.realpath(p_str)
    cur = Path(real_p)
    if cur.is_file():
        cur = cur.parent

    # Check cur and parents directly for .git (directory or worktree file)
    candidates = [cur, *cur.parents]
    for d in candidates:
        git_entry = d / ".git"
        if git_entry.exists():
            return Path(os.path.realpath(d))

    # Fallback to runner git rev-parse --show-toplevel
    try:
        res = runner(["git", "rev-parse", "--show-toplevel"], cwd=cur)
        if res.returncode == 0 and res.stdout.strip():
            return Path(os.path.realpath(res.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        return None

    return None


def workspace_dir(repo_root: str | Path) -> Path:
    """Resolve the active principal-architect-workspace directory for a repo root."""
    root = Path(os.path.realpath(repo_root))
    if (root / NEW_WORKSPACE_REL).exists():
        return root / NEW_WORKSPACE_REL
    if (root / LEGACY_WORKSPACE_REL).exists():
        return root / LEGACY_WORKSPACE_REL
    return root / NEW_WORKSPACE_REL


def daemon_home() -> Path:
    """Resolve the base directory for the pa-daemon plugin state and config."""
    env_val = os.environ.get("PA_DAEMON_HOME")
    if env_val and env_val.strip():
        return Path(os.path.realpath(os.path.expanduser(env_val.strip())))
    return Path(os.path.realpath(Path.home())) / ".gemini" / "config" / "plugins" / "pa-daemon"


def is_repo_enrolled(workspace_paths: Sequence[str | Path]) -> bool:
    """Fast-exit check (<1ms) determining if any given path belongs to an enrolled repo.

    Uses strictly standard-library json and path operations; never imports pydantic or yaml.
    """
    if not workspace_paths:
        return False

    registry_path = daemon_home() / "state" / "registry.json"
    if not registry_path.is_file():
        return False

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

    for wp in workspace_paths:
        p_str = _strip_file_uri(str(wp))
        real_p = os.path.realpath(p_str)
        # Check if real_p itself or any parent directory is in enrolled_roots
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
    """Read a JSONL transcript file into a list of step dicts, ignoring malformed lines."""
    p = Path(path)
    if not p.is_file():
        return []

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

    Inspects steps for type in ('CHECKPOINT', 'CORTEX_STEP_TYPE_CHECKPOINT').
    """
    max_idx: int | None = None
    for idx, step in enumerate(steps):
        stype = step.get("type")
        if stype in ("CHECKPOINT", "CORTEX_STEP_TYPE_CHECKPOINT"):
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
    """Return the absolute path to the templates directory."""
    return Path(__file__).resolve().parent.parent / "skills" / "principal-architect" / "templates"


def render_template(template_text: str, values: Mapping[str, Any]) -> str:
    """Replace {{name}} placeholders in template_text with values from the mapping.

    Raises KeyError if a placeholder key is missing from values.
    """
    pattern = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Template placeholder '{key}' not found in values")
        return str(values[key])

    return pattern.sub(_repl, template_text)
