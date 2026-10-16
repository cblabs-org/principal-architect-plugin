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


# ---------------------------------------------------------------------------
# WO-03.4: models.py (route, step_up, select_architect_model, LanguageServerClient)
# and pa wo debug / pa wo resolve CLI tests
# ---------------------------------------------------------------------------


def test_models_step_up_and_route_all_complexities_and_attempts() -> None:
    """Verify models.step_up and models.route across attempts 1..5, never returning 'pro'."""
    import models

    # 1. step_up mapping & top-tier ceiling ("inherit" never steps to "pro")
    assert models.step_up("flash_lite") == "flash"
    assert models.step_up("flash") == "inherit"
    assert models.step_up("inherit") == "inherit"

    with pytest.raises(ValueError, match="Unrecognized model tier"):
        models.step_up("pro")
    with pytest.raises(ValueError, match="Unrecognized model tier"):
        models.step_up("unknown_tier")

    # 2. route across attempts 1..5 for all 4 complexity tiers (strings and enums)
    for attempt in (1, 2):
        assert models.route("mechanical", attempt=attempt) == "flash_lite"
        assert models.route(schemas.ComplexityTier.mechanical, attempt=attempt) == "flash_lite"
        assert models.route("standard", attempt=attempt) == "flash"
        assert models.route(schemas.ComplexityTier.standard, attempt=attempt) == "flash"
        assert models.route("architect", attempt=attempt) == "inherit"
        assert models.route(schemas.ComplexityTier.architect, attempt=attempt) == "inherit"
        assert models.route("interactive", attempt=attempt) == "inherit"
        assert models.route(schemas.ComplexityTier.interactive, attempt=attempt) == "inherit"

    for attempt in (3, 4, 5):
        assert models.route("mechanical", attempt=attempt) == "flash"
        assert models.route(schemas.ComplexityTier.mechanical, attempt=attempt) == "flash"
        assert models.route("standard", attempt=attempt) == "inherit"
        assert models.route(schemas.ComplexityTier.standard, attempt=attempt) == "inherit"
        assert models.route("architect", attempt=attempt) == "inherit"
        assert models.route("interactive", attempt=attempt) == "inherit"

    # 3. Verify parent_model on Argon or Opus never causes "pro" downgrade
    for parent in ("inherit", "gemini-4-argon-high", "claude-opus-5-5-high"):
        for comp in ("mechanical", "standard", "architect", "interactive"):
            for att in range(1, 6):
                routed = models.route(comp, attempt=att, parent_model=parent)
                assert routed != "pro"
                assert routed in ("flash_lite", "flash", "inherit")

    # 4. Invalid complexity or attempt < 1 raises ValueError
    with pytest.raises(ValueError, match="Unknown complexity tier"):
        models.route("invalid_complexity", attempt=1)
    with pytest.raises(ValueError, match="attempt must be an integer >= 1"):
        models.route("standard", attempt=0)
    with pytest.raises(ValueError, match="attempt must be an integer >= 1"):
        models.route("standard", attempt=-1)


def test_select_architect_model_preferences_catalog_and_state_db(tmp_repo: Path) -> None:
    """Verify select_architect_model preference order, substring match, state.db lookup, and fallback."""
    import models

    assert models.ARCHITECT_MODEL_PREFERENCE == (
        "gemini-4-argon-high",
        "gemini-3.1-pro-high",
        "claude-opus-5-5-high",
    )

    # 1. Default when catalog is None or empty
    assert models.select_architect_model() == "gemini-4-argon-high"
    assert models.select_architect_model([]) == "gemini-4-argon-high"

    # 2. Preference order matching against catalog
    assert (
        models.select_architect_model(["claude-opus-5-5-high", "gemini-3.1-pro-high"])
        == "gemini-3.1-pro-high"
    )
    assert (
        models.select_architect_model(["claude-opus-5-5-high", "gemini-4-argon-high"])
        == "gemini-4-argon-high"
    )
    assert (
        models.select_architect_model(["custom-local-model", "claude-opus-5-5-high"])
        == "claude-opus-5-5-high"
    )

    # 3. Case-insensitive substring matching & fallback to catalog[0]
    assert (
        models.select_architect_model(["provider/GEMINI-3.1-PRO-HIGH-v2", "other"])
        == "provider/GEMINI-3.1-PRO-HIGH-v2"
    )
    assert (
        models.select_architect_model(["custom-model-a", "custom-model-b"])
        == "custom-model-a"
    )

    # 4. Explicit preferred parameter
    assert (
        models.select_architect_model(preferred="claude-opus-5-5-high")
        == "claude-opus-5-5-high"
    )
    assert (
        models.select_architect_model(
            ["gemini-4-argon-high", "claude-opus-5-5-high"],
            preferred="claude-opus-5-5-high",
        )
        == "claude-opus-5-5-high"
    )

    # 5. Lookup from <ws_dir>/.state/state.db repo_config["architect_model"]
    ws_dir = common.workspace_dir(tmp_repo)
    db_file = ws_dir / ".state" / "state.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with state_db.StateDB(db_file) as db:
        db.set_config("architect_model", "claude-opus-5-5-high")

    assert models.select_architect_model(repo_root=tmp_repo) == "claude-opus-5-5-high"
    assert (
        models.select_architect_model(
            ["gemini-4-argon-high", "claude-opus-5-5-high"],
            repo_root=tmp_repo,
        )
        == "claude-opus-5-5-high"
    )


