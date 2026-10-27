"""Principal Architect Plugin (c) 2026 Matt McNeill
https://github.com/matthewmcneill/principal-architect-plugin
SPDX-License-Identifier: Apache-2.0
Module: daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py

Local-Git floor and GitHub multi-machine synchronization bus for the Split-Authority software
delivery workflow.

In the Three-Tier Split-Authority architecture, Git commits, branch stacks, and Pull Request audit
artifacts serve as the durable cross-session and cross-machine source of truth while
`<workspace_dir>/.state/state.db` acts as a gitignored local runtime cache. This module provides a
dual-mode Version Control System synchronization bus (`VCSBus`):
- `LocalGitBus` (`vcs_mode == "local_git"`): Operates 100% offline using local Git branches,
  `git rebase --update-refs` stacked branch restacking, structured commit trailers
  (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`), `<pr_dir>/AUDIT-round-<K>.md` files,
  and `<workspace_dir>/DEFERRED_BACKLOG.md`.
- `GitHubBus` (`vcs_mode == "github"`): Extends `LocalGitBus` to synchronize stacked PRs, machine-
  parseable Cold-Firewall audit review comments (`gh pr review --comment`), and deferred engineering
  issues (`gh issue create --label pa:deferred`) across machines via the `gh` CLI.

Exported API Summary
--------------------
Constants:
- `MAX_AUDIT_ROUNDS`: Hard ceiling on Cold-Firewall audit rounds per PR before mandatory human
  escalation (`5`).

Functions:
- `format_commit_with_trailers(subject, body=None, trailers=None) -> str`: Format a Git commit
  message with subject, optional body, and `Key: Value` trailers.
- `read_commit_trailers(repo_root, *, rev_range=None, max_count=None, runner=common.run) ->
  list[dict[str, Any]]`: Parse `PA-WorkOrder`, `PA-Verified-Hash`, and `PA-Audit-Verdict` trailers
  from `git log`.
- `read_trailers`: Alias for `read_commit_trailers`.
- `format_pa_audit_comment(report, body_markdown=None) -> str`: Render an `AuditReport` with a
  machine-parseable `<!-- pa:audit ... -->` header and `**Audit Verdict:**` summary line.
- `parse_pa_audit_comment(text) -> dict[str, Any] | None`: Parse a `<!-- pa:audit ... -->` comment
  block (and optional YAML frontmatter) into a structured dictionary.
- `write_audit_round(repo_root, pr_id, audit_source, *, commit=True, runner=common.run) -> Path`:
  Validate an `AuditReport`, write `<pr_dir>/AUDIT-round-<K>.md`, update `PROJECT.md` status
  without mutating Part I `charter_hash`, and commit with a `PA-Audit-Verdict` trailer.
- `append_deferred_backlog(repo_root, *, title, summary="", pr_id=None, wo_id=None,
  labels=("pa:deferred",), file_path=None) -> Path`: Append an out-of-scope deferred finding to
  `<workspace_dir>/DEFERRED_BACKLOG.md`.
- `create_or_checkout_branch(repo_root, branch, base_branch="main", *, runner=common.run) -> str`:
  Create `<branch>` from `<base_branch>` or check it out if it already exists, returning `HEAD` SHA.
- `get_vcs_bus(repo_root, *, vcs_mode=None, runner=common.run) -> VCSBus`: Factory returning
  `GitHubBus` or `LocalGitBus` according to explicit `vcs_mode` or `.state/state.db` config.
- `sync_state(repo_root, *, runner=common.run) -> dict[str, Any]`: Rebuild `.state/state.db` and
  reconcile `PROJECT.md` summary rows via the active `VCSBus`.
- `restack_branches(repo_root, *, pr_id=None, onto_branch=None, runner=common.run) ->
  dict[str, Any]`: Rebase stacked PR branches onto their base branches via the active `VCSBus`.

Protocols & Classes:
- `VCSBus` (and backwards-compatible alias `VcsBus`): Runtime-checkable protocol defining the
  unified `local_git` and `github` VCS synchronization contract.
- `LocalGitBus`: Offline Local-Git floor implementation of `VCSBus`.
  - **Lifecycle / Constructors**:
    - `__init__(repo_root, *, runner=common.run) -> None`: Bind bus to resolved repository root and
      subprocess runner.
  - **Own Public API**:
    - `read_trailers`: Alias for `read_commit_trailers`.
  - **VCSBus Protocol Implementation**:
    - `create_or_checkout_branch(branch, base_branch="main") -> str`: Create or check out a local
      branch and return its `HEAD` SHA.
    - `read_commit_trailers(*, rev_range=None, max_count=None) -> list[dict[str, Any]]`: Read
      `PA-*` trailers from local `git log`.
    - `format_commit_with_trailers(subject, body=None, trailers=None) -> str`: Format a commit
      message with `Key: Value` trailers.
    - `write_audit_round(pr_id, audit_source, *, commit=True) -> Path`: Persist
      `<pr_dir>/AUDIT-round-<K>.md`, update `PROJECT.md` status, and commit locally.
    - `append_deferred_backlog(*, title, summary="", pr_id=None, wo_id=None,
      labels=("pa:deferred",), file_path=None) -> Path`: Append a deferred item to
      `<workspace_dir>/DEFERRED_BACKLOG.md`.
    - `create_deferred_issue(*, title, summary="", pr_id=None, wo_id=None,
      labels=("pa:deferred",), file_path=None) -> dict[str, Any]`: Record a deferred item in local
      `DEFERRED_BACKLOG.md`.
    - `open_or_sync_pr(pr_id, *, draft=False) -> dict[str, Any]`: Transition `<PR-ID>` to
      `STAGED_FOR_AUDIT` and verify local branch against base.
    - `view_pr(pr_id_or_number) -> dict[str, Any]`: Return PR metadata synthesized from local
      `PROJECT.md` and `AUDIT-round-*.md` artifacts.
    - `diff_pr(pr_id_or_number) -> str`: Return local `git diff <base_branch>...<branch>`.
    - `post_audit(pr_id, audit_source, *, commit=True) -> dict[str, Any]`: Persist and commit
      `AUDIT-round-<K>.md` locally and update `.state/state.db`.
    - `sync_audit(pr_id) -> dict[str, Any] | None`: Sync the highest-numbered local
      `AUDIT-round-<K>.md` into `.state/state.db`.
    - `sync_state() -> dict[str, Any]`: Rebuild `.state/state.db` and reconcile `PROJECT.md`
      Work Order rows from local Git trailers and specs.
    - `restack_branches(*, pr_id=None, onto_branch=None) -> dict[str, Any]`: Rebase stacked PR
      branches via `git rebase --update-refs`.
- `GitHubBus(LocalGitBus)`: GitHub multi-machine synchronization bus (`vcs_mode == "github"`).
  - **Lifecycle / Constructors**:
    - `__init__(repo_root, *, runner=common.run) -> None`: Inherited from `LocalGitBus`.
  - **Own Public API**:
    - `read_trailers`: Inherited alias for `read_commit_trailers`.
  - **VCSBus Protocol Implementation**:
    - `open_or_sync_pr(pr_id, *, draft=False) -> dict[str, Any]`: Stage `<PR-ID>`, push branch to
      `origin`, and create or update the GitHub PR via `gh pr create` / `gh pr edit`.
    - `view_pr(pr_id_or_number) -> dict[str, Any]`: Inspect a GitHub PR via `gh pr view --json`.
    - `diff_pr(pr_id_or_number) -> str`: Fetch PR diff via `gh pr diff`, falling back to local
      `git diff`.
    - `post_audit(pr_id, audit_source, *, commit=True) -> dict[str, Any]`: Write and commit
      `AUDIT-round-<K>.md` locally and post review comment via `gh pr review --comment`.
    - `sync_audit(pr_id) -> dict[str, Any] | None`: Ingest remote `<!-- pa:audit ... -->` PR
      comments into `<pr_dir>/AUDIT-round-<K>.md` and `.state/state.db`.
    - `create_deferred_issue(*, title, summary="", pr_id=None, wo_id=None,
      labels=("pa:deferred",), file_path=None) -> dict[str, Any]`: Create a GitHub issue with
      `--label pa:deferred` and record in `DEFERRED_BACKLOG.md`.
    - `sync_state() -> dict[str, Any]`: Fetch `origin`, sync remote GitHub PR audits, and rebuild
      `.state/state.db`.
    - `restack_branches(*, pr_id=None, onto_branch=None) -> dict[str, Any]`: Rebase stacked PR
      branches, force-push with lease, and retarget GitHub PR base branches.
    - Inherits `create_or_checkout_branch`, `read_commit_trailers`, `format_commit_with_trailers`,
      `write_audit_round`, and `append_deferred_backlog` from `LocalGitBus`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

# Absolute path to this script's directory so sibling modules can be imported directly.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import post_tool_receipt
import schemas
import state_db
import yaml

# Maximum number of Cold-Firewall audit rounds permitted per PR before human escalation (SPEC §7.3).
MAX_AUDIT_ROUNDS: int = 5

# Regex parsing 'APPROVED (<head_sha>)' or 'CHANGES_REQUESTED (<head_sha>)' from PA-Audit-Verdict.
_AUDIT_VERDICT_TRAILER_RE = re.compile(
    r"^\s*(APPROVED|CHANGES_REQUESTED)(?:\s*\(\s*([0-9a-fA-F]{7,40})\s*\))?\s*$",
    re.IGNORECASE,
)

# Regex capturing the interior key-value payload of a '<!-- pa:audit ... -->' HTML comment header.
_PA_AUDIT_COMMENT_RE = re.compile(
    r"<!--\s*pa:audit\b(.*?)-->",
    re.DOTALL | re.IGNORECASE,
)

# Regex extracting 'key="val"', "key='val'", or 'key=val' pairs from a pa:audit comment header.
_KV_PAIR_RE = re.compile(
    r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>]+))"
)

# Regex matching the human-readable '**Audit Verdict:** APPROVED|CHANGES_REQUESTED' summary line.
_VERDICT_LINE_RE = re.compile(
    r"\*\*Audit Verdict:\*\*\s*(APPROVED|CHANGES_REQUESTED)\b",
    re.IGNORECASE,
)

# Regex extracting the numeric PR ID from a GitHub pull request URL ('.../pull/123').
_PR_URL_NUMBER_RE = re.compile(r"/pull/(\d+)(?:\b|/|$)")

# Regex extracting a full GitHub issue URL ('https://.../issues/123') from gh CLI stdout.
_ISSUE_URL_RE = re.compile(r"(https?://\S+/issues/\d+)")


def _gh_bin() -> str:
    """Return the `gh` executable path, respecting `PA_GH_BIN` environment override.

    Returns:
        Path or executable name for the GitHub CLI binary (defaults to `"gh"`).
    """
    return os.environ.get("PA_GH_BIN", "").strip() or "gh"


def _git_commit_with_fallback(
    real_root: Path,
    commit_msg: str,
    *,
    runner: common.Runner = common.run,
) -> subprocess.CompletedProcess[str]:
    """Run `git commit -m <msg>`, falling back to explicit author config if unset.

    Args:
        real_root: Resolved Git repository root directory.
        commit_msg: Formatted commit message string.
        runner: Subprocess execution callable.

    Returns:
        Completed subprocess result from `git commit`.
    """
    # --- Step 1: Attempt standard git commit using ambient repository/global identity ---
    res = runner(["git", "commit", "-m", commit_msg], cwd=real_root)
    # --- Step 2: Retry with ephemeral Principal Architect author config if identity is missing ---
    if res.returncode != 0:
        combined = f"{res.stderr or ''}\n{res.stdout or ''}".lower()
        if (
            "user.email" in combined
            or "user.name" in combined
            or "tell me who you are" in combined
            or "empty ident" in combined
        ):
            res = runner(
                [
                    "git",
                    "-c",
                    "user.name=Principal Architect",
                    "-c",
                    "user.email=pa@noreply.localhost",
                    "commit",
                    "-m",
                    commit_msg,
                ],
                cwd=real_root,
            )
    return res


def format_commit_with_trailers(
    subject: str,
    body: str | None = None,
    trailers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
) -> str:
    """Format a Git commit message with subject, optional body, and `Key: Value` trailers.

    Args:
        subject: Single-line commit subject (must be non-empty).
        body: Optional multi-line commit body paragraph.
        trailers: Optional mapping or sequence of `(key, value)` trailer pairs.

    Returns:
        Formatted commit message with blank-line-separated paragraphs and trailing `Key: Value`
        lines suitable for `git log --format=%(trailers:...)`.

    Raises:
        ValueError: If `subject` is empty or whitespace-only.
    """
    # --- Step 1: Validate subject and initialize message paragraphs ---
    subj = subject.strip()
    if not subj:
        raise ValueError("Commit subject must not be empty")

    parts: list[str] = [subj]
    if body is not None and body.strip():
        parts.append(body.strip())

    # --- Step 2: Format non-empty trailer pairs into a trailing block ---
    trailer_lines: list[str] = []
    if trailers is not None:
        items = trailers.items() if isinstance(trailers, Mapping) else trailers
        for key, val in items:
            k_str = str(key).strip()
            v_str = str(val).strip() if val is not None else ""
            if k_str and v_str:
                trailer_lines.append(f"{k_str}: {v_str}")

    if trailer_lines:
        parts.append("\n".join(trailer_lines))

    return "\n\n".join(parts)


def _parse_audit_verdict_trailer(raw_val: str) -> tuple[str | None, str | None]:
    """Parse `PA-Audit-Verdict` trailer value `<VERDICT> (<head_sha>)` or `<VERDICT>`.

    Args:
        raw_val: Raw trailer value extracted from `git log`.

    Returns:
        Tuple of `(verdict, head_sha)` where each element is `None` if absent.
    """
    # --- Step 1: Match canonical '<VERDICT> (<head_sha>)' pattern on the first line ---
    cleaned = raw_val.strip()
    if not cleaned:
        return None, None
    first_line = cleaned.splitlines()[0].strip()
    m = _AUDIT_VERDICT_TRAILER_RE.match(first_line)
    if m:
        verdict = m.group(1).upper()
        head_sha = m.group(2) if m.group(2) else None
        return verdict, head_sha

    # --- Step 2: Fall back to whitespace token splitting ---
    tokens = first_line.split()
    verdict_tok = tokens[0].upper() if tokens else None
    sha_tok: str | None = None
    if len(tokens) >= 2:
        cand = tokens[1].strip("()")
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", cand):
            sha_tok = cand
    return verdict_tok, sha_tok


def read_commit_trailers(
    repo_root: str | Path,
    *,
    rev_range: str | None = None,
    max_count: int | None = None,
    runner: common.Runner = common.run,
) -> list[dict[str, Any]]:
    """Read `PA-WorkOrder`, `PA-Verified-Hash`, and `PA-Audit-Verdict` trailers from `git log`.

    Args:
        repo_root: Path to the Git repository root.
        rev_range: Optional revision range (e.g. `"main..HEAD"`) passed to `git log`.
        max_count: Optional maximum number of commits to inspect (`-n<max_count>`).
        runner: Subprocess execution callable.

    Returns:
        List of commit dictionaries containing `sha`, `subject`, `wo_id`, `verified_hash`,
        `audit_verdict`, and `audit_head_sha`.
    """
    # --- Step 1: Construct git log command with binary field/record delimiters ---
    real_root = Path(os.path.realpath(repo_root))
    # Git commit subjects and %(trailers:...) expansions can contain spaces, colons, or embedded
    # newlines when a commit repeats a trailer key. Using ASCII NUL (%x00) to separate the SHA,
    # subject, and individual trailer values—and ASCII Record Separator (%x1e) to delimit commit
    # records—allows unambiguous single-pass splitting without line-wrapping corruption.
    fmt = (
        "%H%x00%s%x00"
        "%(trailers:key=PA-WorkOrder,valueonly=true)%x00"
        "%(trailers:key=PA-Verified-Hash,valueonly=true)%x00"
        "%(trailers:key=PA-Audit-Verdict,valueonly=true)%x1e"
    )
    cmd: list[str] = ["git", "log", f"--format={fmt}"]
    if max_count is not None:
        cmd.append(f"-n{int(max_count)}")
    if rev_range is not None and str(rev_range).strip():
        cmd.append(str(rev_range).strip())

    # --- Step 2: Execute git log and guard against empty or uninitialized repositories ---
    try:
        res = runner(cmd, cwd=real_root)
    except (OSError, subprocess.SubprocessError):
        return []

    if res.returncode != 0 or not res.stdout:
        return []

    # --- Step 3: Split %x1e records and %x00 fields into structured trailer dicts ---
    raw_out = res.stdout
    raw_records = raw_out.split("\x1e") if "\x1e" in raw_out else raw_out.splitlines()

    records: list[dict[str, Any]] = []
    for rec in raw_records:
        rec_clean = rec.strip("\r\n")
        if not rec_clean.strip():
            continue
        fields = rec_clean.split("\x00")
        if len(fields) < 2:
            continue

        sha = fields[0].strip()
        if not sha:
            continue
        subject = fields[1].strip()
        wo_raw = fields[2].strip() if len(fields) > 2 else ""
        vh_raw = fields[3].strip() if len(fields) > 3 else ""
        av_raw = fields[4].strip() if len(fields) > 4 else ""

        wo_id = wo_raw.splitlines()[0].strip() if wo_raw else None
        verified_hash = vh_raw.splitlines()[0].strip() if vh_raw else None
        audit_verdict, audit_head_sha = _parse_audit_verdict_trailer(av_raw)

        records.append(
            {
                "sha": sha,
                "subject": subject,
                "wo_id": wo_id or None,
                "verified_hash": verified_hash or None,
                "audit_verdict": audit_verdict,
                "audit_head_sha": audit_head_sha,
            }
        )

    return records


# Backwards-compatible function alias for callers referencing vcs_sync.read_trailers.
read_trailers = read_commit_trailers


def _count_findings(findings: Sequence[schemas.AuditFinding]) -> tuple[int, int, int]:
    """Return `(blocking, major, minor)` counts from a sequence of `AuditFinding` items.

    Args:
        findings: Sequence of validated `AuditFinding` objects from an `AuditReport`.

    Returns:
        Tuple of `(blocking_count, major_count, minor_count)`.
    """
    blocking = sum(1 for f in findings if f.id.upper().startswith("BLOCKING-"))
    major = sum(1 for f in findings if not f.id.upper().startswith("BLOCKING-"))
    minor = 0
    return blocking, major, minor


def format_pa_audit_comment(
    report: schemas.AuditReport,
    body_markdown: str | None = None,
) -> str:
    """Format a Cold-Firewall `AuditReport` with a machine-parseable `<!-- pa:audit ... -->` header.

    Args:
        report: Validated `AuditReport` instance.
        body_markdown: Optional pre-rendered Markdown body; if provided, missing header or verdict
            markers are prepended without overwriting existing sections.

    Returns:
        Complete Markdown string beginning with the `<!-- pa:audit ... -->` comment header.
    """
    # --- Step 1: Compute finding counts and build machine-parseable header + verdict line ---
    blocking, major, minor = _count_findings(report.findings)
    header_comment = (
        f"<!-- pa:audit pr_id={report.pr_id} round={report.audit_round} "
        f"head_sha={report.head_sha} verdict={report.verdict} "
        f"blocking={blocking} major={major} minor={minor} -->"
    )
    verdict_line = (
        f"**Audit Verdict:** {report.verdict} ({blocking} blocking, {major} non-blocking)"
    )

    # --- Step 2: Wrap existing Markdown body if provided ---
    if body_markdown is not None and body_markdown.strip():
        body_clean = body_markdown.strip()
        lines: list[str] = []
        if not _PA_AUDIT_COMMENT_RE.search(body_clean):
            lines.append(header_comment)
        if not _VERDICT_LINE_RE.search(body_clean):
            lines.append(verdict_line)
        lines.append(body_clean)
        return "\n\n".join(lines) + "\n"

    # --- Step 3: Synthesize default Section 1 (Scorecard) and Section 2 (Findings) Markdown ---
    findings_lines: list[str] = []
    if report.findings:
        for f in report.findings:
            loc = f"{f.file_path}:{f.line_range}" if f.line_range else f.file_path
            findings_lines.append(
                f"- **{f.id}** (`{f.axis}` — `{loc}`): {f.summary}\n"
                f"  - *Remediation:* {f.remediation}"
            )
    else:
        findings_lines.append("_No blocking or non-blocking findings._")

    findings_block = "\n".join(findings_lines)
    return (
        f"{header_comment}\n\n"
        f"# Cold-Firewall Audit — {report.pr_id} (Round {report.audit_round})\n\n"
        f"{verdict_line}\n\n"
        f"## 1. Audit Scorecard\n\n"
        f"- **PR:** `{report.pr_id}`\n"
        f"- **Round:** {report.audit_round}\n"
        f"- **Evaluated HEAD:** `{report.head_sha}`\n"
        f"- **Harness:** `{report.auditor_harness}`\n"
        f"- **Verdict:** `{report.verdict}`\n\n"
        f"## 2. Findings\n\n"
        f"{findings_block}\n"
    )


def parse_pa_audit_comment(text: str) -> dict[str, Any] | None:
    """Parse a `<!-- pa:audit ... -->` comment block (and optional frontmatter) into a dict.

    Args:
        text: Raw PR comment body or `AUDIT-round-<K>.md` file content.

    Returns:
        Dictionary of parsed audit metadata (`pr_id`, `audit_round`, `round`, `head_sha`,
        `verdict`, `blocking`, `major`, `minor`, `auditor_harness`, `github_pr`, `findings`), or
        `None` if no valid `pa:audit` marker is present.
    """
    # --- Step 1: Locate the <!-- pa:audit ... --> HTML comment block ---
    if not text or not text.strip():
        return None

    m = _PA_AUDIT_COMMENT_RE.search(text)
    if m is None:
        return None

    # --- Step 2: Parse key=value attributes (with YAML fallback) from comment interior ---
    inner = m.group(1).strip()
    kv_data: dict[str, Any] = {}

    for kv_match in _KV_PAIR_RE.finditer(inner):
        key = kv_match.group(1).strip()
        val = (
            kv_match.group(2)
            if kv_match.group(2) is not None
            else (kv_match.group(3) if kv_match.group(3) is not None else kv_match.group(4))
        )
        kv_data[key] = val

    if not kv_data and inner:
        try:
            loaded_yaml = yaml.safe_load(inner)
            if isinstance(loaded_yaml, Mapping):
                kv_data.update({str(k): v for k, v in loaded_yaml.items()})
        except yaml.YAMLError:
            return None

    # --- Step 3: Extract optional YAML frontmatter if text is a full AUDIT-round-<K>.md file ---
    fm_data: dict[str, Any] = {}
    if text.lstrip("\ufeff").startswith("---"):
        try:
            parsed_fm, _ = schemas.parse_document(text)
            if isinstance(parsed_fm, dict):
                fm_data = parsed_fm
        except Exception:  # noqa: BLE001
            fm_data = {}

    # --- Step 4: Merge and validate required audit fields and round bounds ---
    pr_id = str(kv_data.get("pr_id") or fm_data.get("pr_id") or "").strip()
    raw_round = (
        kv_data.get("round")
        if "round" in kv_data
        else (
            kv_data.get("audit_round")
            if "audit_round" in kv_data
            else fm_data.get("audit_round")
        )
    )
    head_sha = str(kv_data.get("head_sha") or fm_data.get("head_sha") or "").strip()
    verdict = str(kv_data.get("verdict") or fm_data.get("verdict") or "").strip().upper()

    if not verdict:
        vm = _VERDICT_LINE_RE.search(text)
        if vm:
            verdict = vm.group(1).upper()

    if not pr_id or raw_round is None or not head_sha or verdict not in (
        "APPROVED",
        "CHANGES_REQUESTED",
    ):
        return None

    try:
        audit_round = int(raw_round)
        blocking = int(kv_data.get("blocking", 0))
        major = int(kv_data.get("major", 0))
        minor = int(kv_data.get("minor", 0))
    except (TypeError, ValueError):
        return None

    if not (1 <= audit_round <= MAX_AUDIT_ROUNDS):
        return None

    # --- Step 5: Reconcile findings list and severity counts ---
    findings_raw = fm_data.get("findings")
    if not isinstance(findings_raw, list):
        findings_raw = kv_data.get("findings") if isinstance(kv_data.get("findings"), list) else []

    if findings_raw and blocking == 0 and major == 0:
        for item in findings_raw:
            fid = str(item.get("id", "")) if isinstance(item, Mapping) else ""
            if fid.upper().startswith("BLOCKING-"):
                blocking += 1
            elif fid:
                major += 1

    return {
        "pr_id": pr_id,
        "audit_round": audit_round,
        "round": audit_round,
        "head_sha": head_sha,
        "verdict": verdict,
        "blocking": blocking,
        "major": major,
        "minor": minor,
        "auditor_harness": str(
            kv_data.get("auditor_harness") or fm_data.get("auditor_harness") or "antigravity"
        ),
        "github_pr": fm_data.get("github_pr"),
        "findings": list(findings_raw),
    }


def _find_pr_dir_and_project(
    ws_dir: Path,
    pr_id: str,
) -> tuple[Path, schemas.Document[schemas.ProjectSpec] | None]:
    """Locate `<pr_dir>` and optional loaded `PROJECT.md` for `pr_id` under `ws_dir`.

    Args:
        ws_dir: Active Principal Architect workspace directory.
        pr_id: PR identifier (`PR-01`), slug, branch name, or GitHub PR number string.

    Returns:
        Tuple of `(pr_dir_path, loaded_project_doc_or_none)`.
    """
    # --- Step 1: Scan pr-*/PROJECT.md files for matching PR ID, slug, branch, or github_pr ---
    pr_norm = pr_id.strip().upper()
    slug_norm = pr_id.strip().lower()

    for proj_md in sorted(ws_dir.glob("pr-*/PROJECT.md")):
        pr_dir = proj_md.parent
        try:
            proj_doc = schemas.load_project(proj_md)
        except Exception:  # noqa: BLE001
            if pr_dir.name.lower() == slug_norm or pr_dir.name.lower().startswith(
                f"{slug_norm}-"
            ):
                return pr_dir, None
            continue

        if (
            proj_doc.spec.charter.pr_id.upper() == pr_norm
            or proj_doc.spec.charter.slug.lower() == slug_norm
            or pr_dir.name.lower() == slug_norm
            or proj_doc.spec.charter.branch == pr_id.strip()
            or (
                proj_doc.spec.github_pr is not None
                and str(proj_doc.spec.github_pr) == pr_id.strip()
            )
        ):
            return pr_dir, proj_doc

    # --- Step 2: Check pr-* directories without a valid PROJECT.md ---
    for cand_dir in sorted(ws_dir.glob("pr-*")):
        if cand_dir.is_dir():
            name_low = cand_dir.name.lower()
            if name_low == slug_norm or name_low.startswith(f"{slug_norm}-"):
                proj_md = cand_dir / "PROJECT.md"
                if proj_md.is_file():
                    try:
                        return cand_dir, schemas.load_project(proj_md)
                    except Exception:  # noqa: BLE001
                        return cand_dir, None
                return cand_dir, None

    # --- Step 3: Synthesize deterministic fallback directory path ---
    fallback_name = slug_norm if slug_norm.startswith("pr-") else f"pr-{slug_norm}"
    return ws_dir / fallback_name, None


def _coerce_audit_report_and_sections(
    audit_source: (
        str
        | Path
        | schemas.AuditReport
        | schemas.Document[schemas.AuditReport]
        | Mapping[str, Any]
    ),
) -> tuple[schemas.AuditReport, list[schemas.Section]]:
    """Coerce `audit_source` into a validated `(AuditReport, sections)` pair.

    Args:
        audit_source: File path, raw Markdown/comment string, `AuditReport` model,
            `Document[AuditReport]`, or dictionary mapping.

    Returns:
        Tuple of `(validated_audit_report, markdown_sections)`.

    Raises:
        FileNotFoundError: If `audit_source` is a path that does not exist on disk.
        TypeError: If `audit_source` is of an unsupported type.
        ValueError: If `audit_source` cannot be parsed into a valid `AuditReport`.
    """
    # --- Step 1: Handle pre-parsed Document, AuditReport, or Mapping inputs ---
    if isinstance(audit_source, schemas.Document):
        report = schemas.AuditReport.model_validate(audit_source.spec.model_dump())
        return report, list(audit_source.sections)

    if isinstance(audit_source, schemas.AuditReport):
        report = schemas.AuditReport.model_validate(audit_source.model_dump())
        return report, []

    if isinstance(audit_source, Mapping):
        data = dict(audit_source)
        if "round" in data and "audit_round" not in data:
            data["audit_round"] = data.pop("round")
        data_filtered = {
            k: v
            for k, v in data.items()
            if k
            in (
                "schema_version",
                "pr_id",
                "github_pr",
                "audit_round",
                "head_sha",
                "auditor_harness",
                "verdict",
                "findings",
            )
        }
        report = schemas.AuditReport.model_validate(data_filtered)
        return report, []

    # --- Step 2: Load raw text from Path or string input ---
    raw_text: str | None = None
    if isinstance(audit_source, Path):
        if not audit_source.is_file():
            raise FileNotFoundError(f"Audit source file not found: {audit_source}")
        raw_text = audit_source.read_text(encoding="utf-8")
    elif isinstance(audit_source, str):
        stripped = audit_source.lstrip("\ufeff")
        if not stripped.startswith("---") and "<!--" not in stripped:
            cand_path = Path(audit_source)
            if cand_path.is_file():
                raw_text = cand_path.read_text(encoding="utf-8")
            else:
                raise FileNotFoundError(f"Audit source file not found: {audit_source}")
        else:
            raw_text = audit_source
    else:
        raise TypeError(f"Unsupported audit_source type: {type(audit_source)!r}")

    # --- Step 3: Parse YAML frontmatter document or <!-- pa:audit ... --> comment block ---
    if raw_text.lstrip("\ufeff").startswith("---"):
        fm_data, sections = schemas.parse_document(raw_text)
        report = schemas.AuditReport.model_validate(fm_data)
        return report, sections

    parsed_comment = parse_pa_audit_comment(raw_text)
    if parsed_comment is not None:
        report = schemas.AuditReport.model_validate(
            {
                "pr_id": parsed_comment["pr_id"],
                "github_pr": parsed_comment.get("github_pr"),
                "audit_round": parsed_comment["audit_round"],
                "head_sha": parsed_comment["head_sha"],
                "auditor_harness": parsed_comment.get("auditor_harness", "antigravity"),
                "verdict": parsed_comment["verdict"],
                "findings": parsed_comment.get("findings", []),
            }
        )
        _, sections = schemas.parse_document(f"---\nschema_version: 1\n---\n\n{raw_text}")
        return report, sections

    raise ValueError("Could not parse AuditReport from audit_source")


def write_audit_round(
    repo_root: str | Path,
    pr_id: str,
    audit_source: (
        str
        | Path
        | schemas.AuditReport
        | schemas.Document[schemas.AuditReport]
        | Mapping[str, Any]
    ),
    *,
    commit: bool = True,
    runner: common.Runner = common.run,
) -> Path:
    """Validate `AuditReport`, write `<pr_dir>/AUDIT-round-<K>.md`, update `PROJECT.md`, and commit.

    Args:
        repo_root: Path to the Git repository root.
        pr_id: Target PR identifier (`"PR-01"`).
        audit_source: Audit report source (file path, Markdown string, dict, or `AuditReport`).
        commit: Whether to stage and commit the written artifacts with a `PA-Audit-Verdict` trailer.
        runner: Subprocess execution callable.

    Returns:
        Path to the written `<pr_dir>/AUDIT-round-<K>.md` file.

    Raises:
        ValueError: If `audit_round` is outside `1..MAX_AUDIT_ROUNDS` or `pr_id` mismatches.
        RuntimeError: If `PROJECT.md` `charter_hash` verification or Git staging/commit fails.
    """
    # --- Step 1: Coerce and validate AuditReport against round bounds and target PR ID ---
    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)

    report, sections = _coerce_audit_report_and_sections(audit_source)
    if not (1 <= report.audit_round <= MAX_AUDIT_ROUNDS):
        raise ValueError(
            f"audit_round must be between 1 and {MAX_AUDIT_ROUNDS}, got {report.audit_round}"
        )

    target_pr_norm = pr_id.strip().upper()
    if report.pr_id.upper() != target_pr_norm:
        raise ValueError(
            f"AuditReport pr_id '{report.pr_id}' does not match target PR '{pr_id}'"
        )

    # --- Step 2: Format and write <pr_dir>/AUDIT-round-<K>.md ---
    pr_dir, proj_doc = _find_pr_dir_and_project(ws_dir, report.pr_id)
    pr_dir.mkdir(parents=True, exist_ok=True)

    existing_body = "\n".join(s.full_text() for s in sections).strip()
    formatted_body = format_pa_audit_comment(report, existing_body if existing_body else None)
    _, ensured_sections = schemas.parse_document(
        f"---\nschema_version: 1\n---\n\n{formatted_body}"
    )

    audit_path = pr_dir / f"AUDIT-round-{report.audit_round}.md"
    audit_path.write_text(
        schemas.dump_document(report, ensured_sections),
        encoding="utf-8",
    )

    paths_to_stage: list[str] = [audit_path.resolve().relative_to(real_root).as_posix()]

    # --- Step 3: Update PROJECT.md status without mutating Part I charter_hash ---
    proj_md = pr_dir / "PROJECT.md"
    if proj_doc is not None and proj_md.is_file():
        new_status = (
            schemas.PRState.AUDIT_APPROVED
            if report.verdict == "APPROVED"
            else schemas.PRState.CHANGES_REQUESTED
        )
        if proj_doc.spec.status != new_status:
            proj_doc.spec.status = new_status
            proj_md.write_text(
                schemas.dump_document(proj_doc.spec, proj_doc.sections),
                encoding="utf-8",
            )
            if (
                proj_doc.spec.charter.charter_locked
                and proj_doc.spec.charter.charter_hash
                and not schemas.verify_charter_hash(proj_md)
            ):
                raise RuntimeError(
                    f"PROJECT.md charter_hash verification failed after updating status: {proj_md}"
                )
            paths_to_stage.append(proj_md.resolve().relative_to(real_root).as_posix())

    # --- Step 4: Commit staged artifacts with PA-Audit-Verdict trailer if requested ---
    if commit:
        add_res = runner(["git", "add", "--", *paths_to_stage], cwd=real_root)
        if add_res.returncode != 0:
            raise RuntimeError(f"git add failed: {add_res.stderr.strip()}")

        commit_msg = format_commit_with_trailers(
            f"audit({report.pr_id.lower()}): round {report.audit_round} — {report.verdict}",
            trailers=[("PA-Audit-Verdict", f"{report.verdict} ({report.head_sha})")],
        )
        commit_res = _git_commit_with_fallback(real_root, commit_msg, runner=runner)
        if commit_res.returncode != 0:
            raise RuntimeError(
                f"git commit failed: {commit_res.stderr.strip() or commit_res.stdout.strip()}"
            )

    # --- Step 5: Cache latest audit metadata in .state/state.db if present ---
    db_file = ws_dir / ".state" / "state.db"
    if db_file.is_file():
        audit_meta = {
            "pr_id": report.pr_id.upper(),
            "github_pr": report.github_pr,
            "audit_round": report.audit_round,
            "head_sha": report.head_sha,
            "auditor_harness": report.auditor_harness,
            "verdict": report.verdict,
            "findings_count": len(report.findings),
        }
        with state_db.StateDB(db_file) as db:
            meta_json = json.dumps(audit_meta)
            db.set_config(f"latest_audit:{report.pr_id.upper()}", meta_json)
            db.set_config(f"last_audit_{report.pr_id.upper()}", meta_json)

    return audit_path


def append_deferred_backlog(
    repo_root: str | Path,
    *,
    title: str,
    summary: str = "",
    pr_id: str | None = None,
    wo_id: str | None = None,
    labels: Sequence[str] = ("pa:deferred",),
    file_path: str | None = None,
) -> Path:
    """Append a deferred out-of-scope finding to `<workspace_dir>/DEFERRED_BACKLOG.md`.

    Args:
        repo_root: Path to the Git repository root.
        title: Concise heading for the deferred item (must be non-empty).
        summary: Optional description or remediation notes.
        pr_id: Optional PR identifier where the item was discovered.
        wo_id: Optional Work Order identifier where the item was discovered.
        labels: Sequence of classification labels (defaults to `("pa:deferred",)`).
        file_path: Optional repository-relative file path associated with the finding.

    Returns:
        Path to `<workspace_dir>/DEFERRED_BACKLOG.md`.

    Raises:
        ValueError: If `title` is empty or whitespace-only.
    """
    # --- Step 1: Validate title and resolve DEFERRED_BACKLOG.md path ---
    title_clean = title.strip()
    if not title_clean:
        raise ValueError("Deferred backlog title must not be empty")

    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)
    ws_dir.mkdir(parents=True, exist_ok=True)
    backlog_path = ws_dir / "DEFERRED_BACKLOG.md"

    # --- Step 2: Format metadata bullet and summary section ---
    now_iso = state_db.utc_now_iso()
    labels_list = [str(lbl).strip() for lbl in labels if str(lbl).strip()] or ["pa:deferred"]
    labels_str = ", ".join(f"`{lbl}`" for lbl in labels_list)

    meta_parts: list[str] = [f"**Created:** `{now_iso}`"]
    if pr_id:
        meta_parts.append(f"**PR:** `{pr_id.strip()}`")
    if wo_id:
        meta_parts.append(f"**WO:** `{wo_id.strip()}`")
    meta_parts.append(f"**Labels:** {labels_str}")
    if file_path:
        meta_parts.append(f"**File:** `{file_path.strip()}`")

    entry_lines = [
        f"## {title_clean}",
        "",
        f"- {' | '.join(meta_parts)}",
    ]
    if summary.strip():
        entry_lines.append(f"- **Summary:** {summary.strip()}")
    entry_block = "\n".join(entry_lines) + "\n"

    # --- Step 3: Initialize or append to DEFERRED_BACKLOG.md ---
    if not backlog_path.is_file():
        header = (
            "# Deferred Backlog\n\n"
            "Out-of-scope findings and deferred engineering items recorded by "
            "Principal Architect agents.\n\n"
        )
        backlog_path.write_text(header + entry_block, encoding="utf-8")
    else:
        existing = backlog_path.read_text(encoding="utf-8")
        sep = "\n" if existing.endswith("\n") else "\n\n"
        backlog_path.write_text(existing + sep + entry_block, encoding="utf-8")

    return backlog_path


def _infer_pr_id_from_wo_id(wo_id: str) -> str:
    """Infer `PR-NN` from `WO-NN.M` (e.g. `WO-03.1` -> `PR-03`).

    Args:
        wo_id: Work Order identifier string.

    Returns:
        Inferred `PR-NN` identifier, or `"PR-00"` if `wo_id` does not match `WO-NN.M`.
    """
    m = re.match(r"^WO-(\d+[a-z]?)\.\d+$", wo_id.strip(), re.IGNORECASE)
    if m:
        return f"PR-{m.group(1).upper()}"
    return "PR-00"


def _is_branch_merged(
    repo_root: Path,
    branch: str,
    base_branch: str,
    runner: common.Runner = common.run,
) -> bool:
    """Check whether `branch` is an ancestor of `base_branch` (i.e., merged).

    Uses `git merge-base --is-ancestor` to detect both `git merge` and `gh pr merge`.

    Args:
        repo_root: Path to the Git repository root.
        branch: The feature branch name to check.
        base_branch: The target base branch (e.g., 'main').
        runner: Subprocess execution callable.

    Returns:
        True if `branch` exists and is an ancestor of `base_branch`; False otherwise.
    """
    # --- Step 1: Run git merge-base --is-ancestor and interpret returncode ---
    try:
        result = runner(
            ["git", "merge-base", "--is-ancestor", branch, base_branch],
            cwd=repo_root,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _derive_pr_status(
    proj_doc: schemas.Document[schemas.ProjectSpec],
    repo_root: Path,
    runner: common.Runner = common.run,
    *,
    latest_audit_verdict: str | None = None,
) -> schemas.PRState | None:
    """Derive canonical PR status from WO composition + VCS merge evidence.

    Returns the derived status, or None if the current status should not change.
    Never regresses from GRADUATED or ARCHIVED. Does NOT auto-promote to GRADUATED —
    returns attention_queue signals instead.

    Args:
        proj_doc: Loaded and validated PROJECT.md document.
        repo_root: Path to the Git repository root.
        runner: Subprocess execution callable.
        latest_audit_verdict: Optional audit verdict string ('APPROVED' or 'CHANGES_REQUESTED').

    Returns:
        Derived PRState if it differs from current and is a valid forward transition,
        or None if no change is warranted.
    """
    # --- Step 1: Guard terminal states — never regress from GRADUATED or ARCHIVED ---
    current = proj_doc.spec.status
    if current in (schemas.PRState.GRADUATED, schemas.PRState.ARCHIVED):
        return None

    # --- Step 2: Analyze WO composition ---
    wos = proj_doc.spec.work_orders
    if not wos:
        return None

    all_completed = all(w.status == schemas.WorkOrderStatus.COMPLETED for w in wos)
    any_in_progress = any(w.status == schemas.WorkOrderStatus.IN_PROGRESS for w in wos)
    any_escalated = any(
        w.status in (schemas.WorkOrderStatus.ESCALATED_TO_PA, schemas.WorkOrderStatus.BLOCKED)
        for w in wos
    )

    # --- Step 3: Check VCS merge evidence ---
    charter = proj_doc.spec.charter
    is_merged = _is_branch_merged(repo_root, charter.branch, charter.base_branch, runner)

    # If merged but not yet GRADUATED, signal via attention_queue (not auto-promote)
    if is_merged and current != schemas.PRState.GRADUATED:
        return None

    # --- Step 4: Derive forward-only status transitions ---
    if (
        latest_audit_verdict == "APPROVED"
        and all_completed
        and current != schemas.PRState.AUDIT_APPROVED
    ):
        return schemas.PRState.AUDIT_APPROVED

    if latest_audit_verdict == "CHANGES_REQUESTED":
        return schemas.PRState.CHANGES_REQUESTED

    if all_completed and current in (
        schemas.PRState.PLANNED,
        schemas.PRState.APPROVED,
        schemas.PRState.IN_PROGRESS,
    ):
        return schemas.PRState.STAGED_FOR_AUDIT

    if (any_in_progress or any_escalated) and current in (
        schemas.PRState.PLANNED,
        schemas.PRState.APPROVED,
    ):
        return schemas.PRState.IN_PROGRESS

    return None


def _local_sync_state(
    repo_root: str | Path,
    *,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Rebuild `.state/state.db` and reconcile `PROJECT.md` rows from git trailers and specs.

    Args:
        repo_root: Path to the Git repository root.
        runner: Subprocess execution callable.

    Returns:
        Summary dictionary with `vcs_mode`, `synced_receipts`, `synced_audits`, `synced_wos`,
        `trailers_found`, and `last_vcs_sync_at`.

    Raises:
        RuntimeError: If `PROJECT.md` `charter_hash` verification fails after row reconciliation.
    """
    # --- Step 1: Resolve workspace paths and index git commit trailers by WO-ID and PR-ID ---
    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)
    state_dir = ws_dir / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    db_file = state_dir / "state.db"

    trailers = read_commit_trailers(real_root, runner=runner)
    wo_trailer_map: dict[str, dict[str, Any]] = {}
    audit_trailer_map: dict[str, dict[str, Any]] = {}

    for rec in trailers:
        wo_id = rec.get("wo_id")
        if isinstance(wo_id, str) and wo_id.upper() not in wo_trailer_map:
            wo_trailer_map[wo_id.upper()] = rec
        if rec.get("audit_verdict"):
            subj = str(rec.get("subject") or "")
            m_pr = re.search(r"\b(pr-\d+[a-z]?)\b", subj, re.IGNORECASE)
            if m_pr:
                pr_key = m_pr.group(1).upper()
                if pr_key not in audit_trailer_map:
                    audit_trailer_map[pr_key] = rec

    count_receipts = 0
    count_audits = 0
    count_wos = 0
    repair_log: list[str] = []
    processed_wo_ids: set[str] = set()

    # --- Step 2: Open state.db and scan every pr-* directory in the workspace ---
    with state_db.StateDB(db_file) as db:
        vcs_mode = db.get_config("vcs_mode") or "local_git"
        db.set_config("vcs_mode", vcs_mode)

        if ws_dir.is_dir():
            for pr_dir in sorted(ws_dir.glob("pr-*")):
                if not pr_dir.is_dir():
                    continue
                proj_md = pr_dir / "PROJECT.md"
                proj_doc: schemas.Document[schemas.ProjectSpec] | None = None
                if proj_md.is_file():
                    try:
                        proj_doc = schemas.load_project(proj_md)
                    except Exception:  # noqa: BLE001
                        try:
                            proj_doc, proj_warnings = schemas.load_project_tolerant(proj_md)
                            for w in proj_warnings:
                                repair_log.append(f"{proj_md.name}: {w}")
                            schemas.repair_document_yaml(proj_md, proj_doc.spec, proj_doc.sections)
                        except Exception:  # noqa: BLE001
                            proj_doc = None

                # --- Step 3: Reconcile WORKORDER.md receipts and open escalations ---
                wo_docs_by_id: dict[str, schemas.Document[schemas.WorkOrderSpec]] = {}
                for wo_md in sorted(pr_dir.glob("wo*/WORKORDER.md")):
                    if not wo_md.is_file():
                        continue
                    try:
                        wdoc = schemas.load_workorder(wo_md)
                    except Exception:  # noqa: BLE001, S112
                        # --- Tolerant fallback: parse with lenient schema, repair in-place ---
                        try:
                            wdoc, warnings = schemas.load_workorder_tolerant(wo_md)
                            for w in warnings:
                                repair_log.append(f"{wo_md.name}: {w}")
                            schemas.repair_document_yaml(wo_md, wdoc.spec, wdoc.sections)
                        except Exception:  # noqa: BLE001, S112
                            continue
                    wo_key = wdoc.spec.wo_id.upper()
                    wo_docs_by_id[wo_key] = wdoc
                    processed_wo_ids.add(wo_key)

                    t_rec = wo_trailer_map.get(wo_key)
                    is_completed = wdoc.spec.status == schemas.WorkOrderStatus.COMPLETED or (
                        t_rec is not None and bool(t_rec.get("verified_hash"))
                    )
                    if is_completed:
                        tree_hash = (
                            str(t_rec["verified_hash"])
                            if (t_rec and t_rec.get("verified_hash"))
                            else post_tool_receipt.compute_tree_hash(
                                real_root, wdoc.spec.allowed_files
                            )
                        )
                        receipt_id = (
                            wdoc.spec.completion.receipt_id
                            if (wdoc.spec.completion and wdoc.spec.completion.receipt_id)
                            else f"rcpt_{tree_hash[:12]}"
                        )
                        git_head_sha = (
                            str(t_rec["sha"])
                            if (t_rec and t_rec.get("sha"))
                            else (
                                wdoc.spec.completion.commit_sha
                                if wdoc.spec.completion
                                else None
                            )
                        )
                        post_tool_receipt._upsert_receipt(
                            db,
                            wo_id=wdoc.spec.wo_id,
                            pr_id=wdoc.spec.pr_id,
                            cmd=wdoc.spec.verification_command,
                            exit_code=0,
                            tree_hash=tree_hash,
                            git_head_sha=git_head_sha,
                            valid=1,
                            receipt_id=receipt_id,
                        )
                        count_receipts += 1

                    if (
                        wdoc.spec.status
                        in (
                            schemas.WorkOrderStatus.ESCALATED_TO_PA,
                            schemas.WorkOrderStatus.BLOCKED,
                        )
                        and wdoc.spec.completion is not None
                        and wdoc.spec.completion.escalation_request is not None
                    ):
                        esc_req = wdoc.spec.completion.escalation_request
                        existing_open = db.open_escalations(
                            pr_id=wdoc.spec.pr_id, wo_id=wdoc.spec.wo_id
                        )
                        if not any(
                            e.get("reason_code") == esc_req.reason_code for e in existing_open
                        ):
                            db.insert_escalation(
                                level="wo_to_pa",
                                source_role="engineer",
                                target_role=esc_req.target_role,
                                pr_id=wdoc.spec.pr_id,
                                wo_id=wdoc.spec.wo_id,
                                blocker_type=esc_req.blocker_type,
                                reason_code=esc_req.reason_code,
                                requested_files=esc_req.requested_files,
                                summary=esc_req.summary,
                                status="OPEN",
                            )

                # --- Step 4: Reconcile PROJECT.md work_orders summary rows ---
                if proj_doc is not None:
                    project_modified = False
                    for row in proj_doc.spec.work_orders:
                        row_key = row.id.upper()
                        wdoc = wo_docs_by_id.get(row_key)
                        t_rec = wo_trailer_map.get(row_key)

                        new_status = row.status
                        new_attempts = row.attempts
                        new_sha = row.commit_sha

                        if wdoc is not None:
                            if (
                                wdoc.spec.status == schemas.WorkOrderStatus.COMPLETED
                                or new_status == schemas.WorkOrderStatus.PENDING
                            ):
                                new_status = wdoc.spec.status
                            if wdoc.spec.completion is not None:
                                new_attempts = max(new_attempts, wdoc.spec.completion.attempt_num)
                                if wdoc.spec.completion.commit_sha:
                                    new_sha = wdoc.spec.completion.commit_sha

                        if t_rec is not None:
                            if t_rec.get("sha"):
                                new_sha = str(t_rec["sha"])
                            if (
                                t_rec.get("verified_hash")
                                and new_status == schemas.WorkOrderStatus.PENDING
                            ):
                                new_status = schemas.WorkOrderStatus.COMPLETED
                                new_attempts = max(new_attempts, 1)

                        if (new_status, new_attempts, new_sha) != (
                            row.status,
                            row.attempts,
                            row.commit_sha,
                        ):
                            row.status = new_status
                            row.attempts = new_attempts
                            row.commit_sha = new_sha
                            project_modified = True

                        count_wos += 1

                    # --- Step 4b: Derive PR status from WO composition + VCS evidence ---
                    # Get latest audit verdict for this PR
                    pr_id_upper = proj_doc.spec.charter.pr_id.upper()
                    latest_verdict: str | None = None
                    audit_trailer = audit_trailer_map.get(pr_id_upper)
                    if audit_trailer and audit_trailer.get("audit_verdict"):
                        latest_verdict = str(audit_trailer["audit_verdict"]).upper()

                    derived_status = _derive_pr_status(
                        proj_doc,
                        real_root,
                        runner=runner,
                        latest_audit_verdict=latest_verdict,
                    )

                    if derived_status is not None and derived_status != proj_doc.spec.status:
                        proj_doc.spec.status = derived_status
                        project_modified = True

                    # Check for ungraduated merged branches → attention_queue
                    branch = proj_doc.spec.charter.branch
                    base_branch = proj_doc.spec.charter.base_branch
                    if (
                        proj_doc.spec.status != schemas.PRState.GRADUATED
                        and _is_branch_merged(real_root, branch, base_branch, runner=runner)
                    ):
                        attn_id = f"attn_ungraduated_{pr_id_upper}"
                        existing = db.conn.execute(
                            "SELECT 1 FROM attention_queue WHERE item_id = ? AND status = 'OPEN'",
                            (attn_id,),
                        ).fetchone()
                        if existing is None:
                            db.enqueue(
                                kind="ungraduated_merge",
                                title=f"{pr_id_upper}: Branch merged but not graduated — run `pa pr graduate {pr_id_upper}`",
                                priority=5,
                                pr_id=pr_id_upper,
                                item_id=attn_id,
                            )

                    # Check for all-completed WOs with stale status
                    wos = proj_doc.spec.work_orders
                    if (
                        wos
                        and all(w.status == schemas.WorkOrderStatus.COMPLETED for w in wos)
                        and proj_doc.spec.status in (schemas.PRState.PLANNED, schemas.PRState.APPROVED, schemas.PRState.IN_PROGRESS)
                    ):
                        attn_id = f"attn_stale_status_{pr_id_upper}"
                        existing = db.conn.execute(
                            "SELECT 1 FROM attention_queue WHERE item_id = ? AND status = 'OPEN'",
                            (attn_id,),
                        ).fetchone()
                        if existing is None:
                            db.enqueue(
                                kind="stale_pr_status",
                                title=f"{pr_id_upper}: All WOs completed but PR status is {proj_doc.spec.status.value}",
                                priority=5,
                                pr_id=pr_id_upper,
                                item_id=attn_id,
                            )

                    if project_modified:
                        proj_md.write_text(
                            schemas.dump_document(proj_doc.spec, proj_doc.sections),
                            encoding="utf-8",
                        )
                        if (
                            proj_doc.spec.charter.charter_locked
                            and proj_doc.spec.charter.charter_hash
                            and not schemas.verify_charter_hash(proj_md)
                        ):
                            raise RuntimeError(
                                f"PROJECT.md charter_hash check failed during sync_state: {proj_md}"
                            )

                # --- Step 5: Reconcile AUDIT-round-*.md files in this PR directory ---
                audit_docs: list[schemas.Document[schemas.AuditReport]] = []
                for audit_md in sorted(pr_dir.glob("AUDIT-round-*.md")):
                    if not audit_md.is_file():
                        continue
                    try:
                        audit_docs.append(schemas.load_audit(audit_md))
                    except Exception:  # noqa: BLE001, S112
                        continue

                if audit_docs:
                    audit_docs.sort(key=lambda d: d.spec.audit_round)
                    top_report = audit_docs[-1].spec
                    pr_id_upper = top_report.pr_id.upper()
                    audit_meta = {
                        "pr_id": pr_id_upper,
                        "github_pr": top_report.github_pr,
                        "audit_round": top_report.audit_round,
                        "head_sha": top_report.head_sha,
                        "auditor_harness": top_report.auditor_harness,
                        "verdict": top_report.verdict,
                        "findings_count": len(top_report.findings),
                    }
                    meta_json = json.dumps(audit_meta)
                    db.set_config(f"latest_audit:{pr_id_upper}", meta_json)
                    db.set_config(f"last_audit_{pr_id_upper}", meta_json)
                    count_audits += 1

        # --- Step 6: Reconcile commit trailers for WOs without a local WORKORDER.md file ---
        for wo_key, t_rec in wo_trailer_map.items():
            if wo_key in processed_wo_ids:
                continue
            v_hash = t_rec.get("verified_hash")
            if not v_hash:
                continue
            v_hash_str = str(v_hash)
            pr_id_inferred = _infer_pr_id_from_wo_id(wo_key)
            post_tool_receipt._upsert_receipt(
                db,
                wo_id=wo_key,
                pr_id=pr_id_inferred,
                cmd="reconciled-from-git-trailer",
                exit_code=0,
                tree_hash=v_hash_str,
                git_head_sha=str(t_rec.get("sha") or ""),
                valid=1,
                receipt_id=f"rcpt_{v_hash_str[:12]}",
            )
            count_receipts += 1

        sync_ts = state_db.utc_now_iso()
        db.set_config("last_vcs_sync_at", sync_ts)

    return {
        "vcs_mode": vcs_mode,
        "synced_receipts": count_receipts,
        "synced_audits": count_audits,
        "synced_wos": count_wos,
        "trailers_found": len(trailers),
        "last_vcs_sync_at": sync_ts,
        "repairs": repair_log,
    }


