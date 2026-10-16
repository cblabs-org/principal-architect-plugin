"""Mutually exclusive `external` vs. `builtin` memory graduation engine (`memory_grad.py`).

Implements SPEC §9.1–9.2, Invariant I6, and PR-03 Charter G3 & R5:
- `graduate(repo_root, pr_id, *, memory_mode=None, completed_date=None) -> dict[str, Any]`
- Mode A (`memory_mode == "external"`): strict zero-touch boundary on `<workspace_dir>/memory/`
  (never creates `memory/` and never creates, reads, or mutates `MEMORY.md`, `MODULE_INDEX.md`,
  or `PROJECT_INDEX.md`), writing only a succinct mechanical graduation summary to `PROJECT.md`
  Part III (`## 4.`) and setting `status: GRADUATED`.
- Mode B (`memory_mode == "builtin"`): updates `MEMORY.md` (removing from `## Active Projects`,
  prepending to `## Recently Completed (last 5)`), rolls entries beyond the 5-PR window into
  `PROJECT_INDEX.md`, and idempotently records module rows under `charter.allowed_modules` in
  `MODULE_INDEX.md` with byte-for-byte stability across repeated invocations.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import schemas
import state_db

MAX_RECENT_COMPLETED: int = 5

_GRAD_SUMMARY_START = "<!-- pa:graduation-summary start -->"
_GRAD_SUMMARY_END = "<!-- pa:graduation-summary end -->"
_GRAD_SUMMARY_BLOCK_RE = re.compile(
    re.escape(_GRAD_SUMMARY_START) + r".*?" + re.escape(_GRAD_SUMMARY_END),
    flags=re.DOTALL,
)
_GRAD_COMPLETED_DATE_RE = re.compile(
    r"^\s*-\s*\*\*Completed Date:\*\*\s*(\d{4}-\d{2}-\d{2})\s*$",
    flags=re.MULTILINE,
)
_LAST_UPDATED_COMMENT_RE = re.compile(r"<!--\s*Last updated:.*?-->")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_PR_DIR_LINK_RE = re.compile(r"\.\./([^/)\s]+)/PROJECT\.md", flags=re.IGNORECASE)
_SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")


def _sanitize_cell(text: str) -> str:
    """Sanitize a string for safe inclusion inside a Markdown table cell."""
    cleaned = " ".join(str(text).splitlines()).strip()
    return cleaned.replace("|", "/")


def _split_table_row(line: str) -> list[str]:
    """Split a Markdown table row `| a | b |` into stripped cell strings."""
    inner = line.strip().removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in inner.split("|")]


def _is_separator_row(line: str) -> bool:
    """Return True if `line` is a Markdown table separator row like `|---|---|`."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    cells = _split_table_row(stripped)
    if not cells:
        return False
    return all(_SEPARATOR_CELL_RE.match(c) is not None for c in cells)


def _find_project_for_pr(
    ws_dir: Path,
    pr_id: str,
) -> tuple[Path, Path, schemas.Document[schemas.ProjectSpec]]:
    """Locate `<pr_dir>`, `<pr_dir>/PROJECT.md`, and loaded `Document[ProjectSpec]` for `pr_id`."""
    raw = pr_id.strip()
    if not raw:
        raise ValueError("pr_id must not be empty")

    pr_upper = raw.upper()
    slug_low = raw.lower()

    for proj_md in sorted(ws_dir.glob("pr-*/PROJECT.md")):
        pr_dir = proj_md.parent
        try:
            doc = schemas.load_project(proj_md)
        except Exception:  # noqa: BLE001, S112
            continue

        c_pr_id = doc.spec.charter.pr_id.upper()
        c_slug = doc.spec.charter.slug.lower()
        dir_low = pr_dir.name.lower()
        if (
            c_pr_id == pr_upper
            or c_slug == slug_low
            or dir_low == slug_low
            or dir_low.startswith(f"{slug_low}-")
            or (slug_low.startswith("pr-") and c_slug.startswith(f"{slug_low}-"))
        ):
            return pr_dir, proj_md, doc

    raise FileNotFoundError(f"PROJECT.md not found for PR '{pr_id}' under {ws_dir}")


