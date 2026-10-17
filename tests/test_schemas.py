"""Comprehensive tests for Split-Authority Pydantic v2 models, document parser/renderer, and normative hashes."""

from __future__ import annotations

import json
from pathlib import Path

import common
import pydantic
import pytest
import schemas
import yaml
from pydantic import ValidationError
from schemas import (
    AuditFinding,
    AuditReport,
    CompletionReport,
    ComplexityTier,
    Document,
    EscalationRequest,
    PRCharterSpec,
    PRNodeSpec,
    ProgramSpec,
    ProjectSpec,
    PRState,
    Section,
    WorkOrderSpec,
    WorkOrderStatus,
    WOSummaryRow,
    canonical_json,
    compute_charter_hash,
    compute_spec_hash,
    dump_document,
    load_audit,
    load_program,
    load_project,
    load_workorder,
    norm_section,
    parse_document,
    verify_charter_hash,
    verify_spec_hash,
)


def test_dependencies_importable() -> None:
    """Verify runtime dependencies are installed and importable."""
    assert pydantic.__version__.startswith("2.")
    assert yaml.__version__ is not None


def test_daemon_manifests_valid() -> None:
    """Verify plugin manifests exist and have correct metadata."""
    repo_root = Path(__file__).resolve().parent.parent

    daemon_manifest = repo_root / "daemon" / "plugin.json"
    assert daemon_manifest.is_file(), "daemon/plugin.json must exist"
    daemon_data = json.loads(daemon_manifest.read_text(encoding="utf-8"))
    assert daemon_data["name"] == "pa-daemon"
    assert daemon_data["version"] == "0.1.0"

    workspace_manifest = (
        repo_root
        / "daemon"
        / "workspace-plugin"
        / "principal-architect"
        / "plugin.json"
    )
    assert workspace_manifest.is_file(), "workspace plugin.json must exist"
    workspace_data = json.loads(workspace_manifest.read_text(encoding="utf-8"))
    assert workspace_data["name"] == "principal-architect"
    assert workspace_data["version"] == "0.1.0"


def test_module_docstring_mentions_normative_spec() -> None:
    """Verify schemas.py module docstring states SPEC §6 is normative (Charter R2)."""
    assert schemas.__doc__ is not None
    assert "SPEC" in schemas.__doc__
    assert "normative" in schemas.__doc__.lower()


def test_string_enums() -> None:
    """Verify string enum members match Charter R2."""
    assert {e.value for e in PRState} >= {
        "PLANNED",
        "APPROVED",
        "IN_PROGRESS",
        "STAGED_FOR_AUDIT",
        "CHANGES_REQUESTED",
        "AUDIT_APPROVED",
        "GRADUATED",
        "ARCHIVED",
    }
    assert {e.value for e in WorkOrderStatus} >= {
        "PENDING",
        "IN_PROGRESS",
        "COMPLETED",
        "BLOCKED",
        "ESCALATED_TO_PA",
    }
    assert {e.value for e in ComplexityTier} == {
        "mechanical",
        "standard",
        "architect",
        "interactive",
    }


# ---------------------------------------------------------------------------
# Model Validation Tests (Accept & Reject)
# ---------------------------------------------------------------------------


def test_pr_node_spec_accept_and_reject() -> None:
    valid = PRNodeSpec(
        id="PR-01a",
        slug="pr-01a-core-foundation",
        title="Valid PR Node Title",
        branch="feat/pr-01a-core-foundation",
        allowed_modules=["daemon/"],
    )
    assert valid.status == PRState.PLANNED
    assert valid.base_branch == "main"
    assert valid.github_pr is None

    # Invalid id pattern
    with pytest.raises(ValidationError):
        PRNodeSpec(
            id="PR01",
            slug="pr-01-valid",
            title="Valid Title",
            branch="feat/x",
            allowed_modules=["a"],
        )

    # Invalid slug pattern (uppercase or wrong prefix)
    with pytest.raises(ValidationError):
        PRNodeSpec(
            id="PR-01",
            slug="PR-01-Upper",
            title="Valid Title",
            branch="feat/x",
            allowed_modules=["a"],
        )

    # Title too short (<5) and too long (>140)
    with pytest.raises(ValidationError):
        PRNodeSpec(
            id="PR-01",
            slug="pr-01-short",
            title="abc",
            branch="feat/x",
            allowed_modules=["a"],
        )
    with pytest.raises(ValidationError):
        PRNodeSpec(
            id="PR-01",
            slug="pr-01-long",
            title="x" * 141,
            branch="feat/x",
            allowed_modules=["a"],
        )

    # Empty allowed_modules
    with pytest.raises(ValidationError):
        PRNodeSpec(
            id="PR-01",
            slug="pr-01-empty",
            title="Valid Title",
            branch="feat/x",
            allowed_modules=[],
        )

    # extra="forbid"
    with pytest.raises(ValidationError):
        PRNodeSpec.model_validate(
            {
                "id": "PR-01",
                "slug": "pr-01-extra",
                "title": "Valid Title",
                "branch": "feat/x",
                "allowed_modules": ["a"],
                "unexpected": True,
            }
        )


