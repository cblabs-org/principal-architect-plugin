"""Unit and integration tests for dual-mode hooks (`monitored` vs `autonomous`) and escalation engine."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import common
import escalation
import pa_cli
import post_tool_receipt
import pre_invocation
import pre_tool_gate
import pytest
import schemas
import stop_gate
from state_db import Registry, StateDB


def test_escalation_import_purity() -> None:
    """Verify importing escalation.py does not import pydantic, yaml, or schemas."""
    scripts_dir = str(Path(escalation.__file__).resolve().parent)
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{scripts_dir}:{existing_pythonpath}" if existing_pythonpath else scripts_dir

    code = (
        "import sys, escalation\n"
        "assert 'pydantic' not in sys.modules, f'pydantic imported: {sys.modules[\"pydantic\"]}'\n"
        "assert 'yaml' not in sys.modules, f'yaml imported: {sys.modules[\"yaml\"]}'\n"
        "assert 'schemas' not in sys.modules, f'schemas imported: {sys.modules[\"schemas\"]}'\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert res.returncode == 0, f"Import purity failed:\nstdout: {res.stdout}\nstderr: {res.stderr}"


def test_decide_invalid_rule_or_mode() -> None:
    """Verify decide raises ValueError on unknown rule or invalid mode."""
    with pytest.raises(ValueError, match="Unknown rule"):
        escalation.decide("R99", "monitored")

    with pytest.raises(ValueError, match="Invalid execution mode"):
        escalation.decide("R1", "invalid_mode")


def test_decide_r1_monitored_vs_autonomous() -> None:
    """Verify R1 (Architect no-inline-code) across monitored and autonomous modes."""
    ctx = {"path": "src/app.py"}

    res_mon = escalation.decide("R1", "monitored", ctx)
    assert res_mon["permissionDecision"] == "ask"
    assert res_mon["decision"] == "ask"
    assert "src/app.py" in res_mon["reason"]
    assert res_mon["increment_structural_failures"] is False
    assert res_mon["auto_approve_plan"] is False
    assert res_mon["escalation"] is None

    res_auto = escalation.decide("R1", "autonomous", ctx)
    assert res_auto["permissionDecision"] == "deny"
    assert res_auto["decision"] == "deny"
    assert "Autonomous Mode (R1)" in res_auto["reason"]
    assert "src/app.py" in res_auto["reason"]
    assert res_auto["increment_structural_failures"] is False
    assert res_auto["auto_approve_plan"] is False
    assert res_auto["escalation"] is None


def test_decide_r1b_monitored_vs_autonomous() -> None:
    """Verify R1b (Fractal PROJECT.md Charter lock) across monitored and autonomous modes."""
    ctx = {"path": "outside/module.py", "pr_id": "PR-02"}

    res_mon = escalation.decide("R1b", "monitored", ctx)
    assert res_mon["permissionDecision"] == "ask"
    assert res_mon["decision"] == "ask"
    assert "PR-02" in res_mon["reason"]
    assert "outside/module.py" in res_mon["reason"]
    assert res_mon["increment_structural_failures"] is False
    assert res_mon["escalation"] is None

    res_auto = escalation.decide("R1b", "autonomous", ctx)
    assert res_auto["permissionDecision"] == "deny"
    assert res_auto["decision"] == "deny"
    assert "pa escalate --to-chief" in res_auto["reason"]
    assert res_auto["increment_structural_failures"] is False
    esc = res_auto["escalation"]
    assert esc is not None
    assert esc["level"] == "PA_TO_CHIEF"
    assert esc["source_role"] == "pa"
    assert esc["target_role"] == "chief"
    assert esc["pr_id"] == "PR-02"
    assert esc["blocker_type"] == "charter"
    assert esc["reason_code"] == "CHARTER_AMENDMENT_NEEDED"
    assert esc["requested_files"] == ["outside/module.py"]
    assert esc["enqueue_attention"] is True
    assert esc["attention_kind"] == "charter_escalation"
    assert esc["attention_priority"] == 20


def test_decide_r2_monitored_vs_autonomous() -> None:
    """Verify R2 (Plan Approval Gate on invoke_subagent) across monitored and autonomous modes."""
    base_ctx = {"pr_id": "PR-02"}

    # Monitored mode: always ask
    res_mon = escalation.decide("R2", "monitored", base_ctx)
    assert res_mon["permissionDecision"] == "ask"
    assert res_mon["decision"] == "ask"
    assert "PR-02" in res_mon["reason"]
    assert res_mon["auto_approve_plan"] is False
    assert res_mon["escalation"] is None

    # Autonomous mode with auto_approve_pr_plans=False: deny + enqueue plan_approval
    res_auto_deny = escalation.decide(
        "R2",
        "autonomous",
        {"pr_id": "PR-02", "auto_approve_pr_plans": False, "plan_valid": True},
    )
    assert res_auto_deny["permissionDecision"] == "deny"
    assert res_auto_deny["decision"] == "deny"
    assert res_auto_deny["auto_approve_plan"] is False
    assert res_auto_deny["increment_structural_failures"] is False
    esc = res_auto_deny["escalation"]
    assert esc is not None
    assert esc["level"] == "PA_TO_HUMAN"
    assert esc["source_role"] == "pa"
    assert esc["target_role"] == "human"
    assert esc["pr_id"] == "PR-02"
    assert esc["reason_code"] == "PLAN_APPROVAL_REQUIRED"
    assert esc["enqueue_attention"] is True
    assert esc["attention_kind"] == "plan_approval"
    assert esc["attention_priority"] == 10

    # Autonomous mode with auto_approve_pr_plans=True but plan_valid=False: deny
    res_auto_invalid = escalation.decide(
        "R2",
        "autonomous",
        {"pr_id": "PR-02", "auto_approve_pr_plans": True, "plan_valid": False},
    )
    assert res_auto_invalid["permissionDecision"] == "deny"
    assert res_auto_invalid["auto_approve_plan"] is False
    assert res_auto_invalid["escalation"] is not None

    # Autonomous mode with auto_approve_pr_plans=True and plan_valid=True: allow
    res_auto_allow = escalation.decide(
        "R2",
        "autonomous",
        {"pr_id": "PR-02", "auto_approve_pr_plans": True, "plan_valid": True},
    )
    assert res_auto_allow["permissionDecision"] == "allow"
    assert res_auto_allow["decision"] == "allow"
    assert res_auto_allow["auto_approve_plan"] is True
    assert res_auto_allow["increment_structural_failures"] is False
    assert res_auto_allow["escalation"] is None


def test_decide_r3_monitored_vs_autonomous() -> None:
    """Verify R3 (Worker Strict Boundary Box & Spec Lock) across monitored and autonomous modes."""
    ctx = {"path": "SPEC.md", "pr_id": "PR-02", "wo_id": "WO-02.1"}

    res_mon = escalation.decide("R3", "monitored", ctx)
    assert res_mon["permissionDecision"] == "ask"
    assert res_mon["decision"] == "ask"
    assert "WO-02.1" in res_mon["reason"]
    assert "SPEC.md" in res_mon["reason"]
    assert res_mon["increment_structural_failures"] is False
    assert res_mon["escalation"] is None

    res_auto = escalation.decide("R3", "autonomous", ctx)
    assert res_auto["permissionDecision"] == "deny"
    assert res_auto["decision"] == "deny"
    assert "ESCALATED_TO_PA" in res_auto["reason"]
    assert res_auto["increment_structural_failures"] is True
    esc = res_auto["escalation"]
    assert esc is not None
    assert esc["level"] == "WORKER_TO_PA"
    assert esc["source_role"] == "engineer"
    assert esc["target_role"] == "pa"
    assert esc["pr_id"] == "PR-02"
    assert esc["wo_id"] == "WO-02.1"
    assert esc["blocker_type"] == "boundary"
    assert esc["reason_code"] == "BOUNDARY_EXPANSION_NEEDED"
    assert esc["requested_files"] == ["SPEC.md"]
    assert esc["enqueue_attention"] is True
    assert esc["attention_kind"] == "boundary_escalation"
    assert esc["attention_priority"] == 20


def test_decide_r4_r5_r6_monitored_vs_autonomous() -> None:
    """Verify R4 (Worker git/gh lockdown), R5 (Auditor read-only), and R6 (Graduation audit gate)."""
    # R4: hard deny in both modes, increments structural failures
    for mode in ("monitored", "autonomous"):
        res_r4 = escalation.decide("R4", mode, {"command": "git push origin main"})
        assert res_r4["permissionDecision"] == "deny"
        assert res_r4["decision"] == "deny"
        assert "git push origin main" in res_r4["reason"]
        assert res_r4["increment_structural_failures"] is True
        assert res_r4["escalation"] is None

    # R5: hard deny in both modes, does not increment structural failures
    for mode in ("monitored", "autonomous"):
        res_r5 = escalation.decide("R5", mode, {"command": "rm -rf src"})
        assert res_r5["permissionDecision"] == "deny"
        assert res_r5["decision"] == "deny"
        assert "rm -rf src" in res_r5["reason"]
        assert res_r5["increment_structural_failures"] is False
        assert res_r5["escalation"] is None

    # R6: monitored -> ask, autonomous -> deny
    r6_ctx = {"pr_id": "PR-02", "head_sha": "abc1234"}
    res_r6_mon = escalation.decide("R6", "monitored", r6_ctx)
    assert res_r6_mon["permissionDecision"] == "ask"
    assert "abc1234" in res_r6_mon["reason"]
    assert "PR-02" in res_r6_mon["reason"]
    assert res_r6_mon["increment_structural_failures"] is False
    assert res_r6_mon["escalation"] is None

    res_r6_auto = escalation.decide("R6", "autonomous", r6_ctx)
    assert res_r6_auto["permissionDecision"] == "deny"
    assert "abc1234" in res_r6_auto["reason"]
    assert "PR-02" in res_r6_auto["reason"]
    assert res_r6_auto["increment_structural_failures"] is False
    assert res_r6_auto["escalation"] is None


def test_structural_blocker_signatures() -> None:
    """Verify STRUCTURAL_SIGNATURES and is_structural_blocker detection."""
    assert len(escalation.STRUCTURAL_SIGNATURES) >= 12
    assert escalation.is_structural_blocker(None) is False
    assert escalation.is_structural_blocker("") is False

    # Known structural blockers
    structural_samples = [
        "Error: Exclusive hardware is currently tied to another session.",
        "MCP lock acquisition timeout while connecting to server.",
        "PreToolUse hook returned permissionDecision: deny for write_file.",
        "PERMISSION_DENIED: cannot access protected resource.",
        "Encountered BLOCKER_STRUCTURAL in environment setup.",
        "bash: pytest: command not found",
        "No such file or directory: './.venv/bin/pytest'",
        "ModuleNotFoundError: No module named 'pydantic'",
        "ModuleNotFoundError: No module named 'yaml'",
        "OSError: [Errno 98] Address already in use",
    ]
    for sample in structural_samples:
        assert escalation.is_structural_blocker(sample) is True, f"Missed blocker: {sample}"

    # Normal productive test/assertion failures must return False
    productive_samples = [
        "AssertionError: assert 1 == 2",
        "FAILED tests/test_foo.py::test_bar - ValueError: invalid literal",
        "TypeError: expected str, got int",
        "KeyError: 'missing_key'",
    ]
    for sample in productive_samples:
        assert escalation.is_structural_blocker(sample) is False, f"False positive: {sample}"


def test_record_escalation_and_enqueue_attention(tmp_path: Path) -> None:
    """Verify record_escalation and enqueue_attention persist rows into StateDB."""
    with StateDB(tmp_path / "state.db") as db:
        # 1. Direct enqueue_attention
        attn = escalation.enqueue_attention(
            db,
            kind="custom_notice",
            title="Notice title",
            priority=15,
            pr_id="PR-02",
            wo_id="WO-02.1",
            action_payload={"foo": "bar"},
        )
        assert attn["item_id"].startswith("attn_")
        assert attn["kind"] == "custom_notice"
        assert attn["priority"] == 15

        # 2. record_escalation without enqueue (target_role="pa", enqueue_if_needed=False)
        esc1 = escalation.record_escalation(
            db,
            level="WORKER_TO_PA",
            source_role="engineer",
            target_role="pa",
            pr_id="PR-02",
            wo_id="WO-02.1",
            blocker_type="boundary",
            reason_code="BOUNDARY_EXPANSION_NEEDED",
            requested_files=["extra.py"],
            summary="Need extra.py",
            enqueue_if_needed=False,
        )
        assert esc1["escalation_id"].startswith("esc_")
        assert len(db.open_escalations(wo_id="WO-02.1")) == 1
        assert len(db.list_open()) == 1  # only attn from step 1

        # 3. record_escalation with enqueue_if_needed=True links escalation_id in attention_queue
        esc2 = escalation.record_escalation(
            db,
            level="PA_TO_CHIEF",
            source_role="pa",
            target_role="chief",
            pr_id="PR-02",
            blocker_type="charter",
            reason_code="CHARTER_AMENDMENT_NEEDED",
            requested_files=["outside.py"],
            summary="Need outside.py in charter",
            enqueue_if_needed=True,
            attention_kind="charter_escalation",
            attention_title="🔴 [Charter Escalation] PR-02",
            attention_priority=20,
        )
        open_attn = db.list_open()
        assert len(open_attn) == 2
        linked = next(i for i in open_attn if i["kind"] == "charter_escalation")
        payload = json.loads(linked["action_payload_json"])
        assert payload["escalation_id"] == esc2["escalation_id"]
        assert payload["requested_files"] == ["outside.py"]

        # 4. record_escalation with target_role="human" automatically enqueues attention item
        esc3 = escalation.record_escalation(
            db,
            level="PA_TO_HUMAN",
            source_role="pa",
            target_role="human",
            pr_id="PR-02",
            blocker_type="other",
            reason_code="PLAN_APPROVAL_REQUIRED",
            summary="Approve PR-02 plan",
            attention_priority=10,
        )
        open_attn2 = db.list_open()
        assert len(open_attn2) == 3
        human_item = next(i for i in open_attn2 if i["priority"] == 10)
        assert json.loads(human_item["action_payload_json"])["escalation_id"] == esc3["escalation_id"]


def test_hook_io_and_extract_workspace_paths(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify extract_workspace_paths, read_hook_input, and write_hook_output."""
    # extract_workspace_paths deduplication and ordering
    paths = escalation.extract_workspace_paths(
        {
            "workspacePaths": ["/repo/a", "/repo/b", "/repo/a"],
            "workspaceUris": ["file:///repo/c"],
            "workspaceRoot": "/repo/b",
            "cwd": "/repo/d",
        }
    )
    assert paths == ["/repo/a", "/repo/b", "file:///repo/c", "/repo/d"]

    # Fallback to os.getcwd() when empty or None
    assert escalation.extract_workspace_paths({}) == [os.getcwd()]
    assert escalation.extract_workspace_paths(None) == [os.getcwd()]

    # read_hook_input: valid JSON object
    valid_stream = io.StringIO('{"toolName": "write_file", "cwd": "/tmp"}\n')
    assert escalation.read_hook_input(valid_stream) == {"toolName": "write_file", "cwd": "/tmp"}

    # read_hook_input: empty/whitespace
    assert escalation.read_hook_input(io.StringIO("   \n")) == {}

    # read_hook_input: malformed JSON logs warning to stderr and returns {}
    malformed_stream = io.StringIO("{not valid json")
    assert escalation.read_hook_input(malformed_stream) == {}
    captured = capsys.readouterr()
    assert "Malformed hook JSON stdin" in captured.err

    # read_hook_input: non-dict JSON logs warning to stderr and returns {}
    list_stream = io.StringIO('["a", "b"]')
    assert escalation.read_hook_input(list_stream) == {}
    captured2 = capsys.readouterr()
    assert "Hook stdin must be a JSON object" in captured2.err

    # write_hook_output: writes single JSON line and returns 0
    out_stream = io.StringIO()
    rc = escalation.write_hook_output({"permissionDecision": "allow"}, out_stream)
    assert rc == 0
    assert out_stream.getvalue() == '{"permissionDecision": "allow"}\n'


