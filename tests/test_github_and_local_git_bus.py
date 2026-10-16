"""Unit and integration tests for `vcs_sync.py` (`LocalGitBus` and `GitHubBus`).

WO-03.1 covers the offline `LocalGitBus` floor against real temporary Git repositories
(`tmp_repo`) with zero `gh` binary or network dependency.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import common
import post_tool_receipt
import pytest
import schemas
import state_db
import vcs_sync


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
