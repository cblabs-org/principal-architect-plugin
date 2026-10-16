"""Live ephemeral-port integration tests for `sidecar.json` and `cockpit.py` HTTP + SSE API.

Exercises SPEC.md §10.1-§10.2 and PR-04 Charter G1 & R1-R5:
1. `daemon/sidecars/pa_cockpit/sidecar.json` manifest contract (schema v1, no `agent_permissions`).
2. `GET /api/workspaces`, `GET /api/state?workspace=file://...`, and static UI asset routes.
3. `GET /api/events` SSE streaming (`?once=1` and persistent live state-change push).
4. All `POST` mutation endpoints (`/api/mode`, `/api/pr/approve-plan`, `/api/escalation/resolve`,
   `/api/pr/start`, `/api/wo/debug`, `/api/pr/graduate`, `/api/sync`).
"""

from __future__ import annotations

import http.client
import json
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import cockpit
import common
import escalation
import models
import pa_cli
import post_tool_receipt
import schemas
import state_db
import vcs_sync

REPO_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def running_cockpit_server(daemon_home: Path) -> Iterator[tuple[cockpit.CockpitHTTPServer, str]]:
    """Start `cockpit.create_server` on an ephemeral localhost port in a background thread."""
    server = cockpit.create_server(host="127.0.0.1", port=0, daemon_home=daemon_home)
    host, port = server.server_address[:2]
    base_url = f"http://{host}:{port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server, base_url
    finally:
        server.server_close()
        server.shutdown()
        thread.join(timeout=3.0)


def _http_get_json(url: str) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


def _http_post_json(url: str, payload: dict[str, Any] | str) -> tuple[int, dict[str, Any]]:
    raw = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


def _seed_enrolled_workspace(tmp_repo: Path, daemon_home: Path) -> Path:
    """Enroll `tmp_repo` and scaffold a programme, PR-01, and WO-01.1 for Cockpit API testing."""
    rc = pa_cli.main(
        [
            "enroll",
            str(tmp_repo),
            "--memory-mode",
            "builtin",
            "--vcs-mode",
            "local_git",
        ]
    )
    assert rc == 0

    rc = pa_cli.main(
        [
            "programme",
            "init",
            "cockpit-demo",
            "--title",
            "Cockpit Demo Programme",
            "--path",
            str(tmp_repo),
        ]
    )
    assert rc == 0

    rc = pa_cli.main(
        [
            "programme",
            "charter",
            "PR-01",
            "--slug",
            "pr-01-demo-feature",
            "--title",
            "Demo Feature Implementation",
            "--branch",
            "feat/pr-01-demo-feature",
            "--base-branch",
            "main",
            "--allowed-module",
            "src/",
            "--allowed-module",
            "tests/",
            "--verification-command",
            "true",
            "--required-skill",
            "demo-skill",
            "--path",
            str(tmp_repo),
        ]
    )
    assert rc == 0

    ws_dir = common.workspace_dir(tmp_repo)
    pr_dir = ws_dir / "pr-01-demo-feature"
    proj_md = pr_dir / "PROJECT.md"
    proj_doc = schemas.load_project(proj_md)
    proj_doc.spec.work_orders = [
        schemas.WOSummaryRow(
            id="WO-01.1",
            slug="wo1-core",
            title="Implement Core Module",
            complexity=schemas.ComplexityTier.standard,
            status=schemas.WorkOrderStatus.PENDING,
            attempts=1,
        )
    ]
    proj_md.write_text(
        schemas.dump_document(proj_doc.spec, proj_doc.sections),
        encoding="utf-8",
    )

    wo_dir = pr_dir / "wo1-core"
    wo_dir.mkdir(parents=True, exist_ok=True)
    wo_md = wo_dir / "WORKORDER.md"
    wo_spec = schemas.WorkOrderSpec(
        wo_id="WO-01.1",
        pr_id="PR-01",
        title="Implement Core Module",
        complexity=schemas.ComplexityTier.standard,
        status=schemas.WorkOrderStatus.PENDING,
        allowed_files=["src/core.py"],
        forbidden_files=["SPEC.md"],
        required_skills=["demo-skill"],
        verification_command="true",
    )
    wo_sections = [
        schemas.Section(heading="## 1. Objective", body="Implement `src/core.py`.\n"),
        schemas.Section(heading="## Completion Report", body="_Pending._\n"),
    ]
    wo_spec.spec_hash = schemas.compute_spec_hash(wo_spec, wo_sections)
    wo_md.write_text(schemas.dump_document(wo_spec, wo_sections), encoding="utf-8")

    (tmp_repo / "src").mkdir(parents=True, exist_ok=True)
    (tmp_repo / "src" / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Seed workspace artifacts"],
        cwd=tmp_repo,
        check=True,
        capture_output=True,
    )
    return ws_dir