def test_hooks_json_schema() -> None:
    """Verify daemon/workspace-plugin/principal-architect/hooks.json exists and matches SPEC §7."""
    repo_root = common.find_repo_root(Path(__file__).resolve())
    assert repo_root is not None
    hooks_path = repo_root / "daemon" / "workspace-plugin" / "principal-architect" / "hooks.json"
    assert hooks_path.is_file()

    data = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert "principal-architect" in data
    pa_hooks = data["principal-architect"]
    assert pa_hooks["enabled"] is True

    # PreInvocation
    pre_inv = pa_hooks["PreInvocation"]
    assert len(pre_inv) == 1
    assert pre_inv[0] == {
        "type": "command",
        "command": "python3 ${PLUGIN_ROOT}/scripts/pre_invocation.py",
        "timeout": 10,
    }

    # PreToolUse
    pre_tool = pa_hooks["PreToolUse"]
    assert len(pre_tool) == 1
    assert (
        pre_tool[0]["matcher"]
        == "write_to_file|write_file|replace_file_content|edit_file|multi_replace_file_content|run_command|invoke_subagent"
    )
    assert pre_tool[0]["hooks"] == [
        {
            "type": "command",
            "command": "python3 ${PLUGIN_ROOT}/scripts/pre_tool_gate.py",
            "timeout": 10,
        }
    ]

    # PostToolUse
    post_tool = pa_hooks["PostToolUse"]
    assert len(post_tool) == 1
    assert post_tool[0]["matcher"] == "*"
    assert post_tool[0]["hooks"] == [
        {
            "type": "command",
            "command": "python3 ${PLUGIN_ROOT}/scripts/post_tool_receipt.py",
            "timeout": 10,
        }
    ]

    # Stop
    stop = pa_hooks["Stop"]
    assert len(stop) == 1
    assert stop[0] == {
        "type": "command",
        "command": "python3 ${PLUGIN_ROOT}/scripts/stop_gate.py",
        "timeout": 10,
    }


# ---------------------------------------------------------------------------
# WO-02.2: pre_tool_gate.py tests (Fast-exit, R1-R6, and Traversal Defense)
# ---------------------------------------------------------------------------


def _setup_enrolled_workspace(
    tmp_repo: Path,
    daemon_home: Path,
    *,
    mode: str = "monitored",
    pr_status: schemas.PRState = schemas.PRState.APPROVED,
    auto_approve_pr_plans: bool = False,
) -> tuple[Path, Path, Path]:
    """Provision an enrolled workspace with a locked PROJECT.md and stamped WORKORDER.md."""
    _ = daemon_home
    ws_dir = tmp_repo / common.NEW_WORKSPACE_REL
    pr_dir = ws_dir / "pr-02-agents-and-dual-mode-hooks"
    wo_dir = pr_dir / "wo1-sample"
    wo_dir.mkdir(parents=True, exist_ok=True)
    prog_dir = ws_dir / "programme-sample"
    prog_dir.mkdir(parents=True, exist_ok=True)

    Registry().register(tmp_repo, workspace_dir=ws_dir, slug="test-repo")

    prog_spec = schemas.ProgramSpec(
        programme_id="prog-sample",
        title="Sample Programme",
        status="APPROVED",
        prs=[
            schemas.PRNodeSpec(
                id="PR-02",
                slug="pr-02-agents-and-dual-mode-hooks",
                title="Sample PR Title",
                branch="feat/pr-02",
                allowed_modules=["src/", "tests/"],
            )
        ],
    )
    prog_sections = [
        schemas.Section("## 1. Programme Charter", "Charter body.\n"),
        schemas.Section("## 2. PR Topology", "Topology body.\n"),
        schemas.Section("## 3. Cross-PR Interfaces", "Interfaces body.\n"),
    ]
    (prog_dir / "PROGRAM.md").write_text(
        schemas.dump_document(prog_spec, prog_sections), encoding="utf-8"
    )

    charter = schemas.PRCharterSpec(
        pr_id="PR-02",
        programme_id="prog-sample",
        slug="pr-02-agents-and-dual-mode-hooks",
        title="Sample PR Title",
        branch="feat/pr-02",
        allowed_modules=["src/", "tests/"],
        verification_floor=["pytest"],
        charter_locked=True,
    )
    proj_sections = [
        schemas.Section("## 1. PR Charter: Scope", "Charter scope details.\n"),
        schemas.Section("## 2. Architectural Requirements", "Requirements details.\n"),
        schemas.Section("## 3. Implementation Plan", "Initial plan details.\n"),
        schemas.Section("## 4. Outcome & Session Log", "Log entry.\n"),
    ]
    charter.charter_hash = schemas.compute_charter_hash(charter, proj_sections)

    proj_spec = schemas.ProjectSpec(
        charter=charter,
        status=pr_status,
        work_orders=[
            schemas.WOSummaryRow(
                id="WO-02.1",
                slug="wo1-sample",
                title="Implement src/allowed.py",
                complexity=schemas.ComplexityTier.standard,
            )
        ],
    )
    proj_path = pr_dir / "PROJECT.md"
    proj_path.write_text(schemas.dump_document(proj_spec, proj_sections), encoding="utf-8")

    wo_spec = schemas.WorkOrderSpec(
        wo_id="WO-02.1",
        pr_id="PR-02",
        title="Implement src/allowed.py",
        complexity=schemas.ComplexityTier.standard,
        allowed_files=["src/allowed.py", "src/sub/"],
        forbidden_files=["SPEC.md", "src/sub/secret.py"],
        verification_command="pytest",
    )
    wo_sections = [
        schemas.Section("## 1. Role & Objective", "Objective text.\n"),
        schemas.Section("## 2. Strict Boundary Box", "Boundary text.\n"),
        schemas.Section("## 3. Line-Item Instructions", "- [ ] Do work.\n"),
        schemas.Section("## 4. Verification", "Run pytest.\n"),
        schemas.Section("## Completion Report", "_Pending._\n"),
    ]
    wo_spec.spec_hash = schemas.compute_spec_hash(wo_spec, wo_sections)
    wo_path = wo_dir / "WORKORDER.md"
    wo_path.write_text(schemas.dump_document(wo_spec, wo_sections), encoding="utf-8")

    with StateDB(ws_dir / ".state" / "state.db") as db:
        db.set_config("execution_mode", mode)
        db.set_config("auto_approve_pr_plans", "true" if auto_approve_pr_plans else "false")
        db.bind_session("conv-chief", "chief", programme_id="prog-sample", pr_id="PR-02")
        db.bind_session("conv-pa", "pa", programme_id="prog-sample", pr_id="PR-02")
        db.bind_session(
            "conv-eng",
            "engineer",
            programme_id="prog-sample",
            pr_id="PR-02",
            wo_id="WO-02.1",
        )
        db.bind_session("conv-auditor", "auditor", programme_id="prog-sample", pr_id="PR-02")

    return ws_dir, proj_path, wo_path