def _resolve_memory_mode(ws_dir: Path, memory_mode: str | None) -> str:
    """Resolve and validate `memory_mode` ('external' or 'builtin')."""
    if memory_mode is None:
        db_path = ws_dir / ".state" / "state.db"
        if db_path.is_file():
            with state_db.StateDB(db_path) as db:
                cfg_val = db.get_config("memory_mode")
            resolved = (cfg_val or "builtin").strip().lower()
        else:
            resolved = "builtin"
    else:
        resolved = str(memory_mode).strip().lower()

    if resolved not in ("external", "builtin"):
        raise ValueError(
            f"Invalid memory_mode '{memory_mode}'; expected 'external' or 'builtin'"
        )
    return resolved


def _resolve_completed_date(
    proj_doc: schemas.Document[schemas.ProjectSpec],
    completed_date: str | None,
) -> str:
    """Resolve a deterministic `YYYY-MM-DD` graduation date for `proj_doc`."""
    if completed_date is not None and str(completed_date).strip():
        return str(completed_date).strip()[:10]

    sec4 = proj_doc.section("## 4.")
    if sec4 is not None and sec4.body:
        m_existing = _GRAD_COMPLETED_DATE_RE.search(sec4.body)
        if m_existing:
            return m_existing.group(1)

    approved_at = proj_doc.spec.approved_at
    if approved_at is not None:
        if isinstance(approved_at, datetime):
            return approved_at.strftime("%Y-%m-%d")
        app_str = str(approved_at).strip()
        if len(app_str) >= 10:
            return app_str[:10]

    return datetime.now(UTC).strftime("%Y-%m-%d")


def _latest_audit_summary(pr_dir: Path) -> str:
    """Return a concise 1-line summary of the highest-numbered `AUDIT-round-<K>.md` in `pr_dir`."""
    best_round = -1
    best_doc: schemas.Document[schemas.AuditReport] | None = None
    for audit_path in sorted(pr_dir.glob("AUDIT-round-*.md")):
        try:
            doc = schemas.load_audit(audit_path)
        except Exception:  # noqa: BLE001, S112
            continue
        if doc.spec.audit_round > best_round:
            best_round = doc.spec.audit_round
            best_doc = doc

    if best_doc is None:
        return "none"
    rep = best_doc.spec
    return f"Round {rep.audit_round} — `{rep.verdict}` (`{rep.head_sha[:12]}`)"


def _collect_wo_rows(
    pr_dir: Path,
    proj_doc: schemas.Document[schemas.ProjectSpec],
) -> list[tuple[str, str, int, str]]:
    """Collect `(wo_id, status, attempts, commit_sha)` rows for the graduation summary table."""
    if proj_doc.spec.work_orders:
        return [
            (
                row.id,
                row.status.value,
                int(row.attempts),
                (row.commit_sha[:12] if row.commit_sha else "-"),
            )
            for row in proj_doc.spec.work_orders
        ]

    rows: list[tuple[str, str, int, str]] = []
    for wo_md in sorted(pr_dir.glob("wo*/WORKORDER.md")):
        try:
            wo_doc = schemas.load_workorder(wo_md)
        except Exception:  # noqa: BLE001, S112
            continue
        wspec = wo_doc.spec
        comp = wspec.completion
        attempts = int(comp.attempt_num) if comp is not None else 0
        sha = (comp.commit_sha[:12] if comp and comp.commit_sha else "-")
        rows.append((wspec.wo_id, wspec.status.value, attempts, sha))
    return rows


def _build_graduation_summary_block(
    pr_dir: Path,
    proj_doc: schemas.Document[schemas.ProjectSpec],
    *,
    memory_mode: str,
    completed_date: str,
) -> str:
    """Build the bounded `<!-- pa:graduation-summary start --> ...` block for `PROJECT.md` Part III."""
    pr_id = proj_doc.spec.charter.pr_id
    slug = proj_doc.spec.charter.slug
    audit_line = _latest_audit_summary(pr_dir)
    wo_rows = _collect_wo_rows(pr_dir, proj_doc)

    lines: list[str] = [
        _GRAD_SUMMARY_START,
        f"### Graduation Summary (`{pr_id}` / `{slug}` — `GRADUATED`)",
        "",
        f"- **Completed Date:** {completed_date}",
        f"- **Graduation Mode:** `{memory_mode}`",
        f"- **Latest Audit:** {audit_line}",
        "",
        "| WO-ID | Status | Attempts | Commit SHA |",
        "|---|---|---|---|",
    ]
    if wo_rows:
        for wo_id, status_str, attempts, sha in wo_rows:
            lines.append(f"| {wo_id} | {status_str} | {attempts} | `{sha}` |")
    else:
        lines.append("| - | COMPLETED | 0 | `-` |")
    lines.append(_GRAD_SUMMARY_END)
    return "\n".join(lines)


