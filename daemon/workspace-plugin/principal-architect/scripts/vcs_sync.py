"""Local-Git floor and GitHub multi-machine synchronization bus (`vcs_sync.py`).

Implements SPEC §8 & §11.3 and PR-03 Charter G1, R1, & R2:
- `format_commit_with_trailers`, `read_commit_trailers` (and alias `read_trailers`) parsing
  `PA-WorkOrder`, `PA-Verified-Hash`, and `PA-Audit-Verdict` trailers from `git log`.
- `format_pa_audit_comment` and `parse_pa_audit_comment` handling the machine-parseable
  `<!-- pa:audit ... -->` comment header and `**Audit Verdict:**` line.
- `write_audit_round` validating `AuditReport` (`1 <= audit_round <= 5`), persisting
  `<pr_dir>/AUDIT-round-<K>.md`, updating `PROJECT.md` status (`AUDIT_APPROVED` or
  `CHANGES_REQUESTED`) without mutating Part I `charter_hash`, and committing with
  trailer `PA-Audit-Verdict: <verdict> (<head_sha>)`.
- `append_deferred_backlog` appending deferred items to `<workspace_dir>/DEFERRED_BACKLOG.md`.
- `sync_state` rebuilding `.state/state.db` (`verification_receipts`, `escalations`,
  `latest_audit:<PR-ID>`, `last_vcs_sync_at`) and reconciling `PROJECT.md` `work_orders`
  summary rows from local git trailers and committed Split-Authority artifacts.
- `create_or_checkout_branch`, `restack_branches` (`git rebase --update-refs`), `VcsBus`,
  `LocalGitBus`, `GitHubBus` (`gh pr create/edit/view/diff`, `gh pr review --comment`,
  `gh issue create --label pa:deferred`), and `get_vcs_bus`.
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

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import post_tool_receipt
import schemas
import state_db
import yaml

MAX_AUDIT_ROUNDS: int = 5

_AUDIT_VERDICT_TRAILER_RE = re.compile(
    r"^\s*(APPROVED|CHANGES_REQUESTED)(?:\s*\(\s*([0-9a-fA-F]{7,40})\s*\))?\s*$",
    re.IGNORECASE,
)

_PA_AUDIT_COMMENT_RE = re.compile(
    r"<!--\s*pa:audit\b(.*?)-->",
    re.DOTALL | re.IGNORECASE,
)

_KV_PAIR_RE = re.compile(
    r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>]+))"
)

_VERDICT_LINE_RE = re.compile(
    r"\*\*Audit Verdict:\*\*\s*(APPROVED|CHANGES_REQUESTED)\b",
    re.IGNORECASE,
)

_PR_URL_NUMBER_RE = re.compile(r"/pull/(\d+)(?:\b|/|$)")
_ISSUE_URL_RE = re.compile(r"(https?://\S+/issues/\d+)")


def _gh_bin() -> str:
    """Return the `gh` executable path, respecting `PA_GH_BIN` environment override."""
    return os.environ.get("PA_GH_BIN", "").strip() or "gh"


def _git_commit_with_fallback(
    real_root: Path,
    commit_msg: str,
    *,
    runner: common.Runner = common.run,
) -> subprocess.CompletedProcess[str]:
    """Run `git commit -m <msg>`, falling back to explicit author config if unset."""
    res = runner(["git", "commit", "-m", commit_msg], cwd=real_root)
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
    """Format a Git commit message with subject, optional body, and `Key: Value` trailers."""
    subj = subject.strip()
    if not subj:
        raise ValueError("Commit subject must not be empty")

    parts: list[str] = [subj]
    if body is not None and body.strip():
        parts.append(body.strip())

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
    """Parse `PA-Audit-Verdict` trailer value `<VERDICT> (<head_sha>)` or `<VERDICT>`."""
    cleaned = raw_val.strip()
    if not cleaned:
        return None, None
    first_line = cleaned.splitlines()[0].strip()
    m = _AUDIT_VERDICT_TRAILER_RE.match(first_line)
    if m:
        verdict = m.group(1).upper()
        head_sha = m.group(2) if m.group(2) else None
        return verdict, head_sha
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
    """Read `PA-WorkOrder`, `PA-Verified-Hash`, and `PA-Audit-Verdict` trailers from `git log`."""
    real_root = Path(os.path.realpath(repo_root))
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

    try:
        res = runner(cmd, cwd=real_root)
    except (OSError, subprocess.SubprocessError):
        return []

    if res.returncode != 0 or not res.stdout:
        return []

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


read_trailers = read_commit_trailers


def _count_findings(findings: Sequence[schemas.AuditFinding]) -> tuple[int, int, int]:
    """Return `(blocking, major, minor)` counts from a sequence of `AuditFinding` items."""
    blocking = sum(1 for f in findings if f.id.upper().startswith("BLOCKING-"))
    major = sum(1 for f in findings if not f.id.upper().startswith("BLOCKING-"))
    minor = 0
    return blocking, major, minor


def format_pa_audit_comment(
    report: schemas.AuditReport,
    body_markdown: str | None = None,
) -> str:
    """Format a Cold-Firewall `AuditReport` with a machine-parseable `<!-- pa:audit ... -->` header."""
    blocking, major, minor = _count_findings(report.findings)
    header_comment = (
        f"<!-- pa:audit pr_id={report.pr_id} round={report.audit_round} "
        f"head_sha={report.head_sha} verdict={report.verdict} "
        f"blocking={blocking} major={major} minor={minor} -->"
    )
    verdict_line = (
        f"**Audit Verdict:** {report.verdict} ({blocking} blocking, {major} non-blocking)"
    )

    if body_markdown is not None and body_markdown.strip():
        body_clean = body_markdown.strip()
        lines: list[str] = []
        if not _PA_AUDIT_COMMENT_RE.search(body_clean):
            lines.append(header_comment)
        if not _VERDICT_LINE_RE.search(body_clean):
            lines.append(verdict_line)
        lines.append(body_clean)
        return "\n\n".join(lines) + "\n"

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

    Returns `None` if no valid `pa:audit` marker is present in `text`.
    """
    if not text or not text.strip():
        return None

    m = _PA_AUDIT_COMMENT_RE.search(text)
    if m is None:
        return None

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

    fm_data: dict[str, Any] = {}
    if text.lstrip("\ufeff").startswith("---"):
        try:
            parsed_fm, _ = schemas.parse_document(text)
            if isinstance(parsed_fm, dict):
                fm_data = parsed_fm
        except Exception:  # noqa: BLE001
            fm_data = {}

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
    """Locate `<pr_dir>` and optional loaded `PROJECT.md` for `pr_id` under `ws_dir`."""
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
    """Coerce `audit_source` into a validated `(AuditReport, sections)` pair."""
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
    """Validate `AuditReport`, write `<pr_dir>/AUDIT-round-<K>.md`, update `PROJECT.md`, and commit."""
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
    """Append a deferred out-of-scope finding to `<workspace_dir>/DEFERRED_BACKLOG.md`."""
    title_clean = title.strip()
    if not title_clean:
        raise ValueError("Deferred backlog title must not be empty")

    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)
    ws_dir.mkdir(parents=True, exist_ok=True)
    backlog_path = ws_dir / "DEFERRED_BACKLOG.md"

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
    """Infer `PR-NN` from `WO-NN.M` (e.g. `WO-03.1` -> `PR-03`)."""
    m = re.match(r"^WO-(\d+[a-z]?)\.\d+$", wo_id.strip(), re.IGNORECASE)
    if m:
        return f"PR-{m.group(1).upper()}"
    return "PR-00"