def test_program_spec_accept_and_reject() -> None:
    prog = ProgramSpec(
        programme_id="prog-sample-1",
        title="Sample Programme",
        status="APPROVED",
        prs=[],
    )
    assert prog.schema_version == 1

    # Invalid programme_id pattern
    with pytest.raises(ValidationError):
        ProgramSpec(programme_id="sample-1", title="Sample")

    # Invalid schema_version
    with pytest.raises(ValidationError):
        ProgramSpec.model_validate(
            {"schema_version": 2, "programme_id": "prog-x", "title": "Sample"}
        )

    # Invalid status
    with pytest.raises(ValidationError):
        ProgramSpec.model_validate(
            {"programme_id": "prog-x", "title": "Sample", "status": "INVALID"}
        )

    # Extra field forbidden
    with pytest.raises(ValidationError):
        ProgramSpec.model_validate(
            {"programme_id": "prog-x", "title": "Sample", "extra_field": 1}
        )


def test_pr_charter_wo_summary_and_project_spec() -> None:
    charter = PRCharterSpec(
        pr_id="PR-02",
        programme_id="prog-sample",
        slug="pr-02-hooks",
        title="Hooks Engine",
        branch="feat/pr-02-hooks",
        allowed_modules=["daemon/"],
    )
    wo_row = WOSummaryRow(
        id="WO-02.1",
        slug="wo1-hooks",
        title="Implement hooks",
        complexity=ComplexityTier.standard,
        attempts=2,
    )
    proj = ProjectSpec(
        charter=charter,
        status=PRState.APPROVED,
        approved_at="2026-10-16T18:50:00Z",
        work_orders=[wo_row],
    )
    assert proj.charter.pr_id == "PR-02"
    assert proj.work_orders[0].id == "WO-02.1"

    # Invalid WO id pattern
    with pytest.raises(ValidationError):
        WOSummaryRow(
            id="WO-02-1",
            slug="wo1",
            title="Bad ID",
            complexity=ComplexityTier.mechanical,
        )

    # Negative attempts rejected
    with pytest.raises(ValidationError):
        WOSummaryRow(
            id="WO-02.1",
            slug="wo1",
            title="Neg attempts",
            complexity=ComplexityTier.mechanical,
            attempts=-1,
        )

    # Extra field on ProjectSpec rejected
    with pytest.raises(ValidationError):
        ProjectSpec.model_validate(
            {
                "charter": charter.model_dump(),
                "unknown_key": "nope",
            }
        )