def _update_project_and_program_status(
    ws_dir: Path,
    pr_dir: Path,
    proj_md: Path,
    proj_doc: schemas.Document[schemas.ProjectSpec],
    *,
    memory_mode: str,
    completed_date: str,
) -> None:
    """Set `PROJECT.md` (and optional `PROGRAM.md`) status to `GRADUATED` and write summary."""
    proj_doc.spec.status = schemas.PRState.GRADUATED
    summary_block = _build_graduation_summary_block(
        pr_dir,
        proj_doc,
        memory_mode=memory_mode,
        completed_date=completed_date,
    )

    sec4 = proj_doc.section("## 4.")
    if sec4 is None:
        raise ValueError(f"PROJECT.md is missing required section '## 4.': {proj_md}")

    if _GRAD_SUMMARY_BLOCK_RE.search(sec4.body):
        sec4.body = _GRAD_SUMMARY_BLOCK_RE.sub(lambda _: summary_block, sec4.body, count=1)
    else:
        stripped = sec4.body.rstrip()
        if stripped:
            if not stripped.startswith("\n"):
                stripped = "\n" + stripped
            sec4.body = f"{stripped}\n\n{summary_block}\n"
        else:
            sec4.body = f"\n{summary_block}\n"

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
            f"PROJECT.md charter_hash verification failed after graduation: {proj_md}"
        )

    canonical_pr_id = proj_doc.spec.charter.pr_id.upper()
    slug_low = proj_doc.spec.charter.slug.lower()
    prog_id = proj_doc.spec.charter.programme_id

    for prog_md in sorted(ws_dir.glob("programme-*/PROGRAM.md")):
        try:
            prog_doc = schemas.load_program(prog_md)
        except Exception:  # noqa: BLE001, S112
            continue
        if prog_id and prog_doc.spec.programme_id.lower() != prog_id.lower():
            continue
        changed = False
        for pr_node in prog_doc.spec.prs:
            if (
                pr_node.id.upper() == canonical_pr_id or pr_node.slug.lower() == slug_low
            ) and pr_node.status != schemas.PRState.GRADUATED:
                pr_node.status = schemas.PRState.GRADUATED
                changed = True
        if changed:
            prog_md.write_text(
                schemas.dump_document(prog_doc.spec, prog_doc.sections),
                encoding="utf-8",
            )


def _row_matches_pr(
    row_line: str,
    *,
    pr_id: str,
    slug: str,
    pr_dir_name: str,
) -> bool:
    """Return True if a Markdown table row refers to `(pr_id, slug, pr_dir_name)`."""
    cells = _split_table_row(row_line)
    if not cells:
        return False

    first_cell = cells[0].strip()
    m_link = _MD_LINK_RE.search(first_cell)
    label = m_link.group(1).strip().lower() if m_link else first_cell.strip("`* ").lower()

    pr_low = pr_id.strip().lower()
    slug_low = slug.strip().lower()
    dir_low = pr_dir_name.strip().lower()

    if label in (pr_low, slug_low, dir_low):
        return True

    # Prefix match for e.g. 'pr-01' seeded in ## Active Projects when full slug is 'pr-01-alpha'
    if re.fullmatch(rf"{re.escape(pr_low)}(?:-[a-z0-9-]+)?", label):
        return True

    row_low = row_line.lower()
    return f"../{dir_low}/project.md" in row_low or f"../{slug_low}/project.md" in row_low


def _extract_slug_and_dir_from_row(row_line: str) -> tuple[str, str]:
    """Extract `(slug, pr_dir_name)` from a completed table row `| [<slug>](../<dir>/PROJECT.md) | ...`."""
    cells = _split_table_row(row_line)
    first_cell = cells[0] if cells else ""

    m_link = _MD_LINK_RE.search(first_cell)
    slug = m_link.group(1).strip() if m_link else first_cell.strip("`* ")

    m_dir = _PR_DIR_LINK_RE.search(row_line)
    pr_dir_name = m_dir.group(1).strip() if m_dir else slug
    return slug, pr_dir_name