def create_or_checkout_branch(
    repo_root: str | Path,
    branch: str,
    base_branch: str = "main",
    *,
    runner: common.Runner = common.run,
) -> str:
    """Create `<branch>` from `<base_branch>` if it does not exist, or check it out if it does.

    Args:
        repo_root: Path to the Git repository root.
        branch: Target branch name to create or check out.
        base_branch: Base branch ref used when creating a new branch (default `"main"`).
        runner: Subprocess execution callable.

    Returns:
        The resulting `HEAD` commit SHA after checkout.

    Raises:
        ValueError: If `branch` is empty or whitespace-only.
        RuntimeError: If `git checkout` or `git rev-parse HEAD` fails.
    """
    # --- Step 1: Validate branch arguments ---
    branch_clean = branch.strip()
    base_clean = base_branch.strip() or "main"
    if not branch_clean:
        raise ValueError("branch name must not be empty")

    # --- Step 2: Check whether refs/heads/<branch> exists and check out accordingly ---
    real_root = Path(os.path.realpath(repo_root))
    ref_res = runner(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_clean}"],
        cwd=real_root,
    )
    if ref_res.returncode == 0:
        co_res = runner(["git", "checkout", branch_clean], cwd=real_root)
    else:
        co_res = runner(
            ["git", "checkout", "-b", branch_clean, base_clean],
            cwd=real_root,
        )

    if co_res.returncode != 0:
        raise RuntimeError(
            f"Failed to create or checkout branch '{branch_clean}' (base '{base_clean}'): "
            f"{co_res.stderr.strip() or co_res.stdout.strip()}"
        )

    # --- Step 3: Resolve and return the checked-out HEAD SHA ---
    head_res = runner(["git", "rev-parse", "HEAD"], cwd=real_root)
    if head_res.returncode != 0 or not head_res.stdout.strip():
        raise RuntimeError(
            f"Failed to resolve HEAD after checking out '{branch_clean}': "
            f"{head_res.stderr.strip()}"
        )
    return head_res.stdout.strip()


