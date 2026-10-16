"""Comprehensive unit and byte-stability tests for `memory_grad.py` (`WO-03.3`).

Verifies the strict mutual-exclusion boundary between `external` (`repo-memory`) and
`builtin` (3-file index) graduation modes (Charter G3 & R5, Invariant I6, SPEC §9.1–9.2).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import common
import memory_grad
import pytest
import schemas
import state_db


def _sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of `path`."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_locked_project(
    ws_dir: Path,
    *,
    pr_id: str = "PR-01",
    slug: str = "pr-01-alpha",
    title: str | None = None,
    branch: str | None = None,
    base_branch: str = "main",
    allowed_modules: list[str] | None = None,
    work_orders: list[schemas.WOSummaryRow] | None = None,
    status: schemas.PRState = schemas.PRState.AUDIT_APPROVED,
    approved_at: str | None = "2026-10-16T21:37:00Z",
) -> Path:
    """Create a valid `PROJECT.md` with a verified `charter_hash` under `ws_dir / slug`."""
    pr_dir = ws_dir / slug
    pr_dir.mkdir(parents=True, exist_ok=True)
    proj_md = pr_dir / "PROJECT.md"

    charter = schemas.PRCharterSpec(
        pr_id=pr_id,
        programme_id="prog-alpha",
        slug=slug,
        title=title or f"Deliver {slug} subsystem",
        branch=branch or f"feat/{slug}",
        base_branch=base_branch,
        allowed_modules=allowed_modules or ["src/auth/", "src/api/"],
        verification_floor=["pytest"],
        charter_locked=True,
    )
    sections = [
        schemas.Section(
            heading="## 1. PR Charter: Scope, Goals, & Non-Goals",
            body="\nScope and goals.\n",
        ),
        schemas.Section(
            heading="## 2. Architectural Requirements, Cross-PR Interfaces, & Required Skills/Tools",
            body="\nArchitectural requirements.\n",
        ),
        schemas.Section(
            heading="## 3. Implementation Plan & Work Order Breakdown",
            body="\nWork order breakdown.\n",
        ),
        schemas.Section(
            heading="## 4. Outcome & Session Log",
            body="\n- **2026-10-16:** Approved for execution.\n",
        ),
    ]
    charter.charter_hash = schemas.compute_charter_hash(charter, sections)
    spec = schemas.ProjectSpec(
        charter=charter,
        status=status,
        approved_at=approved_at,
        work_orders=work_orders
        or [
            schemas.WOSummaryRow(
                id=f"WO-{pr_id.split('-')[1]}.1",
                slug="wo1-impl",
                title="Implement core module",
                complexity=schemas.ComplexityTier.standard,
                status=schemas.WorkOrderStatus.COMPLETED,
                attempts=1,
                commit_sha="114ace23784b67850f8d1455e48fa5855ec6aa43",
            )
        ],
    )
    proj_md.write_text(schemas.dump_document(spec, sections), encoding="utf-8")
    assert schemas.verify_charter_hash(proj_md)
    return proj_md


def _write_program(ws_dir: Path, prs: list[schemas.PRNodeSpec]) -> Path:
    """Create a valid `PROGRAM.md` under `ws_dir / programme-alpha`."""
    prog_dir = ws_dir / "programme-alpha"
    prog_dir.mkdir(parents=True, exist_ok=True)
    prog_md = prog_dir / "PROGRAM.md"

    spec = schemas.ProgramSpec(
        programme_id="prog-alpha",
        title="Alpha Programme",
        base_branch="main",
        status="ACTIVE",
        prs=prs,
    )
    sections = [
        schemas.Section(heading="## 1. Programme Overview", body="\nOverview.\n"),
        schemas.Section(heading="## 2. Stacked PR Architecture", body="\nDAG.\n"),
        schemas.Section(heading="## 3. Session Log", body="\nLog.\n"),
    ]
    prog_md.write_text(schemas.dump_document(spec, sections), encoding="utf-8")
    return prog_md


def _recent_completed_rows(memory_md_text: str) -> list[str]:
    """Extract the data rows under `## Recently Completed (last 5)` from `MEMORY.md` text."""
    lines = memory_md_text.splitlines()
    in_recent = False
    after_sep = False
    rows: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if stripped.startswith("## Recently Completed"):
                in_recent = True
                after_sep = False
                continue
            if in_recent:
                break
        if in_recent:
            if not after_sep:
                if memory_grad._is_separator_row(stripped):
                    after_sep = True
                continue
            if stripped.startswith("|"):
                rows.append(stripped)
            elif rows:
                break
    return rows


def _active_project_rows(memory_md_text: str) -> list[str]:
    """Extract the data rows under `## Active Projects` from `MEMORY.md` text."""
    lines = memory_md_text.splitlines()
    in_active = False
    after_sep = False
    rows: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if stripped.startswith("## Active Projects"):
                in_active = True
                after_sep = False
                continue
            if in_active:
                break
        if in_active:
            if not after_sep:
                if memory_grad._is_separator_row(stripped):
                    after_sep = True
                continue
            if stripped.startswith("|"):
                rows.append(stripped)
            elif rows:
                break
    return rows


def test_external_mode_zero_touch_when_memory_dir_absent(tmp_repo: Path) -> None:
    """1. Verify `external` mode never creates `<ws_dir>/memory/` and updates `PROJECT.md` Part III."""
    ws_dir = common.workspace_dir(tmp_repo)
    proj_md = _write_locked_project(ws_dir, pr_id="PR-01", slug="pr-01-alpha")

    # Add an audit report and a PROGRAM.md to verify full graduation summary & status update
    audit_path = proj_md.parent / "AUDIT-round-1.md"
    audit_rep = schemas.AuditReport(
        pr_id="PR-01",
        audit_round=1,
        head_sha="114ace23784b67850f8d1455e48fa5855ec6aa43",
        verdict="APPROVED",
        findings=[],
    )
    audit_path.write_text(
        schemas.dump_document(
            audit_rep,
            [schemas.Section(heading="## 1. Audit Scorecard", body="\nAll green.\n")],
        ),
        encoding="utf-8",
    )
    prog_md = _write_program(
        ws_dir,
        [
            schemas.PRNodeSpec(
                id="PR-01",
                slug="pr-01-alpha",
                title="Deliver pr-01-alpha subsystem",
                branch="feat/pr-01-alpha",
                allowed_modules=["src/auth/", "src/api/"],
                status=schemas.PRState.AUDIT_APPROVED,
            )
        ],
    )

    assert not (ws_dir / "memory").exists()

    res = memory_grad.graduate(
        tmp_repo,
        "PR-01",
        memory_mode="external",
        completed_date="2026-10-16",
    )

    assert res == {
        "pr_id": "PR-01",
        "slug": "pr-01-alpha",
        "memory_mode": "external",
        "status": "GRADUATED",
        "project_md": str(proj_md),
        "memory_files_touched": [],
        "rolled_off_prs": [],
    }
    assert not (ws_dir / "memory").exists()

    reloaded = schemas.load_project(proj_md)
    assert reloaded.spec.status == schemas.PRState.GRADUATED
    assert schemas.verify_charter_hash(proj_md)

    sec4 = reloaded.section("## 4.")
    assert sec4 is not None
    assert "<!-- pa:graduation-summary start -->" in sec4.body
    assert "<!-- pa:graduation-summary end -->" in sec4.body
    assert "- **Graduation Mode:** `external`" in sec4.body
    assert "Round 1 — `APPROVED` (`114ace23784b`)" in sec4.body
    assert "| WO-01.1 | COMPLETED | 1 | `114ace23784b` |" in sec4.body

    reloaded_prog = schemas.load_program(prog_md)
    assert reloaded_prog.spec.prs[0].status == schemas.PRState.GRADUATED


def test_external_mode_zero_mutation_when_memory_files_exist(tmp_repo: Path) -> None:
    """2. Verify `external` mode never mutates existing `memory/{MEMORY,MODULE_INDEX,PROJECT_INDEX}.md`."""
    ws_dir = common.workspace_dir(tmp_repo)
    _write_locked_project(ws_dir, pr_id="PR-01", slug="pr-01-alpha")

    mem_dir = ws_dir / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    memory_md = mem_dir / "MEMORY.md"
    module_index_md = mem_dir / "MODULE_INDEX.md"
    project_index_md = mem_dir / "PROJECT_INDEX.md"

    memory_md.write_bytes(b"SENTINEL_MEMORY_BYTES_DO_NOT_TOUCH\n")
    module_index_md.write_bytes(b"SENTINEL_MODULE_INDEX_BYTES_DO_NOT_TOUCH\n")
    project_index_md.write_bytes(b"SENTINEL_PROJECT_INDEX_BYTES_DO_NOT_TOUCH\n")

    before_hashes = {
        "memory": _sha256_file(memory_md),
        "module": _sha256_file(module_index_md),
        "project": _sha256_file(project_index_md),
    }

    res = memory_grad.graduate(tmp_repo, "PR-01", memory_mode="external")
    assert res["memory_mode"] == "external"
    assert res["memory_files_touched"] == []
    assert res["rolled_off_prs"] == []

    after_hashes = {
        "memory": _sha256_file(memory_md),
        "module": _sha256_file(module_index_md),
        "project": _sha256_file(project_index_md),
    }
    assert after_hashes == before_hashes


def test_external_mode_idempotency(tmp_repo: Path) -> None:
    """3. Verify running `graduate` twice in `external` mode produces byte-identical `PROJECT.md`."""
    ws_dir = common.workspace_dir(tmp_repo)
    proj_md = _write_locked_project(ws_dir, pr_id="PR-01", slug="pr-01-alpha")

    memory_grad.graduate(
        tmp_repo,
        "PR-01",
        memory_mode="external",
        completed_date="2026-10-16",
    )
    run1_bytes = proj_md.read_bytes()

    memory_grad.graduate(
        tmp_repo,
        "PR-01",
        memory_mode="external",
        completed_date="2026-10-16",
    )
    run2_bytes = proj_md.read_bytes()

    assert run2_bytes == run1_bytes
    assert proj_md.read_text(encoding="utf-8").count("<!-- pa:graduation-summary start -->") == 1
    assert schemas.verify_charter_hash(proj_md)


def test_builtin_mode_active_to_completed_and_module_index(tmp_repo: Path) -> None:
    """4. Verify `builtin` mode transitions PR from Active to Recently Completed and updates `MODULE_INDEX.md`."""
    ws_dir = common.workspace_dir(tmp_repo)
    proj_md = _write_locked_project(
        ws_dir,
        pr_id="PR-01",
        slug="pr-01-alpha",
        title="Core authentication and API gateway",
        allowed_modules=["src/auth/", "src/api/"],
    )

    mem_dir = ws_dir / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    memory_md = mem_dir / "MEMORY.md"
    memory_md.write_text(
        "# Principal Architect Memory\n\n"
        "<!-- Last updated: 2026-10-01 -->\n"
        "<!-- memory_mode: builtin -->\n\n"
        "## Active Programs\n\n"
        "| Program | Plan | Status |\n"
        "|---|---|---|\n\n"
        "## Active Projects\n\n"
        "| Project | Status | Modules | Context |\n"
        "|---|---|---|---|\n"
        "| pr-01 | IN_PROGRESS | src/auth/, src/api/ | [PROJECT.md](../pr-01-alpha/PROJECT.md) |\n"
        "| pr-02-beta | PLANNED | src/ui/ | [PROJECT.md](../pr-02-beta/PROJECT.md) |\n\n"
        "## Recently Completed (last 5)\n\n"
        "| Project | Completed | Modules | Key Outcome |\n"
        "|---|---|---|---|\n\n"
        "## Older Projects\n\n"
        "Refer to [PROJECT_INDEX.md](PROJECT_INDEX.md) and [MODULE_INDEX.md](MODULE_INDEX.md).\n",
        encoding="utf-8",
    )

    res = memory_grad.graduate(
        tmp_repo,
        "PR-01",
        memory_mode="builtin",
        completed_date="2026-10-16",
    )

    assert res["pr_id"] == "PR-01"
    assert res["slug"] == "pr-01-alpha"
    assert res["memory_mode"] == "builtin"
    assert res["status"] == "GRADUATED"
    assert res["rolled_off_prs"] == []
    assert len(res["memory_files_touched"]) == 3
    assert schemas.verify_charter_hash(proj_md)

    mem_text = memory_md.read_text(encoding="utf-8")
    assert "<!-- Last updated: 2026-10-16 -->" in mem_text

    active_rows = _active_project_rows(mem_text)
    assert len(active_rows) == 1
    assert "pr-02-beta" in active_rows[0]
    assert all("pr-01" not in r for r in active_rows)

    recent_rows = _recent_completed_rows(mem_text)
    assert len(recent_rows) == 1
    assert recent_rows[0] == (
        "| [pr-01-alpha](../pr-01-alpha/PROJECT.md) | 2026-10-16 "
        "| src/auth/, src/api/ | Core authentication and API gateway |"
    )

    mod_text = (mem_dir / "MODULE_INDEX.md").read_text(encoding="utf-8")
    assert "## src/auth/" in mod_text
    assert "## src/api/" in mod_text
    expected_mod_row = (
        "| [pr-01-alpha](../pr-01-alpha/PROJECT.md) | Core authentication and API gateway "
        "| [PROJECT.md](../pr-01-alpha/PROJECT.md) |"
    )
    assert mod_text.count(expected_mod_row) == 2


def test_builtin_mode_five_pr_window_roll_off(tmp_repo: Path) -> None:
    """5. Verify 5-PR window roll-off into `PROJECT_INDEX.md` across 7 PRs."""
    ws_dir = common.workspace_dir(tmp_repo)
    slugs = [
        ("PR-01", "pr-01-alpha"),
        ("PR-02", "pr-02-beta"),
        ("PR-03", "pr-03-gamma"),
        ("PR-04", "pr-04-delta"),
        ("PR-05", "pr-05-epsilon"),
        ("PR-06", "pr-06-zeta"),
        ("PR-07", "pr-07-eta"),
    ]
    for pr_id, slug in slugs:
        _write_locked_project(
            ws_dir,
            pr_id=pr_id,
            slug=slug,
            title=f"Deliver {slug}",
            allowed_modules=["src/core/", f"src/{slug}/"],
        )

    # Graduate PR-01 through PR-05: window holds up to 5 PRs, zero roll-off
    for idx in range(5):
        pr_id, _ = slugs[idx]
        res = memory_grad.graduate(
            tmp_repo,
            pr_id,
            memory_mode="builtin",
            completed_date=f"2026-10-1{idx + 1}",
        )
        assert res["rolled_off_prs"] == []

    mem_dir = ws_dir / "memory"
    memory_md = mem_dir / "MEMORY.md"
    project_index_md = mem_dir / "PROJECT_INDEX.md"

    rows_after_5 = _recent_completed_rows(memory_md.read_text(encoding="utf-8"))
    assert len(rows_after_5) == 5
    assert "[pr-05-epsilon]" in rows_after_5[0]
    assert "[pr-01-alpha]" in rows_after_5[4]

    # Graduate PR-06: PR-01 rolls off into PROJECT_INDEX.md
    res6 = memory_grad.graduate(
        tmp_repo,
        "PR-06",
        memory_mode="builtin",
        completed_date="2026-10-16",
    )
    assert res6["rolled_off_prs"] == ["pr-01-alpha"]

    rows_after_6 = _recent_completed_rows(memory_md.read_text(encoding="utf-8"))
    assert len(rows_after_6) == 5
    assert [memory_grad._extract_slug_and_dir_from_row(r)[0] for r in rows_after_6] == [
        "pr-06-zeta",
        "pr-05-epsilon",
        "pr-04-delta",
        "pr-03-gamma",
        "pr-02-beta",
    ]

    pi_text_after_6 = project_index_md.read_text(encoding="utf-8")
    assert "[pr-01-alpha](../pr-01-alpha/PROJECT.md)" in pi_text_after_6
    assert "[pr-02-beta]" not in pi_text_after_6

    # Graduate PR-07: PR-02 also rolls off into PROJECT_INDEX.md in chronological order
    res7 = memory_grad.graduate(
        tmp_repo,
        "PR-07",
        memory_mode="builtin",
        completed_date="2026-10-17",
    )
    assert res7["rolled_off_prs"] == ["pr-02-beta"]

    rows_after_7 = _recent_completed_rows(memory_md.read_text(encoding="utf-8"))
    assert [memory_grad._extract_slug_and_dir_from_row(r)[0] for r in rows_after_7] == [
        "pr-07-eta",
        "pr-06-zeta",
        "pr-05-epsilon",
        "pr-04-delta",
        "pr-03-gamma",
    ]

    pi_text_after_7 = project_index_md.read_text(encoding="utf-8")
    assert pi_text_after_7.index("[pr-01-alpha]") < pi_text_after_7.index("[pr-02-beta]")


def test_builtin_mode_byte_stability_on_repeated_runs(tmp_repo: Path) -> None:
    """6. Verify running `graduate` twice in `builtin` mode produces byte-for-byte identical files."""
    ws_dir = common.workspace_dir(tmp_repo)
    slugs = [
        ("PR-01", "pr-01-alpha"),
        ("PR-02", "pr-02-beta"),
        ("PR-03", "pr-03-gamma"),
        ("PR-04", "pr-04-delta"),
        ("PR-05", "pr-05-epsilon"),
        ("PR-06", "pr-06-zeta"),
    ]
    for pr_id, slug in slugs:
        _write_locked_project(
            ws_dir,
            pr_id=pr_id,
            slug=slug,
            title=f"Deliver {slug}",
            allowed_modules=["src/core/", f"src/{slug}/"],
        )

    for idx in range(6):
        pr_id, _ = slugs[idx]
        memory_grad.graduate(
            tmp_repo,
            pr_id,
            memory_mode="builtin",
            completed_date="2026-10-16",
        )

    mem_dir = ws_dir / "memory"
    memory_md = mem_dir / "MEMORY.md"
    module_index_md = mem_dir / "MODULE_INDEX.md"
    project_index_md = mem_dir / "PROJECT_INDEX.md"
    proj6_md = ws_dir / "pr-06-zeta" / "PROJECT.md"

    snap_memory_1 = memory_md.read_bytes()
    snap_module_1 = module_index_md.read_bytes()
    snap_project_1 = project_index_md.read_bytes()
    snap_proj6_1 = proj6_md.read_bytes()

    res6_repeat = memory_grad.graduate(
        tmp_repo,
        "PR-06",
        memory_mode="builtin",
        completed_date="2026-10-16",
    )
    assert res6_repeat["rolled_off_prs"] == []
    assert memory_md.read_bytes() == snap_memory_1
    assert module_index_md.read_bytes() == snap_module_1
    assert project_index_md.read_bytes() == snap_project_1
    assert proj6_md.read_bytes() == snap_proj6_1


def test_state_db_memory_mode_config_lookup_and_validation(tmp_repo: Path) -> None:
    """7. Verify `graduate` reads `memory_mode` from `.state/state.db` when `memory_mode=None`."""
    ws_dir = common.workspace_dir(tmp_repo)
    _write_locked_project(ws_dir, pr_id="PR-01", slug="pr-01-alpha")
    _write_locked_project(ws_dir, pr_id="PR-02", slug="pr-02-beta")

    db_path = ws_dir / ".state" / "state.db"
    with state_db.StateDB(db_path) as db:
        db.set_config("memory_mode", "external")

    res_ext = memory_grad.graduate(tmp_repo, "PR-01", completed_date="2026-10-16")
    assert res_ext["memory_mode"] == "external"
    assert not (ws_dir / "memory").exists()

    with state_db.StateDB(db_path) as db:
        db.set_config("memory_mode", "builtin")

    res_bi = memory_grad.graduate(tmp_repo, "PR-02", completed_date="2026-10-16")
    assert res_bi["memory_mode"] == "builtin"
    assert (ws_dir / "memory" / "MEMORY.md").is_file()

    with pytest.raises(ValueError, match="Invalid memory_mode"):
        memory_grad.graduate(tmp_repo, "PR-02", memory_mode="invalid_mode")

    with pytest.raises(FileNotFoundError, match="PROJECT.md not found"):
        memory_grad.graduate(tmp_repo, "PR-99", memory_mode="external")
