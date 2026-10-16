"""Unit and integration tests for `vcs_sync.py` (`LocalGitBus` and `GitHubBus`).

Covers both the offline `LocalGitBus` floor against real temporary Git repositories (`tmp_repo`)
and the `GitHubBus` multi-machine projection against a mocked `gh` runner (`fake_runner`).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import common
import post_tool_receipt
import pytest
import schemas
import state_db
import vcs_sync

if TYPE_CHECKING:
    from conftest import FakeRunner


def _write_locked_project(
    ws_dir: Path,
    *,
    pr_id: str = "PR-01",
    slug: str = "pr-01-alpha",
    branch: str = "feat/pr-01-alpha",
    base_branch: str = "main",
    allowed_modules: list[str] | None = None,
    work_orders: list[schemas.WOSummaryRow] | None = None,
    status: schemas.PRState = schemas.PRState.APPROVED,
) -> Path:
    """Create a valid `PROJECT.md` with a verified `charter_hash` in `ws_dir / slug`."""
    pr_dir = ws_dir / slug
    pr_dir.mkdir(parents=True, exist_ok=True)
    proj_md = pr_dir / "PROJECT.md"

    charter = schemas.PRCharterSpec(
        pr_id=pr_id,
        programme_id="prog-alpha",
        slug=slug,
        title=f"Title for {pr_id}",
        branch=branch,
        base_branch=base_branch,
        allowed_modules=allowed_modules or ["src/"],
        verification_floor=["pytest"],
        charter_locked=True,
    )
    sections = [
        schemas.Section(heading="## 1. PR Charter: Scope, Goals, & Non-Goals", body="\nScope.\n"),
        schemas.Section(
            heading="## 2. Architectural Requirements, Cross-PR Interfaces, & Required Skills/Tools",
            body="\nRequirements.\n",
        ),
        schemas.Section(heading="## 3. Implementation Plan & Work Order Breakdown", body="\nPlan.\n"),
        schemas.Section(heading="## 4. Outcome & Session Log", body="\nApproved.\n"),
    ]
    charter.charter_hash = schemas.compute_charter_hash(charter, sections)
    spec = schemas.ProjectSpec(
        charter=charter,
        status=status,
        work_orders=work_orders or [],
    )
    proj_md.write_text(schemas.dump_document(spec, sections), encoding="utf-8")
    assert schemas.verify_charter_hash(proj_md)
    return proj_md


def _write_locked_workorder(
    pr_dir: Path,
    *,
    wo_id: str = "WO-01.1",
    pr_id: str = "PR-01",
    slug: str = "wo1-task",
    allowed_files: list[str] | None = None,
    status: schemas.WorkOrderStatus = schemas.WorkOrderStatus.PENDING,
    completion: schemas.CompletionReport | None = None,
) -> Path:
    """Create a valid `WORKORDER.md` with a verified `spec_hash` in `pr_dir / slug`."""
    wo_dir = pr_dir / slug
    wo_dir.mkdir(parents=True, exist_ok=True)
    wo_md = wo_dir / "WORKORDER.md"

    sections = [
        schemas.Section(heading="## 1. Role & Objective", body="\nObjective.\n"),
        schemas.Section(heading="## 2. Strict Boundary Box & Constraints", body="\nBounds.\n"),
        schemas.Section(heading="## Completion Report", body="\nDone.\n"),
    ]
    spec = schemas.WorkOrderSpec(
        wo_id=wo_id,
        pr_id=pr_id,
        title=f"Implement {wo_id}",
        complexity=schemas.ComplexityTier.standard,
        status=status,
        allowed_files=allowed_files or ["src/app.py"],
        verification_command="pytest",
        completion=completion,
    )
    spec.spec_hash = schemas.compute_spec_hash(spec, sections)
    wo_md.write_text(schemas.dump_document(spec, sections), encoding="utf-8")
    assert schemas.verify_spec_hash(wo_md)
    return wo_md


def test_vcs_bus_protocol_and_get_vcs_bus(tmp_repo: Path) -> None:
    """Verify LocalGitBus satisfies VcsBus protocol and get_vcs_bus resolves local_git."""
    bus = vcs_sync.get_vcs_bus(tmp_repo)
    assert isinstance(bus, vcs_sync.LocalGitBus)
    assert isinstance(bus, vcs_sync.VcsBus)
    assert bus.mode == "local_git"
    assert bus.repo_root == tmp_repo.resolve()


def test_create_or_checkout_stacked_branches(tmp_repo: Path) -> None:
    """Verify stacked branch creation (main -> feat/pr-01 -> pr-01/wo1) and idempotent checkout."""
    bus = vcs_sync.LocalGitBus(tmp_repo)

    main_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # 1. Create feat/pr-01 from main
    pr_sha = bus.create_or_checkout_branch("feat/pr-01", base_branch="main")
    assert pr_sha == main_sha

    cur_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert cur_branch == "feat/pr-01"

    # Commit on feat/pr-01
    (tmp_repo / "pr1.txt").write_text("pr1\n", encoding="utf-8")
    subprocess.run(["git", "add", "pr1.txt"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "PR1 base commit"], cwd=tmp_repo, check=True)
    pr_commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert pr_commit_sha != main_sha

    # 2. Create stacked branch pr-01/wo1 from feat/pr-01
    wo_sha = bus.create_or_checkout_branch("pr-01/wo1", base_branch="feat/pr-01")
    assert wo_sha == pr_commit_sha

    # 3. Idempotently checkout existing branch main, then back to pr-01/wo1
    checked_main = bus.create_or_checkout_branch("main")
    assert checked_main == main_sha
    checked_wo = bus.create_or_checkout_branch("pr-01/wo1")
    assert checked_wo == pr_commit_sha

    # 4. Non-existent base branch raises RuntimeError
    with pytest.raises(RuntimeError, match="Failed to create or checkout branch"):
        bus.create_or_checkout_branch("feat/bad", base_branch="nonexistent-base")


def test_format_and_read_commit_trailers(tmp_repo: Path) -> None:
    """Verify formatting and parsing PA-WorkOrder, PA-Verified-Hash, and PA-Audit-Verdict trailers."""
    bus = vcs_sync.LocalGitBus(tmp_repo)

    msg1 = bus.format_commit_with_trailers(
        "WO-01.1: implement alpha",
        body="Implemented alpha feature.",
        trailers={
            "PA-WorkOrder": "WO-01.1",
            "PA-Verified-Hash": "a" * 64,
        },
    )
    assert "WO-01.1: implement alpha\n\nImplemented alpha feature.\n\nPA-WorkOrder: WO-01.1\nPA-Verified-Hash: " in msg1

    (tmp_repo / "alpha.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "alpha.py"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", msg1], cwd=tmp_repo, check=True)
    sha1 = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    msg2 = vcs_sync.format_commit_with_trailers(
        "audit(pr-01): round 1 — APPROVED",
        trailers=[("PA-Audit-Verdict", f"APPROVED ({sha1[:12]})")],
    )
    (tmp_repo / "audit_note.txt").write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "audit_note.txt"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", msg2], cwd=tmp_repo, check=True)
    sha2 = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    records = bus.read_commit_trailers()
    assert len(records) >= 3

    # Latest commit is the audit commit
    assert records[0]["sha"] == sha2
    assert records[0]["wo_id"] is None
    assert records[0]["audit_verdict"] == "APPROVED"
    assert records[0]["audit_head_sha"] == sha1[:12]

    # Second latest is WO-01.1 commit
    assert records[1]["sha"] == sha1
    assert records[1]["wo_id"] == "WO-01.1"
    assert records[1]["verified_hash"] == "a" * 64
    assert records[1]["audit_verdict"] is None

    # Verify alias read_trailers and max_count
    limited = vcs_sync.read_trailers(tmp_repo, max_count=1)
    assert len(limited) == 1
    assert limited[0]["sha"] == sha2


def test_format_and_parse_pa_audit_comment_roundtrip() -> None:
    """Verify format_pa_audit_comment and parse_pa_audit_comment across inline and multi-line forms."""
    report = schemas.AuditReport(
        pr_id="PR-03",
        github_pr=42,
        audit_round=2,
        head_sha="1234567890abcdef",
        auditor_harness="antigravity",
        verdict="CHANGES_REQUESTED",
        findings=[
            schemas.AuditFinding(
                id="BLOCKING-1",
                axis="spec_alignment",
                file_path="scripts/vcs_sync.py",
                line_range="10-20",
                summary="Missing trailer check",
                remediation="Add trailer parser",
            ),
            schemas.AuditFinding(
                id="NON-BLOCKING-1",
                axis="test_quality",
                file_path="tests/test_github_and_local_git_bus.py",
                summary="Add edge case assertion",
                remediation="Assert empty input returns None",
            ),
        ],
    )

    comment_md = vcs_sync.format_pa_audit_comment(report)
    assert (
        "<!-- pa:audit pr_id=PR-03 round=2 head_sha=1234567890abcdef "
        "verdict=CHANGES_REQUESTED blocking=1 major=1 minor=0 -->"
    ) in comment_md
    assert "**Audit Verdict:** CHANGES_REQUESTED (1 blocking, 1 non-blocking)" in comment_md

    parsed = vcs_sync.parse_pa_audit_comment(comment_md)
    assert parsed is not None
    assert parsed["pr_id"] == "PR-03"
    assert parsed["audit_round"] == 2
    assert parsed["head_sha"] == "1234567890abcdef"
    assert parsed["verdict"] == "CHANGES_REQUESTED"
    assert parsed["blocking"] == 1
    assert parsed["major"] == 1
    assert parsed["minor"] == 0

    # Multi-line YAML comment block
    multiline = (
        "<!-- pa:audit\n"
        "pr_id: PR-02\n"
        "round: 1\n"
        "head_sha: deadbeef1234\n"
        "verdict: APPROVED\n"
        "blocking: 0\n"
        "major: 0\n"
        "minor: 0\n"
        "-->\n"
        "**Audit Verdict:** APPROVED (0 blocking, 0 non-blocking)\n"
    )
    parsed_multi = vcs_sync.parse_pa_audit_comment(multiline)
    assert parsed_multi is not None
    assert parsed_multi["pr_id"] == "PR-02"
    assert parsed_multi["audit_round"] == 1
    assert parsed_multi["verdict"] == "APPROVED"

    # Non-audit comment returns None
    assert vcs_sync.parse_pa_audit_comment("Regular PR review comment without markers") is None
    assert vcs_sync.parse_pa_audit_comment("<!-- pa:audit pr_id=PR-01 round=9 -->") is None


def test_write_audit_round_and_charter_hash_preservation(tmp_repo: Path) -> None:
    """Verify write_audit_round writes AUDIT-round-K.md, updates PROJECT.md status, and commits with trailer."""
    ws_dir = common.workspace_dir(tmp_repo)
    proj_md = _write_locked_project(ws_dir, pr_id="PR-01", slug="pr-01-alpha")
    orig_charter_hash = schemas.load_project(proj_md).spec.charter.charter_hash

    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Add PROJECT.md"], cwd=tmp_repo, check=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    bus = vcs_sync.LocalGitBus(tmp_repo)

    # Round 1: CHANGES_REQUESTED
    r1 = schemas.AuditReport(
        pr_id="PR-01",
        audit_round=1,
        head_sha=head_sha[:12],
        verdict="CHANGES_REQUESTED",
        findings=[
            schemas.AuditFinding(
                id="BLOCKING-1",
                axis="invariants",
                file_path="src/app.py",
                summary="Defect found",
                remediation="Fix defect",
            )
        ],
    )
    audit_path_1 = bus.write_audit_round("PR-01", r1, commit=True)
    assert audit_path_1.name == "AUDIT-round-1.md"
    assert audit_path_1.is_file()

    # Both load_audit and parse_pa_audit_comment succeed on AUDIT-round-1.md
    loaded_r1 = schemas.load_audit(audit_path_1)
    assert loaded_r1.spec.verdict == "CHANGES_REQUESTED"
    parsed_r1 = vcs_sync.parse_pa_audit_comment(audit_path_1.read_text(encoding="utf-8"))
    assert parsed_r1 is not None
    assert parsed_r1["verdict"] == "CHANGES_REQUESTED"
    assert parsed_r1["blocking"] == 1

    # PROJECT.md status updated to CHANGES_REQUESTED and charter_hash intact
    proj_after_r1 = schemas.load_project(proj_md)
    assert proj_after_r1.spec.status == schemas.PRState.CHANGES_REQUESTED
    assert proj_after_r1.spec.charter.charter_hash == orig_charter_hash
    assert schemas.verify_charter_hash(proj_md)

    # Round 2: APPROVED
    r2 = {
        "pr_id": "PR-01",
        "audit_round": 2,
        "head_sha": head_sha[:12],
        "verdict": "APPROVED",
        "findings": [],
    }
    audit_path_2 = bus.write_audit_round("PR-01", r2, commit=True)
    assert audit_path_2.name == "AUDIT-round-2.md"
    proj_after_r2 = schemas.load_project(proj_md)
    assert proj_after_r2.spec.status == schemas.PRState.AUDIT_APPROVED
    assert schemas.verify_charter_hash(proj_md)

    # Verify commit trailer on HEAD
    trailers = bus.read_commit_trailers(max_count=1)
    assert trailers[0]["audit_verdict"] == "APPROVED"
    assert trailers[0]["audit_head_sha"] == head_sha[:12]

    # Reject audit_round > 5 and mismatched pr_id
    with pytest.raises(ValueError):
        bus.write_audit_round(
            "PR-01",
            {
                "pr_id": "PR-01",
                "audit_round": 6,
                "head_sha": head_sha[:12],
                "verdict": "APPROVED",
            },
            commit=False,
        )

    with pytest.raises(ValueError, match="does not match target PR"):
        bus.write_audit_round(
            "PR-02",
            {
                "pr_id": "PR-01",
                "audit_round": 3,
                "head_sha": head_sha[:12],
                "verdict": "APPROVED",
            },
            commit=False,
        )


def test_append_deferred_backlog(tmp_repo: Path) -> None:
    """Verify append_deferred_backlog creates and appends entries to DEFERRED_BACKLOG.md."""
    bus = vcs_sync.LocalGitBus(tmp_repo)

    p1 = bus.append_deferred_backlog(
        title="Refactor parser helper",
        summary="Extract duplicate regex into common module",
        pr_id="PR-03",
        wo_id="WO-03.1",
        labels=("pa:deferred", "tech-debt"),
        file_path="scripts/vcs_sync.py",
    )
    assert p1 == common.workspace_dir(tmp_repo) / "DEFERRED_BACKLOG.md"
    assert p1.is_file()

    res2 = bus.create_deferred_issue(
        title="Add benchmark suite",
        summary="Measure cold-start latency across 100 repos",
        pr_id="PR-03",
        wo_id="WO-03.1",
    )
    assert res2["mode"] == "local_git"
    assert res2["issue_url"] is None
    assert Path(res2["backlog_path"]) == p1

    content = p1.read_text(encoding="utf-8")
    assert "# Deferred Backlog" in content
    assert "## Refactor parser helper" in content
    assert "`tech-debt`" in content
    assert "`scripts/vcs_sync.py`" in content
    assert "## Add benchmark suite" in content


def test_sync_state_rebuilds_deleted_state_db(tmp_repo: Path) -> None:
    """Verify sync_state rebuilds state.db from git trailers, WORKORDER.md, and AUDIT-round-K.md."""
    ws_dir = common.workspace_dir(tmp_repo)
    src_dir = tmp_repo / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    app_file = src_dir / "app.py"
    app_file.write_text("print('hello')\n", encoding="utf-8")

    t_hash = post_tool_receipt.compute_tree_hash(tmp_repo, ["src/app.py"])
    rcpt_id = f"rcpt_{t_hash[:12]}"

    proj_md = _write_locked_project(
        ws_dir,
        pr_id="PR-01",
        slug="pr-01-alpha",
        work_orders=[
            schemas.WOSummaryRow(
                id="WO-01.1",
                slug="wo1-task",
                title="Implement WO-01.1",
                complexity=schemas.ComplexityTier.standard,
                status=schemas.WorkOrderStatus.PENDING,
                attempts=0,
                commit_sha=None,
            )
        ],
    )
    _write_locked_workorder(
        proj_md.parent,
        wo_id="WO-01.1",
        pr_id="PR-01",
        slug="wo1-task",
        allowed_files=["src/app.py"],
        status=schemas.WorkOrderStatus.COMPLETED,
        completion=schemas.CompletionReport(
            status=schemas.WorkOrderStatus.COMPLETED,
            attempt_num=2,
            receipt_id=rcpt_id,
            files_modified=["src/app.py"],
            verification_summary="pytest: 1 passed",
        ),
    )

    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    wo_commit_msg = vcs_sync.format_commit_with_trailers(
        "WO-01.1: Implement WO-01.1",
        trailers=[("PA-WorkOrder", "WO-01.1"), ("PA-Verified-Hash", t_hash)],
    )
    subprocess.run(["git", "commit", "-m", wo_commit_msg], cwd=tmp_repo, check=True)
    wo_commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    bus = vcs_sync.LocalGitBus(tmp_repo)
    bus.post_audit(
        "PR-01",
        {
            "pr_id": "PR-01",
            "audit_round": 1,
            "head_sha": wo_commit_sha[:12],
            "verdict": "APPROVED",
            "findings": [],
        },
        commit=True,
    )

    # Delete .state/state.db completely if it exists
    db_file = ws_dir / ".state" / "state.db"
    if db_file.exists():
        db_file.unlink()
    assert not db_file.exists()

    # Run sync_state to rebuild .state/state.db and reconcile PROJECT.md
    summary = bus.sync_state()
    assert summary["vcs_mode"] == "local_git"
    assert summary["synced_receipts"] == 1
    assert summary["synced_audits"] == 1
    assert summary["synced_wos"] == 1
    assert summary["trailers_found"] >= 2
    assert db_file.is_file()

    # Verify StateDB contents
    with state_db.StateDB(db_file) as db:
        rcpt = db.latest_valid_receipt("WO-01.1", tree_hash=t_hash)
        assert rcpt is not None
        assert rcpt["receipt_id"] == rcpt_id
        assert rcpt["git_head_sha"] == wo_commit_sha

        latest_audit_raw = db.get_config("latest_audit:PR-01")
        assert latest_audit_raw is not None
        latest_audit = json.loads(latest_audit_raw)
        assert latest_audit["verdict"] == "APPROVED"
        assert latest_audit["audit_round"] == 1
        assert latest_audit["head_sha"] == wo_commit_sha[:12]
        assert db.get_config("last_vcs_sync_at") is not None

    # Verify PROJECT.md work_orders row was reconciled without breaking charter_hash
    reloaded_proj = schemas.load_project(proj_md)
    assert schemas.verify_charter_hash(proj_md)
    assert reloaded_proj.spec.work_orders[0].status == schemas.WorkOrderStatus.COMPLETED
    assert reloaded_proj.spec.work_orders[0].attempts == 2
    assert reloaded_proj.spec.work_orders[0].commit_sha == wo_commit_sha


def test_restack_branches_updates_stacked_branch_onto_new_main(tmp_repo: Path) -> None:
    """Verify restack_branches rebases a stacked PR branch onto an updated base branch."""
    ws_dir = common.workspace_dir(tmp_repo)
    bus = vcs_sync.LocalGitBus(tmp_repo)

    # 1. Create feat/pr-01-alpha from main and add a commit
    bus.create_or_checkout_branch("feat/pr-01-alpha", base_branch="main")
    _write_locked_project(
        ws_dir,
        pr_id="PR-01",
        slug="pr-01-alpha",
        branch="feat/pr-01-alpha",
        base_branch="main",
    )
    (tmp_repo / "feature.txt").write_text("feature work\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Add feature work"], cwd=tmp_repo, check=True)

    # 2. Advance main with an upstream commit
    bus.create_or_checkout_branch("main")
    (tmp_repo / "upstream.txt").write_text("upstream change\n", encoding="utf-8")
    subprocess.run(["git", "add", "upstream.txt"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Upstream commit on main"], cwd=tmp_repo, check=True)
    new_main_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # 3. Run restack_branches for PR-01
    res = bus.restack_branches(pr_id="PR-01")
    assert "feat/pr-01-alpha" in res["restacked"]
    assert res["commands"] == [["git", "rebase", "--update-refs", "main", "feat/pr-01-alpha"]]

    # Verify feat/pr-01-alpha now has new_main_sha as its parent
    parent_sha = subprocess.run(
        ["git", "rev-parse", "feat/pr-01-alpha~1"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert parent_sha == new_main_sha
    assert (tmp_repo / "upstream.txt").is_file()
    assert (tmp_repo / "feature.txt").is_file()


def test_open_or_sync_pr_and_sync_audit(tmp_repo: Path) -> None:
    """Verify open_or_sync_pr transitions status to STAGED_FOR_AUDIT and sync_audit updates StateDB."""
    ws_dir = common.workspace_dir(tmp_repo)
    bus = vcs_sync.LocalGitBus(tmp_repo)

    bus.create_or_checkout_branch("feat/pr-01-alpha", base_branch="main")
    proj_md = _write_locked_project(
        ws_dir,
        pr_id="PR-01",
        slug="pr-01-alpha",
        branch="feat/pr-01-alpha",
        base_branch="main",
        status=schemas.PRState.IN_PROGRESS,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Initial PR-01 commit"], cwd=tmp_repo, check=True)

    # 1. open_or_sync_pr transitions PROJECT.md to STAGED_FOR_AUDIT and preserves charter_hash
    res_open = bus.open_or_sync_pr("PR-01")
    assert res_open["mode"] == "local_git"
    assert res_open["pr_id"] == "PR-01"
    assert res_open["status"] == "STAGED_FOR_AUDIT"
    assert schemas.load_project(proj_md).spec.status == schemas.PRState.STAGED_FOR_AUDIT
    assert schemas.verify_charter_hash(proj_md)

    # 2. Write an audit file without committing, then call sync_audit
    head_sha = res_open["head_sha"]
    bus.write_audit_round(
        "PR-01",
        {
            "pr_id": "PR-01",
            "audit_round": 1,
            "head_sha": head_sha[:12],
            "verdict": "APPROVED",
            "findings": [],
        },
        commit=False,
    )
    db_file = ws_dir / ".state" / "state.db"
    if db_file.exists():
        db_file.unlink()

    synced = bus.sync_audit("PR-01")
    assert synced is not None
    assert synced["verdict"] == "APPROVED"
    assert synced["audit_round"] == 1
    assert db_file.is_file()
    with state_db.StateDB(db_file) as db:
        raw = db.get_config("latest_audit:PR-01")
        assert raw is not None
        assert json.loads(raw)["head_sha"] == head_sha[:12]


# ---------------------------------------------------------------------------
# WO-03.2: GitHubBus & get_vcs_bus tests (mocked gh via FakeRunner)
# ---------------------------------------------------------------------------


def test_get_vcs_bus_resolves_local_git_and_github_modes(
    tmp_repo: Path,
    fake_runner: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify get_vcs_bus dispatches LocalGitBus vs GitHubBus from param or state.db, and respects PA_GH_BIN."""
    # Explicit vcs_mode parameter
    local_bus = vcs_sync.get_vcs_bus(tmp_repo, vcs_mode="local_git", runner=fake_runner)
    assert isinstance(local_bus, vcs_sync.LocalGitBus)
    assert not isinstance(local_bus, vcs_sync.GitHubBus)
    assert local_bus.mode == "local_git"

    gh_bus = vcs_sync.get_vcs_bus(tmp_repo, vcs_mode="github", runner=fake_runner)
    assert isinstance(gh_bus, vcs_sync.GitHubBus)
    assert isinstance(gh_bus, vcs_sync.VcsBus)
    assert gh_bus.mode == "github"

    # Configured in .state/state.db
    ws_dir = common.workspace_dir(tmp_repo)
    db_file = ws_dir / ".state" / "state.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with state_db.StateDB(db_file) as db:
        db.set_config("vcs_mode", "github")

    resolved_bus = vcs_sync.get_vcs_bus(tmp_repo, runner=fake_runner)
    assert isinstance(resolved_bus, vcs_sync.GitHubBus)
    assert resolved_bus.mode == "github"

    # PA_GH_BIN override
    monkeypatch.setenv("PA_GH_BIN", "/custom/bin/gh-mock")
    assert vcs_sync._gh_bin() == "/custom/bin/gh-mock"
    monkeypatch.delenv("PA_GH_BIN", raising=False)
    assert vcs_sync._gh_bin() == "gh"