def _update_markdown_table_in_block(
    block_text: str,
    transform_fn: Callable[[list[str]], list[str]],
    default_header: tuple[str, str],
) -> str:
    """Locate the first Markdown table in `block_text` and replace its data rows via `transform_fn`."""
    lines = block_text.splitlines()
    sep_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx - 1].strip().startswith("|") and _is_separator_row(lines[idx]):
            sep_idx = idx
            break

    if sep_idx is None:
        new_rows = transform_fn([])
        out_lines = list(lines)
        if out_lines and out_lines[-1].strip():
            out_lines.append("")
        out_lines.append(default_header[0])
        out_lines.append(default_header[1])
        out_lines.extend(new_rows)
        return "\n".join(out_lines) + "\n"

    data_start = sep_idx + 1
    data_end = data_start
    while data_end < len(lines) and lines[data_end].strip().startswith("|"):
        data_end += 1

    existing_rows = [lines[i].strip() for i in range(data_start, data_end)]
    updated_rows = transform_fn(existing_rows)

    rebuilt = lines[:data_start] + updated_rows + lines[data_end:]
    trailing_nl = "\n" if block_text.endswith("\n") else ""
    return "\n".join(rebuilt) + trailing_nl


def _ensure_builtin_memory_files(mem_dir: Path, completed_date: str) -> tuple[Path, Path, Path]:
    """Ensure `MEMORY.md`, `MODULE_INDEX.md`, and `PROJECT_INDEX.md` exist in `mem_dir`."""
    mem_dir.mkdir(parents=True, exist_ok=True)
    memory_md = mem_dir / "MEMORY.md"
    module_index_md = mem_dir / "MODULE_INDEX.md"
    project_index_md = mem_dir / "PROJECT_INDEX.md"

    tpl_vars = {"updated_at": completed_date}
    if not memory_md.is_file():
        memory_md.write_text(
            common.render_template_file("MEMORY.md.tpl", tpl_vars),
            encoding="utf-8",
        )
    if not module_index_md.is_file():
        module_index_md.write_text(
            common.render_template_file("MODULE_INDEX.md.tpl", tpl_vars),
            encoding="utf-8",
        )
    if not project_index_md.is_file():
        project_index_md.write_text(
            common.render_template_file("PROJECT_INDEX.md.tpl", tpl_vars),
            encoding="utf-8",
        )

    return memory_md, module_index_md, project_index_md


def _update_memory_md(
    memory_md: Path,
    *,
    pr_id: str,
    slug: str,
    pr_dir_name: str,
    completed_date: str,
    modules_summary: str,
    key_outcome: str,
) -> list[str]:
    """Update `MEMORY.md` and return any rows that rolled off the 5-PR window."""
    raw_text = memory_md.read_text(encoding="utf-8")
    raw_text = _LAST_UPDATED_COMMENT_RE.sub(
        f"<!-- Last updated: {completed_date} -->",
        raw_text,
        count=1,
    )

    chunks = re.split(r"(?m)^(?=## )", raw_text)
    completed_row = (
        f"| [{slug}](../{pr_dir_name}/PROJECT.md) | {completed_date} "
        f"| {_sanitize_cell(modules_summary)} | {_sanitize_cell(key_outcome)} |"
    )

    overflow_rows: list[str] = []
    updated_chunks: list[str] = []
    found_recent = False

    for chunk in chunks:
        if chunk.startswith("## Active Projects"):
            chunk = _update_markdown_table_in_block(
                chunk,
                lambda rows: [
                    r
                    for r in rows
                    if not _row_matches_pr(r, pr_id=pr_id, slug=slug, pr_dir_name=pr_dir_name)
                ],
                ("| Project | Status | Modules | Context |", "|---|---|---|---|"),
            )
        elif chunk.startswith("## Recently Completed"):
            found_recent = True

            def _transform_recent(rows: list[str]) -> list[str]:
                filtered = [
                    r
                    for r in rows
                    if not _row_matches_pr(r, pr_id=pr_id, slug=slug, pr_dir_name=pr_dir_name)
                ]
                combined = [completed_row, *filtered]
                kept = combined[:MAX_RECENT_COMPLETED]
                overflow_rows.extend(combined[MAX_RECENT_COMPLETED:])
                return kept

            chunk = _update_markdown_table_in_block(
                chunk,
                _transform_recent,
                ("| Project | Completed | Modules | Key Outcome |", "|---|---|---|---|"),
            )
        updated_chunks.append(chunk)

    if not found_recent:
        recent_sec = (
            "\n## Recently Completed (last 5)\n\n"
            "| Project | Completed | Modules | Key Outcome |\n"
            "|---|---|---|---|\n"
            f"{completed_row}\n"
        )
        updated_chunks.append(recent_sec)

    final_text = "".join(updated_chunks)
    if not final_text.endswith("\n"):
        final_text += "\n"
    memory_md.write_text(final_text, encoding="utf-8")
    return overflow_rows


