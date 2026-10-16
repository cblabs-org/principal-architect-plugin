"""Unit and integration tests for dual-mode hooks (`monitored` vs `autonomous`) and escalation engine."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import common
import escalation
import pytest
from state_db import StateDB


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
