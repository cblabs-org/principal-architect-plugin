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
- load_daemon_env: Load optional `<PA_DAEMON_HOME>/bin/env.sh` overrides into `os.environ`.
- app_data_dir: Resolve the Antigravity application data directory (`ANTIGRAVITY_APP_DIR`).
- cli_data_dir: Resolve the Antigravity CLI data directory (`ANTIGRAVITY_CLI_DIR`).
- cli_bin: Resolve the Antigravity CLI executable name or path (`ANTIGRAVITY_CLI_BIN`).
- agentapi_bin: Resolve the `agentapi` CLI executable path (`ANTIGRAVITY_AGENTAPI_BIN`).
- activate_daemon_venv: Register `site-packages` from the daemon or repo `.venv` on `sys.path`.
- is_repo_enrolled: Fast-exit check (< 1 ms) determining if any path belongs to an enrolled repo.
- read_transcript: Parse a JSONL conversation transcript file into a list of step dictionaries.
- latest_checkpoint_step: Find the highest checkpoint step index in a sequence of transcript steps.
- templates_dir: Return the absolute path to the Markdown document templates directory.
- render_template: Substitute `{{name}}` placeholders in a template string from a value mapping.
- render_template_file: Load a named template file from `templates_dir()` and render it.
- sha_matches: Check whether two Git commit SHAs match (supporting >=7-char prefixes).
- head_matches_audited_sha: Check whether `current_head_sha` matches `audited_sha` directly or via audit/PROJECT.md commits.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import site
import subprocess
import sys
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


# Matches simple `export KEY="VALUE"` or `KEY=VALUE` assignments in `bin/env.sh`.
_ENV_ASSIGNMENT_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def load_daemon_env(daemon_dir: str | Path | None = None) -> dict[str, str]:
    """Load optional `<PA_DAEMON_HOME>/bin/{pa.env,env.sh}` overrides into `os.environ`.

    Allows environment-specific deployment wrappers (such as custom `ANTIGRAVITY_APP_DIR`,
    `ANTIGRAVITY_CLI_DIR`, `ANTIGRAVITY_CLI_BIN`, or `ANTIGRAVITY_AGENTAPI_BIN` paths) to
    be inherited automatically even when Python hook entrypoints are spawned directly
    without going through a shell wrapper. Explicit process environment variables take
    precedence.

    Args:
        daemon_dir: Optional explicit `pa-daemon` directory override (defaults to `daemon_home()`).

    Returns:
        Dictionary of key-value pairs parsed from `bin/pa.env` or `bin/env.sh` (empty if absent).
    """
    # --- Step 1: Locate optional bin/pa.env or bin/env.sh inside the daemon directory ---
    base_dir = Path(os.path.realpath(daemon_dir)) if daemon_dir is not None else daemon_home()
    loaded: dict[str, str] = {}
    home_str = str(Path.home())

    for fname in ("pa.env", "env.sh"):
        env_file = base_dir / "bin" / fname
        if not env_file.is_file():
            continue

        # --- Step 2: Parse simple KEY=VALUE lines and populate unset os.environ keys ---
        try:
            raw_lines = env_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        for raw_line in raw_lines:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = _ENV_ASSIGNMENT_RE.match(stripped)
            if not match:
                continue
            key, raw_val = match.group(1), match.group(2).strip()
            if len(raw_val) >= 2 and raw_val[0] == raw_val[-1] and raw_val[0] in ('"', "'"):
                val = raw_val[1:-1]
            else:
                val = raw_val.split("#", 1)[0].strip()
            # Expand basic $HOME / ${HOME} / ~ tokens in path values
            val = val.replace("${HOME}", home_str).replace("$HOME", home_str)
            val = os.path.expanduser(val)
            loaded[key] = val
            if key not in os.environ or not os.environ[key].strip():
                os.environ[key] = val
    return loaded


def app_data_dir() -> Path:
    """Resolve the Antigravity application data directory (`ANTIGRAVITY_APP_DIR`).

    Loads optional `<PA_DAEMON_HOME>/bin/env.sh` defaults first, honors the
    `ANTIGRAVITY_APP_DIR` environment variable when set and non-empty, and otherwise
    defaults to `~/.gemini/antigravity`.

    Returns:
        Canonical `Path` to the Antigravity application data directory.
    """
    load_daemon_env()
    env_val = os.environ.get("ANTIGRAVITY_APP_DIR")
    if env_val and env_val.strip():
        return Path(os.path.realpath(os.path.expanduser(env_val.strip())))
    return Path(os.path.realpath(Path.home())) / ".gemini" / "antigravity"