def _update_project_index_md(
    project_index_md: Path,
    overflow_rows: list[str],
) -> list[str]:
    """Archive rolled-off rows from `MEMORY.md` into `PROJECT_INDEX.md` idempotently."""
    rolled_off_slugs: list[str] = []
    if not overflow_rows:
        return rolled_off_slugs

    entries_to_archive: list[tuple[str, str, str]] = []
    for ov_row in overflow_rows:
        cells = _split_table_row(ov_row)
        ro_slug, ro_dir = _extract_slug_and_dir_from_row(ov_row)
        ro_completed = cells[1] if len(cells) > 1 else ""
        ro_modules = cells[2] if len(cells) > 2 else ""
        ro_outcome = cells[3] if len(cells) > 3 else ro_modules
        scope_cell = _sanitize_cell(ro_outcome or ro_modules)
        pi_row = (
            f"| [{ro_slug}](../{ro_dir}/PROJECT.md) | {ro_completed} "
            f"| {scope_cell} | {ro_completed} | [PROJECT.md](../{ro_dir}/PROJECT.md) |"
        )
        rolled_off_slugs.append(ro_slug)
        entries_to_archive.append((ro_slug, ro_dir, pi_row))

    raw_text = project_index_md.read_text(encoding="utf-8")

    def _transform_archive(rows: list[str]) -> list[str]:
        updated = list(rows)
        for ro_slug, ro_dir, pi_row in entries_to_archive:
            replaced = False
            for idx, existing in enumerate(updated):
                ex_slug, ex_dir = _extract_slug_and_dir_from_row(existing)
                if ex_slug.lower() == ro_slug.lower() or ex_dir.lower() == ro_dir.lower():
                    updated[idx] = pi_row
                    replaced = True
                    break
            if not replaced:
                updated.append(pi_row)
        return updated

    updated_text = _update_markdown_table_in_block(
        raw_text,
        _transform_archive,
        ("| Project | Completed | Scope | Session | Context |", "|---|---|---|---|---|"),
    )
    if not updated_text.endswith("\n"):
        updated_text += "\n"
    project_index_md.write_text(updated_text, encoding="utf-8")
    return rolled_off_slugs


def _heading_matches_module(heading_line: str, module_str: str) -> bool:
    """Return True if an H2 heading line (`## ...`) matches `module_str`."""
    h_text = heading_line.removeprefix("## ").strip()
    mod_clean = module_str.strip()
    if not h_text or not mod_clean:
        return False

    h_low = h_text.lower()
    mod_low = mod_clean.lower()
    mod_stripped = mod_low.strip("/")

    if h_low == mod_low or h_low.strip("/") == mod_stripped:
        return True
    return bool(mod_stripped and mod_stripped in h_low)


def _update_module_index_md(
    module_index_md: Path,
    *,
    pr_id: str,
    slug: str,
    pr_dir_name: str,
    title: str,
    allowed_modules: list[str],
) -> None:
    """Idempotently record `slug` under each module in `allowed_modules` inside `MODULE_INDEX.md`."""
    raw_text = module_index_md.read_text(encoding="utf-8")
    chunks = re.split(r"(?m)^(?=## )", raw_text)

    if chunks and not chunks[0].startswith("## "):
        preamble = chunks[0]
        h2_chunks = list(chunks[1:])
    else:
        preamble = ""
        h2_chunks = list(chunks)

    mod_row = (
        f"| [{slug}](../{pr_dir_name}/PROJECT.md) | {_sanitize_cell(title)} "
        f"| [PROJECT.md](../{pr_dir_name}/PROJECT.md) |"
    )

    def _upsert_mod_row(rows: list[str]) -> list[str]:
        updated = list(rows)
        for idx, existing in enumerate(updated):
            if _row_matches_pr(existing, pr_id=pr_id, slug=slug, pr_dir_name=pr_dir_name):
                updated[idx] = mod_row
                return updated
        updated.append(mod_row)
        return updated

    for raw_mod in allowed_modules:
        mod_clean = str(raw_mod).strip()
        if not mod_clean:
            continue

        matched_idx: int | None = None
        for idx, sec_chunk in enumerate(h2_chunks):
            first_line = sec_chunk.splitlines()[0] if sec_chunk else ""
            if _heading_matches_module(first_line, mod_clean):
                matched_idx = idx
                break

        if matched_idx is not None:
            h2_chunks[matched_idx] = _update_markdown_table_in_block(
                h2_chunks[matched_idx],
                _upsert_mod_row,
                ("| Project | Scope | Context |", "|---|---|---|"),
            )
        else:
            new_sec = (
                f"## {mod_clean}\n\n"
                "| Project | Scope | Context |\n"
                "|---|---|---|\n"
                f"{mod_row}\n"
            )
            h2_chunks.append(new_sec)

    parts: list[str] = []
    if preamble.strip():
        parts.append(preamble.rstrip() + "\n")
    for sec in h2_chunks:
        parts.append(sec.strip() + "\n")

    final_text = "\n".join(parts)
    if not final_text.endswith("\n"):
        final_text += "\n"
    module_index_md.write_text(final_text, encoding="utf-8")