def test_escalation_completion_and_workorder_spec() -> None:
    esc = EscalationRequest(
        blocker_type="boundary",
        reason_code="NEED_EXTRA_FILE",
        target_role="pa",
        requested_files=["scripts/extra.py"],
        summary="Need access to scripts/extra.py to wire helper.",
    )
    comp = CompletionReport(
        status=WorkOrderStatus.ESCALATED_TO_PA,
        attempt_num=2,
        verification_summary="Blocked on boundary expansion",
        escalation_request=esc,
    )
    wo = WorkOrderSpec(
        wo_id="WO-01.3",
        pr_id="PR-01",
        title="Schemas and document parser implementation",
        complexity=ComplexityTier.architect,
        allowed_files=["daemon/workspace-plugin/principal-architect/scripts/schemas.py"],
        verification_command="pytest tests/test_schemas.py",
        completion=comp,
    )
    assert wo.completion is not None
    assert wo.completion.escalation_request is not None
    assert wo.completion.escalation_request.target_role == "pa"

    # EscalationRequest invalid blocker_type or summary > 500
    with pytest.raises(ValidationError):
        EscalationRequest(
            blocker_type="unknown",  # type: ignore[arg-type]
            reason_code="X",
            target_role="pa",
            summary="ok",
        )
    with pytest.raises(ValidationError):
        EscalationRequest(
            blocker_type="structural",
            reason_code="X",
            target_role="pa",
            summary="x" * 501,
        )

    # CompletionReport attempt_num out of [1, 5] or verification_summary > 280
    with pytest.raises(ValidationError):
        CompletionReport(
            status=WorkOrderStatus.COMPLETED,
            attempt_num=6,
            verification_summary="ok",
        )
    with pytest.raises(ValidationError):
        CompletionReport(
            status=WorkOrderStatus.COMPLETED,
            attempt_num=1,
            verification_summary="x" * 281,
        )

    # WorkOrderSpec constraints: max_attempts (1..5), max_structural_failures (1..3), verification_command >= 2
    with pytest.raises(ValidationError):
        WorkOrderSpec(
            wo_id="WO-01.1",
            pr_id="PR-01",
            title="Valid WorkOrder Title",
            complexity=ComplexityTier.standard,
            allowed_files=["a.py"],
            verification_command="x",
        )
    with pytest.raises(ValidationError):
        WorkOrderSpec(
            wo_id="WO-01.1",
            pr_id="PR-01",
            title="Valid WorkOrder Title",
            complexity=ComplexityTier.standard,
            allowed_files=["a.py"],
            verification_command="pytest",
            max_attempts=6,
        )
    with pytest.raises(ValidationError):
        WorkOrderSpec(
            wo_id="WO-01.1",
            pr_id="PR-01",
            title="Valid WorkOrder Title",
            complexity=ComplexityTier.standard,
            allowed_files=["a.py"],
            verification_command="pytest",
            max_structural_failures=4,
        )


def test_audit_finding_and_report_accept_and_reject() -> None:
    finding = AuditFinding(
        id="BLOCKING-1",
        axis="spec_alignment",
        file_path="scripts/schemas.py",
        line_range="L10-L20",
        summary="Missing field",
        remediation="Add field",
    )
    report = AuditReport(
        pr_id="PR-01",
        audit_round=1,
        head_sha="abcdef1234567",
        verdict="CHANGES_REQUESTED",
        findings=[finding],
    )
    assert report.findings[0].id == "BLOCKING-1"

    # Invalid finding id pattern
    with pytest.raises(ValidationError):
        AuditFinding(
            id="MINOR-1",
            axis="invariants",
            file_path="a.py",
            summary="s",
            remediation="r",
        )

    # Invalid audit_round (>5) or head_sha (<7 or >40)
    with pytest.raises(ValidationError):
        AuditReport(
            pr_id="PR-01",
            audit_round=6,
            head_sha="abcdef1",
            verdict="APPROVED",
        )
    with pytest.raises(ValidationError):
        AuditReport(
            pr_id="PR-01",
            audit_round=1,
            head_sha="abc",
            verdict="APPROVED",
        )
    with pytest.raises(ValidationError):
        AuditReport(
            pr_id="PR-01",
            audit_round=1,
            head_sha="a" * 41,
            verdict="APPROVED",
        )


# ---------------------------------------------------------------------------
# Document Parser, Renderer, Round-Trip & Loaders
# ---------------------------------------------------------------------------