def _collect_restack_targets(
    real_root: Path,
    ws_dir: Path,
    pr_id: str | None,
    onto_branch: str | None,
    runner: common.Runner,
) -> list[tuple[str, str, str]]:
    """Return ordered `(pr_id, branch, base_branch)` tuples for `restack_branches`.

    Args:
        real_root: Resolved Git repository root directory.
        ws_dir: Active Principal Architect workspace directory.
        pr_id: Optional target PR ID or branch name filter.
        onto_branch: Optional explicit target base branch override.
        runner: Subprocess execution callable.

    Returns:
        Ordered list of `(pr_id, branch_name, onto_base_branch)` tuples to rebase.
    """
    # --- Step 1: Collect declared PR stack branches from PROGRAM.md and PROJECT.md files ---
    targets: list[tuple[str, str, str]] = []
    seen_branches: set[str] = set()

    if ws_dir.is_dir():
        for prog_md in sorted(ws_dir.glob("programme-*/PROGRAM.md")):
            if not prog_md.is_file():
                continue
            try:
                prog_doc = schemas.load_program(prog_md)
            except Exception:  # noqa: BLE001, S112
                continue
            for node in prog_doc.spec.prs:
                if node.branch not in seen_branches:
                    seen_branches.add(node.branch)
                    targets.append((node.id, node.branch, node.base_branch))

        for proj_md in sorted(ws_dir.glob("pr-*/PROJECT.md")):
            if not proj_md.is_file():
                continue
            try:
                proj_doc = schemas.load_project(proj_md)
            except Exception:  # noqa: BLE001, S112
                continue
            ch = proj_doc.spec.charter
            if ch.branch not in seen_branches:
                seen_branches.add(ch.branch)
                targets.append((ch.pr_id, ch.branch, ch.base_branch))

    # --- Step 2: Discover feat/pr-* branches from local git refs when invoked from main ---
    refs_res = runner(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        cwd=real_root,
    )
    if refs_res.returncode == 0 and refs_res.stdout:
        for line in sorted(refs_res.stdout.splitlines()):
            br_name = line.strip()
            if not br_name or br_name in seen_branches:
                continue
            m_feat = re.match(
                r"^(?:feat/)?(pr-(\d+[a-z]?)(?:-[a-z0-9-]+)?)$",
                br_name,
                re.IGNORECASE,
            )
            if m_feat:
                slug_cand = m_feat.group(1)
                inferred_pr_id = f"PR-{m_feat.group(2).upper()}"
                inferred_base = "main"
                for ws_rel in (common.NEW_WORKSPACE_REL, common.LEGACY_WORKSPACE_REL):
                    show_res = runner(
                        [
                            "git",
                            "show",
                            f"{br_name}:{ws_rel.as_posix()}/{slug_cand}/PROJECT.md",
                        ],
                        cwd=real_root,
                    )
                    if show_res.returncode == 0 and show_res.stdout.strip():
                        try:
                            fm_d, _ = schemas.parse_document(show_res.stdout)
                            pspec = schemas.ProjectSpec.model_validate(fm_d)
                            inferred_pr_id = pspec.charter.pr_id
                            inferred_base = pspec.charter.base_branch
                            break
                        except Exception:  # noqa: BLE001, S110
                            pass
                seen_branches.add(br_name)
                targets.append((inferred_pr_id, br_name, inferred_base))

    # --- Step 3: Filter by explicit pr_id or verify existing local branch refs ---
    if pr_id is not None and pr_id.strip():
        needle = pr_id.strip()
        filtered = [
            (pid, br, base)
            for (pid, br, base) in targets
            if pid.upper() == needle.upper() or br == needle
        ]
        if filtered:
            return [
                (pid, br, onto_branch if onto_branch is not None else base)
                for (pid, br, base) in filtered
            ]
        # Allow passing a branch name directly as pr_id when no PROJECT.md exists
        ref_check = runner(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{needle}"],
            cwd=real_root,
        )
        if ref_check.returncode == 0:
            return [(needle, needle, onto_branch or "main")]

    if targets:
        existing_targets: list[tuple[str, str, str]] = []
        for pid, br, base in targets:
            ref_check = runner(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{br}"],
                cwd=real_root,
            )
            if ref_check.returncode == 0:
                existing_targets.append(
                    (pid, br, onto_branch if onto_branch is not None else base)
                )
        if existing_targets:
            return existing_targets

    # --- Step 4: Fall back to current checked-out branch if non-detached and non-base ---
    cur_res = runner(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=real_root)
    cur_branch = cur_res.stdout.strip() if cur_res.returncode == 0 else ""
    if cur_branch and cur_branch != "HEAD":
        target_base = onto_branch or "main"
        if cur_branch != target_base:
            return [(pr_id or cur_branch, cur_branch, target_base)]

    return []