def test_language_server_client_connected_and_headless_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify LanguageServerClient RPC calls when connected and graceful fallback when headless or failing."""
    import models

    monkeypatch.delenv("ANTIGRAVITY_LS_ADDRESS", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_CSRF_TOKEN", raising=False)

    # 1. Headless mode when env vars unset and no custom transport
    headless_client = models.LanguageServerClient()
    assert not headless_client.is_connected()

    res_start_hl = headless_client.start_conversation(
        title="🔬 [Debug WO-03.4] Test",
        prompt="PA_ROLE: debugger\nWO_ID: WO-03.4",
        role="debugger",
        pin=True,
    )
    assert res_start_hl["connected"] is False
    assert res_start_hl["pinned"] is False
    assert res_start_hl["conversation_id"].startswith("headless-debugger-")
    assert res_start_hl["bridge_prompt"] == "PA_ROLE: debugger\nWO_ID: WO-03.4"
    assert res_start_hl["fallback"] == "bridge_prompt"

    res_pin_hl = headless_client.set_pinned(res_start_hl["conversation_id"], True)
    assert res_pin_hl == {
        "connected": False,
        "conversation_id": res_start_hl["conversation_id"],
        "pinned": False,
        "fallback": "headless",
    }

    res_msg_hl = headless_client.send_message(res_start_hl["conversation_id"], "Wakeup")
    assert res_msg_hl == {
        "connected": False,
        "conversation_id": res_start_hl["conversation_id"],
        "delivered": False,
        "bridge_prompt": "Wakeup",
        "fallback": "bridge_prompt",
    }

    # 2. Connected mode with mock transport
    rpc_calls: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def _mock_transport(
        endpoint: str,
        payload: dict[str, object],
        headers: dict[str, str],
    ) -> dict[str, object]:
        rpc_calls.append((endpoint, dict(payload), dict(headers)))
        if endpoint.endswith("StartConversation"):
            return {"conversationId": "conv-ide-999"}
        return {"ok": True}

    connected_client = models.LanguageServerClient(
        address="127.0.0.1:42100",
        csrf_token="csrf-secret",
        transport=_mock_transport,
    )
    assert connected_client.is_connected()

    res_start_ok = connected_client.start_conversation(
        title="PA Session",
        prompt="PA_ROLE: pa\nPR_ID: PR-03",
        role="pa",
        model="gemini-4-argon-high",
        pin=True,
    )
    assert res_start_ok["connected"] is True
    assert res_start_ok["conversation_id"] == "conv-ide-999"
    assert res_start_ok["pinned"] is True
    assert res_start_ok["fallback"] is None
    assert len(rpc_calls) == 2
    assert rpc_calls[0][0].endswith("StartConversation")
    assert rpc_calls[0][2]["x-codeium-csrf-token"] == "csrf-secret"
    assert rpc_calls[1][0].endswith("SetPinned")
    assert rpc_calls[1][1] == {"conversationId": "conv-ide-999", "pinned": True}

    res_unpin_ok = connected_client.set_pinned("conv-ide-999", False)
    assert res_unpin_ok == {
        "connected": True,
        "conversation_id": "conv-ide-999",
        "pinned": False,
    }

    res_send_ok = connected_client.send_message("conv-ide-999", "Resolved WO-03.4")
    assert res_send_ok == {
        "connected": True,
        "conversation_id": "conv-ide-999",
        "delivered": True,
    }

    # 3. Transport raising OSError falls back cleanly without raising
    def _failing_transport(
        _endpoint: str,
        _payload: dict[str, object],
        _headers: dict[str, str],
    ) -> dict[str, object]:
        raise OSError("connection refused")

    failing_client = models.LanguageServerClient(
        address="127.0.0.1:42100",
        csrf_token="csrf-secret",
        transport=_failing_transport,
    )
    res_fail_start = failing_client.start_conversation(
        title="Fail Session",
        prompt="Prompt",
        role="debugger",
    )
    assert res_fail_start["connected"] is False
    assert res_fail_start["fallback"] == "bridge_prompt"

    res_fail_pin = failing_client.set_pinned("conv-ide-999", True)
    assert res_fail_pin["connected"] is False
    assert res_fail_pin["fallback"] == "headless"

    res_fail_msg = failing_client.send_message("conv-ide-999", "Ping")
    assert res_fail_msg["connected"] is False
    assert res_fail_msg["fallback"] == "bridge_prompt"


def test_pa_wo_debug_and_resolve_cli_end_to_end(
    tmp_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify `pa wo debug` and `pa wo resolve` end-to-end against tmp_repo."""
    import pa_cli

    monkeypatch.delenv("ANTIGRAVITY_LS_ADDRESS", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_CSRF_TOKEN", raising=False)

    ws_dir = common.workspace_dir(tmp_repo)
    src_dir = tmp_repo / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    app_py = src_dir / "app.py"
    app_py.write_text("VALUE = 1\n", encoding="utf-8")

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
                status=schemas.WorkOrderStatus.IN_PROGRESS,
                attempts=2,
            )
        ],
    )
    wo_md = _write_locked_workorder(
        proj_md.parent,
        wo_id="WO-01.1",
        pr_id="PR-01",
        slug="wo1-task",
        allowed_files=["src/app.py"],
        status=schemas.WorkOrderStatus.IN_PROGRESS,
    )
    # Set verification_command to a fast python check on src/app.py
    wo_doc = schemas.load_workorder(wo_md)
    wo_doc.spec.verification_command = "python3 -c 'import sys; sys.exit(0)'"
    wo_doc.spec.spec_hash = schemas.compute_spec_hash(wo_doc.spec, wo_doc.sections)
    wo_md.write_text(schemas.dump_document(wo_doc.spec, wo_doc.sections), encoding="utf-8")
    assert schemas.verify_spec_hash(wo_md)

    db_file = ws_dir / ".state" / "state.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with state_db.StateDB(db_file) as db:
        db.bind_session(
            "conv-pa-owner",
            role="pa",
            pr_id="PR-01",
            pinned=1,
        )

    # 1. Run `pa wo debug WO-01.1 --path <tmp_repo> --reason "Unit test failure in app.py"`
    capsys.readouterr()
    rc_debug = pa_cli.main(
        [
            "wo",
            "debug",
            "WO-01.1",
            "--path",
            str(tmp_repo),
            "--reason",
            "Unit test failure in app.py",
        ]
    )
    assert rc_debug == 0
    debug_out = json.loads(capsys.readouterr().out)
    assert debug_out["wo_id"] == "WO-01.1"
    assert debug_out["pr_id"] == "PR-01"
    assert debug_out["status"] == "BLOCKED"
    assert debug_out["conversation_id"].startswith("headless-debugger-")
    assert "PA_ROLE: debugger" in debug_out["bridge_prompt"]
    assert "Unit test failure in app.py" in debug_out["bridge_prompt"]

    # Verify WORKORDER.md and PROJECT.md transitioned to BLOCKED with hashes intact
    wo_after_debug = schemas.load_workorder(wo_md)
    assert wo_after_debug.spec.status == schemas.WorkOrderStatus.BLOCKED
    assert schemas.verify_spec_hash(wo_md)
    proj_after_debug = schemas.load_project(proj_md)
    assert proj_after_debug.spec.work_orders[0].status == schemas.WorkOrderStatus.BLOCKED
    assert schemas.verify_charter_hash(proj_md)

    # Verify debugger session and open escalation in state.db
    dbg_conv_id = debug_out["conversation_id"]
    with state_db.StateDB(db_file) as db:
        dbg_sess = db.get_session(dbg_conv_id)
        assert dbg_sess is not None
        assert dbg_sess["role"] == "debugger"
        assert dbg_sess["wo_id"] == "WO-01.1"
        open_escs = db.open_escalations(wo_id="WO-01.1")
        assert len(open_escs) == 1
        assert open_escs[0]["reason_code"] == "DEBUG_ESCALATION"
        assert open_escs[0]["target_role"] == "debugger"
        open_attn = [
            i for i in db.list_open() if i.get("wo_id") == "WO-01.1"
        ]
        assert len(open_attn) == 1

    # 2. Missing --summary returns exit code 1
    assert pa_cli.main(["wo", "resolve", "WO-01.1", "--path", str(tmp_repo)]) == 1

    # 3. Run `pa wo resolve WO-01.1 --summary "Fixed off-by-one in app.py" --path <tmp_repo>`
    app_py.write_text("VALUE = 2\n", encoding="utf-8")
    capsys.readouterr()
    rc_resolve = pa_cli.main(
        [
            "wo",
            "resolve",
            "WO-01.1",
            "--summary",
            "Fixed off-by-one in app.py",
            "--path",
            str(tmp_repo),
        ]
    )
    assert rc_resolve == 0
    resolve_out = json.loads(capsys.readouterr().out)
    assert resolve_out["wo_id"] == "WO-01.1"
    assert resolve_out["status"] == "COMPLETED"
    assert resolve_out["receipt_id"].startswith("rcpt_")
    assert dbg_conv_id in resolve_out["unpinned_debugger_sessions"]
    assert "conv-pa-owner" in resolve_out["notified_pa_sessions"]

    # Verify WORKORDER.md is COMPLETED with summary in verification_summary and decisions_made
    wo_after_resolve = schemas.load_workorder(wo_md)
    assert wo_after_resolve.spec.status == schemas.WorkOrderStatus.COMPLETED
    assert wo_after_resolve.spec.completion is not None
    assert wo_after_resolve.spec.completion.verification_summary == "Fixed off-by-one in app.py"
    assert "Fixed off-by-one in app.py" in wo_after_resolve.spec.completion.decisions_made
    assert schemas.verify_spec_hash(wo_md)

    # Verify state.db receipt is valid, escalations & attention items resolved, debugger unpinned
    with state_db.StateDB(db_file) as db:
        rcpt = db.latest_valid_receipt("WO-01.1", tree_hash=resolve_out["tree_hash"])
        assert rcpt is not None
        assert rcpt["receipt_id"] == resolve_out["receipt_id"]
        assert db.open_escalations(wo_id="WO-01.1") == []
        assert [i for i in db.list_open() if i.get("wo_id") == "WO-01.1"] == []
        dbg_sess_after = db.get_session(dbg_conv_id)
        assert dbg_sess_after is not None
        assert dbg_sess_after["pinned"] == 0