def cli_data_dir() -> Path:
    """Resolve the Antigravity CLI data directory (`ANTIGRAVITY_CLI_DIR`).

    Loads optional `<PA_DAEMON_HOME>/bin/env.sh` defaults first, honors the
    `ANTIGRAVITY_CLI_DIR` environment variable when set and non-empty, and otherwise
    defaults to `~/.gemini/antigravity-cli`.

    Returns:
        Canonical `Path` to the Antigravity CLI data directory.
    """
    load_daemon_env()
    env_val = os.environ.get("ANTIGRAVITY_CLI_DIR")
    if env_val and env_val.strip():
        return Path(os.path.realpath(os.path.expanduser(env_val.strip())))
    return Path(os.path.realpath(Path.home())) / ".gemini" / "antigravity-cli"


def cli_bin() -> str:
    """Resolve the configured Antigravity CLI executable name or path (`ANTIGRAVITY_CLI_BIN`).

    Loads optional `<PA_DAEMON_HOME>/bin/env.sh` defaults first, honors the
    `ANTIGRAVITY_CLI_BIN` environment variable when set and non-empty, and otherwise
    defaults to `"agy"`.

    Returns:
        Executable name or expanded filesystem path string for the Antigravity CLI.
    """
    load_daemon_env()
    env_val = os.environ.get("ANTIGRAVITY_CLI_BIN")
    if env_val and env_val.strip():
        return os.path.expanduser(env_val.strip())
    return "agy"


def agentapi_bin() -> str | None:
    """Resolve the `agentapi` CLI executable path if available.

    Searches in precedence order:
    1. `ANTIGRAVITY_AGENTAPI_BIN` environment variable (or `<PA_DAEMON_HOME>/bin/env.sh`)
    2. `agentapi` on `PATH` via `shutil.which("agentapi")`
    3. `<ANTIGRAVITY_APP_DIR>/bin/agentapi`

    Returns:
        Resolved executable path string if found and executable, or `None` otherwise.
    """
    # --- Step 1: Check explicit ANTIGRAVITY_AGENTAPI_BIN override ---
    load_daemon_env()
    env_val = os.environ.get("ANTIGRAVITY_AGENTAPI_BIN")
    if env_val and env_val.strip():
        expanded = os.path.expanduser(env_val.strip())
        found_override = shutil.which(expanded)
        if found_override:
            return found_override
        cand = Path(expanded)
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)

    # --- Step 2: Check PATH via shutil.which and fallback to <app_data_dir>/bin/agentapi ---
    which_bin = shutil.which("agentapi")
    if which_bin:
        return which_bin

    app_bin = app_data_dir() / "bin" / "agentapi"
    if app_bin.is_file() and os.access(app_bin, os.X_OK):
        return str(app_bin)

    return None


def activate_daemon_venv(daemon_dir: str | Path | None = None) -> bool:
    """Register `site-packages` from the daemon or co-located `.venv` onto `sys.path`.

    Ensures that when `cockpit.py` (spawned by `sidecar.json` via system `python3`) or
    `pa_cli.py` is executed directly under a PEP 668 externally-managed Python interpreter,
    third-party schema packages (`pydantic` and `pyyaml`) installed in
    `<PA_DAEMON_HOME>/.venv` or the repository `.venv` remain importable.

    Args:
        daemon_dir: Optional explicit `pa-daemon` directory override (defaults to `daemon_home()`).

    Returns:
        `True` if at least one `.venv` `site-packages` directory was found and registered;
        `False` otherwise.
    """
    # --- Step 1: Collect candidate .venv directories from daemon_home and bundle root ---
    primary_daemon = Path(os.path.realpath(daemon_dir)) if daemon_dir is not None else daemon_home()
    bundle_root = Path(__file__).resolve().parents[3]
    candidates: list[Path] = [primary_daemon / ".venv"]
    if (bundle_root / ".venv") not in candidates:
        candidates.append(bundle_root / ".venv")

    # --- Step 2: Locate matching site-packages directories and register via site.addsitedir ---
    py_tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
    exact_matches: list[Path] = []
    fallback_matches: list[Path] = []
    for venv_dir in candidates:
        if not venv_dir.is_dir():
            continue
        for exact_sp in (
            venv_dir / "lib" / py_tag / "site-packages",
            venv_dir / "Lib" / "site-packages",
        ):
            if exact_sp.is_dir() and exact_sp not in exact_matches:
                exact_matches.append(exact_sp)
        lib_dir = venv_dir / "lib"
        if lib_dir.is_dir():
            for child in sorted(lib_dir.glob("python*/site-packages")):
                if child not in exact_matches and child not in fallback_matches:
                    fallback_matches.append(child)

    selected = exact_matches if exact_matches else fallback_matches
    for sp in selected:
        site.addsitedir(str(sp))
    return bool(selected)


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