def test_sidecar_manifest_contract() -> None:
    """Verify `daemon/sidecars/pa_cockpit/sidecar.json` matches SPEC.md §10.1 and Charter G1/R5."""
    sidecar_path = REPO_ROOT / "daemon" / "sidecars" / "pa_cockpit" / "sidecar.json"
    assert sidecar_path.is_file()

    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert data["schema"] == "v1"
    assert data["ui"]["entrypoint"] == "SIDECAR_UI_ENTRYPOINT_AUX_PANE"
    assert "Principal Architect" in data["ui"]["title"]
    assert data["main"] == [
        "python3",
        "${PLUGIN_ROOT}/workspace-plugin/principal-architect/scripts/cockpit.py",
    ]
    assert data["restart_policy"] == "on_failure"
    assert data["env"]["PYTHONPATH"] == (
        "${PLUGIN_ROOT}/workspace-plugin/principal-architect/scripts"
    )
    assert "agent_permissions" not in data
    assert "agent_permissions" not in json.dumps(data)


def test_get_workspaces_state_and_static_routes(
    tmp_repo: Path,
    daemon_home: Path,
) -> None:
    """Verify `GET /api/workspaces`, `GET /api/state?workspace=file://...`, and static asset serving."""
    ws_dir = _seed_enrolled_workspace(tmp_repo, daemon_home)
    db_file = ws_dir / ".state" / "state.db"

    t_hash = post_tool_receipt.compute_tree_hash(tmp_repo, ["src/core.py"])
    with state_db.StateDB(db_file) as db:
        db.bind_session(
            "conv-pa-pr01",
            role="pa",
            programme_id="prog-cockpit-demo",
            pr_id="PR-01",
            pinned=1,
        )
        db.bind_session(
            "conv-worker-wo01",
            role="engineer",
            pr_id="PR-01",
            wo_id="WO-01.1",
            attempt_num=2,
            pinned=0,
        )
        db.insert_receipt(
            wo_id="WO-01.1",
            pr_id="PR-01",
            cmd="true",
            exit_code=0,
            tree_hash=t_hash,
            git_head_sha="abcdef123456",
            valid=1,
            receipt_id=f"rcpt_{t_hash[:12]}",
        )
        # Enqueue two attention items with different priorities to verify priority ordering
        escalation.enqueue_attention(
            db,
            kind="plan_approval",
            title="Approve PR-01 Plan",
            priority=20,
            pr_id="PR-01",
        )
        esc_row = escalation.record_escalation(
            db,
            level="WORKER_TO_PA",
            source_role="engineer",
            target_role="pa",
            pr_id="PR-01",
            wo_id="WO-01.1",
            blocker_type="boundary",
            reason_code="BOUNDARY_EXPANSION_NEEDED",
            requested_files=["src/helper.py"],
            summary="Need src/helper.py in allowed_files",
            enqueue_if_needed=True,
            attention_kind="boundary_escalation",
            attention_title="Boundary expansion for WO-01.1",
            attention_priority=5,
        )

    with running_cockpit_server(daemon_home) as (_, base_url):
        # 1. Static UI asset routes
        for route, expected_ct in (
            ("/", "text/html"),
            ("/index.html", "text/html"),
            ("/styles.css", "text/css"),
            ("/app.js", "application/javascript"),
            ("/preload.js", "application/javascript"),
        ):
            with urllib.request.urlopen(f"{base_url}{route}", timeout=5.0) as resp:
                assert resp.status == 200
                assert expected_ct in resp.headers.get("Content-Type", "")
                body_text = resp.read().decode("utf-8")
                assert len(body_text) > 0
                if route == "/preload.js":
                    assert "window.sidecar" in body_text

        # 2. GET /api/workspaces
        status, ws_payload = _http_get_json(f"{base_url}/api/workspaces")
        assert status == 200
        assert ws_payload["ok"] is True
        assert ws_payload["active_workspace"] == str(tmp_repo.resolve())
        assert len(ws_payload["workspaces"]) == 1
        assert ws_payload["workspaces"][0]["repo_root"] == str(tmp_repo.resolve())
        assert ws_payload["workspaces"][0]["uri"] == f"file://{tmp_repo.resolve()}"

        # 3. GET /api/state with file:// URI
        ws_uri = urllib.parse.quote(f"file://{tmp_repo.resolve()}", safe="")
        status, state_payload = _http_get_json(f"{base_url}/api/state?workspace={ws_uri}")
        assert status == 200
        assert state_payload["ok"] is True

        env = state_payload["env"]
        assert env["vcs_mode"] == "local_git"
        assert env["memory_mode"] == "builtin"
        assert env["execution_mode"] == "monitored"
        assert env["architect_model"] in models.ARCHITECT_MODEL_PREFERENCE
        assert env["repo_root"] == str(tmp_repo.resolve())
        assert env["workspace_dir"] == str(ws_dir)

        assert len(state_payload["programmes"]) == 1
        assert state_payload["programmes"][0]["programme_id"] == "prog-cockpit-demo"

        assert len(state_payload["prs"]) == 1
        pr01 = state_payload["prs"][0]
        assert pr01["pr_id"] == "PR-01"
        assert pr01["charter_locked"] is True
        assert pr01["charter_valid"] is True
        assert pr01["charter_hash"]
        assert pr01["pa_conversation_id"] == "conv-pa-pr01"

        assert len(pr01["work_orders"]) == 1
        wo01 = pr01["work_orders"][0]
        assert wo01["wo_id"] == "WO-01.1"
        assert wo01["receipt_id"] == f"rcpt_{t_hash[:12]}"
        assert wo01["tree_hash"] == t_hash
        assert wo01["subagent_id"] == "conv-worker-wo01"
        assert wo01["attempts"] == 2
        assert wo01["complexity"] == "standard"
        assert wo01["required_skills"] == ["demo-skill"]
        assert wo01["spec_valid"] is True

        # Attention queue sorted by priority ASC (priority 5 before priority 20)
        attn = state_payload["attention_queue"]
        assert len(attn) == 2
        assert attn[0]["priority"] == 5
        assert attn[0]["escalation"]["escalation_id"] == esc_row["escalation_id"]
        assert attn[0]["escalation"]["trigger_code"] == "BOUNDARY_EXPANSION_NEEDED"
        assert attn[0]["escalation"]["requested_files"] == ["src/helper.py"]
        assert attn[1]["priority"] == 20

        assert len(state_payload["escalations"]) == 1
        assert state_payload["escalations"][0]["escalation_id"] == esc_row["escalation_id"]

        # 4. Unknown workspace returns 404
        missing_uri = urllib.parse.quote(str(tmp_repo.parent / "nonexistent_repo"), safe="")
        status_404, err_payload = _http_get_json(
            f"{base_url}/api/state?workspace={missing_uri}"
        )
        assert status_404 == 404
        assert err_payload["ok"] is False