def test_github_bus_open_or_sync_pr_creates_then_edits_pr(
    tmp_repo: Path,
    fake_runner: FakeRunner,
) -> None:
    """Verify GitHubBus.open_or_sync_pr pushes branch, calls gh pr create, records github_pr, and later calls gh pr edit."""
    ws_dir = common.workspace_dir(tmp_repo)
    bus = vcs_sync.GitHubBus(tmp_repo, runner=fake_runner)

    bus.create_or_checkout_branch("feat/pr-01-alpha", base_branch="main")
    proj_md = _write_locked_project(
        ws_dir,
        pr_id="PR-01",
        slug="pr-01-alpha",
        branch="feat/pr-01-alpha",
        base_branch="main",
        status=schemas.PRState.IN_PROGRESS,
        work_orders=[
            schemas.WOSummaryRow(
                id="WO-01.1",
                slug="wo1-task",
                title="Task 1",
                complexity=schemas.ComplexityTier.standard,
                status=schemas.WorkOrderStatus.COMPLETED,
                attempts=1,
                commit_sha="1234567890abcdef",
            )
        ],
    )
    orig_charter_hash = schemas.load_project(proj_md).spec.charter.charter_hash
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Add PR-01 project"], cwd=tmp_repo, check=True)

    # First call: no existing PR -> gh pr view returns 1, gh pr create returns PR URL
    fake_runner.set_response(["git", "push"], returncode=0, stdout="Everything up-to-date\n")
    fake_runner.set_response(
        ["gh", "pr", "view", "feat/pr-01-alpha"],
        returncode=1,
        stderr="no pull requests found for branch\n",
    )
    fake_runner.set_response(
        ["gh", "pr", "create"],
        returncode=0,
        stdout="https://github.com/example/repo/pull/17\n",
    )

    res1 = bus.open_or_sync_pr("PR-01", draft=True)
    assert res1["mode"] == "github"
    assert res1["pr_id"] == "PR-01"
    assert res1["branch"] == "feat/pr-01-alpha"
    assert res1["base_branch"] == "main"
    assert res1["status"] == "STAGED_FOR_AUDIT"
    assert res1["github_pr"] == 17
    assert res1["pr_url"] == "https://github.com/example/repo/pull/17"

    # Verify git push and gh pr create were called with expected flags
    push_calls = [c for c in fake_runner.calls if c[:3] == ["git", "push", "-u"]]
    assert len(push_calls) >= 1
    assert push_calls[0] == ["git", "push", "-u", "origin", "feat/pr-01-alpha"]

    create_calls = [c for c in fake_runner.calls if c[:3] == ["gh", "pr", "create"]]
    assert len(create_calls) == 1
    create_cmd = create_calls[0]
    assert "--base" in create_cmd and create_cmd[create_cmd.index("--base") + 1] == "main"
    assert (
        "--head" in create_cmd
        and create_cmd[create_cmd.index("--head") + 1] == "feat/pr-01-alpha"
    )
    assert "--draft" in create_cmd
    body_arg = create_cmd[create_cmd.index("--body") + 1]
    assert "`main` -> `feat/pr-01-alpha`" in body_arg
    assert "`WO-01.1`" in body_arg

    # Verify PROJECT.md now records github_pr: 17 and preserves charter_hash
    reloaded = schemas.load_project(proj_md)
    assert reloaded.spec.github_pr == 17
    assert reloaded.spec.status == schemas.PRState.STAGED_FOR_AUDIT
    assert reloaded.spec.charter.charter_hash == orig_charter_hash
    assert schemas.verify_charter_hash(proj_md)

    # Second call: github_pr is already 17 -> invokes gh pr edit 17
    fake_runner.calls.clear()
    fake_runner.set_response(
        ["gh", "pr", "edit", "17"],
        returncode=0,
        stdout="https://github.com/example/repo/pull/17\n",
    )
    res2 = bus.open_or_sync_pr("PR-01", draft=False)
    assert res2["github_pr"] == 17
    assert res2["pr_url"] == "https://github.com/example/repo/pull/17"

    edit_calls = [c for c in fake_runner.calls if c[:3] == ["gh", "pr", "edit"]]
    assert len(edit_calls) == 1
    assert edit_calls[0][:4] == ["gh", "pr", "edit", "17"]
    assert not any(c[:3] == ["gh", "pr", "create"] for c in fake_runner.calls)