def sha_matches(sha_a: str, sha_b: str) -> bool:
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


def head_matches_audited_sha(
    real_root: Path,
    pr_dir: Path,
    current_head_sha: str,
    audited_sha: str,
    *,
    runner: Runner = run,
) -> bool:
    """Verify `audited_sha` matches `current_head_sha` (or ancestor when only audit/PROJECT.md changed).

    In `local_git` mode (and default `pa pr post-audit` runs), recording the Cold-Firewall
    `AuditReport` creates a new commit on top of the very `HEAD` SHA (`audited_sha`) that the
    auditor evaluated. To prevent that audit-recording commit (or subsequent `PROJECT.md`
    status/ledger updates) from invalidating its own `head_sha` match during `PreToolUse`
    Rule R6, `Stop` gate auditor evaluation, or `pa pr graduate`, this function accepts
    `current_head_sha` when the diff from `audited_sha` to `current_head_sha` touches
    exclusively `AUDIT-round-<K>.md` and/or `PROJECT.md` inside `pr_dir`.

    Args:
        real_root: Canonical repository root `Path`.
        pr_dir: Pull Request workspace directory `Path`.
        current_head_sha: Current `git rev-parse HEAD` commit SHA.
        audited_sha: `head_sha` recorded inside the `AuditReport`.
        runner: Subprocess runner callable.

    Returns:
        `True` if `current_head_sha` matches `audited_sha` directly or via audit/PROJECT.md-only commits.
    """
    # --- Step 1: Check direct SHA match against current HEAD ---
    if sha_matches(current_head_sha, audited_sha):
        return True
    if not current_head_sha or current_head_sha == "HEAD" or len(audited_sha.strip()) < 7:
        return False

    try:
        pr_dir_rel = pr_dir.resolve().relative_to(real_root.resolve()).as_posix()
    except ValueError:
        return False
    allowed_audit_re = re.compile(rf"^{re.escape(pr_dir_rel)}/AUDIT-round-\d+\.md$")
    proj_rel = f"{pr_dir_rel}/PROJECT.md"

    def _diff_only_touches_audit_or_project(base_ref: str) -> bool:
        diff_res = runner(
            ["git", "diff", "--name-only", base_ref, current_head_sha],
            cwd=real_root,
        )
        if diff_res.returncode != 0:
            return False
        changed_files = [ln.strip() for ln in diff_res.stdout.splitlines() if ln.strip()]
        if not changed_files:
            return True
        return all(cf == proj_rel or bool(allowed_audit_re.match(cf)) for cf in changed_files)

    # --- Step 2: Check if HEAD~1 matches audited_sha and HEAD only touched audit/project docs ---
    parent_res = runner(["git", "rev-parse", "HEAD~1"], cwd=real_root)
    if parent_res.returncode == 0 and parent_res.stdout.strip():
        parent_sha = parent_res.stdout.strip()
        if sha_matches(parent_sha, audited_sha):
            return _diff_only_touches_audit_or_project(parent_sha)

    # --- Step 3: Check if audited_sha is an ancestor of HEAD with only audit/project doc diffs ---
    anc_res = runner(
        ["git", "merge-base", "--is-ancestor", audited_sha.strip(), current_head_sha],
        cwd=real_root,
    )
    if anc_res.returncode == 0:
        return _diff_only_touches_audit_or_project(audited_sha.strip())

    return False