# ---------------------------------------------------------------------------
# WO-03.5: Complete `pa` CLI lifecycle commands & Rule R6 graduation gate
# ---------------------------------------------------------------------------


def test_pa_cli_local_git_end_to_end_lifecycle(
    tmp_repo: Path,
    daemon_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify full `local_git` CLI lifecycle from `pa enroll` through `pa pr graduate` and `restack`."""
    import pa_cli

    _ = daemon_home
    monkeypatch.delenv("ANTIGRAVITY_LS_ADDRESS", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_CSRF_TOKEN", raising=False)

    # 1. `pa enroll` in local_git + builtin mode
    capsys.readouterr()
    assert (
        pa_cli.main(
            [
                "enroll",
                str(tmp_repo),
                "--vcs-mode",
                "local_git",
                "--memory-mode",
                "builtin",
            ]
        )
        == 0
    )

    ws_dir = common.workspace_dir(tmp_repo)

    # 2. `pa programme init alpha --title "Alpha Programme"`
    capsys.readouterr()
    assert (
        pa_cli.main(
            [
                "programme",
                "init",
                "alpha",
                "--title",
                "Alpha Programme",
                "--base-branch",
                "main",
                "--path",
                str(tmp_repo),
            ]
        )
        == 0
    )
    prog_out = json.loads(capsys.readouterr().out)
    assert prog_out["programme_id"] == "prog-alpha"
    prog_md = Path(prog_out["program_md"])
    assert prog_md.is_file()
    assert schemas.load_program(prog_md).spec.title == "Alpha Programme"

    # 3. `pa programme charter PR-01`
    capsys.readouterr()
    assert (
        pa_cli.main(
            [
                "programme",
                "charter",
                "PR-01",
                "--slug",
                "pr-01-alpha",
                "--title",
                "Alpha Core Feature",
                "--branch",
                "feat/pr-01-alpha",
                "--base-branch",
                "main",
                "--allowed-module",
                "src/",
                "--verification-command",
                "python3 -c 'import sys; sys.exit(0)'",
                "--path",
                str(tmp_repo),
            ]
        )
        == 0
    )
    charter_out = json.loads(capsys.readouterr().out)
    assert charter_out["pr_id"] == "PR-01"
    assert charter_out["slug"] == "pr-01-alpha"
    assert charter_out["charter_locked"] is True
    proj_md = Path(charter_out["project_md"])
    assert proj_md.is_file()
    assert schemas.verify_charter_hash(proj_md)

    # Confirm PROGRAM.md now includes PR-01 node
    prog_doc = schemas.load_program(prog_md)
    assert len(prog_doc.spec.prs) == 1
    assert prog_doc.spec.prs[0].id == "PR-01"

    # Commit the programme & charter scaffolding on main so branch switch is clean
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Scaffold programme and PR-01 charter"], cwd=tmp_repo, check=True)

    # 4. `pa pr start PR-01` -> creates/checks out feat/pr-01-alpha and binds PA session
    capsys.readouterr()
    assert pa_cli.main(["pr", "start", "PR-01", "--path", str(tmp_repo)]) == 0
    start_out = json.loads(capsys.readouterr().out)
    assert start_out["pr_id"] == "PR-01"
    assert start_out["branch"] == "feat/pr-01-alpha"
    assert "PA_ROLE: pa" in start_out["bridge_prompt"]

    # 5. Author WO-01.1 in PROJECT.md Part II and wo1-task/WORKORDER.md, then `pa pr approve-plan`
    proj_doc = schemas.load_project(proj_md)
    proj_doc.spec.work_orders = [
        schemas.WOSummaryRow(
            id="WO-01.1",
            slug="wo1-task",
            title="Implement alpha module",
            complexity=schemas.ComplexityTier.standard,
            status=schemas.WorkOrderStatus.PENDING,
        )
    ]
    proj_md.write_text(
        schemas.dump_document(proj_doc.spec, proj_doc.sections),
        encoding="utf-8",
    )
    wo_md = _write_locked_workorder(
        proj_md.parent,
        wo_id="WO-01.1",
        pr_id="PR-01",
        slug="wo1-task",
        allowed_files=["src/app.py"],
        status=schemas.WorkOrderStatus.PENDING,
    )
    wo_doc = schemas.load_workorder(wo_md)
    wo_doc.spec.verification_command = "python3 -c 'import sys; sys.exit(0)'"
    wo_doc.spec.spec_hash = schemas.compute_spec_hash(wo_doc.spec, wo_doc.sections)
    wo_md.write_text(schemas.dump_document(wo_doc.spec, wo_doc.sections), encoding="utf-8")

    assert pa_cli.main(["pr", "approve-plan", "PR-01", "--path", str(tmp_repo)]) == 0
    assert schemas.load_project(proj_md).spec.status == schemas.PRState.APPROVED

    # Commit the approved plan before worker implementation
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Approve PR-01 plan"], cwd=tmp_repo, check=True)

    # 6. Implement src/app.py and run `pa wo verify WO-01.1`
    src_dir = tmp_repo / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "app.py").write_text("ALPHA = True\n", encoding="utf-8")
    assert pa_cli.main(["wo", "verify", "WO-01.1", "--path", str(tmp_repo)]) == 0

    # 7. `pa pr claim PR-01` -> verifies WO-01.1 is listed in completed_wos
    capsys.readouterr()
    assert pa_cli.main(["pr", "claim", "PR-01", "--path", str(tmp_repo)]) == 0
    claim_out = json.loads(capsys.readouterr().out)
    assert claim_out["pr_id"] == "PR-01"
    assert claim_out["completed_wos"] == ["WO-01.1"]
    assert claim_out["pending_wos"] == []
    assert "PA_ROLE: pa" in claim_out["continuation_prompt"]

    # 8. `pa pr open-or-sync PR-01` -> transitions status to STAGED_FOR_AUDIT
    capsys.readouterr()
    assert pa_cli.main(["pr", "open-or-sync", "PR-01", "--path", str(tmp_repo)]) == 0
    open_out = json.loads(capsys.readouterr().out)
    assert open_out["mode"] == "local_git"
    assert open_out["status"] == "STAGED_FOR_AUDIT"
    staged_head_sha = open_out["head_sha"]

    # 9. `pa pr post-audit PR-01 --file <audit_file>`
    audit_input = tmp_repo / ".state_audit_input.md"
    audit_report = schemas.AuditReport(
        pr_id="PR-01",
        audit_round=1,
        head_sha=staged_head_sha[:12],
        verdict="APPROVED",
        findings=[],
    )
    audit_input.write_text(
        schemas.dump_document(audit_report, []),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert (
        pa_cli.main(
            [
                "pr",
                "post-audit",
                "PR-01",
                "--file",
                str(audit_input),
                "--path",
                str(tmp_repo),
            ]
        )
        == 0
    )
    post_audit_out = json.loads(capsys.readouterr().out)
    assert post_audit_out["verdict"] == "APPROVED"
    assert post_audit_out["audit_round"] == 1
    audit_input.unlink()

    # 10. `pa pr sync-audit PR-01`
    capsys.readouterr()
    assert pa_cli.main(["pr", "sync-audit", "PR-01", "--path", str(tmp_repo)]) == 0
    sync_audit_out = json.loads(capsys.readouterr().out)
    assert sync_audit_out["verdict"] == "APPROVED"
    assert sync_audit_out["head_sha"] == staged_head_sha[:12]

    # 11. `pa pr graduate PR-01` (verifies Rule R6 when HEAD is the audit commit and runs verification_floor)
    capsys.readouterr()
    assert (
        pa_cli.main(
            [
                "pr",
                "graduate",
                "PR-01",
                "--completed-date",
                "2026-10-16",
                "--path",
                str(tmp_repo),
            ]
        )
        == 0
    )
    grad_out = json.loads(capsys.readouterr().out)
    assert grad_out["pr_id"] == "PR-01"
    assert grad_out["status"] == "GRADUATED"
    assert grad_out["memory_mode"] == "builtin"
    assert start_out["conversation_id"] in grad_out["unpinned_pa_sessions"]
    assert prog_out["conversation_id"] in grad_out["notified_chief_sessions"]
    assert schemas.load_project(proj_md).spec.status == schemas.PRState.GRADUATED
    assert schemas.load_program(prog_md).spec.prs[0].status == schemas.PRState.GRADUATED
    assert "pr-01-alpha" in (ws_dir / "memory" / "MEMORY.md").read_text(encoding="utf-8")

    # 12. `pa issue create` & `pa sync` & `pa pr restack`
    capsys.readouterr()
    assert (
        pa_cli.main(
            [
                "issue",
                "create",
                "--title",
                "Follow-up cleanup",
                "--summary",
                "Defer minor refactor to PR-02",
                "--pr-id",
                "PR-01",
                "--wo-id",
                "WO-01.1",
                "--file-path",
                "src/app.py",
                "--path",
                str(tmp_repo),
            ]
        )
        == 0
    )
    issue_out = json.loads(capsys.readouterr().out)
    assert issue_out["mode"] == "local_git"
    assert Path(issue_out["backlog_path"]).is_file()
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Record deferred backlog"], cwd=tmp_repo, check=True)

    capsys.readouterr()
    assert pa_cli.main(["sync", "--path", str(tmp_repo)]) == 0
    sync_out = json.loads(capsys.readouterr().out)
    assert sync_out["vcs_mode"] == "local_git"
    assert sync_out["synced_audits"] >= 1
    assert sync_out["synced_receipts"] >= 1

    capsys.readouterr()
    assert (
        pa_cli.main(
            [
                "pr",
                "restack",
                "--pr-id",
                "PR-01",
                "--onto",
                "main",
                "--path",
                str(tmp_repo),
            ]
        )
        == 0
    )
    restack_out = json.loads(capsys.readouterr().out)
    assert "feat/pr-01-alpha" in restack_out["restacked"]


def test_pa_pr_graduate_enforces_rule_r6_and_invalidates_on_new_commit(
    tmp_repo: Path,
    daemon_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify `pa pr graduate` rejects missing/CHANGES_REQUESTED/stale audits and failing verification_floor."""
    import pa_cli

    _ = daemon_home
    monkeypatch.delenv("ANTIGRAVITY_LS_ADDRESS", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_CSRF_TOKEN", raising=False)

    assert (
        pa_cli.main(
            [
                "enroll",
                str(tmp_repo),
                "--vcs-mode",
                "local_git",
                "--memory-mode",
                "external",
            ]
        )
        == 0
    )
    assert (
        pa_cli.main(
            [
                "pr",
                "start",
                "PR-01",
                "--slug",
                "pr-01-alpha",
                "--title",
                "Standalone Alpha PR",
                "--branch",
                "feat/pr-01-alpha",
                "--base-branch",
                "main",
                "--allowed-module",
                "src/",
                "--verification-command",
                "python3 -c 'import sys; sys.exit(0)'",
                "--path",
                str(tmp_repo),
            ]
        )
        == 0
    )
    ws_dir = common.workspace_dir(tmp_repo)
    proj_md = ws_dir / "pr-01-alpha" / "PROJECT.md"
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Start PR-01"], cwd=tmp_repo, check=True)

    # 1. Attempt graduate before any audit exists -> must fail with exit code 1
    capsys.readouterr()
    assert pa_cli.main(["pr", "graduate", "PR-01", "--path", str(tmp_repo)]) == 1
    err1 = capsys.readouterr().err
    assert "lacks an APPROVED Cold-Firewall Audit verdict" in err1
    assert schemas.load_project(proj_md).spec.status != schemas.PRState.GRADUATED

    # 2. Post Round 1 with verdict: CHANGES_REQUESTED -> must fail with exit code 1
    head_sha_1 = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    audit_file = tmp_repo / "audit_tmp.md"
    audit_file.write_text(
        schemas.dump_document(
            schemas.AuditReport(
                pr_id="PR-01",
                audit_round=1,
                head_sha=head_sha_1[:12],
                verdict="CHANGES_REQUESTED",
                findings=[
                    schemas.AuditFinding(
                        id="BLOCKING-1",
                        axis="invariants",
                        file_path="src/app.py",
                        summary="Missing invariant check",
                        remediation="Add invariant check",
                    )
                ],
            ),
            [],
        ),
        encoding="utf-8",
    )
    assert (
        pa_cli.main(
            [
                "pr",
                "post-audit",
                "PR-01",
                "--file",
                str(audit_file),
                "--path",
                str(tmp_repo),
            ]
        )
        == 0
    )
    audit_file.unlink()

    capsys.readouterr()
    assert pa_cli.main(["pr", "graduate", "PR-01", "--path", str(tmp_repo)]) == 1
    err2 = capsys.readouterr().err
    assert "lacks an APPROVED Cold-Firewall Audit verdict" in err2

    # 3. Post Round 2 with verdict: APPROVED for current HEAD, then land a NEW code commit after the audit!
    head_sha_2 = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    audit_file.write_text(
        schemas.dump_document(
            schemas.AuditReport(
                pr_id="PR-01",
                audit_round=2,
                head_sha=head_sha_2[:12],
                verdict="APPROVED",
                findings=[],
            ),
            [],
        ),
        encoding="utf-8",
    )
    assert (
        pa_cli.main(
            [
                "pr",
                "post-audit",
                "PR-01",
                "--file",
                str(audit_file),
                "--path",
                str(tmp_repo),
            ]
        )
        == 0
    )
    audit_file.unlink()

    # Land an unaudited code commit on the branch after Round 2 audit
    (tmp_repo / "src").mkdir(parents=True, exist_ok=True)
    (tmp_repo / "src" / "unaudited.py").write_text("UNAUDITED = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/unaudited.py"], cwd=tmp_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Unaudited post-audit code change"], cwd=tmp_repo, check=True)
    new_head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    capsys.readouterr()
    assert pa_cli.main(["pr", "graduate", "PR-01", "--path", str(tmp_repo)]) == 1
    err3 = capsys.readouterr().err
    assert f"current HEAD ({new_head_sha}) lacks an APPROVED Cold-Firewall Audit verdict" in err3
    assert schemas.load_project(proj_md).spec.status != schemas.PRState.GRADUATED

    # 4. Post Round 3 APPROVED for new_head_sha -> graduate succeeds!
    audit_file.write_text(
        schemas.dump_document(
            schemas.AuditReport(
                pr_id="PR-01",
                audit_round=3,
                head_sha=new_head_sha[:12],
                verdict="APPROVED",
                findings=[],
            ),
            [],
        ),
        encoding="utf-8",
    )
    assert (
        pa_cli.main(
            [
                "pr",
                "post-audit",
                "PR-01",
                "--file",
                str(audit_file),
                "--path",
                str(tmp_repo),
            ]
        )
        == 0
    )
    audit_file.unlink()

    capsys.readouterr()
    assert pa_cli.main(["pr", "graduate", "PR-01", "--path", str(tmp_repo)]) == 0
    grad_out = json.loads(capsys.readouterr().out)
    assert grad_out["status"] == "GRADUATED"
    assert grad_out["memory_mode"] == "external"
    assert grad_out["memory_files_touched"] == []
    assert not (ws_dir / "memory").exists()
    assert schemas.load_project(proj_md).spec.status == schemas.PRState.GRADUATED


def test_pa_cli_github_mode_lifecycle_with_mocked_gh(
    tmp_repo: Path,
    daemon_home: Path,
    fake_runner: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify `pa` CLI commands in `github` mode against a mocked `gh` runner."""
    import pa_cli

    _ = daemon_home
    monkeypatch.delenv("ANTIGRAVITY_LS_ADDRESS", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_CSRF_TOKEN", raising=False)

    # Delegate real `git` commands to common.run while mocking `gh` commands and `git push`/`git fetch`
    def _hybrid_runner(
        cmd: list[str],
        *,
        cwd: str | Path | None = None,
        timeout: float | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if cmd and (
            cmd[0] == "gh"
            or cmd[:2] in (["git", "push"], ["git", "fetch"])
        ):
            return fake_runner(cmd, cwd=cwd, timeout=timeout, env=env)
        return common.run(cmd, cwd=cwd, timeout=timeout, env=env)

    # 1. Enroll in github mode
    assert (
        pa_cli.main(
            [
                "enroll",
                str(tmp_repo),
                "--vcs-mode",
                "github",
                "--memory-mode",
                "external",
            ],
            runner=_hybrid_runner,
        )
        == 0
    )

    # 2. Charter PR-01 with --open-draft
    fake_runner.set_response(["git", "push"], returncode=0, stdout="")
    fake_runner.set_response(["gh", "pr", "view"], returncode=1, stderr="not found")
    fake_runner.set_response(
        ["gh", "pr", "create"],
        returncode=0,
        stdout="https://github.com/example/repo/pull/31\n",
    )
    capsys.readouterr()
    assert (
        pa_cli.main(
            [
                "programme",
                "charter",
                "PR-01",
                "--slug",
                "pr-01-alpha",
                "--title",
                "GitHub Mode PR",
                "--branch",
                "feat/pr-01-alpha",
                "--base-branch",
                "main",
                "--allowed-module",
                "src/",
                "--open-draft",
                "--path",
                str(tmp_repo),
            ],
            runner=_hybrid_runner,
        )
        == 0
    )
    charter_out = json.loads(capsys.readouterr().out)
    assert charter_out["draft_pr"]["github_pr"] == 31

    # 3. `pa pr post-audit` posts via `gh pr review 31 --comment`
    fake_runner.set_response(["gh", "pr", "review"], returncode=0, stdout="")
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    audit_file = tmp_repo / "gh_audit.md"
    audit_file.write_text(
        schemas.dump_document(
            schemas.AuditReport(
                pr_id="PR-01",
                github_pr=31,
                audit_round=1,
                head_sha=head_sha[:12],
                verdict="APPROVED",
                findings=[],
            ),
            [],
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert (
        pa_cli.main(
            [
                "pr",
                "post-audit",
                "PR-01",
                "--file",
                str(audit_file),
                "--path",
                str(tmp_repo),
            ],
            runner=_hybrid_runner,
        )
        == 0
    )
    post_out = json.loads(capsys.readouterr().out)
    assert post_out["mode"] == "github"
    assert post_out["review_posted"] is True
    audit_file.unlink()

    review_calls = [c for c in fake_runner.calls if c[:3] == ["gh", "pr", "review"]]
    assert len(review_calls) == 1
    assert "--comment" in review_calls[0]
    assert "--approve" not in review_calls[0]

    # 4. `pa issue create` calls `gh issue create --label pa:deferred`
    fake_runner.set_response(
        ["gh", "issue", "create"],
        returncode=0,
        stdout="https://github.com/example/repo/issues/99\n",
    )
    capsys.readouterr()
    assert (
        pa_cli.main(
            [
                "issue",
                "create",
                "--title",
                "Deferred GitHub issue",
                "--summary",
                "Out of scope finding",
                "--pr-id",
                "PR-01",
                "--path",
                str(tmp_repo),
            ],
            runner=_hybrid_runner,
        )
        == 0
    )
    issue_out = json.loads(capsys.readouterr().out)
    assert issue_out["mode"] == "github"
    assert issue_out["issue_url"] == "https://github.com/example/repo/issues/99"