def test_github_bus_post_audit_always_uses_comment_never_approve_or_request_changes(
    tmp_repo: Path,
    fake_runner: FakeRunner,
) -> None:
    """Verify GitHubBus.post_audit writes AUDIT-round-1.md and posts via gh pr review --comment --body-file."""
    ws_dir = common.workspace_dir(tmp_repo)
    proj_md = _write_locked_project(
        ws_dir,
        pr_id="PR-01",
        slug="pr-01-alpha",
        branch="feat/pr-01-alpha",
        base_branch="main",
    )
    # Set github_pr = 23 on PROJECT.md
    proj_doc = schemas.load_project(proj_md)
    proj_doc.spec.github_pr = 23
    proj_md.write_text(
        schemas.dump_document(proj_doc.spec, proj_doc.sections),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Add PROJECT.md with PR #23"], cwd=tmp_repo, check=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    fake_runner.set_response(["gh", "pr", "review"], returncode=0, stdout="")
    bus = vcs_sync.GitHubBus(tmp_repo, runner=fake_runner)

    res = bus.post_audit(
        "PR-01",
        {
            "pr_id": "PR-01",
            "github_pr": 23,
            "audit_round": 1,
            "head_sha": head_sha[:12],
            "verdict": "APPROVED",
            "findings": [],
        },
        commit=True,
    )
    assert res["mode"] == "github"
    assert res["review_posted"] is True
    assert res["github_pr"] == 23
    assert Path(res["audit_path"]).name == "AUDIT-round-1.md"
    assert Path(res["audit_path"]).is_file()

    # Check git trailer on HEAD commit
    trailers = bus.read_commit_trailers(max_count=1)
    assert trailers[0]["audit_verdict"] == "APPROVED"
    assert trailers[0]["audit_head_sha"] == head_sha[:12]

    # Check gh pr review command
    review_calls = [c for c in fake_runner.calls if c[:3] == ["gh", "pr", "review"]]
    assert len(review_calls) == 1
    review_cmd = review_calls[0]
    assert review_cmd[:4] == ["gh", "pr", "review", "23"]
    assert "--comment" in review_cmd
    assert "--approve" not in review_cmd
    assert "--request-changes" not in review_cmd
    assert "--body-file" in review_cmd

    body_file_path = Path(review_cmd[review_cmd.index("--body-file") + 1])
    assert body_file_path.is_file()
    body_text = body_file_path.read_text(encoding="utf-8")
    parsed = vcs_sync.parse_pa_audit_comment(body_text)
    assert parsed is not None
    assert parsed["pr_id"] == "PR-01"
    assert parsed["audit_round"] == 1
    assert parsed["head_sha"] == head_sha[:12]
    assert parsed["verdict"] == "APPROVED"


def test_github_bus_sync_audit_and_sync_state_ingest_remote_pr_review(
    tmp_repo: Path,
    fake_runner: FakeRunner,
) -> None:
    """Verify GitHubBus.sync_audit and sync_state reconstruct AUDIT-round-2.md and state.db from a remote PR review."""
    ws_dir = common.workspace_dir(tmp_repo)
    proj_md = _write_locked_project(
        ws_dir,
        pr_id="PR-01",
        slug="pr-01-alpha",
        branch="feat/pr-01-alpha",
        base_branch="main",
        status=schemas.PRState.STAGED_FOR_AUDIT,
    )
    proj_doc = schemas.load_project(proj_md)
    proj_doc.spec.github_pr = 42
    proj_md.write_text(
        schemas.dump_document(proj_doc.spec, proj_doc.sections),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Stage PR-01"], cwd=tmp_repo, check=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    remote_review_body = (
        f"<!-- pa:audit pr_id=PR-01 round=2 head_sha={head_sha[:12]} "
        "verdict=APPROVED blocking=0 major=1 minor=0 -->\n\n"
        "**Audit Verdict:** APPROVED (0 blocking, 1 non-blocking)\n"
    )
    gh_view_payload = {
        "number": 42,
        "url": "https://github.com/example/repo/pull/42",
        "headRefOid": head_sha,
        "reviews": [{"body": remote_review_body}],
        "comments": [],
    }
    fake_runner.set_response(["git", "fetch", "origin"], returncode=0, stdout="")
    fake_runner.set_response(
        ["gh", "pr", "view", "42"],
        returncode=0,
        stdout=json.dumps(gh_view_payload),
    )

    bus = vcs_sync.GitHubBus(tmp_repo, runner=fake_runner)

    # 1. sync_audit materializes AUDIT-round-2.md locally and updates PROJECT.md
    synced = bus.sync_audit("PR-01")
    assert synced is not None
    assert synced["mode"] == "github"
    assert synced["pr_id"] == "PR-01"
    assert synced["audit_round"] == 2
    assert synced["verdict"] == "APPROVED"
    assert synced["head_sha"] == head_sha[:12]
    assert synced["findings_count"] == 1

    audit_r2_path = proj_md.parent / "AUDIT-round-2.md"
    assert audit_r2_path.is_file()
    loaded_r2 = schemas.load_audit(audit_r2_path)
    assert loaded_r2.spec.audit_round == 2
    assert loaded_r2.spec.verdict == "APPROVED"
    assert loaded_r2.spec.head_sha == head_sha[:12]

    reloaded_proj = schemas.load_project(proj_md)
    assert reloaded_proj.spec.status == schemas.PRState.AUDIT_APPROVED
    assert schemas.verify_charter_hash(proj_md)

    # 2. Delete local AUDIT-round-2.md and state.db, then run GitHubBus.sync_state()
    audit_r2_path.unlink()
    db_file = ws_dir / ".state" / "state.db"
    if db_file.exists():
        db_file.unlink()

    state_summary = bus.sync_state()
    assert state_summary["vcs_mode"] == "github"
    assert state_summary["synced_audits"] == 1
    assert audit_r2_path.is_file()
    assert any(c == ["git", "fetch", "origin"] for c in fake_runner.calls)

    with state_db.StateDB(db_file) as db:
        assert db.get_config("vcs_mode") == "github"
        raw_audit = db.get_config("latest_audit:PR-01")
        assert raw_audit is not None
        meta = json.loads(raw_audit)
        assert meta["verdict"] == "APPROVED"
        assert meta["audit_round"] == 2
        assert meta["head_sha"] == head_sha[:12]


def test_github_bus_create_deferred_issue_and_fallback(
    tmp_repo: Path,
    fake_runner: FakeRunner,
) -> None:
    """Verify GitHubBus.create_deferred_issue passes --label pa:deferred and falls back to DEFERRED_BACKLOG.md."""
    bus = vcs_sync.GitHubBus(tmp_repo, runner=fake_runner)

    # 1. Successful gh issue create
    fake_runner.set_response(
        ["gh", "issue", "create"],
        returncode=0,
        stdout="https://github.com/example/repo/issues/88\n",
    )
    res_ok = bus.create_deferred_issue(
        title="Clean up legacy migration shim",
        summary="Remove once v0.2.0 ships",
        pr_id="PR-03",
        wo_id="WO-03.2",
        labels=("tech-debt",),
        file_path="scripts/vcs_sync.py",
    )
    assert res_ok["mode"] == "github"
    assert res_ok["issue_url"] == "https://github.com/example/repo/issues/88"
    backlog_path = Path(res_ok["backlog_path"])
    assert backlog_path.is_file()

    issue_calls = [c for c in fake_runner.calls if c[:3] == ["gh", "issue", "create"]]
    assert len(issue_calls) == 1
    issue_cmd = issue_calls[0]
    assert "--label" in issue_cmd
    # Confirm "pa:deferred" is always included even when caller passed only ("tech-debt",)
    label_indices = [i for i, tok in enumerate(issue_cmd) if tok == "--label"]
    label_values = [issue_cmd[i + 1] for i in label_indices]
    assert "pa:deferred" in label_values
    assert "tech-debt" in label_values

    # 2. Failed gh issue create falls back cleanly to DEFERRED_BACKLOG.md
    fake_runner.set_response(
        ["gh", "issue", "create"],
        returncode=1,
        stderr="GraphQL: network unreachable\n",
    )
    res_fail = bus.create_deferred_issue(
        title="Offline deferred finding",
        summary="Recorded while offline",
        pr_id="PR-03",
        wo_id="WO-03.2",
    )
    assert res_fail["mode"] == "github"
    assert res_fail["issue_url"] is None
    assert Path(res_fail["backlog_path"]) == backlog_path
    backlog_text = backlog_path.read_text(encoding="utf-8")
    assert "## Clean up legacy migration shim" in backlog_text
    assert "## Offline deferred finding" in backlog_text


def test_github_bus_restack_branches_pushes_with_lease_and_edits_pr_base(
    tmp_repo: Path,
    fake_runner: FakeRunner,
) -> None:
    """Verify GitHubBus.restack_branches rebases, pushes with --force-with-lease, and runs gh pr edit --base."""
    ws_dir = common.workspace_dir(tmp_repo)
    bus = vcs_sync.GitHubBus(tmp_repo, runner=fake_runner)

    bus.create_or_checkout_branch("feat/pr-01-alpha", base_branch="main")
    proj_md = _write_locked_project(
        ws_dir,
        pr_id="PR-01",
        slug="pr-01-alpha",
        branch="feat/pr-01-alpha",
        base_branch="main",
    )
    proj_doc = schemas.load_project(proj_md)
    proj_doc.spec.github_pr = 55
    proj_md.write_text(
        schemas.dump_document(proj_doc.spec, proj_doc.sections),
        encoding="utf-8",
    )
    (tmp_repo / "pr1_work.txt").write_text("work\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "PR-01 work"], cwd=tmp_repo, check=True)

    # Advance main
    bus.create_or_checkout_branch("main")
    (tmp_repo / "main_advance.txt").write_text("advance\n", encoding="utf-8")
    subprocess.run(["git", "add", "main_advance.txt"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Advance main"], cwd=tmp_repo, check=True)

    fake_runner.calls.clear()
    fake_runner.set_response(["git", "push", "--force-with-lease"], returncode=0, stdout="")
    fake_runner.set_response(["gh", "pr", "edit"], returncode=0, stdout="")

    res = bus.restack_branches(pr_id="PR-01", onto_branch="main")
    assert res["restacked"] == ["feat/pr-01-alpha"]
    assert ["git", "rebase", "--update-refs", "main", "feat/pr-01-alpha"] in res["commands"]
    assert [
        "git",
        "push",
        "--force-with-lease",
        "origin",
        "feat/pr-01-alpha",
    ] in res["commands"]
    assert ["gh", "pr", "edit", "55", "--base", "main"] in res["commands"]


def test_github_bus_view_pr_and_diff_pr_with_local_fallback(
    tmp_repo: Path,
    fake_runner: FakeRunner,
) -> None:
    """Verify GitHubBus.view_pr and diff_pr command construction, JSON parsing, and local diff fallback."""
    ws_dir = common.workspace_dir(tmp_repo)
    bus = vcs_sync.GitHubBus(tmp_repo, runner=fake_runner)

    bus.create_or_checkout_branch("feat/pr-01-alpha", base_branch="main")
    proj_md = _write_locked_project(
        ws_dir,
        pr_id="PR-01",
        slug="pr-01-alpha",
        branch="feat/pr-01-alpha",
        base_branch="main",
    )
    proj_doc = schemas.load_project(proj_md)
    proj_doc.spec.github_pr = 77
    proj_md.write_text(
        schemas.dump_document(proj_doc.spec, proj_doc.sections),
        encoding="utf-8",
    )
    (tmp_repo / "diff_target.py").write_text("VALUE = 42\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Add diff_target.py"], cwd=tmp_repo, check=True)

    expected_view = {
        "number": 77,
        "url": "https://github.com/example/repo/pull/77",
        "state": "OPEN",
        "title": "PR-01: Title for PR-01",
        "body": "Body text",
        "baseRefName": "main",
        "headRefName": "feat/pr-01-alpha",
        "headRefOid": "abcdef123456",
        "reviews": [],
        "comments": [],
    }
    fake_runner.set_response(
        ["gh", "pr", "view", "77"],
        returncode=0,
        stdout=json.dumps(expected_view),
    )
    fake_runner.set_response(
        ["gh", "pr", "diff", "77"],
        returncode=0,
        stdout="diff --git a/diff_target.py b/diff_target.py\n+VALUE = 42\n",
    )

    view_out = bus.view_pr("PR-01")
    assert view_out["number"] == 77
    assert view_out["headRefName"] == "feat/pr-01-alpha"

    diff_out = bus.diff_pr("PR-01")
    assert "+VALUE = 42" in diff_out

    # When gh pr diff fails (non-zero), falls back to local git diff main...feat/pr-01-alpha
    fake_runner.set_response(
        ["gh", "pr", "diff", "77"],
        returncode=1,
        stderr="offline\n",
    )
    fallback_diff = bus.diff_pr("PR-01")
    assert "diff_target.py" in fallback_diff
    assert "+VALUE = 42" in fallback_diff