def test_parse_and_dump_document_round_trip_with_preamble_and_unknown_sections() -> None:
    raw = (
        "\ufeff---\n"
        "schema_version: 1\n"
        "programme_id: prog-demo\n"
        "title: Demo Programme\n"
        "base_branch: main\n"
        "status: DRAFT\n"
        "prs: []\n"
        "---\n\n"
        "# Demo Programme\n\n"
        "<!-- custom comment in preamble -->\n\n"
        "## Custom Intro Section\n\n"
        "Intro text preserved verbatim.\n\n"
        "## 1. Architectural Vision & System Invariants\n\n"
        "Vision body.\n\n"
        "## 2. Cross-PR Contracts & Interfaces\n\n"
        "Contracts body.\n\n"
        "## 3. Programme Session Log\n\n"
        "Session log body.\n"
    )
    fm1, sections1 = parse_document(raw)
    model = ProgramSpec.model_validate(fm1)
    assert sections1[0].heading == ""
    assert "# Demo Programme" in sections1[0].body
    assert "<!-- custom comment in preamble -->" in sections1[0].body
    assert sections1[1].heading == "## Custom Intro Section"

    dumped = dump_document(model, sections1)
    fm2, sections2 = parse_document(dumped)
    assert fm2 == fm1
    assert sections2 == sections1
    assert dump_document(fm2, sections2) == dumped


def test_parse_document_errors() -> None:
    with pytest.raises(ValueError, match="YAML frontmatter"):
        parse_document("# No frontmatter here\n")

    with pytest.raises(ValueError, match="mapping"):
        parse_document("---\n- item1\n- item2\n---\n## 1. Sec\n")