def test_sse_events_once_and_live_push(
    tmp_repo: Path,
    daemon_home: Path,
) -> None:
    """Verify `GET /api/events` SSE stream with `?once=1` and persistent live state change push."""
    ws_dir = _seed_enrolled_workspace(tmp_repo, daemon_home)
    db_file = ws_dir / ".state" / "state.db"

    with running_cockpit_server(daemon_home) as (server, base_url):
        host, port = server.server_address[:2]
        ws_param = urllib.parse.quote(f"file://{tmp_repo.resolve()}", safe="")

        # 1. Deterministic single-frame mode (?once=1)
        with urllib.request.urlopen(
            f"{base_url}/api/events?workspace={ws_param}&once=1",
            timeout=5.0,
        ) as resp:
            assert resp.status == 200
            assert "text/event-stream" in resp.headers.get("Content-Type", "")
            raw_sse = resp.read().decode("utf-8")

        assert raw_sse.startswith("event: state\ndata: ")
        data_line = next(ln for ln in raw_sse.splitlines() if ln.startswith("data: "))
        once_state = json.loads(data_line.removeprefix("data: "))
        assert once_state["ok"] is True
        assert once_state["env"]["execution_mode"] == "monitored"

        # 2. Persistent SSE stream receiving live update when state.db changes
        conn = http.client.HTTPConnection(host, port, timeout=5.0)
        try:
            conn.request("GET", f"/api/events?workspace={ws_param}")
            sse_resp = conn.getresponse()
            assert sse_resp.status == 200
            assert "text/event-stream" in (sse_resp.getheader("Content-Type") or "")

            def _read_next_state_frame() -> dict[str, Any]:
                event_type = ""
                while True:
                    line = sse_resp.fp.readline().decode("utf-8")
                    if not line:
                        raise RuntimeError("Unexpected EOF on SSE stream")
                    stripped = line.strip()
                    if stripped.startswith("event:"):
                        event_type = stripped.removeprefix("event:").strip()
                    elif stripped.startswith("data:") and event_type == "state":
                        payload_str = stripped.removeprefix("data:").strip()
                        # Consume trailing blank line
                        sse_resp.fp.readline()
                        return json.loads(payload_str)

            first_frame = _read_next_state_frame()
            assert first_frame["env"]["execution_mode"] == "monitored"

            # Mutate state.db in a separate thread after a short delay
            def _mutate_db() -> None:
                time.sleep(0.15)
                with state_db.StateDB(db_file) as db:
                    db.set_config("execution_mode", "autonomous")

            mut_thread = threading.Thread(target=_mutate_db, daemon=True)
            mut_thread.start()

            second_frame = _read_next_state_frame()
            assert second_frame["env"]["execution_mode"] == "autonomous"
            mut_thread.join(timeout=2.0)
        finally:
            conn.close()