def test_pre_tool_gate_unenrolled_fast_exit_and_import_purity(
    tmp_path: Path, daemon_home: Path
) -> None:
    """Verify unenrolled fast-exit (<1ms) and zero pydantic/yaml/schemas imports."""
    _ = daemon_home
    unenrolled = tmp_path / "unenrolled-repo"
    unenrolled.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "workspacePaths": [str(unenrolled)],
        "toolCall": {"name": "write_file", "args": {"Path": "src/foo.py", "Content": "x = 1\n"}},
    }

    # Warm-up call
    assert pre_tool_gate.evaluate_pre_tool(payload) == {}

    iterations = 25
    start = time.perf_counter()
    for _ in range(iterations):
        res = pre_tool_gate.evaluate_pre_tool(payload)
        assert res == {}
    elapsed_ms = ((time.perf_counter() - start) * 1000.0) / iterations
    assert elapsed_ms < 1.0, f"Unenrolled fast-exit took {elapsed_ms:.3f} ms (limit < 1.0 ms)"

    # Verify import purity on the unenrolled path in a fresh subprocess
    script_path = Path(pre_tool_gate.__file__).resolve()
    scripts_dir = str(script_path.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = scripts_dir
    code = (
        "import sys, pre_tool_gate\n"
        f"res = pre_tool_gate.evaluate_pre_tool({{'workspacePaths': [{str(unenrolled)!r}]}})\n"
        "assert res == {}\n"
        "assert 'pydantic' not in sys.modules\n"
        "assert 'yaml' not in sys.modules\n"
        "assert 'schemas' not in sys.modules\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, f"Import purity failed:\n{proc.stdout}\n{proc.stderr}"

    # Verify CLI subprocess execution on unenrolled repo outputs {} and exits 0
    cli_proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert cli_proc.returncode == 0
    assert json.loads(cli_proc.stdout.strip()) == {}


def test_path_resolution_pattern_matching_and_simulate_edit(tmp_repo: Path) -> None:
    """Verify resolve_repo_rel_path, matches_pattern, and simulate_file_edit helpers."""
    inside, rel, _ = pre_tool_gate.resolve_repo_rel_path(tmp_repo, "src/module/file.py")
    assert inside is True
    assert rel == "src/module/file.py"

    # file:// URI inside repo
    uri = f"file://{tmp_repo}/src/app.py"
    inside_uri, rel_uri, _ = pre_tool_gate.resolve_repo_rel_path(tmp_repo, uri)
    assert inside_uri is True
    assert rel_uri == "src/app.py"

    # ../ traversal escaping repo_root
    inside_esc, raw_esc, _ = pre_tool_gate.resolve_repo_rel_path(tmp_repo, "../../etc/passwd")
    assert inside_esc is False
    assert raw_esc == "../../etc/passwd"

    # Pattern matching variations
    assert pre_tool_gate.matches_pattern("src/foo.py", "src/")
    assert pre_tool_gate.matches_pattern("src/nested/bar.py", "src/**")
    assert pre_tool_gate.matches_pattern("src/foo.py", "src/*.py")
    assert pre_tool_gate.matches_pattern("README.md", "README.md")
    assert not pre_tool_gate.matches_pattern("other/foo.py", "src/")

    # simulate_file_edit variations
    base_text = "alpha\nbeta\ngamma\n"
    assert (
        pre_tool_gate.simulate_file_edit(
            base_text, "write_file", {"Path": "a.txt", "Content": "new\n"}
        )
        == "new\n"
    )
    assert (
        pre_tool_gate.simulate_file_edit(
            base_text, "write_file", {"Path": "a.txt", "Content": "delta\n", "Append": True}
        )
        == "alpha\nbeta\ngamma\ndelta\n"
    )
    assert (
        pre_tool_gate.simulate_file_edit(
            base_text,
            "edit_file",
            {"Path": "a.txt", "Target": "beta", "Replacement": "BETA"},
        )
        == "alpha\nBETA\ngamma\n"
    )
    assert (
        pre_tool_gate.simulate_file_edit(
            base_text,
            "multi_replace_file_content",
            {
                "TargetFile": "a.txt",
                "ReplacementChunks": [
                    {"TargetContent": "alpha", "ReplacementContent": "A"},
                    {"TargetContent": "gamma", "ReplacementContent": "G"},
                ],
            },
        )
        == "A\nbeta\nG\n"
    )
    assert (
        pre_tool_gate.simulate_file_edit(
            base_text, "edit_file", {"Path": "a.txt", "Target": "missing", "Replacement": "X"}
        )
        is None
    )


def test_pre_tool_gate_r1_and_r1b_architect_gates(
    tmp_repo: Path, daemon_home: Path
) -> None:
    """Verify R1 (Architect no-inline-code) and R1b (Charter lock & allowed_modules)."""
    ws_dir, proj_path, wo_path = _setup_enrolled_workspace(
        tmp_repo, daemon_home, mode="monitored"
    )

    # 1. R1: Chief and PA editing application code outside .agents/ -> ask in monitored, deny in autonomous
    for conv_id in ("conv-chief", "conv-pa"):
        res_mon = pre_tool_gate.evaluate_pre_tool(
            {
                "conversationId": conv_id,
                "toolCall": {
                    "name": "write_file",
                    "args": {"Path": "src/inline_hack.py", "Content": "x = 1\n"},
                },
            },
            repo_root=tmp_repo,
        )
        assert res_mon["rule"] == "R1"
        assert res_mon["permissionDecision"] == "ask"

    with StateDB(ws_dir / ".state" / "state.db") as db:
        db.set_config("execution_mode", "autonomous")

    for conv_id in ("conv-chief", "conv-pa"):
        res_auto = pre_tool_gate.evaluate_pre_tool(
            {
                "conversationId": conv_id,
                "toolCall": {
                    "name": "write_file",
                    "args": {"Path": "src/inline_hack.py", "Content": "x = 1\n"},
                },
            },
            repo_root=tmp_repo,
        )
        assert res_auto["rule"] == "R1"
        assert res_auto["permissionDecision"] == "deny"

    # Architect shell command mutating outside .agents/ triggers R1
    res_cmd_r1 = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-pa",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "echo bad > src/app.py"}},
        },
        repo_root=tmp_repo,
    )
    assert res_cmd_r1["rule"] == "R1"
    assert res_cmd_r1["permissionDecision"] == "deny"

    # Chief attempting to edit WORKORDER.md triggers R1, but Chief editing PROGRAM.md is allowed
    res_chief_wo = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-chief",
            "toolCall": {
                "name": "edit_file",
                "args": {
                    "Path": str(wo_path.relative_to(tmp_repo)),
                    "Target": "Objective text.",
                    "Replacement": "Changed by chief.",
                },
            },
        },
        repo_root=tmp_repo,
    )
    assert res_chief_wo["rule"] == "R1"
    assert res_chief_wo["permissionDecision"] == "deny"

    prog_rel = str((ws_dir / "programme-sample" / "PROGRAM.md").relative_to(tmp_repo))
    res_chief_prog = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-chief",
            "toolCall": {
                "name": "edit_file",
                "args": {
                    "Path": prog_rel,
                    "Target": "Charter body.",
                    "Replacement": "Updated charter body.",
                },
            },
        },
        repo_root=tmp_repo,
    )
    assert res_chief_prog["permissionDecision"] == "allow"

    # 2. R1b: PA editing Part II (## 3. Implementation Plan) of PROJECT.md is allowed
    proj_rel = str(proj_path.relative_to(tmp_repo))
    res_pa_part2 = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-pa",
            "toolCall": {
                "name": "edit_file",
                "args": {
                    "Path": proj_rel,
                    "Target": "Initial plan details.",
                    "Replacement": "Updated Part II plan details.",
                },
            },
        },
        repo_root=tmp_repo,
    )
    assert res_pa_part2["permissionDecision"] == "allow"

    # R1b: PA tampering with Part I (## 1. PR Charter: Scope) of PROJECT.md is blocked
    res_pa_part1_auto = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-pa",
            "toolCall": {
                "name": "edit_file",
                "args": {
                    "Path": proj_rel,
                    "Target": "Charter scope details.",
                    "Replacement": "Tampered charter scope.",
                },
            },
        },
        repo_root=tmp_repo,
    )
    assert res_pa_part1_auto["rule"] == "R1b"
    assert res_pa_part1_auto["permissionDecision"] == "deny"
    assert res_pa_part1_auto["escalation"]["reason_code"] == "CHARTER_AMENDMENT_NEEDED"

    # R1b: PA editing PROGRAM.md is blocked
    res_pa_prog = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-pa",
            "toolCall": {
                "name": "edit_file",
                "args": {
                    "Path": prog_rel,
                    "Target": "Charter body.",
                    "Replacement": "PA edit.",
                },
            },
        },
        repo_root=tmp_repo,
    )
    assert res_pa_prog["rule"] == "R1b"
    assert res_pa_prog["permissionDecision"] == "deny"

    # R1b: PA authoring WORKORDER.md with allowed_files outside charter.allowed_modules
    wo_rel = str(wo_path.relative_to(tmp_repo))
    res_pa_wo_outside = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-pa",
            "toolCall": {
                "name": "edit_file",
                "args": {
                    "Path": wo_rel,
                    "Target": "- src/allowed.py",
                    "Replacement": "- outside_module/forbidden.py",
                },
            },
        },
        repo_root=tmp_repo,
    )
    assert res_pa_wo_outside["rule"] == "R1b"
    assert res_pa_wo_outside["permissionDecision"] == "deny"
    assert res_pa_wo_outside["escalation"]["requested_files"] == ["outside_module/forbidden.py"]

    # Switch to monitored mode and verify R1b returns "ask"
    with StateDB(ws_dir / ".state" / "state.db") as db:
        db.set_config("execution_mode", "monitored")
    res_pa_part1_mon = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-pa",
            "toolCall": {
                "name": "edit_file",
                "args": {
                    "Path": proj_rel,
                    "Target": "Charter scope details.",
                    "Replacement": "Tampered charter scope.",
                },
            },
        },
        repo_root=tmp_repo,
    )
    assert res_pa_part1_mon["rule"] == "R1b"
    assert res_pa_part1_mon["permissionDecision"] == "ask"


def test_pre_tool_gate_r2_plan_approval_gate(tmp_repo: Path, daemon_home: Path) -> None:
    """Verify R2 (PA invoke_subagent Plan Approval Gate) across monitored and autonomous modes."""
    ws_dir, proj_path, wo_path = _setup_enrolled_workspace(
        tmp_repo,
        daemon_home,
        mode="monitored",
        pr_status=schemas.PRState.PLANNED,
        auto_approve_pr_plans=False,
    )

    invoke_payload: dict[str, Any] = {
        "conversationId": "conv-pa",
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "TypeName": "pa-engineer",
                "Role": "WO-02.1 Worker",
                "Prompt": "PA_ROLE: engineer\nPR_ID: PR-02\nWO_ID: WO-02.1\nExecute WO-02.1.",
            },
        },
    }

    # 1. Monitored mode with status=PLANNED -> ask
    res_mon = pre_tool_gate.evaluate_pre_tool(invoke_payload, repo_root=tmp_repo)
    assert res_mon["rule"] == "R2"
    assert res_mon["permissionDecision"] == "ask"

    # Invoking pa-auditor is not blocked by R2
    auditor_payload: dict[str, Any] = {
        "conversationId": "conv-pa",
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "TypeName": "pa-auditor",
                "Role": "Cold-Firewall Auditor",
                "Prompt": "PA_ROLE: auditor\nPR_ID: PR-02\nAudit PR-02.",
            },
        },
    }
    assert (
        pre_tool_gate.evaluate_pre_tool(auditor_payload, repo_root=tmp_repo)["permissionDecision"]
        == "allow"
    )

    # 2. Autonomous mode with auto_approve_pr_plans=false -> deny + enqueue plan_approval
    with StateDB(ws_dir / ".state" / "state.db") as db:
        db.set_config("execution_mode", "autonomous")
        db.set_config("auto_approve_pr_plans", "false")

    res_auto_deny = pre_tool_gate.evaluate_pre_tool(invoke_payload, repo_root=tmp_repo)
    assert res_auto_deny["rule"] == "R2"
    assert res_auto_deny["permissionDecision"] == "deny"
    with StateDB(ws_dir / ".state" / "state.db") as db:
        attn = db.list_open(pr_id="PR-02")
        assert any(i["kind"] == "plan_approval" for i in attn)

    # 3. Autonomous mode with auto_approve_pr_plans=true and valid plan -> allow + auto-approve
    # Clear spec_hash on wo_path first to verify R2 stamps it on auto-approval
    wo_doc = schemas.load_workorder(wo_path)
    wo_doc.spec.spec_hash = None
    wo_path.write_text(schemas.dump_document(wo_doc.spec, wo_doc.sections), encoding="utf-8")

    with StateDB(ws_dir / ".state" / "state.db") as db:
        db.set_config("auto_approve_pr_plans", "true")

    res_auto_allow = pre_tool_gate.evaluate_pre_tool(invoke_payload, repo_root=tmp_repo)
    assert res_auto_allow["rule"] == "R2"
    assert res_auto_allow["permissionDecision"] == "allow"
    assert res_auto_allow["auto_approve_plan"] is True

    updated_proj = schemas.load_project(proj_path)
    assert updated_proj.spec.status == schemas.PRState.APPROVED
    assert updated_proj.spec.approved_at is not None

    updated_wo = schemas.load_workorder(wo_path)
    assert updated_wo.spec.spec_hash is not None
    assert schemas.verify_spec_hash(updated_wo) is True