def test_typed_loaders_and_missing_required_sections(tmp_path: Path) -> None:
    # Valid Audit document
    audit_path = tmp_path / "AUDIT-round-1.md"
    audit_spec = AuditReport(
        pr_id="PR-01",
        audit_round=1,
        head_sha="1234567890abcdef",
        verdict="APPROVED",
    )
    audit_path.write_text(
        dump_document(audit_spec, [Section(heading="## 1. Audit Summary", body="All good.\n")]),
        encoding="utf-8",
    )
    loaded_audit = load_audit(audit_path)
    assert isinstance(loaded_audit, Document)
    assert loaded_audit.spec.verdict == "APPROVED"
    assert loaded_audit.section("## 1.") is not None

    # Program missing ## 3. raises ValueError
    prog_path = tmp_path / "PROGRAM.md"
    prog_spec = ProgramSpec(programme_id="prog-test", title="Test")
    prog_path.write_text(
        dump_document(
            prog_spec,
            [
                Section(heading="## 1. Vision", body="v\n"),
                Section(heading="## 2. Contracts", body="c\n"),
            ],
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="## 3."):
        load_program(prog_path)

    # WorkOrder missing ## Completion Report raises ValueError
    wo_path = tmp_path / "WORKORDER.md"
    wo_spec = WorkOrderSpec(
        wo_id="WO-01.1",
        pr_id="PR-01",
        title="Sample Work Order",
        complexity=ComplexityTier.mechanical,
        allowed_files=["a.py"],
        verification_command="pytest",
    )
    wo_path.write_text(
        dump_document(wo_spec, [Section(heading="## 1. Objective", body="obj\n")]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Completion Report"):
        load_workorder(wo_path)


# ---------------------------------------------------------------------------
# Normative Hashing: Determinism, Tamper Detection & Part II Invariance
# ---------------------------------------------------------------------------


def test_charter_hash_determinism_tamper_and_part2_invariance(tmp_path: Path) -> None:
    charter = PRCharterSpec(
        pr_id="PR-01",
        programme_id="prog-test",
        slug="pr-01-test",
        title="Test PR",
        branch="feat/pr-01-test",
        allowed_modules=["daemon/"],
    )
    proj = ProjectSpec(charter=charter, status=PRState.PLANNED)
    sections = [
        Section(heading="", body="# PR-01\n\n"),
        Section(heading="## 1. PR Charter: Scope, Goals, & Non-Goals", body="Scope text.  \n\n"),
        Section(heading="## 2. Architectural Requirements", body="Req text.\n\n"),
        Section(heading="## 3. Implementation Plan", body="Initial plan.\n\n"),
        Section(heading="## 4. Outcome & Session Log", body="Initial log.\n"),
    ]

    h = compute_charter_hash(proj, sections)
    proj.charter.charter_hash = h

    p = tmp_path / "PROJECT.md"
    p.write_text(dump_document(proj, sections), encoding="utf-8")
    assert verify_charter_hash(p) is True

    # Mutating Part II/III (status, approved_at, work_orders, ## 3., ## 4.) preserves charter_hash
    doc = load_project(p)
    doc.spec.status = PRState.APPROVED
    doc.spec.work_orders.append(
        WOSummaryRow(
            id="WO-01.1",
            slug="wo1",
            title="First WO",
            complexity=ComplexityTier.mechanical,
            status=WorkOrderStatus.COMPLETED,
        )
    )
    sec3 = doc.section("## 3.")
    assert sec3 is not None
    sec3.body = "Updated Part II implementation plan with details.\n\n"
    sec4 = doc.section("## 4.")
    assert sec4 is not None
    sec4.body = "Updated Part III session log.\n"
    p.write_text(dump_document(doc.spec, doc.sections), encoding="utf-8")
    assert verify_charter_hash(p) is True

    # Tampering with Part I section ## 1. invalidates charter_hash
    sec1 = doc.section("## 1.")
    assert sec1 is not None
    sec1.body = "Tampered scope text!\n\n"
    p.write_text(dump_document(doc.spec, doc.sections), encoding="utf-8")
    assert verify_charter_hash(p) is False

    # Missing charter_hash returns False
    doc.spec.charter.charter_hash = None
    assert verify_charter_hash(doc) is False


def test_spec_hash_determinism_tamper_and_completion_invariance(tmp_path: Path) -> None:
    wo = WorkOrderSpec(
        wo_id="WO-01.1",
        pr_id="PR-01",
        title="Sample Work Order",
        complexity=ComplexityTier.standard,
        allowed_files=["scripts/a.py"],
        verification_command="pytest",
    )
    sections = [
        Section(heading="", body="# WO-01.1\n\n"),
        Section(heading="## 1. Role & Objective", body="Objective text.\n\n"),
        Section(heading="## 2. Strict Boundary Box", body="Boundary text.\n\n"),
        Section(heading="## Completion Report", body="_Pending._\n"),
    ]
    sh = compute_spec_hash(wo, sections)
    wo.spec_hash = sh

    p = tmp_path / "WORKORDER.md"
    p.write_text(dump_document(wo, sections), encoding="utf-8")
    assert verify_spec_hash(p) is True

    # Updating status, completion block, and ## Completion Report preserves spec_hash
    doc = load_workorder(p)
    doc.spec.status = WorkOrderStatus.COMPLETED
    doc.spec.completion = CompletionReport(
        status=WorkOrderStatus.COMPLETED,
        attempt_num=1,
        receipt_id="rcpt_123",
        commit_sha="abcdef1",
        files_modified=["scripts/a.py"],
        verification_summary="10 passed",
    )
    comp_sec = doc.section("## Completion Report")
    assert comp_sec is not None
    comp_sec.body = "### Summary\nCompleted all items.\n"
    p.write_text(dump_document(doc.spec, doc.sections), encoding="utf-8")
    assert verify_spec_hash(p) is True

    # Tampering with allowed_files or Part I section invalidates spec_hash
    doc.spec.allowed_files.append("scripts/unauthorized.py")
    assert verify_spec_hash(doc) is False

    doc.spec.allowed_files = ["scripts/a.py"]
    sec1 = doc.section("## 1.")
    assert sec1 is not None
    sec1.body = "Tampered objective!\n"
    assert verify_spec_hash(doc) is False

    doc.spec.spec_hash = None
    assert verify_spec_hash(doc) is False


# ---------------------------------------------------------------------------
# Dogfood Verification on Committed Repository Artifacts (Charter G4, R12)
# ---------------------------------------------------------------------------


def test_dogfood_committed_programme_project_and_workorders() -> None:
    repo_root = common.find_repo_root(__file__)
    assert repo_root is not None
    ws_dir = common.workspace_dir(repo_root)

    # 1. PROGRAM.md
    prog_path = ws_dir / "programme-principal-architect-plugin" / "PROGRAM.md"
    prog_doc = load_program(prog_path)
    assert prog_doc.spec.programme_id == "prog-principal-architect-plugin"
    assert len(prog_doc.spec.prs) == 5

    # 2. PROJECT.md and locked charter_hash
    proj_path = ws_dir / "pr-01-core-schemas-and-enrollment" / "PROJECT.md"
    proj_doc = load_project(proj_path)
    assert proj_doc.spec.charter.pr_id == "PR-01"
    assert (
        proj_doc.spec.charter.charter_hash
        == "9005d5135f25ae53fd2ed1b6ee63ece115b521cbaccd4469fd690fb6ca061d1a"
    )
    assert verify_charter_hash(proj_doc) is True
    assert verify_charter_hash(proj_path) is True

    # 3. WORKORDER.md files for WO-01.1 through WO-01.6
    for wo_slug in (
        "wo1-dev-bootstrap-and-package-skeleton",
        "wo2-common-stdlib-foundations",
        "wo3-schemas-models-and-document-layer",
        "wo4-state-db-and-registry",
        "wo5-templates",
        "wo6-pa-cli-enroll-unenroll-status-mode",
    ):
        wo_path = ws_dir / "pr-01-core-schemas-and-enrollment" / wo_slug / "WORKORDER.md"
        wo_doc = load_workorder(wo_path)
        assert wo_doc.spec.pr_id == "PR-01"
        assert verify_spec_hash(wo_doc) is True, f"spec_hash verification failed for {wo_slug}"
        assert verify_spec_hash(wo_path) is True


def test_templates_exist_and_render_successfully(tmp_path: Path) -> None:
    t_dir = common.templates_dir()
    for name in (
        "PROGRAM.md.tpl",
        "PROJECT.md.tpl",
        "WORKORDER.md.tpl",
        "AUDIT.md.tpl",
        "MEMORY.md.tpl",
        "MODULE_INDEX.md.tpl",
        "PROJECT_INDEX.md.tpl",
    ):
        assert (t_dir / name).is_file(), f"Template {name} must exist"

    # Render PROGRAM
    prog_text = common.render_template_file(
        "PROGRAM",
        {
            "programme_id": "prog-test",
            "title": "Test Programme",
            "base_branch": "main",
        },
    )
    prog_path = tmp_path / "PROGRAM.md"
    prog_path.write_text(prog_text, encoding="utf-8")
    doc_prog = load_program(prog_path)
    assert doc_prog.spec.programme_id == "prog-test"

    # Render PROJECT
    proj_text = common.render_template_file(
        "PROJECT",
        {
            "pr_id": "PR-01",
            "programme_id": "prog-test",
            "slug": "pr-01-test",
            "title": "Test PR",
            "branch": "feat/pr-01-test",
            "base_branch": "main",
            "allowed_module": "daemon/",
            "verification_command": "pytest",
        },
    )
    proj_path = tmp_path / "PROJECT.md"
    proj_path.write_text(proj_text, encoding="utf-8")
    doc_proj = load_project(proj_path)
    assert doc_proj.spec.charter.pr_id == "PR-01"

    # Render WORKORDER
    wo_text = common.render_template_file(
        "WORKORDER",
        {
            "wo_id": "WO-01.1",
            "pr_id": "PR-01",
            "title": "Test Work Order",
            "complexity": "mechanical",
            "allowed_file": "daemon/",
            "verification_command": "pytest",
        },
    )
    wo_path = tmp_path / "WORKORDER.md"
    wo_path.write_text(wo_text, encoding="utf-8")
    doc_wo = load_workorder(wo_path)
    assert doc_wo.spec.wo_id == "WO-01.1"

    # Render AUDIT
    audit_text = common.render_template_file(
        "AUDIT",
        {
            "pr_id": "PR-01",
            "audit_round": 1,
            "head_sha": "abcdef1234567",
            "auditor_harness": "cli",
            "verdict": "APPROVED",
        },
    )
    audit_path = tmp_path / "AUDIT-round-1.md"
    audit_path.write_text(audit_text, encoding="utf-8")
    doc_audit = load_audit(audit_path)
    assert doc_audit.spec.verdict == "APPROVED"

    # Render memory templates
    mem_text = common.render_template_file("MEMORY", {"updated_at": "2026-10-16"})
    assert "{{" not in mem_text
    assert "PROJECT_INDEX.md" in mem_text

    mod_text = common.render_template_file("MODULE_INDEX", {})
    assert "{{" not in mod_text

    proj_idx_text = common.render_template_file("PROJECT_INDEX", {})
    assert "{{" not in proj_idx_text


def test_canonical_json_and_norm_section_helpers() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert norm_section("  ## 1. Title  \nLine 1   \nLine 2\n\n") == "## 1. Title\nLine 1\nLine 2"