def _local_restack_branches(
    repo_root: str | Path,
    *,
    pr_id: str | None = None,
    onto_branch: str | None = None,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Rebase stacked PR branches onto their base branches via `git rebase --update-refs`.

    Args:
        repo_root: Path to the Git repository root.
        pr_id: Optional PR ID or branch name filter.
        onto_branch: Optional target base branch override.
        runner: Subprocess execution callable.

    Returns:
        Dictionary containing `restacked` branch names, per-branch `details`, and `commands`.

    Raises:
        RuntimeError: If `git rebase --update-refs` returns a non-zero exit code.
    """
    # --- Step 1: Discover ordered restack targets ---
    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)

    targets = _collect_restack_targets(real_root, ws_dir, pr_id, onto_branch, runner)
    restacked: list[str] = []
    details: list[dict[str, Any]] = []
    commands: list[list[str]] = []

    # --- Step 2: Execute git rebase --update-refs for each target branch ---
    for pid, branch, target_base in targets:
        cmd = ["git", "rebase", "--update-refs", target_base, branch]
        commands.append(cmd)
        res = runner(cmd, cwd=real_root)
        if res.returncode != 0:
            raise RuntimeError(
                f"git rebase --update-refs failed for '{branch}' onto '{target_base}': "
                f"{res.stderr.strip() or res.stdout.strip()}"
            )
        head_res = runner(["git", "rev-parse", "HEAD"], cwd=real_root)
        head_sha = head_res.stdout.strip() if head_res.returncode == 0 else ""
        restacked.append(branch)
        details.append(
            {
                "pr_id": pid,
                "branch": branch,
                "onto_branch": target_base,
                "head_sha": head_sha,
            }
        )

    return {
        "restacked": restacked,
        "details": details,
        "commands": commands,
    }


def _resolve_pr_target(
    ws_dir: Path,
    pr_id_or_number: str | int,
) -> tuple[str, Path | None, schemas.Document[schemas.ProjectSpec] | None]:
    """Resolve `(target_arg, pr_dir, proj_doc)` from a PR ID, slug, branch, or GitHub PR number.

    Args:
        ws_dir: Active Principal Architect workspace directory.
        pr_id_or_number: PR identifier (`"PR-01"`), slug, branch name, or integer PR number.

    Returns:
        Tuple of `(gh_cli_target_str, pr_dir_or_none, project_doc_or_none)`.
    """
    # --- Step 1: Handle integer GitHub PR numbers ---
    if isinstance(pr_id_or_number, int) or str(pr_id_or_number).strip().isdigit():
        num_int = int(str(pr_id_or_number).strip())
        if ws_dir.is_dir():
            for proj_md in sorted(ws_dir.glob("pr-*/PROJECT.md")):
                if not proj_md.is_file():
                    continue
                try:
                    pdoc = schemas.load_project(proj_md)
                except Exception:  # noqa: BLE001, S112
                    continue
                if pdoc.spec.github_pr == num_int:
                    return str(num_int), proj_md.parent, pdoc
        return str(num_int), None, None

    # --- Step 2: Resolve string PR ID, slug, or branch against local PROJECT.md files ---
    raw_str = str(pr_id_or_number).strip()
    pr_dir, proj_doc = _find_pr_dir_and_project(ws_dir, raw_str)
    if proj_doc is not None:
        if proj_doc.spec.github_pr is not None:
            return str(proj_doc.spec.github_pr), pr_dir, proj_doc
        return proj_doc.spec.charter.branch, pr_dir, proj_doc
    if pr_dir.is_dir():
        return raw_str, pr_dir, None
    return raw_str, None, None


def _render_pr_body(proj_doc: schemas.Document[schemas.ProjectSpec]) -> str:
    """Render a deterministic GitHub PR body from `PROJECT.md` Charter and Work Orders.

    Args:
        proj_doc: Loaded `PROJECT.md` document.

    Returns:
        Formatted Markdown string summarizing the PR Charter and Work Order table.
    """
    # --- Step 1: Render PR header and Charter metadata bullets ---
    ch = proj_doc.spec.charter
    lines: list[str] = [
        f"## {ch.pr_id} — {ch.title}",
        "",
        f"- **Programme:** `{ch.programme_id}`",
        f"- **Stack:** `{ch.base_branch}` -> `{ch.branch}`",
        f"- **Status:** `{proj_doc.spec.status.value}`",
        "",
        "### Work Orders",
        "",
        "| WO-ID | Slug | Title | Complexity | Status | Attempts | Commit |",
        "|---|---|---|---|---|---|---|",
    ]
    # --- Step 2: Populate Work Orders summary table ---
    if proj_doc.spec.work_orders:
        for row in proj_doc.spec.work_orders:
            sha_short = f"`{row.commit_sha[:7]}`" if row.commit_sha else "—"
            lines.append(
                f"| `{row.id}` | `{row.slug}` | {row.title} | `{row.complexity.value}` | "
                f"`{row.status.value}` | {row.attempts} | {sha_short} |"
            )
    else:
        lines.append("| — | — | _No Work Orders decomposed yet_ | — | — | 0 | — |")
    return "\n".join(lines) + "\n"


def _extract_pr_number_and_url(text: str) -> tuple[int | None, str | None]:
    """Extract `(pr_number, pr_url)` from `gh pr create` or `gh pr view --json` output.

    Args:
        text: Raw stdout string from `gh pr create`, `gh pr edit`, or `gh pr view`.

    Returns:
        Tuple of `(pr_number_or_none, pr_url_or_none)`.
    """
    # --- Step 1: Parse JSON output when gh was invoked with --json ---
    cleaned = text.strip()
    if not cleaned:
        return None, None

    if cleaned.startswith("{"):
        try:
            data = json.loads(cleaned)
            if isinstance(data, Mapping):
                num_val = data.get("number")
                url_val = data.get("url")
                pr_num = int(num_val) if num_val is not None else None
                pr_url = str(url_val).strip() if url_val else None
                return pr_num, pr_url
        except (ValueError, TypeError):
            pass

    # --- Step 2: Scan plain-text lines for a '.../pull/<number>' URL ---
    for line in reversed(cleaned.splitlines()):
        line_s = line.strip()
        m = _PR_URL_NUMBER_RE.search(line_s)
        if m:
            pr_num = int(m.group(1))
            url_cand = line_s if line_s.startswith("http") else None
            return pr_num, url_cand

    if cleaned.isdigit():
        return int(cleaned), None

    return None, None


def _extract_issue_url(text: str) -> str | None:
    """Extract an issue URL from `gh issue create` stdout.

    Args:
        text: Raw stdout string from `gh issue create`.

    Returns:
        Extracted `http(s)://.../issues/<number>` URL string, or `None` if not found.
    """
    # --- Step 1: Check for JSON object with 'url' field ---
    cleaned = text.strip()
    if not cleaned:
        return None

    if cleaned.startswith("{"):
        try:
            data = json.loads(cleaned)
            if isinstance(data, Mapping) and data.get("url"):
                return str(data["url"]).strip()
        except (ValueError, TypeError):
            pass

    # --- Step 2: Match '.../issues/<number>' regex or trailing HTTP URL ---
    m = _ISSUE_URL_RE.search(cleaned)
    if m:
        return m.group(1)

    for line in reversed(cleaned.splitlines()):
        line_s = line.strip()
        if line_s.startswith(("http://", "https://")):
            return line_s
    return None


@runtime_checkable
class VCSBus(Protocol):
    """Protocol for the Principal Architect VCS synchronization bus (`local_git` & `github`).

    Attributes:
        mode: Active VCS synchronization mode (`"local_git"` or `"github"`).
        repo_root: Resolved path to the Git repository root.
        runner: Subprocess execution callable used for `git` and `gh` invocations.
    """

    # Active VCS synchronization mode ('local_git' or 'github').
    mode: Literal["local_git", "github"]
    # Resolved path to the Git repository root.
    repo_root: Path
    # Subprocess execution callable used for git and gh commands.
    runner: common.Runner

    def create_or_checkout_branch(self, branch: str, base_branch: str = "main") -> str:
        """Create `<branch>` from `<base_branch>` or check it out if it already exists.

        Args:
            branch: Target branch name.
            base_branch: Base branch ref used when creating `<branch>`.

        Returns:
            Resulting `HEAD` commit SHA.
        """
        ...

    def read_commit_trailers(
        self,
        *,
        rev_range: str | None = None,
        max_count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read `PA-*` commit trailers from `git log`.

        Args:
            rev_range: Optional Git revision range.
            max_count: Optional maximum number of commits to inspect.

        Returns:
            List of parsed commit trailer dictionaries.
        """
        ...

    def format_commit_with_trailers(
        self,
        subject: str,
        body: str | None = None,
        trailers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
    ) -> str:
        """Format a Git commit message with `Key: Value` trailers.

        Args:
            subject: Commit subject line.
            body: Optional commit body text.
            trailers: Optional mapping or sequence of `(key, value)` trailer pairs.

        Returns:
            Formatted commit message string.
        """
        ...

    def write_audit_round(
        self,
        pr_id: str,
        audit_source: (
            str
            | Path
            | schemas.AuditReport
            | schemas.Document[schemas.AuditReport]
            | Mapping[str, Any]
        ),
        *,
        commit: bool = True,
    ) -> Path:
        """Write `<pr_dir>/AUDIT-round-<K>.md`, update `PROJECT.md` status, and commit.

        Args:
            pr_id: Target PR identifier.
            audit_source: Audit report source object, path, or Markdown string.
            commit: Whether to commit the updated artifacts with a `PA-Audit-Verdict` trailer.

        Returns:
            Path to the written `AUDIT-round-<K>.md` file.
        """
        ...

    def append_deferred_backlog(
        self,
        *,
        title: str,
        summary: str = "",
        pr_id: str | None = None,
        wo_id: str | None = None,
        labels: Sequence[str] = ("pa:deferred",),
        file_path: str | None = None,
    ) -> Path:
        """Append a deferred finding to `<workspace_dir>/DEFERRED_BACKLOG.md`.

        Args:
            title: Deferred item title.
            summary: Optional description or remediation notes.
            pr_id: Optional originating PR identifier.
            wo_id: Optional originating Work Order identifier.
            labels: Classification labels (defaults to `("pa:deferred",)`).
            file_path: Optional repository-relative file path.

        Returns:
            Path to `<workspace_dir>/DEFERRED_BACKLOG.md`.
        """
        ...

    def create_deferred_issue(
        self,
        *,
        title: str,
        summary: str = "",
        pr_id: str | None = None,
        wo_id: str | None = None,
        labels: Sequence[str] = ("pa:deferred",),
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Record a deferred issue in `DEFERRED_BACKLOG.md` (and GitHub Issues in `github` mode).

        Args:
            title: Deferred issue title.
            summary: Optional description or remediation notes.
            pr_id: Optional originating PR identifier.
            wo_id: Optional originating Work Order identifier.
            labels: Classification labels (defaults to `("pa:deferred",)`).
            file_path: Optional repository-relative file path.

        Returns:
            Dictionary describing the recorded backlog path and optional `issue_url`.
        """
        ...

    def open_or_sync_pr(self, pr_id: str, *, draft: bool = False) -> dict[str, Any]:
        """Stage `<PR-ID>` for Cold-Firewall audit and synchronize PR metadata.

        Args:
            pr_id: Target PR identifier.
            draft: Whether to open a newly created GitHub PR as a draft.

        Returns:
            Dictionary summarizing PR branch, status, `github_pr`, and `head_sha`.
        """
        ...

    def view_pr(self, pr_id_or_number: str | int) -> dict[str, Any]:
        """Return PR metadata and review comments for `pr_id_or_number`.

        Args:
            pr_id_or_number: PR identifier, slug, branch name, or GitHub PR number.

        Returns:
            Dictionary of PR metadata (`number`, `url`, `state`, `title`, `body`, `reviews`, etc.).
        """
        ...

    def diff_pr(self, pr_id_or_number: str | int) -> str:
        """Return the cumulative PR diff for `pr_id_or_number`.

        Args:
            pr_id_or_number: PR identifier, slug, branch name, or GitHub PR number.

        Returns:
            Unified diff string between the PR's base branch and head branch.
        """
        ...

    def post_audit(
        self,
        pr_id: str,
        audit_source: (
            str
            | Path
            | schemas.AuditReport
            | schemas.Document[schemas.AuditReport]
            | Mapping[str, Any]
        ),
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Persist `AUDIT-round-<K>.md` locally (and post to GitHub PR in `github` mode).

        Args:
            pr_id: Target PR identifier.
            audit_source: Audit report source object, path, or Markdown string.
            commit: Whether to commit `AUDIT-round-<K>.md` and `PROJECT.md` locally.

        Returns:
            Dictionary summarizing the published audit round, verdict, and paths.
        """
        ...

    def sync_audit(self, pr_id: str) -> dict[str, Any] | None:
        """Synchronize the latest Cold-Firewall audit for `pr_id` into `.state/state.db`.

        Args:
            pr_id: Target PR identifier.

        Returns:
            Audit metadata dictionary, or `None` if no audit rounds exist for `pr_id`.
        """
        ...

    def sync_state(self) -> dict[str, Any]:
        """Rebuild `.state/state.db` and reconcile `PROJECT.md` summary rows.

        Returns:
            Dictionary summarizing synced receipts, audits, Work Orders, and timestamp.
        """
        ...

    def restack_branches(
        self,
        *,
        pr_id: str | None = None,
        onto_branch: str | None = None,
    ) -> dict[str, Any]:
        """Rebase stacked PR branches onto their base branches via `git rebase --update-refs`.

        Args:
            pr_id: Optional target PR identifier or branch name filter.
            onto_branch: Optional base branch override.

        Returns:
            Dictionary with `restacked` branches, per-branch `details`, and executed `commands`.
        """
        ...


# Backwards-compatible protocol alias preserving existing imports of vcs_sync.VcsBus.
VcsBus = VCSBus


class LocalGitBus:
    """Offline Local-Git floor implementation requiring zero GitHub or network access.

    Attributes:
        mode: Literal mode identifier (`"local_git"`).
        repo_root: Resolved path to the Git repository root.
        runner: Subprocess execution callable used for `git` invocations.
    """

    # Active VCS synchronization mode ('local_git' floor).
    mode: Literal["local_git", "github"] = "local_git"

    def __init__(
        self,
        repo_root: str | Path,
        *,
        runner: common.Runner = common.run,
    ) -> None:
        """Initialize the Local-Git synchronization bus for `repo_root`.

        Args:
            repo_root: Path to the target Git repository root.
            runner: Subprocess execution callable (defaults to `common.run`).
        """
        self.repo_root = Path(os.path.realpath(repo_root))  # Canonical repository root path
        self.runner = runner  # Subprocess runner for git operations

    def create_or_checkout_branch(self, branch: str, base_branch: str = "main") -> str:
        """Create `<branch>` from `<base_branch>` or check it out if it already exists.

        Args:
            branch: Target branch name to create or check out.
            base_branch: Base branch ref used when creating a new branch (default `"main"`).

        Returns:
            Resulting `HEAD` commit SHA.
        """
        return create_or_checkout_branch(
            self.repo_root,
            branch,
            base_branch,
            runner=self.runner,
        )

    def read_commit_trailers(
        self,
        *,
        rev_range: str | None = None,
        max_count: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read `PA-*` commit trailers from local `git log`.

        Args:
            rev_range: Optional revision range (e.g. `"main..HEAD"`).
            max_count: Optional maximum number of commits to inspect.

        Returns:
            List of parsed commit trailer dictionaries.
        """
        return read_commit_trailers(
            self.repo_root,
            rev_range=rev_range,
            max_count=max_count,
            runner=self.runner,
        )

    # Backwards-compatible method alias for read_commit_trailers.
    read_trailers = read_commit_trailers

    def format_commit_with_trailers(
        self,
        subject: str,
        body: str | None = None,
        trailers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
    ) -> str:
        """Format a commit message with `Key: Value` trailers.

        Args:
            subject: Single-line commit subject.
            body: Optional commit body text.
            trailers: Optional mapping or sequence of `(key, value)` trailer pairs.

        Returns:
            Formatted commit message string.
        """
        return format_commit_with_trailers(subject, body=body, trailers=trailers)

    def write_audit_round(
        self,
        pr_id: str,
        audit_source: (
            str
            | Path
            | schemas.AuditReport
            | schemas.Document[schemas.AuditReport]
            | Mapping[str, Any]
        ),
        *,
        commit: bool = True,
    ) -> Path:
        """Write `<pr_dir>/AUDIT-round-<K>.md`, update `PROJECT.md` status, and commit.

        Args:
            pr_id: Target PR identifier.
            audit_source: Audit report source object, path, or Markdown string.
            commit: Whether to stage and commit the audit artifacts locally.

        Returns:
            Path to the written `<pr_dir>/AUDIT-round-<K>.md` file.
        """
        return write_audit_round(
            self.repo_root,
            pr_id,
            audit_source,
            commit=commit,
            runner=self.runner,
        )

    def append_deferred_backlog(
        self,
        *,
        title: str,
        summary: str = "",
        pr_id: str | None = None,
        wo_id: str | None = None,
        labels: Sequence[str] = ("pa:deferred",),
        file_path: str | None = None,
    ) -> Path:
        """Append a deferred finding to `<workspace_dir>/DEFERRED_BACKLOG.md`.

        Args:
            title: Concise heading for the deferred item.
            summary: Optional description or remediation notes.
            pr_id: Optional PR identifier where the item was found.
            wo_id: Optional Work Order identifier where the item was found.
            labels: Classification labels (defaults to `("pa:deferred",)`).
            file_path: Optional repository-relative file path.

        Returns:
            Path to `<workspace_dir>/DEFERRED_BACKLOG.md`.
        """
        return append_deferred_backlog(
            self.repo_root,
            title=title,
            summary=summary,
            pr_id=pr_id,
            wo_id=wo_id,
            labels=labels,
            file_path=file_path,
        )

    def create_deferred_issue(
        self,
        *,
        title: str,
        summary: str = "",
        pr_id: str | None = None,
        wo_id: str | None = None,
        labels: Sequence[str] = ("pa:deferred",),
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Record a deferred issue in local `DEFERRED_BACKLOG.md`.

        Args:
            title: Concise heading for the deferred item.
            summary: Optional description or remediation notes.
            pr_id: Optional originating PR identifier.
            wo_id: Optional originating Work Order identifier.
            labels: Classification labels (defaults to `("pa:deferred",)`).
            file_path: Optional repository-relative file path.

        Returns:
            Dictionary with `mode`, `backlog_path`, and `issue_url` (`None` in local mode).
        """
        backlog_path = self.append_deferred_backlog(
            title=title,
            summary=summary,
            pr_id=pr_id,
            wo_id=wo_id,
            labels=labels,
            file_path=file_path,
        )
        return {
            "mode": self.mode,
            "backlog_path": str(backlog_path),
            "issue_url": None,
        }

    def open_or_sync_pr(self, pr_id: str, *, draft: bool = False) -> dict[str, Any]:
        """Transition `<PR-ID>` to `STAGED_FOR_AUDIT` and verify local branch against base.

        Args:
            pr_id: Target PR identifier (`"PR-01"`).
            draft: Ignored in `local_git` mode; accepted for protocol compatibility.

        Returns:
            Dictionary with `mode`, `pr_id`, `branch`, `base_branch`, `status`, `github_pr`, and
            `head_sha`.

        Raises:
            ValueError: If `PROJECT.md` for `pr_id` cannot be found.
            RuntimeError: If `base_branch` does not exist locally or `charter_hash` check fails.
        """
        # --- Step 1: Locate PROJECT.md and verify base_branch exists locally ---
        _ = draft
        ws_dir = common.workspace_dir(self.repo_root)
        pr_dir, proj_doc = _find_pr_dir_and_project(ws_dir, pr_id)
        if proj_doc is None:
            raise ValueError(f"PROJECT.md for '{pr_id}' not found in {ws_dir}")

        proj_md = pr_dir / "PROJECT.md"
        branch = proj_doc.spec.charter.branch
        base_branch = proj_doc.spec.charter.base_branch
        canonical_pr_id = proj_doc.spec.charter.pr_id

        base_res = self.runner(
            ["git", "rev-parse", "--verify", base_branch],
            cwd=self.repo_root,
        )
        if base_res.returncode != 0:
            raise RuntimeError(f"Base branch '{base_branch}' does not exist locally")

        # --- Step 2: Transition PROJECT.md status to STAGED_FOR_AUDIT and commit if changed ---
        if proj_doc.spec.status != schemas.PRState.STAGED_FOR_AUDIT:
            proj_doc.spec.status = schemas.PRState.STAGED_FOR_AUDIT
            proj_md.write_text(
                schemas.dump_document(proj_doc.spec, proj_doc.sections),
                encoding="utf-8",
            )
            if (
                proj_doc.spec.charter.charter_locked
                and proj_doc.spec.charter.charter_hash
                and not schemas.verify_charter_hash(proj_md)
            ):
                raise RuntimeError(
                    f"PROJECT.md charter_hash check failed on open_or_sync_pr: {proj_md}"
                )
            rel_proj = proj_md.resolve().relative_to(self.repo_root).as_posix()
            add_res = self.runner(["git", "add", "--", rel_proj], cwd=self.repo_root)
            if add_res.returncode == 0:
                _git_commit_with_fallback(
                    self.repo_root,
                    f"chore({canonical_pr_id.lower()}): stage for Cold-Firewall audit",
                    runner=self.runner,
                )

        # --- Step 3: Resolve HEAD SHA and return staged PR summary ---
        head_res = self.runner(["git", "rev-parse", "HEAD"], cwd=self.repo_root)
        head_sha = head_res.stdout.strip() if head_res.returncode == 0 else ""

        return {
            "mode": self.mode,
            "pr_id": canonical_pr_id,
            "branch": branch,
            "base_branch": base_branch,
            "status": schemas.PRState.STAGED_FOR_AUDIT.value,
            "github_pr": proj_doc.spec.github_pr,
            "head_sha": head_sha,
        }

    def view_pr(self, pr_id_or_number: str | int) -> dict[str, Any]:
        """Return PR metadata from local `PROJECT.md` and `AUDIT-round-*.md` files.

        Args:
            pr_id_or_number: PR identifier, slug, branch name, or GitHub PR number.

        Returns:
            Dictionary mirroring the `gh pr view --json` schema using local artifacts.

        Raises:
            ValueError: If no matching `PROJECT.md` exists under `<workspace_dir>/`.
        """
        # --- Step 1: Resolve local PROJECT.md and current HEAD SHA ---
        ws_dir = common.workspace_dir(self.repo_root)
        target, pr_dir, proj_doc = _resolve_pr_target(ws_dir, pr_id_or_number)
        if proj_doc is None or pr_dir is None:
            raise ValueError(f"PR '{pr_id_or_number}' not found in {ws_dir}")

        head_res = self.runner(["git", "rev-parse", "HEAD"], cwd=self.repo_root)
        head_sha = head_res.stdout.strip() if head_res.returncode == 0 else ""

        # --- Step 2: Collect local AUDIT-round-*.md bodies as synthetic review entries ---
        reviews: list[dict[str, Any]] = []
        for audit_md in sorted(pr_dir.glob("AUDIT-round-*.md")):
            if audit_md.is_file():
                reviews.append({"body": audit_md.read_text(encoding="utf-8")})

        return {
            "number": proj_doc.spec.github_pr,
            "url": None,
            "state": proj_doc.spec.status.value,
            "title": f"{proj_doc.spec.charter.pr_id}: {proj_doc.spec.charter.title}",
            "body": _render_pr_body(proj_doc),
            "baseRefName": proj_doc.spec.charter.base_branch,
            "headRefName": proj_doc.spec.charter.branch,
            "headRefOid": head_sha,
            "reviews": reviews,
            "comments": [],
            "target": target,
        }

    def diff_pr(self, pr_id_or_number: str | int) -> str:
        """Return local `git diff <base_branch>...<branch>` for `pr_id_or_number`.

        Args:
            pr_id_or_number: PR identifier, slug, branch name, or GitHub PR number.

        Returns:
            Unified diff string from `git diff`.
        """
        # --- Step 1: Resolve base and head branch names from PROJECT.md (or default main..HEAD) ---
        ws_dir = common.workspace_dir(self.repo_root)
        _, _, proj_doc = _resolve_pr_target(ws_dir, pr_id_or_number)
        if proj_doc is not None:
            base_branch = proj_doc.spec.charter.base_branch
            branch = proj_doc.spec.charter.branch
        else:
            base_branch = "main"
            branch = "HEAD"

        # --- Step 2: Run three-dot merge-base diff with two-dot fallback ---
        res = self.runner(
            ["git", "diff", f"{base_branch}...{branch}"],
            cwd=self.repo_root,
        )
        if res.returncode == 0:
            return res.stdout
        res_fallback = self.runner(
            ["git", "diff", base_branch, branch],
            cwd=self.repo_root,
        )
        return res_fallback.stdout

    def post_audit(
        self,
        pr_id: str,
        audit_source: (
            str
            | Path
            | schemas.AuditReport
            | schemas.Document[schemas.AuditReport]
            | Mapping[str, Any]
        ),
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Persist `AUDIT-round-<K>.md` locally, commit with trailer, and update `state.db`.

        Args:
            pr_id: Target PR identifier.
            audit_source: Audit report source object, path, or Markdown string.
            commit: Whether to commit the audit round and status update locally.

        Returns:
            Dictionary with `mode`, `pr_id`, `audit_round`, `verdict`, `head_sha`, `audit_path`,
            and `github_pr`.
        """
        audit_path = self.write_audit_round(pr_id, audit_source, commit=commit)
        audit_doc = schemas.load_audit(audit_path)
        report = audit_doc.spec
        return {
            "mode": self.mode,
            "pr_id": report.pr_id,
            "audit_round": report.audit_round,
            "verdict": report.verdict,
            "head_sha": report.head_sha,
            "audit_path": str(audit_path),
            "github_pr": report.github_pr,
        }

    def sync_audit(self, pr_id: str) -> dict[str, Any] | None:
        """Sync the latest `AUDIT-round-<K>.md` for `pr_id` into `.state/state.db`.

        Args:
            pr_id: Target PR identifier.

        Returns:
            Audit metadata dictionary for the highest-numbered round, or `None` if none exist.
        """
        # --- Step 1: Locate PR directory and load all AUDIT-round-*.md documents ---
        ws_dir = common.workspace_dir(self.repo_root)
        pr_dir, proj_doc = _find_pr_dir_and_project(ws_dir, pr_id)
        if not pr_dir.is_dir():
            return None

        audit_docs: list[schemas.Document[schemas.AuditReport]] = []
        for audit_md in sorted(pr_dir.glob("AUDIT-round-*.md")):
            if not audit_md.is_file():
                continue
            try:
                audit_docs.append(schemas.load_audit(audit_md))
            except Exception:  # noqa: BLE001, S112
                continue

        if not audit_docs:
            return None

        # --- Step 2: Select the highest audit_round and reconcile PROJECT.md status ---
        audit_docs.sort(key=lambda d: d.spec.audit_round)
        top_doc = audit_docs[-1]
        report = top_doc.spec
        pr_id_upper = report.pr_id.upper()

        proj_md = pr_dir / "PROJECT.md"
        if proj_doc is not None and proj_md.is_file():
            target_status = (
                schemas.PRState.AUDIT_APPROVED
                if report.verdict == "APPROVED"
                else schemas.PRState.CHANGES_REQUESTED
            )
            if proj_doc.spec.status != target_status and proj_doc.spec.status not in (
                schemas.PRState.GRADUATED,
                schemas.PRState.ARCHIVED,
            ):
                proj_doc.spec.status = target_status
                proj_md.write_text(
                    schemas.dump_document(proj_doc.spec, proj_doc.sections),
                    encoding="utf-8",
                )

        # --- Step 3: Persist latest_audit:<PR-ID> metadata in .state/state.db ---
        audit_meta: dict[str, Any] = {
            "mode": self.mode,
            "pr_id": pr_id_upper,
            "github_pr": report.github_pr,
            "audit_round": report.audit_round,
            "head_sha": report.head_sha,
            "auditor_harness": report.auditor_harness,
            "verdict": report.verdict,
            "findings_count": len(report.findings),
            "audit_path": str(top_doc.path) if top_doc.path else None,
        }
        db_file = ws_dir / ".state" / "state.db"
        db_file.parent.mkdir(parents=True, exist_ok=True)
        with state_db.StateDB(db_file) as db:
            meta_json = json.dumps(audit_meta)
            db.set_config(f"latest_audit:{pr_id_upper}", meta_json)
            db.set_config(f"last_audit_{pr_id_upper}", meta_json)

        return audit_meta

    def sync_state(self) -> dict[str, Any]:
        """Rebuild `.state/state.db` and reconcile `PROJECT.md` summary rows from local Git.

        Returns:
            Dictionary summarizing synced receipts, audits, Work Orders, and timestamp.
        """
        return _local_sync_state(self.repo_root, runner=self.runner)

    def restack_branches(
        self,
        *,
        pr_id: str | None = None,
        onto_branch: str | None = None,
    ) -> dict[str, Any]:
        """Rebase stacked branches via `git rebase --update-refs`.

        Args:
            pr_id: Optional target PR identifier or branch name filter.
            onto_branch: Optional base branch override.

        Returns:
            Dictionary with `restacked` branches, per-branch `details`, and executed `commands`.
        """
        return _local_restack_branches(
            self.repo_root,
            pr_id=pr_id,
            onto_branch=onto_branch,
            runner=self.runner,
        )


class GitHubBus(LocalGitBus):
    """GitHub multi-machine synchronization bus (`vcs_mode == 'github'`).

    Extends `LocalGitBus` so every operation maintains local Git/file artifacts first and then
    synchronizes PRs, review comments, and deferred issues with GitHub via the `gh` CLI.

    Attributes:
        mode: Literal mode identifier (`"github"`).
    """

    # Active VCS synchronization mode ('github' multi-machine bus).
    mode: Literal["local_git", "github"] = "github"

    def open_or_sync_pr(self, pr_id: str, *, draft: bool = False) -> dict[str, Any]:
        """Stage `<PR-ID>`, push branch to `origin`, and create or update the GitHub PR.

        Args:
            pr_id: Target PR identifier (`"PR-01"`).
            draft: Whether to pass `--draft` when creating a new GitHub PR.

        Returns:
            Dictionary with `mode`, `pr_id`, `branch`, `base_branch`, `status`, `github_pr`,
            `pr_url`, and `head_sha`.

        Raises:
            ValueError: If `PROJECT.md` for `pr_id` cannot be found.
            RuntimeError: If `gh pr create`, `gh pr edit`, or `charter_hash` verification fails.
        """
        # --- Step 1: Stage PR locally via LocalGitBus and load PROJECT.md ---
        local_info = super().open_or_sync_pr(pr_id, draft=draft)
        ws_dir = common.workspace_dir(self.repo_root)
        pr_dir, proj_doc = _find_pr_dir_and_project(ws_dir, pr_id)
        if proj_doc is None:
            raise ValueError(f"PROJECT.md for '{pr_id}' not found in {ws_dir}")

        proj_md = pr_dir / "PROJECT.md"
        branch = proj_doc.spec.charter.branch
        base_branch = proj_doc.spec.charter.base_branch
        canonical_pr_id = proj_doc.spec.charter.pr_id

        # --- Step 2: Push branch to origin and render deterministic PR title and body ---
        self.runner(["git", "push", "-u", "origin", branch], cwd=self.repo_root)

        title = f"{canonical_pr_id}: {proj_doc.spec.charter.title}"
        body = _render_pr_body(proj_doc)

        gh = _gh_bin()
        pr_number: int | None = proj_doc.spec.github_pr
        pr_url: str | None = None
        pr_existed = pr_number is not None

        # --- Step 3: Probe whether a GitHub PR already exists for this branch ---
        if not pr_existed:
            view_res = self.runner(
                [
                    gh,
                    "pr",
                    "view",
                    branch,
                    "--json",
                    "number,url,state,baseRefName,headRefName",
                ],
                cwd=self.repo_root,
            )
            if view_res.returncode == 0 and view_res.stdout.strip():
                num_v, url_v = _extract_pr_number_and_url(view_res.stdout)
                if num_v is not None:
                    pr_number = num_v
                    pr_url = url_v
                    pr_existed = True

        # --- Step 4: Create a new GitHub PR or edit the existing PR ---
        if not pr_existed:
            create_cmd: list[str] = [
                gh,
                "pr",
                "create",
                "--base",
                base_branch,
                "--head",
                branch,
                "--title",
                title,
                "--body",
                body,
            ]
            if draft:
                create_cmd.append("--draft")
            create_res = self.runner(create_cmd, cwd=self.repo_root)
            if create_res.returncode != 0:
                raise RuntimeError(
                    f"gh pr create failed: "
                    f"{create_res.stderr.strip() or create_res.stdout.strip()}"
                )
            pr_number, pr_url = _extract_pr_number_and_url(create_res.stdout)
            if pr_number is None:
                view_after = self.runner(
                    [gh, "pr", "view", branch, "--json", "number,url"],
                    cwd=self.repo_root,
                )
                if view_after.returncode == 0 and view_after.stdout.strip():
                    num_after, url_after = _extract_pr_number_and_url(view_after.stdout)
                    pr_number = num_after
                    pr_url = pr_url or url_after
        else:
            edit_target = str(pr_number) if pr_number is not None else branch
            edit_cmd = [
                gh,
                "pr",
                "edit",
                edit_target,
                "--base",
                base_branch,
                "--title",
                title,
                "--body",
                body,
            ]
            edit_res = self.runner(edit_cmd, cwd=self.repo_root)
            if edit_res.returncode != 0:
                raise RuntimeError(
                    f"gh pr edit failed: {edit_res.stderr.strip() or edit_res.stdout.strip()}"
                )
            if pr_url is None and edit_res.stdout.strip():
                _, parsed_url = _extract_pr_number_and_url(edit_res.stdout)
                pr_url = parsed_url

        # --- Step 5: Persist github_pr in PROJECT.md, verify charter_hash, and push update ---
        if pr_number is not None and proj_doc.spec.github_pr != pr_number:
            proj_doc.spec.github_pr = pr_number
            proj_md.write_text(
                schemas.dump_document(proj_doc.spec, proj_doc.sections),
                encoding="utf-8",
            )
            if (
                proj_doc.spec.charter.charter_locked
                and proj_doc.spec.charter.charter_hash
                and not schemas.verify_charter_hash(proj_md)
            ):
                raise RuntimeError(
                    f"PROJECT.md charter_hash check failed after setting github_pr: {proj_md}"
                )
            rel_proj = proj_md.resolve().relative_to(self.repo_root).as_posix()
            add_res = self.runner(["git", "add", "--", rel_proj], cwd=self.repo_root)
            if add_res.returncode == 0:
                commit_res = _git_commit_with_fallback(
                    self.repo_root,
                    f"chore({canonical_pr_id.lower()}): record github_pr #{pr_number}",
                    runner=self.runner,
                )
                if commit_res.returncode == 0:
                    self.runner(["git", "push", "-u", "origin", branch], cwd=self.repo_root)

        head_res = self.runner(["git", "rev-parse", "HEAD"], cwd=self.repo_root)
        head_sha = (
            head_res.stdout.strip()
            if head_res.returncode == 0 and head_res.stdout.strip()
            else local_info["head_sha"]
        )

        return {
            "mode": "github",
            "pr_id": canonical_pr_id,
            "branch": branch,
            "base_branch": base_branch,
            "status": schemas.PRState.STAGED_FOR_AUDIT.value,
            "github_pr": pr_number,
            "pr_url": pr_url,
            "head_sha": head_sha,
        }

    def view_pr(self, pr_id_or_number: str | int) -> dict[str, Any]:
        """Inspect a GitHub PR via `gh pr view <target> --json ...`.

        Args:
            pr_id_or_number: PR identifier, slug, branch name, or GitHub PR number.

        Returns:
            Decoded JSON dictionary returned by `gh pr view`.

        Raises:
            RuntimeError: If `gh pr view` fails or returns malformed JSON.
        """
        # --- Step 1: Resolve target identifier and execute gh pr view --json ---
        ws_dir = common.workspace_dir(self.repo_root)
        target, _, _ = _resolve_pr_target(ws_dir, pr_id_or_number)
        gh = _gh_bin()
        cmd = [
            gh,
            "pr",
            "view",
            str(target),
            "--json",
            "number,url,state,title,body,baseRefName,headRefName,headRefOid,reviews,comments",
        ]
        res = self.runner(cmd, cwd=self.repo_root)
        if res.returncode != 0:
            raise RuntimeError(
                f"gh pr view failed for '{target}': {res.stderr.strip() or res.stdout.strip()}"
            )
        # --- Step 2: Decode and validate JSON dictionary payload ---
        try:
            data = json.loads(res.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse gh pr view JSON for '{target}': {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected gh pr view payload for '{target}'")  # noqa: TRY004
        return data

    def diff_pr(self, pr_id_or_number: str | int) -> str:
        """Fetch PR diff via `gh pr diff <target>`, falling back to local `git diff`.

        Args:
            pr_id_or_number: PR identifier, slug, branch name, or GitHub PR number.

        Returns:
            Unified diff string from `gh pr diff` or local `git diff`.
        """
        ws_dir = common.workspace_dir(self.repo_root)
        target, _, _ = _resolve_pr_target(ws_dir, pr_id_or_number)
        gh = _gh_bin()
        res = self.runner([gh, "pr", "diff", str(target)], cwd=self.repo_root)
        if res.returncode == 0:
            return res.stdout
        return super().diff_pr(pr_id_or_number)

    def post_audit(
        self,
        pr_id: str,
        audit_source: (
            str
            | Path
            | schemas.AuditReport
            | schemas.Document[schemas.AuditReport]
            | Mapping[str, Any]
        ),
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Write and commit `AUDIT-round-<K>.md` locally and post via `gh pr review --comment`.

        Args:
            pr_id: Target PR identifier.
            audit_source: Audit report source object, path, or Markdown string.
            commit: Whether to commit `AUDIT-round-<K>.md` and `PROJECT.md` locally.

        Returns:
            Dictionary with local audit metadata plus `body_file`, `review_posted`, and
            `review_command`.
        """
        # --- Step 1: Persist and commit AUDIT-round-<K>.md locally via LocalGitBus ---
        local_res = super().post_audit(pr_id, audit_source, commit=commit)
        audit_doc = schemas.load_audit(local_res["audit_path"])
        report = audit_doc.spec

        # --- Step 2: Render <!-- pa:audit ... --> review comment body to .state/ file ---
        existing_body = "\n".join(s.full_text() for s in audit_doc.sections).strip()
        comment_body = format_pa_audit_comment(
            report, existing_body if existing_body else None
        )

        ws_dir = common.workspace_dir(self.repo_root)
        state_dir = ws_dir / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        body_file = state_dir / f"audit_comment_{report.pr_id.lower()}_r{report.audit_round}.md"
        body_file.write_text(comment_body, encoding="utf-8")

        # --- Step 3: Post review via gh pr review --comment (safe for same-account authoring) ---
        if report.github_pr is not None:
            target = str(report.github_pr)
        else:
            target, _, proj_doc = _resolve_pr_target(ws_dir, pr_id)
            if proj_doc is not None and proj_doc.spec.github_pr is not None:
                target = str(proj_doc.spec.github_pr)

        gh = _gh_bin()
        # CRITICAL (Charter R2 & SPEC §11.3): Always use `--comment`, never `--approve` or
        # `--request-changes`, for same-account GitHub review compatibility.
        cmd = [
            gh,
            "pr",
            "review",
            str(target),
            "--comment",
            "--body-file",
            str(body_file),
        ]
        review_res = self.runner(cmd, cwd=self.repo_root)

        return {
            **local_res,
            "mode": "github",
            "github_pr": int(target) if str(target).isdigit() else local_res.get("github_pr"),
            "body_file": str(body_file),
            "review_posted": review_res.returncode == 0,
            "review_command": cmd,
        }

    def sync_audit(self, pr_id: str) -> dict[str, Any] | None:
        """Ingest remote `<!-- pa:audit ... -->` PR comments into `AUDIT-round-<K>.md` & `state.db`.

        Args:
            pr_id: Target PR identifier.

        Returns:
            Latest synced audit metadata dictionary, or `None` if no local or remote audits exist.
        """
        # --- Step 1: Query remote GitHub PR reviews and comments via gh pr view ---
        ws_dir = common.workspace_dir(self.repo_root)
        target, pr_dir, proj_doc = _resolve_pr_target(ws_dir, pr_id)
        canonical_pr_id = (
            proj_doc.spec.charter.pr_id if proj_doc is not None else pr_id.strip().upper()
        )
        if pr_dir is None:
            pr_dir, _ = _find_pr_dir_and_project(ws_dir, canonical_pr_id)

        gh = _gh_bin()
        cmd = [
            gh,
            "pr",
            "view",
            str(target),
            "--json",
            "number,url,headRefOid,reviews,comments",
        ]
        res = self.runner(cmd, cwd=self.repo_root)
        if res.returncode == 0 and res.stdout.strip():
            try:
                payload = json.loads(res.stdout)
            except json.JSONDecodeError:
                payload = None

            # --- Step 2: Parse <!-- pa:audit ... --> blocks and materialize missing local files ---
            if isinstance(payload, Mapping):
                remote_num = (
                    int(payload["number"])
                    if isinstance(payload.get("number"), int)
                    else (proj_doc.spec.github_pr if proj_doc is not None else None)
                )
                items: list[Any] = []
                if isinstance(payload.get("reviews"), list):
                    items.extend(payload["reviews"])
                if isinstance(payload.get("comments"), list):
                    items.extend(payload["comments"])

                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    body_text = str(item.get("body") or "")
                    parsed = parse_pa_audit_comment(body_text)
                    if parsed is None:
                        continue
                    if parsed["pr_id"].upper() != canonical_pr_id.upper():
                        continue

                    round_num = int(parsed["audit_round"])
                    existing_audit_md = pr_dir / f"AUDIT-round-{round_num}.md"
                    needs_write = not existing_audit_md.is_file()
                    if not needs_write:
                        try:
                            existing_doc = schemas.load_audit(existing_audit_md)
                            if (
                                existing_doc.spec.verdict != parsed["verdict"]
                                or existing_doc.spec.head_sha != parsed["head_sha"]
                            ):
                                needs_write = True
                        except Exception:  # noqa: BLE001
                            needs_write = True

                    if needs_write:
                        raw_findings = parsed.get("findings") or []
                        findings_objs: list[schemas.AuditFinding] = []
                        for f_item in raw_findings:
                            if isinstance(f_item, schemas.AuditFinding):
                                findings_objs.append(f_item)
                            elif isinstance(f_item, Mapping):
                                findings_objs.append(schemas.AuditFinding.model_validate(f_item))

                        if not findings_objs:
                            for b_idx in range(1, int(parsed.get("blocking", 0)) + 1):
                                findings_objs.append(
                                    schemas.AuditFinding(
                                        id=f"BLOCKING-{b_idx}",
                                        axis="spec_alignment",
                                        file_path="PROJECT.md",
                                        summary="Synced blocking finding from GitHub PR review",
                                        remediation="See GitHub PR review comment details",
                                    )
                                )
                            for m_idx in range(1, int(parsed.get("major", 0)) + 1):
                                findings_objs.append(
                                    schemas.AuditFinding(
                                        id=f"NON-BLOCKING-{m_idx}",
                                        axis="test_quality",
                                        file_path="PROJECT.md",
                                        summary="Synced non-blocking finding from GitHub PR review",
                                        remediation="See GitHub PR review comment details",
                                    )
                                )

                        report = schemas.AuditReport(
                            pr_id=canonical_pr_id.upper(),
                            github_pr=remote_num or parsed.get("github_pr"),
                            audit_round=round_num,
                            head_sha=parsed["head_sha"],
                            auditor_harness=parsed.get("auditor_harness", "antigravity"),
                            verdict=parsed["verdict"],
                            findings=findings_objs,
                        )
                        write_audit_round(
                            self.repo_root,
                            canonical_pr_id,
                            report,
                            commit=False,
                            runner=self.runner,
                        )

        # --- Step 3: Delegate final state.db reconciliation to LocalGitBus.sync_audit ---
        synced = super().sync_audit(pr_id)
        if synced is not None:
            synced["mode"] = "github"
        return synced

    def create_deferred_issue(
        self,
        *,
        title: str,
        summary: str = "",
        pr_id: str | None = None,
        wo_id: str | None = None,
        labels: Sequence[str] = ("pa:deferred",),
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Create a GitHub issue with `--label pa:deferred` and record in `DEFERRED_BACKLOG.md`.

        Args:
            title: Issue title.
            summary: Optional issue description or remediation context.
            pr_id: Optional originating PR identifier.
            wo_id: Optional originating Work Order identifier.
            labels: Classification labels (always includes `"pa:deferred"`).
            file_path: Optional repository-relative file path.

        Returns:
            Dictionary with `mode`, `issue_url`, `backlog_path`, and executed `command`.
        """
        # --- Step 1: Normalize labels and assemble GitHub issue Markdown body ---
        normalized_labels: list[str] = ["pa:deferred"]
        for lbl in labels:
            lbl_s = str(lbl).strip()
            if lbl_s and lbl_s not in normalized_labels:
                normalized_labels.append(lbl_s)

        body_lines: list[str] = []
        if pr_id:
            body_lines.append(f"- **PR:** `{pr_id.strip()}`")
        if wo_id:
            body_lines.append(f"- **Work Order:** `{wo_id.strip()}`")
        if file_path:
            body_lines.append(f"- **File:** `{file_path.strip()}`")
        if summary.strip():
            if body_lines:
                body_lines.append("")
            body_lines.append(summary.strip())
        body = "\n".join(body_lines) if body_lines else title.strip()

        # --- Step 2: Invoke gh issue create with --label pa:deferred ---
        gh = _gh_bin()
        cmd: list[str] = [
            gh,
            "issue",
            "create",
            "--title",
            title.strip(),
            "--body",
            body,
        ]
        for lbl in normalized_labels:
            cmd.extend(["--label", lbl])

        issue_url: str | None = None
        try:
            res = self.runner(cmd, cwd=self.repo_root)
            if res.returncode == 0 and res.stdout.strip():
                issue_url = _extract_issue_url(res.stdout)
        except (OSError, subprocess.SubprocessError):
            issue_url = None

        # --- Step 3: Append entry to local DEFERRED_BACKLOG.md ---
        backlog_path = self.append_deferred_backlog(
            title=title,
            summary=summary,
            pr_id=pr_id,
            wo_id=wo_id,
            labels=normalized_labels,
            file_path=file_path,
        )
        return {
            "mode": "github",
            "issue_url": issue_url,
            "backlog_path": str(backlog_path),
            "command": cmd,
        }

    def sync_state(self) -> dict[str, Any]:
        """Fetch `origin`, sync remote GitHub PR audits, and rebuild `.state/state.db`.

        Returns:
            Dictionary summarizing synced receipts, audits, Work Orders, and `vcs_mode`.
        """
        # --- Step 1: Fetch remote refs and ingest remote PR audit comments ---
        self.runner(["git", "fetch", "origin"], cwd=self.repo_root)

        ws_dir = common.workspace_dir(self.repo_root)
        if ws_dir.is_dir():
            for proj_md in sorted(ws_dir.glob("pr-*/PROJECT.md")):
                if not proj_md.is_file():
                    continue
                try:
                    proj_doc = schemas.load_project(proj_md)
                except Exception:  # noqa: BLE001, S112
                    continue
                self.sync_audit(proj_doc.spec.charter.pr_id)

        # --- Step 2: Rebuild local state.db and ensure vcs_mode == 'github' ---
        res = super().sync_state()
        res["vcs_mode"] = "github"
        db_file = ws_dir / ".state" / "state.db"
        if db_file.is_file():
            with state_db.StateDB(db_file) as db:
                db.set_config("vcs_mode", "github")
        return res

    def restack_branches(
        self,
        *,
        pr_id: str | None = None,
        onto_branch: str | None = None,
    ) -> dict[str, Any]:
        """Rebase stacked PR branches, force-push with lease, and retarget GitHub PR bases.

        Args:
            pr_id: Optional target PR identifier or branch name filter.
            onto_branch: Optional base branch override.

        Returns:
            Dictionary with `restacked` branches, per-branch `details`, and executed `commands`.
        """
        # --- Step 1: Rebase local branch stack via LocalGitBus.restack_branches ---
        res = super().restack_branches(pr_id=pr_id, onto_branch=onto_branch)
        ws_dir = common.workspace_dir(self.repo_root)
        gh = _gh_bin()

        # --- Step 2: Force-push each rebased branch with lease and update GitHub PR base ref ---
        for entry in res.get("details", []):
            branch = str(entry["branch"])
            onto = str(entry["onto_branch"])
            pid = str(entry["pr_id"])

            push_cmd = ["git", "push", "--force-with-lease", "origin", branch]
            res["commands"].append(push_cmd)
            self.runner(push_cmd, cwd=self.repo_root)

            target, _, _ = _resolve_pr_target(ws_dir, pid)
            edit_cmd = [gh, "pr", "edit", str(target), "--base", onto]
            res["commands"].append(edit_cmd)
            self.runner(edit_cmd, cwd=self.repo_root)

        return res


def get_vcs_bus(
    repo_root: str | Path,
    *,
    vcs_mode: str | None = None,
    runner: common.Runner = common.run,
) -> VCSBus:
    """Return the configured `VCSBus` instance (`GitHubBus` or `LocalGitBus`).

    Args:
        repo_root: Path to the Git repository root.
        vcs_mode: Optional explicit mode (`"github"` or `"local_git"`); read from `.state/state.db`
            when `None`.
        runner: Subprocess execution callable.

    Returns:
        `GitHubBus` when `vcs_mode == "github"`, otherwise `LocalGitBus`.
    """
    # --- Step 1: Resolve vcs_mode from argument or .state/state.db ---
    real_root = Path(os.path.realpath(repo_root))
    resolved_mode = vcs_mode
    if not resolved_mode:
        ws_dir = common.workspace_dir(real_root)
        db_file = ws_dir / ".state" / "state.db"
        if db_file.is_file():
            with state_db.StateDB(db_file) as db:
                resolved_mode = db.get_config("vcs_mode") or "local_git"
        else:
            resolved_mode = "local_git"

    # --- Step 2: Instantiate matching VCSBus implementation ---
    if str(resolved_mode).strip().lower() == "github":
        return GitHubBus(real_root, runner=runner)
    return LocalGitBus(real_root, runner=runner)


def sync_state(
    repo_root: str | Path,
    *,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Rebuild `.state/state.db` and reconcile `PROJECT.md` rows via the active `VCSBus`.

    Args:
        repo_root: Path to the Git repository root.
        runner: Subprocess execution callable.

    Returns:
        Dictionary summarizing synced receipts, audits, Work Orders, and timestamp.
    """
    return get_vcs_bus(repo_root, runner=runner).sync_state()


def restack_branches(
    repo_root: str | Path,
    *,
    pr_id: str | None = None,
    onto_branch: str | None = None,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Rebase stacked PR branches onto their base branches via the active `VCSBus`.

    Args:
        repo_root: Path to the Git repository root.
        pr_id: Optional target PR identifier or branch name filter.
        onto_branch: Optional base branch override.
        runner: Subprocess execution callable.

    Returns:
        Dictionary with `restacked` branches, per-branch `details`, and executed `commands`.
    """
    return get_vcs_bus(repo_root, runner=runner).restack_branches(
        pr_id=pr_id,
        onto_branch=onto_branch,
    )