def test_pre_tool_gate_r3_r4_worker_boundary_and_traversal(
    tmp_repo: Path, daemon_home: Path, tmp_path: Path
) -> None:
    """Verify R3 (allowed/forbidden/spec_hash/realpath traversal) and R4 (git/gh lockdown)."""
    ws_dir, _, wo_path = _setup_enrolled_workspace(
        tmp_repo, daemon_home, mode="autonomous"
    )

    # 1. Worker editing allowed file -> allow
    res_allowed = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "src/allowed.py", "Content": "print('ok')\n"},
            },
        },
        repo_root=tmp_repo,
    )
    assert res_allowed["permissionDecision"] == "allow"

    # 2. Worker editing file outside allowed_files -> deny + structural_failures incremented + escalation
    res_outside = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "src/disallowed.py", "Content": "print('no')\n"},
            },
        },
        repo_root=tmp_repo,
    )
    assert res_outside["rule"] == "R3"
    assert res_outside["permissionDecision"] == "deny"
    assert res_outside["escalation"]["reason_code"] == "BOUNDARY_EXPANSION_NEEDED"
    with StateDB(ws_dir / ".state" / "state.db") as db:
        sess = db.get_session("conv-eng")
        assert sess is not None
        assert sess["structural_failures"] == 1
        assert len(db.open_escalations(wo_id="WO-02.1")) == 1

    # 3. Worker editing file matching forbidden_files inside an allowed directory (src/sub/secret.py)
    res_forbidden = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "src/sub/secret.py", "Content": "secret = 1\n"},
            },
        },
        repo_root=tmp_repo,
    )
    assert res_forbidden["rule"] == "R3"
    assert res_forbidden["permissionDecision"] == "deny"

    # 4. Path traversal (../) outside repo_root -> blocked with PATH_TRAVERSAL_BLOCKED
    res_traversal = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "../../outside_escape.py", "Content": "pwned\n"},
            },
        },
        repo_root=tmp_repo,
    )
    assert res_traversal["rule"] == "R3"
    assert res_traversal["permissionDecision"] == "deny"
    assert res_traversal["escalation"]["reason_code"] == "PATH_TRAVERSAL_BLOCKED"

    # 5. Symlink escape inside allowed directory pointing outside repo_root and to forbidden SPEC.md
    src_sub = tmp_repo / "src" / "sub"
    src_sub.mkdir(parents=True, exist_ok=True)
    outside_file = tmp_path / "outside_target.txt"
    outside_file.write_text("secret\n", encoding="utf-8")
    symlink_outside = src_sub / "evil_outside.py"
    symlink_outside.symlink_to(outside_file)

    res_sym_out = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "src/sub/evil_outside.py", "Content": "overwrite\n"},
            },
        },
        repo_root=tmp_repo,
    )
    assert res_sym_out["rule"] == "R3"
    assert res_sym_out["permissionDecision"] == "deny"
    assert res_sym_out["escalation"]["reason_code"] == "PATH_TRAVERSAL_BLOCKED"

    spec_md = tmp_repo / "SPEC.md"
    spec_md.write_text("# Spec\n", encoding="utf-8")
    symlink_spec = src_sub / "evil_spec.py"
    symlink_spec.symlink_to(spec_md)

    res_sym_spec = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "src/sub/evil_spec.py", "Content": "overwrite spec\n"},
            },
        },
        repo_root=tmp_repo,
    )
    assert res_sym_spec["rule"] == "R3"
    assert res_sym_spec["permissionDecision"] == "deny"
    assert res_sym_spec["escalation"]["reason_code"] == "BOUNDARY_EXPANSION_NEEDED"

    # 6. Worker editing Part II of bound WORKORDER.md preserving spec_hash -> allow
    wo_rel = str(wo_path.relative_to(tmp_repo))
    res_wo_part2 = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {
                "name": "edit_file",
                "args": {
                    "Path": wo_rel,
                    "Target": "_Pending._",
                    "Replacement": "Completed all items.",
                },
            },
        },
        repo_root=tmp_repo,
    )
    assert res_wo_part2["permissionDecision"] == "allow"

    # 7. Worker tampering with Part I of bound WORKORDER.md -> blocked with SPEC_LOCK_VIOLATION
    res_wo_tamper = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {
                "name": "edit_file",
                "args": {
                    "Path": wo_rel,
                    "Target": "Objective text.",
                    "Replacement": "Modified Part I objective.",
                },
            },
        },
        repo_root=tmp_repo,
    )
    assert res_wo_tamper["rule"] == "R3"
    assert res_wo_tamper["permissionDecision"] == "deny"
    assert res_wo_tamper["escalation"]["reason_code"] == "SPEC_LOCK_VIOLATION"

    # 8. R4: Worker git/gh lockdown in both monitored and autonomous modes
    for mode in ("monitored", "autonomous"):
        with StateDB(ws_dir / ".state" / "state.db") as db:
            db.set_config("execution_mode", mode)

        for bad_cmd in (
            "git push origin HEAD",
            "git checkout -b feat/rogue",
            "git switch main",
            "git branch -D main",
            "git rebase main",
            "git merge feat/other",
            "git reset --hard HEAD~1",
            "gh pr create --title test",
            "gh issue create --title test",
        ):
            res_r4 = pre_tool_gate.evaluate_pre_tool(
                {
                    "conversationId": "conv-eng",
                    "toolCall": {"name": "run_command", "args": {"CommandLine": bad_cmd}},
                },
                repo_root=tmp_repo,
            )
            assert res_r4["rule"] == "R4", f"Expected R4 for {bad_cmd}"
            assert res_r4["permissionDecision"] == "deny"

        for ok_cmd in (
            "git status",
            "git diff",
            "git add src/allowed.py",
            'git commit -m "WO-02.1: test git push guard"',
            "./.venv/bin/pytest",
        ):
            res_ok = pre_tool_gate.evaluate_pre_tool(
                {
                    "conversationId": "conv-eng",
                    "toolCall": {"name": "run_command", "args": {"CommandLine": ok_cmd}},
                },
                repo_root=tmp_repo,
            )
            assert res_ok["permissionDecision"] == "allow", f"Unexpected block for {ok_cmd}"


def test_pre_tool_gate_r5_auditor_and_r6_graduation(
    tmp_repo: Path, daemon_home: Path
) -> None:
    """Verify R5 (Auditor read-only lockdown) and R6 (Graduation audit gate)."""
    ws_dir, proj_path, _ = _setup_enrolled_workspace(
        tmp_repo, daemon_home, mode="monitored"
    )

    # 1. R5: Auditor blocked on file mutation tools, invoke_subagent, and mutating shell commands
    for mode in ("monitored", "autonomous"):
        with StateDB(ws_dir / ".state" / "state.db") as db:
            db.set_config("execution_mode", mode)

        res_file = pre_tool_gate.evaluate_pre_tool(
            {
                "conversationId": "conv-auditor",
                "toolCall": {
                    "name": "write_file",
                    "args": {"Path": "src/allowed.py", "Content": "x = 1\n"},
                },
            },
            repo_root=tmp_repo,
        )
        assert res_file["rule"] == "R5"
        assert res_file["permissionDecision"] == "deny"

        res_sub = pre_tool_gate.evaluate_pre_tool(
            {
                "conversationId": "conv-auditor",
                "toolCall": {"name": "invoke_subagent", "args": {"TypeName": "self"}},
            },
            repo_root=tmp_repo,
        )
        assert res_sub["rule"] == "R5"
        assert res_sub["permissionDecision"] == "deny"

        for bad_auditor_cmd in (
            "git commit -m 'audit'",
            "rm -rf src",
            "sed -i 's/a/b/' README.md",
            "echo hacked > README.md",
        ):
            res_cmd = pre_tool_gate.evaluate_pre_tool(
                {
                    "conversationId": "conv-auditor",
                    "toolCall": {"name": "run_command", "args": {"CommandLine": bad_auditor_cmd}},
                },
                repo_root=tmp_repo,
            )
            assert res_cmd["rule"] == "R5"
            assert res_cmd["permissionDecision"] == "deny"

        for ok_auditor_cmd in (
            "git diff main...HEAD",
            "gh pr diff 12",
            "pytest -q 2>&1",
            "pa pr post-audit PR-02 --verdict APPROVED",
        ):
            res_ok = pre_tool_gate.evaluate_pre_tool(
                {
                    "conversationId": "conv-auditor",
                    "toolCall": {"name": "run_command", "args": {"CommandLine": ok_auditor_cmd}},
                },
                repo_root=tmp_repo,
            )
            assert res_ok["permissionDecision"] == "allow"

    # 2. R6: pa pr graduate / gh pr merge without matching APPROVED AuditReport
    with StateDB(ws_dir / ".state" / "state.db") as db:
        db.set_config("execution_mode", "monitored")

    res_r6_mon = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-pa",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "pa pr graduate PR-02"}},
        },
        repo_root=tmp_repo,
    )
    assert res_r6_mon["rule"] == "R6"
    assert res_r6_mon["permissionDecision"] == "ask"

    with StateDB(ws_dir / ".state" / "state.db") as db:
        db.set_config("execution_mode", "autonomous")

    res_r6_auto = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-pa",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "gh pr merge 42 --squash"}},
        },
        repo_root=tmp_repo,
    )
    assert res_r6_auto["rule"] == "R6"
    assert res_r6_auto["permissionDecision"] == "deny"

    # Write an APPROVED AuditReport matching current HEAD SHA and verify R6 allows graduation
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    audit_spec = schemas.AuditReport(
        pr_id="PR-02",
        audit_round=1,
        head_sha=head_sha,
        verdict="APPROVED",
        findings=[],
    )
    audit_path = proj_path.parent / "AUDIT-round-1.md"
    audit_path.write_text(
        schemas.dump_document(audit_spec, [schemas.Section("## Audit Summary", "LGTM.\n")]),
        encoding="utf-8",
    )

    res_r6_approved = pre_tool_gate.evaluate_pre_tool(
        {
            "conversationId": "conv-pa",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "pa pr graduate PR-02"}},
        },
        repo_root=tmp_repo,
    )
    assert res_r6_approved["permissionDecision"] == "allow"

    # Subprocess stdin/stdout round-trip on enrolled repo
    script_path = Path(pre_tool_gate.__file__).resolve()
    env = dict(os.environ)
    sub_res = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps(
            {
                "workspacePaths": [str(tmp_repo)],
                "conversationId": "conv-eng",
                "toolCall": {"name": "run_command", "args": {"CommandLine": "git push"}},
            }
        ),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert sub_res.returncode == 0
    sub_json = json.loads(sub_res.stdout.strip())
    assert sub_json["rule"] == "R4"
    assert sub_json["permissionDecision"] == "deny"


# ---------------------------------------------------------------------------
# WO-02.3: post_tool_receipt.py and pa wo verify tests
# ---------------------------------------------------------------------------


def test_post_tool_receipt_unenrolled_fast_exit_and_import_purity(
    tmp_path: Path, daemon_home: Path
) -> None:
    """Verify post_tool_receipt.py unenrolled fast-exit (<1ms) and zero pydantic/yaml/schemas imports."""
    _ = daemon_home
    unenrolled = tmp_path / "unenrolled-post-repo"
    unenrolled.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "workspacePaths": [str(unenrolled)],
        "conversationId": "conv-eng",
        "toolCall": {"name": "write_file", "args": {"Path": "src/foo.py", "Content": "x = 1\n"}},
    }

    # Warm-up call
    assert post_tool_receipt.evaluate_post_tool(payload) == {}

    iterations = 25
    start = time.perf_counter()
    for _ in range(iterations):
        res = post_tool_receipt.evaluate_post_tool(payload)
        assert res == {}
    elapsed_ms = ((time.perf_counter() - start) * 1000.0) / iterations
    assert elapsed_ms < 1.0, f"Unenrolled fast-exit took {elapsed_ms:.3f} ms (limit < 1.0 ms)"

    # Verify import purity on the unenrolled path in a fresh subprocess
    script_path = Path(post_tool_receipt.__file__).resolve()
    scripts_dir = str(script_path.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = scripts_dir
    code = (
        "import sys, post_tool_receipt\n"
        f"res = post_tool_receipt.evaluate_post_tool({{'workspacePaths': [{str(unenrolled)!r}]}})\n"
        "assert res == {}\n"
        "assert 'pydantic' not in sys.modules\n"
        "assert 'yaml' not in sys.modules\n"
        "assert 'schemas' not in sys.modules\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, f"Import purity failed:\n{proc.stdout}\n{proc.stderr}"

    # Verify CLI subprocess execution on unenrolled repo outputs {} and exits 0
    cli_proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert cli_proc.returncode == 0
    assert json.loads(cli_proc.stdout.strip()) == {}


def test_compute_tree_hash_determinism_and_exclusions(tmp_repo: Path) -> None:
    """Verify compute_tree_hash determinism, sensitivity to byte edits, and exclusion of .git/.state/outside."""
    src_dir = tmp_repo / "src" / "sub"
    src_dir.mkdir(parents=True, exist_ok=True)
    f_allowed = tmp_repo / "src" / "allowed.py"
    f_sub = src_dir / "helper.py"
    f_allowed.write_text("def a():\n    return 1\n", encoding="utf-8")
    f_sub.write_text("def b():\n    return 2\n", encoding="utf-8")

    allowed = ["src/allowed.py", "src/sub/"]
    h1 = post_tool_receipt.compute_tree_hash(tmp_repo, allowed)
    h2 = post_tool_receipt.compute_tree_hash(tmp_repo, list(reversed(allowed)))
    assert len(h1) == 64
    assert h1 == h2

    # Modifying a file outside allowed_files or inside .state/ or .git/ does not change tree_hash
    (tmp_repo / "src" / "outside.py").write_text("outside = True\n", encoding="utf-8")
    state_dir = tmp_repo / "src" / "sub" / ".state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "ephemeral.db").write_bytes(b"sqlite-bytes")
    assert post_tool_receipt.compute_tree_hash(tmp_repo, allowed) == h1

    # Modifying a single byte in an allowed file changes tree_hash
    f_allowed.write_text("def a():\n    return 2\n", encoding="utf-8")
    h3 = post_tool_receipt.compute_tree_hash(tmp_repo, allowed)
    assert h3 != h1


def test_post_tool_receipt_lifecycle_stamping_invalidation_and_attempts(
    tmp_repo: Path, daemon_home: Path
) -> None:
    """Verify PostToolUse receipt stamping, invalidation on edit/command, and attempt/structural counters."""
    ws_dir, _, _ = _setup_enrolled_workspace(tmp_repo, daemon_home, mode="autonomous")
    db_file = ws_dir / ".state" / "state.db"

    allowed_file = tmp_repo / "src" / "allowed.py"
    allowed_file.parent.mkdir(parents=True, exist_ok=True)
    allowed_file.write_text("x = 1\n", encoding="utf-8")

    # 1. Run verification_command ("pytest") with exitCode=0 -> stamps valid=1 receipt
    res_pass = post_tool_receipt.evaluate_post_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "./.venv/bin/pytest -q"}},
            "exitCode": 0,
            "output": "Command exited with code 0.\n1 passed in 0.02s\n",
        },
        repo_root=tmp_repo,
    )
    assert res_pass == {}

    expected_hash = post_tool_receipt.compute_tree_hash(
        tmp_repo, ["src/allowed.py", "src/sub/"]
    )
    with StateDB(db_file) as db:
        rcpt = db.latest_valid_receipt("WO-02.1", expected_hash)
        assert rcpt is not None
        assert rcpt["valid"] == 1
        assert rcpt["receipt_id"] == f"rcpt_{expected_hash[:12]}"
        assert rcpt["exit_code"] == 0

    # 2. Subsequent file edit invalidates the receipt (valid=0)
    allowed_file.write_text("x = 2\n", encoding="utf-8")
    post_tool_receipt.evaluate_post_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {
                "name": "edit_file",
                "args": {"Path": "src/allowed.py", "Target": "x = 1", "Replacement": "x = 2"},
            },
        },
        repo_root=tmp_repo,
    )
    with StateDB(db_file) as db:
        assert db.latest_valid_receipt("WO-02.1") is None

    # 3. Re-stamp receipt, then invalidate via mutating shell command (redirect / rm)
    post_tool_receipt.evaluate_post_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "pytest"}},
            "output": "Command exited with code 0.\n",
        },
        repo_root=tmp_repo,
    )
    with StateDB(db_file) as db:
        assert db.latest_valid_receipt("WO-02.1") is not None

    # Read-only shell command does NOT invalidate receipt
    post_tool_receipt.evaluate_post_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git status --short"}},
            "exitCode": 0,
        },
        repo_root=tmp_repo,
    )
    with StateDB(db_file) as db:
        assert db.latest_valid_receipt("WO-02.1") is not None

    # Mutating shell command (redirect) invalidates receipt
    post_tool_receipt.evaluate_post_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "echo 'x = 3' > src/allowed.py"},
            },
            "exitCode": 0,
        },
        repo_root=tmp_repo,
    )
    with StateDB(db_file) as db:
        assert db.latest_valid_receipt("WO-02.1") is None

    # 4. Verification failure (normal test assertion error) -> increments attempt_num only
    post_tool_receipt.evaluate_post_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "pytest"}},
            "exitCode": 1,
            "output": "FAILED test_foo.py - AssertionError: assert 2 == 3",
        },
        repo_root=tmp_repo,
    )
    with StateDB(db_file) as db:
        sess = db.get_session("conv-eng")
        assert sess is not None
        assert sess["attempt_num"] == 2
        assert sess["structural_failures"] == 0
        assert db.latest_valid_receipt("WO-02.1") is None

    # 5. Verification failure with structural blocker signature -> increments attempt_num AND structural_failures
    post_tool_receipt.evaluate_post_tool(
        {
            "conversationId": "conv-eng",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "pytest"}},
            "toolResult": {
                "exitCode": 1,
                "stderr": "Error: Exclusive hardware is currently tied to another process.",
            },
        },
        repo_root=tmp_repo,
    )
    with StateDB(db_file) as db:
        sess2 = db.get_session("conv-eng")
        assert sess2 is not None
        assert sess2["attempt_num"] == 3
        assert sess2["structural_failures"] == 1