def test_post_mutation_endpoints(
    tmp_repo: Path,
    daemon_home: Path,
) -> None:
    """Verify all `POST /api/*` mutation endpoints (`mode`, `approve-plan`, `escalation/resolve`, `pr/start`, `wo/debug`, `pr/graduate`, `sync`)."""
    ws_dir = _seed_enrolled_workspace(tmp_repo, daemon_home)
    db_file = ws_dir / ".state" / "state.db"
    pr_dir = ws_dir / "pr-01-demo-feature"
    proj_md = pr_dir / "PROJECT.md"
    wo_md = pr_dir / "wo1-core" / "WORKORDER.md"

    with running_cockpit_server(daemon_home) as (_, base_url):
        ws_str = str(tmp_repo.resolve())

        # 1. POST /api/mode (valid transitions and 400 validation errors)
        code, mode_res = _http_post_json(
            f"{base_url}/api/mode",
            {
                "workspace": ws_str,
                "mode": "autonomous",
                "architect_model": "claude-opus-5-5-high",
            },
        )
        assert code == 200
        assert mode_res["ok"] is True
        assert mode_res["execution_mode"] == "autonomous"
        assert mode_res["architect_model"] == "claude-opus-5-5-high"

        code_bad, bad_res = _http_post_json(
            f"{base_url}/api/mode",
            {"workspace": ws_str, "mode": "invalid-mode"},
        )
        assert code_bad == 400
        assert bad_res["ok"] is False

        code_bad_json, _ = _http_post_json(f"{base_url}/api/mode", "{not-valid-json")
        assert code_bad_json == 400

        # 2. POST /api/pr/approve-plan
        with state_db.StateDB(db_file) as db:
            escalation.record_escalation(
                db,
                level="PA_TO_HUMAN",
                source_role="pa",
                target_role="human",
                pr_id="PR-01",
                reason_code="PLAN_APPROVAL_REQUIRED",
                summary="Plan approval required for PR-01",
                enqueue_if_needed=True,
                attention_kind="plan_approval",
                attention_title="Approve PR-01 Plan",
            )

        code_app, app_res = _http_post_json(
            f"{base_url}/api/pr/approve-plan",
            {"workspace": ws_str, "pr_id": "PR-01", "approved_by": "reviewer"},
        )
        assert code_app == 200
        assert app_res["ok"] is True
        assert app_res["status"] == "APPROVED"
        reloaded_proj = schemas.load_project(proj_md)
        assert reloaded_proj.spec.status == schemas.PRState.APPROVED
        assert schemas.verify_charter_hash(reloaded_proj) is True
        assert schemas.verify_spec_hash(wo_md) is True

        # 3. POST /api/escalation/resolve (approve expands allowed_files; deny leaves unchanged)
        with state_db.StateDB(db_file) as db:
            esc_approve = escalation.record_escalation(
                db,
                level="WORKER_TO_PA",
                source_role="engineer",
                target_role="pa",
                pr_id="PR-01",
                wo_id="WO-01.1",
                blocker_type="boundary",
                reason_code="BOUNDARY_EXPANSION_NEEDED",
                requested_files=["src/extra.py"],
                summary="Need src/extra.py",
                enqueue_if_needed=True,
                attention_kind="boundary_escalation",
                attention_title="Boundary expansion WO-01.1",
            )
            esc_deny = escalation.record_escalation(
                db,
                level="WORKER_TO_PA",
                source_role="engineer",
                target_role="pa",
                pr_id="PR-01",
                wo_id="WO-01.1",
                blocker_type="boundary",
                reason_code="BOUNDARY_EXPANSION_NEEDED",
                requested_files=["src/forbidden_extra.py"],
                summary="Need src/forbidden_extra.py",
                enqueue_if_needed=True,
                attention_kind="boundary_escalation",
                attention_title="Boundary expansion deny WO-01.1",
            )

        code_res_ok, res_ok = _http_post_json(
            f"{base_url}/api/escalation/resolve",
            {
                "workspace": ws_str,
                "escalation_id": esc_approve["escalation_id"],
                "decision": "approve",
            },
        )
        assert code_res_ok == 200
        assert res_ok["ok"] is True
        assert res_ok["status"] == "RESOLVED"
        assert "src/extra.py" in res_ok["allowed_files"]

        wo_after_approve = schemas.load_workorder(wo_md)
        assert "src/extra.py" in wo_after_approve.spec.allowed_files
        assert schemas.verify_spec_hash(wo_after_approve) is True

        code_res_deny, res_deny = _http_post_json(
            f"{base_url}/api/escalation/resolve",
            {
                "workspace": ws_str,
                "escalation_id": esc_deny["escalation_id"],
                "decision": "deny",
            },
        )
        assert code_res_deny == 200
        assert res_deny["ok"] is True
        assert res_deny["status"] == "DENIED"
        wo_after_deny = schemas.load_workorder(wo_md)
        assert "src/forbidden_extra.py" not in wo_after_deny.spec.allowed_files

        with state_db.StateDB(db_file) as db:
            assert db.open_escalations() == []
            assert db.list_open() == []

        # 4. POST /api/pr/start
        code_start, start_res = _http_post_json(
            f"{base_url}/api/pr/start",
            {
                "workspace": ws_str,
                "pr_id": "PR-01",
                "conversation_id": "conv-pa-started",
            },
        )
        assert code_start == 200
        assert start_res["ok"] is True
        assert start_res["conversation_id"] == "conv-pa-started"
        _, state_after_start = _http_get_json(
            f"{base_url}/api/state?workspace={urllib.parse.quote(ws_str, safe='')}"
        )
        assert state_after_start["prs"][0]["pa_conversation_id"] == "conv-pa-started"

        # 5. POST /api/wo/debug
        with state_db.StateDB(db_file) as db:
            dbg_esc = escalation.record_escalation(
                db,
                level="WORKER_TO_PA",
                source_role="engineer",
                target_role="pa",
                pr_id="PR-01",
                wo_id="WO-01.1",
                blocker_type="verification",
                reason_code="MAX_ATTEMPTS_EXHAUSTED",
                summary="Exhausted 5 attempts",
                enqueue_if_needed=True,
                attention_kind="debugger_escalation",
                attention_title="Debug WO-01.1",
            )

        code_dbg, dbg_res = _http_post_json(
            f"{base_url}/api/wo/debug",
            {
                "workspace": ws_str,
                "wo_id": "WO-01.1",
                "conversation_id": "conv-debugger-01",
            },
        )
        assert code_dbg == 200
        assert dbg_res["ok"] is True
        assert dbg_res["conversation_id"] == "conv-debugger-01"
        assert dbg_res["pinned"] is True
        with state_db.StateDB(db_file) as db:
            sess = db.get_session("conv-debugger-01")
            assert sess is not None
            assert sess["pinned"] == 1
            cur_esc = db.conn.execute(
                "SELECT status FROM escalations WHERE escalation_id = ?",
                (dbg_esc["escalation_id"],),
            ).fetchone()
            assert cur_esc["status"] == "RESOLVED"

        # 6. POST /api/pr/graduate (409 before APPROVED audit; 200 after write_audit_round)
        code_grad_409, grad_409 = _http_post_json(
            f"{base_url}/api/pr/graduate",
            {"workspace": ws_str, "pr_id": "PR-01"},
        )
        assert code_grad_409 == 409
        assert grad_409["ok"] is False

        # Commit any workspace spec changes before stamping audit on current HEAD
        subprocess.run(["git", "add", "."], cwd=tmp_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Update workspace state before audit"],
            cwd=tmp_repo,
            check=True,
            capture_output=True,
        )
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        vcs_sync.write_audit_round(
            tmp_repo,
            "PR-01",
            schemas.AuditReport(
                pr_id="PR-01",
                audit_round=1,
                head_sha=head_sha,
                verdict="APPROVED",
                findings=[],
            ),
            commit=True,
        )

        code_grad_200, grad_200 = _http_post_json(
            f"{base_url}/api/pr/graduate",
            {"workspace": ws_str, "pr_id": "PR-01"},
        )
        assert code_grad_200 == 200
        assert grad_200["ok"] is True
        assert grad_200["status"] == "GRADUATED"
        assert schemas.load_project(proj_md).spec.status == schemas.PRState.GRADUATED

        # 7. POST /api/sync
        code_sync, sync_res = _http_post_json(
            f"{base_url}/api/sync",
            {"workspace": ws_str},
        )
        assert code_sync == 200
        assert sync_res["ok"] is True
        assert "synced_audits" in sync_res
        assert sync_res["synced_audits"] >= 1