def graduate(
    repo_root: str | Path,
    pr_id: str,
    *,
    memory_mode: str | None = None,
    completed_date: str | None = None,
) -> dict[str, Any]:
    """Graduate `pr_id` according to the mutually exclusive `external` vs. `builtin` memory mode.

    In `external` mode (`repo-memory` active):
    - Updates `PROJECT.md` status to `GRADUATED` and writes a succinct mechanical graduation
      summary to Part III (`## 4.`).
    - Updates `PROGRAM.md` PR node status to `GRADUATED` if present.
    - NEVER creates `<workspace_dir>/memory/` and NEVER creates, reads, or modifies
      `MEMORY.md`, `MODULE_INDEX.md`, or `PROJECT_INDEX.md`.

    In `builtin` mode:
    - Updates `PROJECT.md` and `PROGRAM.md` as above.
    - Removes the PR from `MEMORY.md` `## Active Projects`, prepends it to
      `## Recently Completed (last 5)`, rolls any entries beyond the 5-PR window into
      `PROJECT_INDEX.md`, and idempotently records module rows in `MODULE_INDEX.md`.
    """
    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)
    resolved_mode = _resolve_memory_mode(ws_dir, memory_mode)

    pr_dir, proj_md, proj_doc = _find_project_for_pr(ws_dir, pr_id)
    canonical_pr_id = proj_doc.spec.charter.pr_id
    slug = proj_doc.spec.charter.slug
    resolved_date = _resolve_completed_date(proj_doc, completed_date)

    _update_project_and_program_status(
        ws_dir,
        pr_dir,
        proj_md,
        proj_doc,
        memory_mode=resolved_mode,
        completed_date=resolved_date,
    )

    if resolved_mode == "external":
        return {
            "pr_id": canonical_pr_id,
            "slug": slug,
            "memory_mode": "external",
            "status": schemas.PRState.GRADUATED.value,
            "project_md": str(proj_md),
            "memory_files_touched": [],
            "rolled_off_prs": [],
        }

    mem_dir = ws_dir / "memory"
    memory_md, module_index_md, project_index_md = _ensure_builtin_memory_files(
        mem_dir, resolved_date
    )

    modules_summary = ", ".join(proj_doc.spec.charter.allowed_modules)
    key_outcome = proj_doc.spec.charter.title

    overflow_rows = _update_memory_md(
        memory_md,
        pr_id=canonical_pr_id,
        slug=slug,
        pr_dir_name=pr_dir.name,
        completed_date=resolved_date,
        modules_summary=modules_summary,
        key_outcome=key_outcome,
    )
    rolled_off_slugs = _update_project_index_md(project_index_md, overflow_rows)
    _update_module_index_md(
        module_index_md,
        pr_id=canonical_pr_id,
        slug=slug,
        pr_dir_name=pr_dir.name,
        title=proj_doc.spec.charter.title,
        allowed_modules=list(proj_doc.spec.charter.allowed_modules),
    )

    return {
        "pr_id": canonical_pr_id,
        "slug": slug,
        "memory_mode": "builtin",
        "status": schemas.PRState.GRADUATED.value,
        "project_md": str(proj_md),
        "memory_files_touched": [
            str(memory_md),
            str(module_index_md),
            str(project_index_md),
        ],
        "rolled_off_prs": rolled_off_slugs,
    }