def test_pa_wo_verify_end_to_end(
    tmp_repo: Path, daemon_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify `pa wo verify <WO-ID>` scope hygiene, spec_hash check, test execution, and git commit."""
    ws_dir, proj_path, wo_path = _setup_enrolled_workspace(
        tmp_repo, daemon_home, mode="autonomous"
    )
    (ws_dir / ".gitignore").write_text(".state/\n", encoding="utf-8")

    # Configure verification_command to a fast python assertion on src/allowed.py
    wo_doc = schemas.load_workorder(wo_path)
    wo_doc.spec.verification_command = (
        f'{sys.executable} -c "import pathlib; '
        "assert 'VALUE = 42' in pathlib.Path('src/allowed.py').read_text(encoding='utf-8'); "
        "print('1 passed in 0.01s')\""
    )
    wo_doc.spec.spec_hash = schemas.compute_spec_hash(wo_doc.spec, wo_doc.sections)
    wo_path.write_text(schemas.dump_document(wo_doc.spec, wo_doc.sections), encoding="utf-8")

    # Commit the baseline workspace files so git status starts clean
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initialize workspace for WO-02.1"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
    )

    allowed_file = tmp_repo / "src" / "allowed.py"
    allowed_file.parent.mkdir(parents=True, exist_ok=True)
    allowed_file.write_text("VALUE = 0\n", encoding="utf-8")

    # 1. Scope hygiene failure: untracked file outside allowed_files -> exit 1
    rogue_file = tmp_repo / "src" / "rogue.py"
    rogue_file.write_text("rogue = True\n", encoding="utf-8")
    capsys.readouterr()
    rc_scope = pa_cli.main(["wo", "verify", "WO-02.1", "--path", str(tmp_repo)])
    assert rc_scope == 1
    scope_err = capsys.readouterr().err
    assert "Scope hygiene check failed" in scope_err
    assert "src/rogue.py" in scope_err
    rogue_file.unlink()

    # 2. Tampered WORKORDER.md Part I spec_hash -> exit 1
    orig_wo_text = wo_path.read_text(encoding="utf-8")
    wo_path.write_text(
        orig_wo_text.replace("Objective text.", "Tampered objective text."),
        encoding="utf-8",
    )
    capsys.readouterr()
    rc_tamper = pa_cli.main(["wo", "verify", "WO-02.1", "--path", str(tmp_repo)])
    assert rc_tamper == 1
    assert "spec_hash verification failed" in capsys.readouterr().err
    wo_path.write_text(orig_wo_text, encoding="utf-8")

    # 3. Failing verification_command -> exit 1
    capsys.readouterr()
    rc_fail_ver = pa_cli.main(["wo", "verify", "WO-02.1", "--path", str(tmp_repo)])
    assert rc_fail_ver == 1
    assert "verification_command failed" in capsys.readouterr().err

    # 4. Passing verification_command & clean scope -> exit 0, stamps receipt, updates docs, commits
    allowed_file.write_text("VALUE = 42\n", encoding="utf-8")
    capsys.readouterr()
    rc_ok = pa_cli.main(["wo", "verify", "WO-02.1", "--path", str(tmp_repo)])
    assert rc_ok == 0

    # Working tree must be completely clean after pa wo verify
    status_after = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert status_after == "", f"Expected clean git status, got:\n{status_after}"

    expected_hash = post_tool_receipt.compute_tree_hash(
        tmp_repo, ["src/allowed.py", "src/sub/"]
    )
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    commit_body = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert "WO-02.1: Implement src/allowed.py" in commit_body
    assert "PA-WorkOrder: WO-02.1" in commit_body
    assert f"PA-Verified-Hash: {expected_hash}" in commit_body

    # Check verification_receipts in state.db
    with StateDB(ws_dir / ".state" / "state.db") as db:
        rcpt = db.latest_valid_receipt("WO-02.1", expected_hash)
        assert rcpt is not None
        assert rcpt["valid"] == 1
        assert rcpt["receipt_id"] == f"rcpt_{expected_hash[:12]}"
        assert rcpt["git_head_sha"] == head_sha

    # Check WORKORDER.md Part II and spec_hash preservation
    verified_wo = schemas.load_workorder(wo_path)
    assert schemas.verify_spec_hash(wo_path) is True
    assert verified_wo.spec.status == schemas.WorkOrderStatus.COMPLETED
    assert verified_wo.spec.completion is not None
    assert verified_wo.spec.completion.status == schemas.WorkOrderStatus.COMPLETED
    assert verified_wo.spec.completion.receipt_id == f"rcpt_{expected_hash[:12]}"
    assert verified_wo.spec.completion.files_modified == ["src/allowed.py"]
    assert "1 passed in 0.01s" in verified_wo.spec.completion.verification_summary

    # Check PROJECT.md update and charter_hash preservation
    verified_proj = schemas.load_project(proj_path)
    assert schemas.verify_charter_hash(proj_path) is True
    wo_row = verified_proj.spec.work_orders[0]
    assert wo_row.id == "WO-02.1"
    assert wo_row.status == schemas.WorkOrderStatus.COMPLETED
    assert wo_row.attempts >= 1


# ---------------------------------------------------------------------------
# WO-02.4: stop_gate.py tests (Fast-exit, Two-Tier Retry Ceiling, Case A/B, Auditor)
# ---------------------------------------------------------------------------


def test_stop_gate_unenrolled_fast_exit_and_import_purity(
    tmp_path: Path, daemon_home: Path
) -> None:
    """Verify stop_gate.py unenrolled fast-exit (<1ms) and zero pydantic/yaml/schemas imports."""
    _ = daemon_home
    unenrolled = tmp_path / "unenrolled-stop-repo"
    unenrolled.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "workspacePaths": [str(unenrolled)],
        "conversationId": "conv-eng",
        "terminationReason": "NO_TOOL_CALL",
    }

    # Warm-up call
    assert stop_gate.evaluate_stop(payload) == {}

    iterations = 25
    start = time.perf_counter()
    for _ in range(iterations):
        res = stop_gate.evaluate_stop(payload)
        assert res == {}
    elapsed_ms = ((time.perf_counter() - start) * 1000.0) / iterations
    assert elapsed_ms < 1.0, f"Unenrolled fast-exit took {elapsed_ms:.3f} ms (limit < 1.0 ms)"

    # Verify import purity on the unenrolled path in a fresh subprocess
    script_path = Path(stop_gate.__file__).resolve()
    scripts_dir = str(script_path.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = scripts_dir
    code = (
        "import sys, stop_gate\n"
        f"res = stop_gate.evaluate_stop({{'workspacePaths': [{str(unenrolled)!r}]}})\n"
        "assert res == {}\n"
        "assert 'pydantic' not in sys.modules\n"
        "assert 'yaml' not in sys.modules\n"
        "assert 'schemas' not in sys.modules\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, f"Import purity failed:\n{proc.stdout}\n{proc.stderr}"

    # Verify CLI subprocess execution on unenrolled repo outputs {} and exits 0
    cli_proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert cli_proc.returncode == 0
    assert json.loads(cli_proc.stdout.strip()) == {}


def test_stop_gate_two_tier_retry_fast_fail_structural_and_transcript_errors(
    tmp_repo: Path, daemon_home: Path
) -> None:
    """Verify fast-fail structural escalation on structural_failures >= 2 or 3 consecutive error steps."""
    ws_dir, _, wo_path = _setup_enrolled_workspace(tmp_repo, daemon_home, mode="autonomous")
    db_file = ws_dir / ".state" / "state.db"

    # 1. structural_failures >= 2 (at attempt_num == 1) -> fast-fails immediately with {}
    with StateDB(db_file) as db:
        db.update_session("conv-eng", attempt_num=1, structural_failures=2)

    res_struct = stop_gate.evaluate_stop(
        {"conversationId": "conv-eng", "terminationReason": "NO_TOOL_CALL"},
        repo_root=tmp_repo,
    )
    assert res_struct == {}

    wo_after = schemas.load_workorder(wo_path)
    assert wo_after.spec.status == schemas.WorkOrderStatus.ESCALATED_TO_PA
    assert wo_after.spec.completion is not None
    assert wo_after.spec.completion.status == schemas.WorkOrderStatus.ESCALATED_TO_PA
    assert wo_after.spec.completion.escalation_request is not None
    assert wo_after.spec.completion.escalation_request.reason_code == "STRUCTURAL_FAST_FAIL"
    assert schemas.verify_spec_hash(wo_path) is True

    with StateDB(db_file) as db:
        escs = db.open_escalations(wo_id="WO-02.1")
        assert len(escs) == 1
        assert escs[0]["reason_code"] == "STRUCTURAL_FAST_FAIL"
        assert escs[0]["blocker_type"] == "structural"
        attn = db.list_open(pr_id="PR-02")
        assert any("Structural blocker on WO-02.1" in i["title"] for i in attn)

    # 2. Reset WORKORDER.md to PENDING and structural_failures=0, but provide a transcript with 3 consecutive ERROR_MESSAGE steps
    wo_after.spec.status = schemas.WorkOrderStatus.PENDING
    wo_after.spec.completion = None
    wo_path.write_text(
        schemas.dump_document(wo_after.spec, wo_after.sections),
        encoding="utf-8",
    )
    with StateDB(db_file) as db:
        db.update_session("conv-eng", attempt_num=1, structural_failures=0)

    transcript_file = tmp_repo / "transcript_errors.jsonl"
    transcript_steps = [
        {"step_index": 0, "type": "USER_INPUT", "status": "DONE", "content": "Start work"},
        {"step_index": 1, "type": "ERROR_MESSAGE", "status": "ERROR", "content": "Err 1"},
        {"step_index": 2, "type": "CORTEX_STEP_TYPE_ERROR_MESSAGE", "status": "DONE", "content": "Err 2"},
        {"step_index": 3, "type": "PLANNER_RESPONSE", "status": "ERROR", "content": "Err 3"},
    ]
    transcript_file.write_text(
        "\n".join(json.dumps(s) for s in transcript_steps) + "\n",
        encoding="utf-8",
    )

    res_err_steps = stop_gate.evaluate_stop(
        {
            "conversationId": "conv-eng",
            "terminationReason": "NO_TOOL_CALL",
            "transcriptPath": f"file://{transcript_file}",
        },
        repo_root=tmp_repo,
    )
    assert res_err_steps == {}

    wo_after_err = schemas.load_workorder(wo_path)
    assert wo_after_err.spec.status == schemas.WorkOrderStatus.ESCALATED_TO_PA
    with StateDB(db_file) as db:
        escs2 = db.open_escalations(wo_id="WO-02.1")
        assert len(escs2) == 2


def test_stop_gate_productive_retries_and_bounded_continuation_ceiling(
    tmp_repo: Path, daemon_home: Path
) -> None:
    """Verify productive retries (1..4 -> continue) and 5-attempt ceiling (5 -> BLOCKED + pa-debugger)."""
    ws_dir, _, wo_path = _setup_enrolled_workspace(tmp_repo, daemon_home, mode="autonomous")
    db_file = ws_dir / ".state" / "state.db"

    # Calling evaluate_stop repeatedly starting at attempt_num=1 must return "continue" 4 times
    # (1->2, 2->3, 3->4, 4->5) and on the 5th call (attempt_num=5) terminate with {} and BLOCKED.
    for expected_att in (1, 2, 3, 4):
        res = stop_gate.evaluate_stop(
            {"conversationId": "conv-eng", "terminationReason": "NO_TOOL_CALL"},
            repo_root=tmp_repo,
        )
        assert res["decision"] == "continue"
        assert f"(attempt {expected_att}/5)" in res["reason"]
        assert "missing verification receipt" in res["reason"]
        with StateDB(db_file) as db:
            sess = db.get_session("conv-eng")
            assert sess is not None
            assert sess["attempt_num"] == expected_att + 1

    # 5th call (attempt_num == 5): hits productive ceiling, marks BLOCKED, enqueues pa-debugger, returns {}
    res_ceiling = stop_gate.evaluate_stop(
        {"conversationId": "conv-eng", "terminationReason": "NO_TOOL_CALL"},
        repo_root=tmp_repo,
    )
    assert res_ceiling == {}

    wo_blocked = schemas.load_workorder(wo_path)
    assert wo_blocked.spec.status == schemas.WorkOrderStatus.BLOCKED
    assert wo_blocked.spec.completion is not None
    assert wo_blocked.spec.completion.status == schemas.WorkOrderStatus.BLOCKED
    assert schemas.verify_spec_hash(wo_path) is True

    with StateDB(db_file) as db:
        escs = db.open_escalations(wo_id="WO-02.1")
        assert len(escs) == 1
        assert escs[0]["target_role"] == "debugger"
        assert escs[0]["reason_code"] == "MAX_ATTEMPTS_EXCEEDED"
        attn = db.list_open(pr_id="PR-02")
        assert any(
            i["kind"] == "debugger_escalation" and "🔬 [Debug WO-02.1]" in i["title"]
            for i in attn
        )


def test_stop_gate_case_a_and_case_b_invariants(
    tmp_repo: Path, daemon_home: Path
) -> None:
    """Verify Case A (explicit escalation) and Case B (receipt, git clean/commit, CompletionReport)."""
    ws_dir, _, wo_path = _setup_enrolled_workspace(tmp_repo, daemon_home, mode="autonomous")
    (ws_dir / ".gitignore").write_text(".state/\n", encoding="utf-8")
    db_file = ws_dir / ".state" / "state.db"

    # 1. Case A with missing CompletionReport -> returns "continue" and increments attempt_num
    wo_doc = schemas.load_workorder(wo_path)
    wo_doc.spec.status = schemas.WorkOrderStatus.ESCALATED_TO_PA
    wo_doc.spec.completion = None
    wo_path.write_text(schemas.dump_document(wo_doc.spec, wo_doc.sections), encoding="utf-8")

    res_case_a_incomplete = stop_gate.evaluate_stop(
        {"conversationId": "conv-eng", "terminationReason": "NO_TOOL_CALL"},
        repo_root=tmp_repo,
    )
    assert res_case_a_incomplete["decision"] == "continue"
    assert "lacks a valid CompletionReport/escalation_request" in res_case_a_incomplete["reason"]

    # 2. Case A with valid escalation_request -> records escalation in state.db and returns {}
    wo_doc.spec.completion = schemas.CompletionReport(
        status=schemas.WorkOrderStatus.ESCALATED_TO_PA,
        attempt_num=2,
        verification_summary="Blocked by boundary restriction on src/extra.py.",
        escalation_request=schemas.EscalationRequest(
            blocker_type="boundary",
            reason_code="BOUNDARY_EXPANSION_NEEDED",
            target_role="pa",
            requested_files=["src/extra.py"],
            summary="Need src/extra.py added to allowed_files.",
        ),
    )
    wo_path.write_text(schemas.dump_document(wo_doc.spec, wo_doc.sections), encoding="utf-8")

    res_case_a_ok = stop_gate.evaluate_stop(
        {"conversationId": "conv-eng", "terminationReason": "NO_TOOL_CALL"},
        repo_root=tmp_repo,
    )
    assert res_case_a_ok == {}
    with StateDB(db_file) as db:
        escs = db.open_escalations(wo_id="WO-02.1")
        assert len(escs) == 1
        assert escs[0]["reason_code"] == "BOUNDARY_EXPANSION_NEEDED"
        assert json.loads(escs[0]["requested_files_json"]) == ["src/extra.py"]

    # 3. Reset to Case B and test individual failure modes before full `pa wo verify` success
    with StateDB(db_file) as db:
        db.update_session("conv-eng", attempt_num=1, structural_failures=0)

    wo_doc = schemas.load_workorder(wo_path)
    wo_doc.spec.status = schemas.WorkOrderStatus.PENDING
    wo_doc.spec.completion = None
    wo_doc.spec.verification_command = (
        f'{sys.executable} -c "import pathlib; '
        "assert 'READY = True' in pathlib.Path('src/allowed.py').read_text(encoding='utf-8')\""
    )
    wo_doc.spec.spec_hash = schemas.compute_spec_hash(wo_doc.spec, wo_doc.sections)
    wo_path.write_text(schemas.dump_document(wo_doc.spec, wo_doc.sections), encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Baseline before WO-02.1"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
    )

    allowed_file = tmp_repo / "src" / "allowed.py"
    allowed_file.parent.mkdir(parents=True, exist_ok=True)
    allowed_file.write_text("READY = True\n", encoding="utf-8")

    # Run `pa wo verify WO-02.1` so all 3 Case B invariants are satisfied
    rc_verify = pa_cli.main(["wo", "verify", "WO-02.1", "--path", str(tmp_repo)])
    assert rc_verify == 0

    # Case B success: evaluate_stop returns {}
    assert (
        stop_gate.evaluate_stop(
            {"conversationId": "conv-eng", "terminationReason": "NO_TOOL_CALL"},
            repo_root=tmp_repo,
        )
        == {}
    )

    # Case B failure mode (a) & (b): post-verify edit to src/allowed.py -> stale receipt & uncommitted file
    allowed_file.write_text("READY = True\nEXTRA = 1\n", encoding="utf-8")
    res_stale = stop_gate.evaluate_stop(
        {"conversationId": "conv-eng", "terminationReason": "NO_TOOL_CALL"},
        repo_root=tmp_repo,
    )
    assert res_stale["decision"] == "continue"
    assert "missing verification receipt" in res_stale["reason"]
    assert "uncommitted files in allowed_files or WORKORDER.md" in res_stale["reason"]

    # Restore src/allowed.py to clean verified state
    allowed_file.write_text("READY = True\n", encoding="utf-8")
    assert (
        stop_gate.evaluate_stop(
            {"conversationId": "conv-eng", "terminationReason": "NO_TOOL_CALL"},
            repo_root=tmp_repo,
        )
        == {}
    )

    # Case B failure mode (c): incomplete CompletionReport (receipt_id=None) -> "continue"
    with StateDB(db_file) as db:
        db.update_session("conv-eng", attempt_num=1, structural_failures=0)
    wo_verified = schemas.load_workorder(wo_path)
    assert wo_verified.spec.completion is not None
    wo_verified.spec.completion.receipt_id = None
    wo_path.write_text(
        schemas.dump_document(wo_verified.spec, wo_verified.sections),
        encoding="utf-8",
    )
    res_bad_comp = stop_gate.evaluate_stop(
        {"conversationId": "conv-eng", "terminationReason": "NO_TOOL_CALL"},
        repo_root=tmp_repo,
    )
    assert res_bad_comp["decision"] == "continue"
    assert "incomplete Completion Report" in res_bad_comp["reason"]


def test_stop_gate_auditor_requires_audit_report_for_current_head(
    tmp_repo: Path, daemon_home: Path
) -> None:
    """Verify pa-auditor Stop gate blocks until AUDIT-round-*.md exists for current HEAD."""
    ws_dir, proj_path, _ = _setup_enrolled_workspace(tmp_repo, daemon_home, mode="autonomous")
    db_file = ws_dir / ".state" / "state.db"

    # 1. Without AUDIT-round-1.md -> returns "continue" and increments attempt_num
    res_missing = stop_gate.evaluate_stop(
        {"conversationId": "conv-auditor", "terminationReason": "NO_TOOL_CALL"},
        repo_root=tmp_repo,
    )
    assert res_missing["decision"] == "continue"
    assert "pa pr post-audit PR-02" in res_missing["reason"]
    with StateDB(db_file) as db:
        sess = db.get_session("conv-auditor")
        assert sess is not None
        assert sess["attempt_num"] == 2

    # 2. Write AUDIT-round-1.md with a stale SHA -> still returns "continue"
    audit_path = proj_path.parent / "AUDIT-round-1.md"
    stale_audit = schemas.AuditReport(
        pr_id="PR-02",
        audit_round=1,
        head_sha="000000000000",
        verdict="APPROVED",
        findings=[],
    )
    audit_path.write_text(
        schemas.dump_document(stale_audit, [schemas.Section("## Audit Summary", "Stale.\n")]),
        encoding="utf-8",
    )
    res_stale = stop_gate.evaluate_stop(
        {"conversationId": "conv-auditor", "terminationReason": "NO_TOOL_CALL"},
        repo_root=tmp_repo,
    )
    assert res_stale["decision"] == "continue"

    # 3. Update AUDIT-round-1.md to match current HEAD SHA -> returns {}
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    valid_audit = schemas.AuditReport(
        pr_id="PR-02",
        audit_round=1,
        head_sha=head_sha,
        verdict="CHANGES_REQUESTED",
        findings=[
            schemas.AuditFinding(
                id="BLOCKING-1",
                axis="edge_cases",
                file_path="src/allowed.py",
                summary="Handle empty input",
                remediation="Add guard clause",
            )
        ],
    )
    audit_path.write_text(
        schemas.dump_document(valid_audit, [schemas.Section("## Audit Summary", "Findings.\n")]),
        encoding="utf-8",
    )
    assert (
        stop_gate.evaluate_stop(
            {"conversationId": "conv-auditor", "terminationReason": "NO_TOOL_CALL"},
            repo_root=tmp_repo,
        )
        == {}
    )


# ---------------------------------------------------------------------------
# WO-02.5: pre_invocation.py tests (Fast-exit, Spawn Header Binding,
#          CHECKPOINT/Rewind Re-injection, and Memory Mode Separation)
# ---------------------------------------------------------------------------


def test_pre_invocation_unenrolled_fast_exit_and_import_purity(
    tmp_path: Path, daemon_home: Path
) -> None:
    """Verify pre_invocation.py unenrolled fast-exit (<1ms) and zero pydantic/yaml/schemas imports."""
    _ = daemon_home
    unenrolled = tmp_path / "unenrolled-preinv-repo"
    unenrolled.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "workspacePaths": [str(unenrolled)],
        "conversationId": "conv-unbound",
        "prompt": "PA_ROLE: engineer\nWO_ID: WO-02.1\nPR_ID: PR-02\n",
    }

    # Warm-up call
    assert pre_invocation.evaluate_pre_invocation(payload) == {}

    iterations = 25
    start = time.perf_counter()
    for _ in range(iterations):
        res = pre_invocation.evaluate_pre_invocation(payload)
        assert res == {}
    elapsed_ms = ((time.perf_counter() - start) * 1000.0) / iterations
    assert elapsed_ms < 1.0, f"Unenrolled fast-exit took {elapsed_ms:.3f} ms (limit < 1.0 ms)"

    # Verify import purity on the unenrolled path in a fresh subprocess
    script_path = Path(pre_invocation.__file__).resolve()
    scripts_dir = str(script_path.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = scripts_dir
    code = (
        "import sys, pre_invocation\n"
        f"res = pre_invocation.evaluate_pre_invocation({{'workspacePaths': [{str(unenrolled)!r}]}})\n"
        "assert res == {}\n"
        "assert 'pydantic' not in sys.modules\n"
        "assert 'yaml' not in sys.modules\n"
        "assert 'schemas' not in sys.modules\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, f"Import purity failed:\n{proc.stdout}\n{proc.stderr}"

    # Verify CLI subprocess execution on unenrolled repo outputs {} and exits 0
    cli_proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert cli_proc.returncode == 0
    assert json.loads(cli_proc.stdout.strip()) == {}


def test_parse_spawn_header_and_turn1_session_binding(
    tmp_repo: Path, daemon_home: Path
) -> None:
    """Verify parse_spawn_header and Turn 1 unbound subagent session binding & injection."""
    header_sample = (
        "> **PA_ROLE**: `pa-engineer`\n"
        "- WO_ID: WO-02.1\n"
        "PR_ID: PR-02\n"
        "PROGRAMME_ID: prog-sample\n"
    )
    parsed = pre_invocation.parse_spawn_header(header_sample)
    assert parsed == {
        "role": "engineer",
        "wo_id": "WO-02.1",
        "pr_id": "PR-02",
        "programme_id": "prog-sample",
    }
    assert pre_invocation.parse_spawn_header("Just a normal prompt without headers") == {}

    ws_dir, _, wo_path = _setup_enrolled_workspace(tmp_repo, daemon_home, mode="autonomous")
    db_file = ws_dir / ".state" / "state.db"

    # Configure required_skills on WO-02.1 and create a repo skill file on disk
    skill_md = tmp_repo / ".agents" / "skills" / "framework-expert" / "SKILL.md"
    skill_md.parent.mkdir(parents=True, exist_ok=True)
    skill_md.write_text("# Framework Expert Skill\n", encoding="utf-8")

    wo_doc = schemas.load_workorder(wo_path)
    wo_doc.spec.required_skills = ["framework-expert"]
    wo_doc.spec.spec_hash = schemas.compute_spec_hash(wo_doc.spec, wo_doc.sections)
    wo_path.write_text(schemas.dump_document(wo_doc.spec, wo_doc.sections), encoding="utf-8")

    transcript_file = tmp_repo / "subagent_turn1.jsonl"
    turn1_steps = [
        {
            "step_index": 0,
            "type": "USER_INPUT",
            "content": (
                "PA_ROLE: engineer\n"
                "WO_ID: WO-02.1\n"
                "PR_ID: PR-02\n"
                "PROGRAMME_ID: prog-sample\n\n"
                "Execute WO-02.1 now."
            ),
        },
        {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "Starting work."},
    ]
    transcript_file.write_text(
        "\n".join(json.dumps(s) for s in turn1_steps) + "\n",
        encoding="utf-8",
    )

    # Turn 1: Unbound conversationId binds in state.db and receives injectSteps
    res_t1 = pre_invocation.evaluate_pre_invocation(
        {
            "conversationId": "conv-new-worker",
            "transcriptPath": f"file://{transcript_file}",
        },
        repo_root=tmp_repo,
    )
    assert "injectSteps" in res_t1
    assert len(res_t1["injectSteps"]) == 1
    injected_msg = res_t1["injectSteps"][0]["userMessage"]
    assert "WO-02.1" in injected_msg
    assert "PR-02" in injected_msg
    assert "src/allowed.py" in injected_msg
    assert "pytest" in injected_msg
    assert str(skill_md) in injected_msg

    with StateDB(db_file) as db:
        sess = db.get_session("conv-new-worker")
        assert sess is not None
        assert sess["role"] == "engineer"
        assert sess["wo_id"] == "WO-02.1"
        assert sess["pr_id"] == "PR-02"
        assert sess["programme_id"] == "prog-sample"
        assert sess["last_checkpoint_step"] == 2

    # Turn 2: Append normal steps without CHECKPOINT or rewind -> returns {} (no duplicate injection)
    turn2_steps = [
        *turn1_steps,
        {"step_index": 2, "type": "TOOL_CALL", "content": "read_file"},
        {"step_index": 3, "type": "PLANNER_RESPONSE", "content": "Continuing work."},
    ]
    transcript_file.write_text(
        "\n".join(json.dumps(s) for s in turn2_steps) + "\n",
        encoding="utf-8",
    )
    res_t2 = pre_invocation.evaluate_pre_invocation(
        {
            "conversationId": "conv-new-worker",
            "transcriptPath": str(transcript_file),
        },
        repo_root=tmp_repo,
    )
    assert res_t2 == {}
    with StateDB(db_file) as db:
        sess2 = db.get_session("conv-new-worker")
        assert sess2 is not None
        assert sess2["last_checkpoint_step"] == 4


def test_pre_invocation_checkpoint_compaction_and_rewind_reinjection(
    tmp_repo: Path, daemon_home: Path
) -> None:
    """Verify CHECKPOINT compaction and step-count rewind trigger context re-injection."""
    ws_dir, _, _ = _setup_enrolled_workspace(tmp_repo, daemon_home, mode="monitored")
    db_file = ws_dir / ".state" / "state.db"

    transcript_file = tmp_repo / "compaction_transcript.jsonl"
    initial_steps = [
        {"step_index": idx, "type": "USER_INPUT", "content": f"Step {idx}"}
        for idx in range(5)
    ]
    transcript_file.write_text(
        "\n".join(json.dumps(s) for s in initial_steps) + "\n",
        encoding="utf-8",
    )

    # First call on pre-bound conv-eng (where last_checkpoint_step is initially None) -> injects and sets watermark=5
    res_init = pre_invocation.evaluate_pre_invocation(
        {"conversationId": "conv-eng", "transcriptPath": str(transcript_file)},
        repo_root=tmp_repo,
    )
    assert "injectSteps" in res_init
    with StateDB(db_file) as db:
        assert db.get_session("conv-eng")["last_checkpoint_step"] == 5

    # Normal progression (6 steps, no CHECKPOINT) -> no injection, watermark updates to 6
    initial_steps.append({"step_index": 5, "type": "PLANNER_RESPONSE", "content": "Step 5"})
    transcript_file.write_text(
        "\n".join(json.dumps(s) for s in initial_steps) + "\n",
        encoding="utf-8",
    )
    assert (
        pre_invocation.evaluate_pre_invocation(
            {"conversationId": "conv-eng", "transcriptPath": str(transcript_file)},
            repo_root=tmp_repo,
        )
        == {}
    )
    with StateDB(db_file) as db:
        assert db.get_session("conv-eng")["last_checkpoint_step"] == 6

    # 1. Append a CHECKPOINT step at step_index=10 -> triggers re-injection and updates watermark to 10
    checkpoint_steps = [
        *initial_steps,
        {"step_index": 10, "type": "CHECKPOINT", "content": "Compacted context"},
    ]
    transcript_file.write_text(
        "\n".join(json.dumps(s) for s in checkpoint_steps) + "\n",
        encoding="utf-8",
    )
    res_cp = pre_invocation.evaluate_pre_invocation(
        {"conversationId": "conv-eng", "transcriptPath": str(transcript_file)},
        repo_root=tmp_repo,
    )
    assert "injectSteps" in res_cp
    with StateDB(db_file) as db:
        assert db.get_session("conv-eng")["last_checkpoint_step"] == 10

    # Calling again with the same CHECKPOINT step does NOT re-inject
    assert (
        pre_invocation.evaluate_pre_invocation(
            {"conversationId": "conv-eng", "transcriptPath": str(transcript_file)},
            repo_root=tmp_repo,
        )
        == {}
    )

    # 2. Rewind transcript back to 3 steps (no CHECKPOINT) -> triggers re-injection and updates watermark to 3
    rewound_steps = initial_steps[:3]
    transcript_file.write_text(
        "\n".join(json.dumps(s) for s in rewound_steps) + "\n",
        encoding="utf-8",
    )
    res_rewind = pre_invocation.evaluate_pre_invocation(
        {"conversationId": "conv-eng", "transcriptPath": str(transcript_file)},
        repo_root=tmp_repo,
    )
    assert "injectSteps" in res_rewind
    with StateDB(db_file) as db:
        assert db.get_session("conv-eng")["last_checkpoint_step"] == 3


def test_pre_invocation_memory_mode_builtin_vs_external_separation(
    tmp_repo: Path, daemon_home: Path
) -> None:
    """Verify strict memory_mode payload separation between builtin and external modes."""
    ws_dir, _, _ = _setup_enrolled_workspace(tmp_repo, daemon_home, mode="autonomous")
    db_file = ws_dir / ".state" / "state.db"

    mem_dir = ws_dir / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (mem_dir / "MEMORY.md").write_text(
        "# Repository Memory\n- Secret builtin invariant: ALPHA_BETA_GAMMA\n",
        encoding="utf-8",
    )
    (mem_dir / "MODULE_INDEX.md").write_text(
        "# Module Index\n\n"
        "## src/ Subsystem\n- Invariant for src/ module: SRC_INDEX_MARKER\n\n"
        "## unrelated/ Subsystem\n- Unrelated note: UNRELATED_MARKER\n",
        encoding="utf-8",
    )

    # 1. memory_mode = "builtin": includes MEMORY.md, matching MODULE_INDEX.md section, and Full Distillation Mode
    with StateDB(db_file) as db:
        db.set_config("memory_mode", "builtin")
        db.update_session("conv-pa", last_checkpoint_step=None)
        db.update_session("conv-eng", last_checkpoint_step=None)

    res_pa_builtin = pre_invocation.evaluate_pre_invocation(
        {"conversationId": "conv-pa", "invocationNum": 1},
        repo_root=tmp_repo,
    )
    pa_builtin_msg = res_pa_builtin["injectSteps"][0]["userMessage"]
    assert "Full Distillation Mode" in pa_builtin_msg
    assert "ALPHA_BETA_GAMMA" in pa_builtin_msg
    assert "SRC_INDEX_MARKER" in pa_builtin_msg
    assert "UNRELATED_MARKER" not in pa_builtin_msg

    res_eng_builtin = pre_invocation.evaluate_pre_invocation(
        {"conversationId": "conv-eng", "invocationNum": 1},
        repo_root=tmp_repo,
    )
    eng_builtin_msg = res_eng_builtin["injectSteps"][0]["userMessage"]
    assert "Full Distillation Mode (memory_mode=builtin)" in eng_builtin_msg

    # 2. memory_mode = "external": completely omits MEMORY.md & MODULE_INDEX.md and instructs Succinct Mode
    with StateDB(db_file) as db:
        db.set_config("memory_mode", "external")
        db.update_session("conv-pa", last_checkpoint_step=None)
        db.update_session("conv-eng", last_checkpoint_step=None)

    res_pa_external = pre_invocation.evaluate_pre_invocation(
        {"conversationId": "conv-pa", "invocationNum": 1},
        repo_root=tmp_repo,
    )
    pa_ext_msg = res_pa_external["injectSteps"][0]["userMessage"]
    assert "Succinct Write-Back Mode" in pa_ext_msg
    assert "ALPHA_BETA_GAMMA" not in pa_ext_msg
    assert "SRC_INDEX_MARKER" not in pa_ext_msg
    assert "MEMORY.md" not in pa_ext_msg
    assert "MODULE_INDEX.md" not in pa_ext_msg

    res_eng_external = pre_invocation.evaluate_pre_invocation(
        {"conversationId": "conv-eng", "invocationNum": 1},
        repo_root=tmp_repo,
    )
    eng_ext_msg = res_eng_external["injectSteps"][0]["userMessage"]
    assert "Succinct Mode (memory_mode=external)" in eng_ext_msg
    assert "ALPHA_BETA_GAMMA" not in eng_ext_msg


# ---------------------------------------------------------------------------
# WO-02.6: Custom Agent Definitions, Rule, SKILL.md, `pa pr approve-plan`,
#          `pa escalate`, and PR-02 Dogfood Workspace Verification
# ---------------------------------------------------------------------------


def test_agent_frontmatter_rule_and_skill_compliance() -> None:
    """Verify all 5 agents/pa-*.md files, 00-pa-operating-model.md, and SKILL.md (SPEC §5.2, Charter R6)."""
    repo_root = common.find_repo_root(Path(__file__).resolve())
    assert repo_root is not None
    plugin_dir = repo_root / "daemon" / "workspace-plugin" / "principal-architect"
    agents_dir = plugin_dir / "agents"

    expected_agents = (
        "pa-chief-architect.md",
        "pa-principal-architect.md",
        "pa-engineer.md",
        "pa-auditor.md",
        "pa-debugger.md",
    )

    parsed_agents: dict[str, dict[str, Any]] = {}
    for fname in expected_agents:
        fpath = agents_dir / fname
        assert fpath.is_file(), f"Missing agent definition: {fpath}"
        fm_data, sections = schemas.parse_document(fpath.read_text(encoding="utf-8"))
        assert isinstance(fm_data.get("name"), str) and fm_data["name"].strip()
        assert fm_data["name"] == fname.removesuffix(".md")
        assert isinstance(fm_data.get("description"), str) and fm_data["description"].strip()
        assert fm_data.get("model") == "inherit"
        assert fm_data.get("excludeDefaultComponents") is False
        assert isinstance(fm_data.get("tools"), list) and len(fm_data["tools"]) >= 1
        assert len(sections) >= 1
        parsed_agents[fname] = fm_data

    # 1. pa-engineer.md and pa-auditor.md capability scoping
    for sub_name in ("pa-engineer.md", "pa-auditor.md"):
        fm = parsed_agents[sub_name]
        assert fm.get("inheritCustomizations") is False
        assert fm.get("skills") == [
            ".agents/plugins/principal-architect-workspace/.state/pa-skills.json"
        ]
        assert fm.get("rules") == [
            ".agents/plugins/principal-architect-workspace/.state/pa-worker-rules.json"
        ]

    # 2. pa-engineer.md tool and role restrictions
    eng_fm = parsed_agents["pa-engineer.md"]
    assert eng_fm.get("mainAgent") is False
    assert eng_fm.get("subagent") is True
    assert eng_fm.get("inheritMcp") is True
    eng_tools = set(eng_fm["tools"])
    for forbidden_tool in (
        "invoke_subagent",
        "ask_question",
        "search_web",
        "search_marketplace",
    ):
        assert forbidden_tool not in eng_tools

    # 3. pa-auditor.md read-only tool and MCP restrictions
    aud_fm = parsed_agents["pa-auditor.md"]
    assert aud_fm.get("mainAgent") is True
    assert aud_fm.get("subagent") is True
    assert aud_fm.get("inheritMcp") is False
    aud_tools = set(aud_fm["tools"])
    for forbidden_write_tool in (
        "write_to_file",
        "write_file",
        "replace_file_content",
        "edit_file",
        "multi_replace_file_content",
        "invoke_subagent",
    ):
        assert forbidden_write_tool not in aud_tools

    # 4. pa-chief-architect.md and pa-principal-architect.md configuration
    for arch_name in ("pa-chief-architect.md", "pa-principal-architect.md"):
        afm = parsed_agents[arch_name]
        assert afm.get("mainAgent") is True
        assert afm.get("subagent") is True
        assert afm.get("inheritMcp") is True
        assert afm.get("skills") == [
            ".agents/plugins/principal-architect-workspace/.state/pa-skills.json"
        ]
        assert afm.get("rules") == [".agents/rules"]
        assert "invoke_subagent" in afm["tools"]
        assert "ask_question" in afm["tools"]

    # 5. pa-debugger.md configuration
    dbg_fm = parsed_agents["pa-debugger.md"]
    assert dbg_fm.get("mainAgent") is True
    assert dbg_fm.get("subagent") is True
    assert dbg_fm.get("inheritMcp") is True
    assert dbg_fm.get("skills") == [
        ".agents/plugins/principal-architect-workspace/.state/pa-skills.json"
    ]
    assert dbg_fm.get("rules") == [
        ".agents/plugins/principal-architect-workspace/.state/pa-worker-rules.json"
    ]
    assert "ask_question" in dbg_fm["tools"]

    # 6. Rule file compliance: no YAML frontmatter and < 8192 bytes
    rule_path = plugin_dir / "rules" / "00-pa-operating-model.md"
    assert rule_path.is_file()
    rule_bytes = rule_path.read_bytes()
    assert 0 < len(rule_bytes) < 8192
    rule_text = rule_bytes.decode("utf-8")
    assert not rule_text.lstrip().startswith("---")

    # 7. SKILL.md compliance: valid YAML frontmatter with name == "principal-architect"
    skill_path = plugin_dir / "skills" / "principal-architect" / "SKILL.md"
    assert skill_path.is_file()
    skill_fm, skill_sections = schemas.parse_document(skill_path.read_text(encoding="utf-8"))
    assert skill_fm.get("name") == "principal-architect"
    assert isinstance(skill_fm.get("description"), str) and skill_fm["description"].strip()
    assert len(skill_sections) >= 1


def test_pa_pr_approve_plan_cli(
    tmp_repo: Path, daemon_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify `pa pr approve-plan` validates charter_hash and allowed_modules, stamps spec_hash, and resolves plan_approval."""
    ws_dir, proj_path, wo_path = _setup_enrolled_workspace(
        tmp_repo,
        daemon_home,
        mode="autonomous",
        pr_status=schemas.PRState.PLANNED,
    )
    db_file = ws_dir / ".state" / "state.db"

    # Enqueue an open plan_approval item and PLAN_APPROVAL_REQUIRED escalation
    with StateDB(db_file) as db:
        escalation.record_escalation(
            db,
            level="PA_TO_HUMAN",
            source_role="pa",
            target_role="human",
            pr_id="PR-02",
            blocker_type="other",
            reason_code="PLAN_APPROVAL_REQUIRED",
            summary="Approve PR-02 plan",
            enqueue_if_needed=True,
            attention_kind="plan_approval",
            attention_title="🟠 [Plan Approval] PR-02",
            attention_priority=10,
        )
        assert len(db.list_open(pr_id="PR-02")) == 1

    # 1. Rejects (exit 1) when a Work Order's allowed_files falls outside charter.allowed_modules
    wo_doc = schemas.load_workorder(wo_path)
    wo_doc.spec.allowed_files = ["src/allowed.py", "outside_charter/hack.py"]
    wo_doc.spec.spec_hash = None
    wo_path.write_text(schemas.dump_document(wo_doc.spec, wo_doc.sections), encoding="utf-8")

    rc_outside = pa_cli.main(["pr", "approve-plan", "PR-02", "--path", str(tmp_repo)])
    assert rc_outside == 1
    assert "outside charter.allowed_modules" in capsys.readouterr().err
    assert schemas.load_project(proj_path).spec.status == schemas.PRState.PLANNED

    # Restore valid allowed_files on WO-02.1
    wo_doc.spec.allowed_files = ["src/allowed.py", "src/sub/**"]
    wo_doc.spec.spec_hash = None
    wo_path.write_text(schemas.dump_document(wo_doc.spec, wo_doc.sections), encoding="utf-8")

    # 2. Rejects (exit 1) when PROJECT.md Part I charter_hash is tampered with
    original_proj_text = proj_path.read_text(encoding="utf-8")
    proj_path.write_text(
        original_proj_text.replace("Charter scope details.", "Tampered charter scope."),
        encoding="utf-8",
    )
    rc_tampered = pa_cli.main(["pr", "approve-plan", "PR-02", "--path", str(tmp_repo)])
    assert rc_tampered == 1
    assert "charter_hash verification failed" in capsys.readouterr().err

    # Restore valid PROJECT.md
    proj_path.write_text(original_proj_text, encoding="utf-8")

    # 3. Succeeds (exit 0) when valid: stamps spec_hash, sets status=APPROVED + approved_at, and resolves plan_approval
    rc_ok = pa_cli.main(["pr", "approve-plan", "PR-02", "--path", str(tmp_repo)])
    assert rc_ok == 0
    assert "Approved plan for PR-02" in capsys.readouterr().err

    approved_proj = schemas.load_project(proj_path)
    assert approved_proj.spec.status == schemas.PRState.APPROVED
    assert approved_proj.spec.approved_at is not None
    assert schemas.verify_charter_hash(proj_path) is True

    stamped_wo = schemas.load_workorder(wo_path)
    assert stamped_wo.spec.spec_hash is not None
    assert schemas.verify_spec_hash(wo_path) is True

    with StateDB(db_file) as db:
        assert db.list_open(pr_id="PR-02") == []
        assert db.open_escalations(pr_id="PR-02") == []


def test_pa_escalate_cli(
    tmp_repo: Path, daemon_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify `pa escalate` across `--to-pa`, `--to-chief`, and `--to-human` in monitored and autonomous modes."""
    ws_dir, _, _ = _setup_enrolled_workspace(tmp_repo, daemon_home, mode="monitored")
    db_file = ws_dir / ".state" / "state.db"

    # Missing summary returns exit 1
    rc_missing = pa_cli.main(["escalate", "--to-pa", "--path", str(tmp_repo)])
    assert rc_missing == 1
    assert "--summary is required" in capsys.readouterr().err

    # 1. --to-pa in monitored mode: records escalation in escalations, does not enqueue in attention_queue
    rc_pa = pa_cli.main(
        [
            "escalate",
            "--to-pa",
            "--pr-id",
            "PR-02",
            "--wo-id",
            "WO-02.1",
            "--blocker-type",
            "boundary",
            "--reason-code",
            "BOUNDARY_EXPANSION_NEEDED",
            "--requested-file",
            "src/extra.py",
            "--summary",
            "Need src/extra.py in allowed_files",
            "--path",
            str(tmp_repo),
        ]
    )
    assert rc_pa == 0
    esc_pa_id = capsys.readouterr().out.strip()
    assert esc_pa_id.startswith("esc_")

    with StateDB(db_file) as db:
        escs = db.open_escalations(wo_id="WO-02.1")
        assert len(escs) == 1
        assert escs[0]["escalation_id"] == esc_pa_id
        assert escs[0]["level"] == "wo_to_pa"
        assert escs[0]["source_role"] == "engineer"
        assert escs[0]["target_role"] == "pa"
        assert json.loads(escs[0]["requested_files_json"]) == ["src/extra.py"]
        assert escs[0]["summary"] == "Need src/extra.py in allowed_files"
        assert db.list_open(pr_id="PR-02") == []

    # 2. --to-human in monitored mode: records escalation AND enqueues into attention_queue (priority 15)
    rc_human = pa_cli.main(
        [
            "escalate",
            "--to-human",
            "--pr-id",
            "PR-02",
            "--reason-code",
            "STRATEGIC_DECISION",
            "--path",
            str(tmp_repo),
            "Need human sign-off on API change",
        ]
    )
    assert rc_human == 0
    esc_human_id = capsys.readouterr().out.strip()
    assert esc_human_id.startswith("esc_")

    with StateDB(db_file) as db:
        human_escs = db.open_escalations(target_role="human")
        assert len(human_escs) == 1
        assert human_escs[0]["level"] == "chief_to_human"
        assert human_escs[0]["source_role"] == "chief"
        assert human_escs[0]["target_role"] == "human"
        open_attn = db.list_open(pr_id="PR-02")
        assert len(open_attn) == 1
        assert open_attn[0]["priority"] == 15
        assert json.loads(open_attn[0]["action_payload_json"])["escalation_id"] == esc_human_id

    # 3. --to-chief in autonomous mode: records escalation AND enqueues into attention_queue (priority 20)
    with StateDB(db_file) as db:
        db.set_config("execution_mode", "autonomous")

    rc_chief = pa_cli.main(
        [
            "escalate",
            "--to-chief",
            "--pr-id",
            "PR-02",
            "--blocker-type",
            "charter",
            "--reason-code",
            "CHARTER_AMENDMENT_NEEDED",
            "--requested-file",
            "daemon/new_module.py",
            "--summary",
            "Need daemon/new_module.py in allowed_modules",
            "--path",
            str(tmp_repo),
        ]
    )
    assert rc_chief == 0
    esc_chief_id = capsys.readouterr().out.strip()
    assert esc_chief_id.startswith("esc_")

    with StateDB(db_file) as db:
        chief_escs = db.open_escalations(target_role="chief")
        assert len(chief_escs) == 1
        assert chief_escs[0]["escalation_id"] == esc_chief_id
        assert chief_escs[0]["level"] == "pa_to_chief"
        assert chief_escs[0]["source_role"] == "pa"
        assert chief_escs[0]["target_role"] == "chief"
        assert json.loads(chief_escs[0]["requested_files_json"]) == ["daemon/new_module.py"]
        open_attn2 = db.list_open(pr_id="PR-02")
        assert len(open_attn2) == 2
        assert any(
            json.loads(i["action_payload_json"]).get("escalation_id") == esc_chief_id
            and i["priority"] == 20
            for i in open_attn2
        )


def test_pr02_dogfood_workspace_specs_and_hashes() -> None:
    """Validate this repository's own PR-02 PROJECT.md and WO-02.1..WO-02.6 WORKORDER.md files and hashes."""
    repo_root = common.find_repo_root(Path(__file__).resolve())
    assert repo_root is not None
    ws_dir = common.workspace_dir(repo_root)
    pr02_dir = ws_dir / "pr-02-agents-and-dual-mode-hooks"
    proj_md = pr02_dir / "PROJECT.md"
    assert proj_md.is_file()

    proj_doc = schemas.load_project(proj_md)
    assert proj_doc.spec.charter.pr_id == "PR-02"
    assert proj_doc.spec.charter.charter_locked is True
    assert schemas.verify_charter_hash(proj_md) is True
    assert len(proj_doc.spec.work_orders) == 6

    wo_paths = sorted(pr02_dir.glob("wo*/WORKORDER.md"))
    assert len(wo_paths) == 6
    expected_ids = [f"WO-02.{idx}" for idx in range(1, 7)]
    found_ids: list[str] = []

    for wp in wo_paths:
        wo_doc = schemas.load_workorder(wp)
        assert wo_doc.spec.pr_id == "PR-02"
        assert wo_doc.spec.spec_hash is not None
        assert schemas.verify_spec_hash(wp) is True, f"spec_hash mismatch on {wp}"
        for af in wo_doc.spec.allowed_files:
            assert pa_cli._is_pattern_within_allowed_modules(
                af,
                proj_doc.spec.charter.allowed_modules,
                pre_tool_gate.matches_any_pattern,
            ), f"{wo_doc.spec.wo_id} allowed_files '{af}' outside PR-02 allowed_modules"
        found_ids.append(wo_doc.spec.wo_id)

    assert found_ids == expected_ids