def test_cockpit_frontend_assets_and_ui_contract(
    daemon_home: Path,
) -> None:
    """Verify `daemon/sidecars/pa_cockpit/ui/{index.html,styles.css,app.js}` per SPEC.md §10.3 & Charter G2/R5."""
    ui_dir = REPO_ROOT / "daemon" / "sidecars" / "pa_cockpit" / "ui"
    index_path = ui_dir / "index.html"
    styles_path = ui_dir / "styles.css"
    app_path = ui_dir / "app.js"

    assert index_path.is_file()
    assert styles_path.is_file()
    assert app_path.is_file()

    disk_html = index_path.read_text(encoding="utf-8")
    disk_css = styles_path.read_text(encoding="utf-8")
    disk_js = app_path.read_text(encoding="utf-8")

    with running_cockpit_server(daemon_home) as (_, base_url):
        # 1. Static asset HTTP serving matches disk files
        for route, expected_ct, expected_body in (
            ("/", "text/html", disk_html),
            ("/index.html", "text/html", disk_html),
            ("/styles.css", "text/css", disk_css),
            ("/app.js", "application/javascript", disk_js),
        ):
            with urllib.request.urlopen(f"{base_url}{route}", timeout=5.0) as resp:
                assert resp.status == 200
                assert expected_ct in resp.headers.get("Content-Type", "")
                served = resp.read().decode("utf-8")
                assert served == expected_body

        with urllib.request.urlopen(f"{base_url}/preload.js", timeout=5.0) as resp:
            assert resp.status == 200
            assert "application/javascript" in resp.headers.get("Content-Type", "")
            assert "window.sidecar" in resp.read().decode("utf-8")

    # 2. index.html contract checks (SPEC.md §10.3)
    assert "<title>Principal Architect Cockpit</title>" in disk_html
    assert '<link rel="stylesheet" href="/styles.css">' in disk_html
    assert '<script src="/preload.js"></script>' in disk_html
    assert '<script src="/app.js"' in disk_html
    for zone_id in (
        "zone-header",
        "zone-attention",
        "zone-dag",
        "workspace-select",
        "badge-vcs-mode",
        "badge-memory-mode",
        "btn-sync",
        "btn-mode-monitored",
        "btn-mode-autonomous",
        "architect-model-select",
        "attention-count",
        "attention-list",
        "dag-container",
    ):
        assert f'id="{zone_id}"' in disk_html

    # 3. styles.css host theme CSS variables & class selectors
    for css_var in (
        "--background",
        "--foreground",
        "--card",
        "--border",
        "--primary",
        "--muted-foreground",
    ):
        assert css_var in disk_css
        assert f"var({css_var}" in disk_css

    for selector in (
        ".cockpit-header",
        ".mode-toggle",
        ".badge",
        ".btn",
        ".btn-primary",
        ".btn-danger",
        ".attention-inbox",
        ".attention-card",
        ".programme-card",
        ".pr-card",
        ".wo-row",
        ".status-pill",
        ".charter-badge",
        ".receipt-badge",
    ):
        assert selector in disk_css

    # 4. app.js sidecar bindings, SSE stream, POST endpoints, and SPEC §10.3 UI labels
    assert "onWorkspaceChange" in disk_js
    assert "toggleConversation" in disk_js
    assert "EventSource" in disk_js
    assert "/api/events" in disk_js
    assert "/api/workspaces" in disk_js
    assert "/api/state" in disk_js

    for post_endpoint in (
        "/api/mode",
        "/api/pr/approve-plan",
        "/api/escalation/resolve",
        "/api/pr/start",
        "/api/wo/debug",
        "/api/pr/graduate",
        "/api/sync",
    ):
        assert post_endpoint in disk_js

    for required_label in (
        "🔔 Human Attention Needed",
        "🔒 Charter by Chief",
        "Approve Plan",
        "Approve & Resume",
        "Deny",
        "Launch Interactive Debug",
        "Graduate PR",
        "Jump to PA",
        "Peek Worker",
    ):
        assert required_label in disk_js or required_label in disk_html