def _local_sync_state(
    repo_root: str | Path,
    *,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Rebuild `.state/state.db` and reconcile `PROJECT.md` rows from git trailers and specs."""
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
    processed_wo_ids: set[str] = set()

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
                        proj_doc = None

                wo_docs_by_id: dict[str, schemas.Document[schemas.WorkOrderSpec]] = {}
                for wo_md in sorted(pr_dir.glob("wo*/WORKORDER.md")):
                    if not wo_md.is_file():
                        continue
                    try:
                        wdoc = schemas.load_workorder(wo_md)
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

                # Reconcile AUDIT-round-*.md files in this PR directory
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

        # Reconcile any commit trailers for WOs without a local WORKORDER.md file
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
    }


def create_or_checkout_branch(
    repo_root: str | Path,
    branch: str,
    base_branch: str = "main",
    *,
    runner: common.Runner = common.run,
) -> str:
    """Create `<branch>` from `<base_branch>` if it does not exist, or check it out if it does.

    Returns the resulting `HEAD` commit SHA.
    """
    branch_clean = branch.strip()
    base_clean = base_branch.strip() or "main"
    if not branch_clean:
        raise ValueError("branch name must not be empty")

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
    """Return ordered `(pr_id, branch, base_branch)` tuples for `restack_branches`."""
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

    # Also discover `feat/pr-*` branches from local git refs when invoked from `main`
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
    """Rebase stacked PR branches onto their base branches via `git rebase --update-refs`."""
    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)

    targets = _collect_restack_targets(real_root, ws_dir, pr_id, onto_branch, runner)
    restacked: list[str] = []
    details: list[dict[str, Any]] = []
    commands: list[list[str]] = []

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
    """Resolve `(target_arg, pr_dir, proj_doc)` from a PR ID, slug, branch, or GitHub PR number."""
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
    """Render a deterministic GitHub PR body from `PROJECT.md` Charter and Work Orders."""
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
    """Extract `(pr_number, pr_url)` from `gh pr create` or `gh pr view --json` output."""
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
    """Extract an issue URL from `gh issue create` stdout."""
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

    m = _ISSUE_URL_RE.search(cleaned)
    if m:
        return m.group(1)

    for line in reversed(cleaned.splitlines()):
        line_s = line.strip()
        if line_s.startswith(("http://", "https://")):
            return line_s
    return None


@runtime_checkable
class VcsBus(Protocol):
    """Protocol for the Principal Architect VCS synchronization bus (`local_git` & `github`)."""

    mode: Literal["local_git", "github"]
    repo_root: Path
    runner: common.Runner

    def create_or_checkout_branch(self, branch: str, base_branch: str = "main") -> str: ...

    def read_commit_trailers(
        self,
        *,
        rev_range: str | None = None,
        max_count: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def format_commit_with_trailers(
        self,
        subject: str,
        body: str | None = None,
        trailers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
    ) -> str: ...

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
    ) -> Path: ...

    def append_deferred_backlog(
        self,
        *,
        title: str,
        summary: str = "",
        pr_id: str | None = None,
        wo_id: str | None = None,
        labels: Sequence[str] = ("pa:deferred",),
        file_path: str | None = None,
    ) -> Path: ...

    def create_deferred_issue(
        self,
        *,
        title: str,
        summary: str = "",
        pr_id: str | None = None,
        wo_id: str | None = None,
        labels: Sequence[str] = ("pa:deferred",),
        file_path: str | None = None,
    ) -> dict[str, Any]: ...

    def open_or_sync_pr(self, pr_id: str, *, draft: bool = False) -> dict[str, Any]: ...

    def view_pr(self, pr_id_or_number: str | int) -> dict[str, Any]: ...

    def diff_pr(self, pr_id_or_number: str | int) -> str: ...

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
    ) -> dict[str, Any]: ...

    def sync_audit(self, pr_id: str) -> dict[str, Any] | None: ...

    def sync_state(self) -> dict[str, Any]: ...

    def restack_branches(
        self,
        *,
        pr_id: str | None = None,
        onto_branch: str | None = None,
    ) -> dict[str, Any]: ...


class LocalGitBus:
    """Offline Local-Git floor implementation requiring zero GitHub or network access."""

    mode: Literal["local_git", "github"] = "local_git"

    def __init__(
        self,
        repo_root: str | Path,
        *,
        runner: common.Runner = common.run,
    ) -> None:
        self.repo_root = Path(os.path.realpath(repo_root))
        self.runner = runner

    def create_or_checkout_branch(self, branch: str, base_branch: str = "main") -> str:
        """Create `<branch>` from `<base_branch>` or check it out if it already exists."""
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
        """Read `PA-*` commit trailers from local `git log`."""
        return read_commit_trailers(
            self.repo_root,
            rev_range=rev_range,
            max_count=max_count,
            runner=self.runner,
        )

    read_trailers = read_commit_trailers

    def format_commit_with_trailers(
        self,
        subject: str,
        body: str | None = None,
        trailers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
    ) -> str:
        """Format a commit message with `Key: Value` trailers."""
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
        """Write `<pr_dir>/AUDIT-round-<K>.md`, update `PROJECT.md` status, and commit."""
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
        """Append a deferred finding to `<workspace_dir>/DEFERRED_BACKLOG.md`."""
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
        """Record a deferred issue in local `DEFERRED_BACKLOG.md`."""
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
        """Transition `<PR-ID>` to `STAGED_FOR_AUDIT` and verify local branch against base."""
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
        """Return PR metadata from local `PROJECT.md` and `AUDIT-round-*.md` files."""
        ws_dir = common.workspace_dir(self.repo_root)
        target, pr_dir, proj_doc = _resolve_pr_target(ws_dir, pr_id_or_number)
        if proj_doc is None or pr_dir is None:
            raise ValueError(f"PR '{pr_id_or_number}' not found in {ws_dir}")

        head_res = self.runner(["git", "rev-parse", "HEAD"], cwd=self.repo_root)
        head_sha = head_res.stdout.strip() if head_res.returncode == 0 else ""
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
        """Return local `git diff <base_branch>...<branch>` for `pr_id_or_number`."""
        ws_dir = common.workspace_dir(self.repo_root)
        _, _, proj_doc = _resolve_pr_target(ws_dir, pr_id_or_number)
        if proj_doc is not None:
            base_branch = proj_doc.spec.charter.base_branch
            branch = proj_doc.spec.charter.branch
        else:
            base_branch = "main"
            branch = "HEAD"

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
        """Persist `AUDIT-round-<K>.md` locally, commit with trailer, and update `state.db`."""
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
        """Sync the latest `AUDIT-round-<K>.md` for `pr_id` into `.state/state.db`."""
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
        """Rebuild `.state/state.db` and reconcile `PROJECT.md` summary rows from local Git."""
        return _local_sync_state(self.repo_root, runner=self.runner)

    def restack_branches(
        self,
        *,
        pr_id: str | None = None,
        onto_branch: str | None = None,
    ) -> dict[str, Any]:
        """Rebase stacked branches via `git rebase --update-refs`."""
        return _local_restack_branches(
            self.repo_root,
            pr_id=pr_id,
            onto_branch=onto_branch,
            runner=self.runner,
        )


class GitHubBus(LocalGitBus):
    """GitHub multi-machine synchronization bus (`vcs_mode == 'github'`)."""

    mode: Literal["local_git", "github"] = "github"

    def open_or_sync_pr(self, pr_id: str, *, draft: bool = False) -> dict[str, Any]:
        """Stage `<PR-ID>`, push branch to `origin`, and create or update the GitHub PR."""
        local_info = super().open_or_sync_pr(pr_id, draft=draft)
        ws_dir = common.workspace_dir(self.repo_root)
        pr_dir, proj_doc = _find_pr_dir_and_project(ws_dir, pr_id)
        if proj_doc is None:
            raise ValueError(f"PROJECT.md for '{pr_id}' not found in {ws_dir}")

        proj_md = pr_dir / "PROJECT.md"
        branch = proj_doc.spec.charter.branch
        base_branch = proj_doc.spec.charter.base_branch
        canonical_pr_id = proj_doc.spec.charter.pr_id

        # 1. Push branch to origin
        self.runner(["git", "push", "-u", "origin", branch], cwd=self.repo_root)

        # 2. Build deterministic PR title and body
        title = f"{canonical_pr_id}: {proj_doc.spec.charter.title}"
        body = _render_pr_body(proj_doc)

        gh = _gh_bin()
        pr_number: int | None = proj_doc.spec.github_pr
        pr_url: str | None = None
        pr_existed = pr_number is not None

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
        """Inspect a GitHub PR via `gh pr view <target> --json ...`."""
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
        try:
            data = json.loads(res.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse gh pr view JSON for '{target}': {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected gh pr view payload for '{target}'")  # noqa: TRY004
        return data

    def diff_pr(self, pr_id_or_number: str | int) -> str:
        """Fetch PR diff via `gh pr diff <target>`, falling back to local `git diff`."""
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
        """Write and commit `AUDIT-round-<K>.md` locally and post via `gh pr review --comment`."""
        local_res = super().post_audit(pr_id, audit_source, commit=commit)
        audit_doc = schemas.load_audit(local_res["audit_path"])
        report = audit_doc.spec

        existing_body = "\n".join(s.full_text() for s in audit_doc.sections).strip()
        comment_body = format_pa_audit_comment(
            report, existing_body if existing_body else None
        )

        ws_dir = common.workspace_dir(self.repo_root)
        state_dir = ws_dir / ".state"
        state_dir.mkdir(parents=True, exist_ok=True)
        body_file = state_dir / f"audit_comment_{report.pr_id.lower()}_r{report.audit_round}.md"
        body_file.write_text(comment_body, encoding="utf-8")

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
        """Ingest remote `<!-- pa:audit ... -->` PR comments into `AUDIT-round-<K>.md` & `state.db`."""
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

            if isinstance(payload, Mapping):
                remote_num = (
                    int(payload["number"])
                    if isinstance(payload.get("number"), int)
                    else (proj_doc.spec.github_pr if proj_doc is not None else None)
                )
                items: list[ Any] = []
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
        """Create a GitHub issue with `--label pa:deferred` and record in `DEFERRED_BACKLOG.md`."""
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
        """Fetch `origin`, sync remote GitHub PR audits, and rebuild `.state/state.db`."""
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
        """Rebase stacked PR branches, force-push with lease, and retarget GitHub PR bases."""
        res = super().restack_branches(pr_id=pr_id, onto_branch=onto_branch)
        ws_dir = common.workspace_dir(self.repo_root)
        gh = _gh_bin()

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
) -> VcsBus:
    """Return the configured `VcsBus` instance (`GitHubBus` or `LocalGitBus`)."""
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

    if str(resolved_mode).strip().lower() == "github":
        return GitHubBus(real_root, runner=runner)
    return LocalGitBus(real_root, runner=runner)


def sync_state(
    repo_root: str | Path,
    *,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Rebuild `.state/state.db` and reconcile `PROJECT.md` rows via the active `VcsBus`."""
    return get_vcs_bus(repo_root, runner=runner).sync_state()


def restack_branches(
    repo_root: str | Path,
    *,
    pr_id: str | None = None,
    onto_branch: str | None = None,
    runner: common.Runner = common.run,
) -> dict[str, Any]:
    """Rebase stacked PR branches onto their base branches via the active `VcsBus`."""
    return get_vcs_bus(repo_root, runner=runner).restack_branches(
        pr_id=pr_id,
        onto_branch=onto_branch,
    )
