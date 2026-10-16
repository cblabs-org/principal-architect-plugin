"""Comprehensive unit and integration tests for state DB, sync, and common foundations."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import common
import pytest
from conftest import FakeRunner


def test_sqlite_available() -> None:
    """Verify sqlite3 is available in python stdlib with WAL support."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    row = cur.fetchone()
    assert row is not None
    conn.close()


def test_common_import_purity() -> None:
    """Verify common.py uses stdlib only and does not import pydantic or yaml."""
    scripts_dir = str(Path(common.__file__).resolve().parent)
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{scripts_dir}:{existing_pythonpath}" if existing_pythonpath else scripts_dir

    code = (
        "import sys, common\n"
        "assert 'pydantic' not in sys.modules, f'pydantic imported: {sys.modules[\"pydantic\"]}'\n"
        "assert 'yaml' not in sys.modules, f'yaml imported: {sys.modules[\"yaml\"]}'\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert res.returncode == 0, f"Import purity failed:\nstdout: {res.stdout}\nstderr: {res.stderr}"


def test_find_repo_root(tmp_repo: Path, tmp_path: Path) -> None:
    """Verify find_repo_root detects repo root, subdirectories, file URIs, and non-repos."""
    # Root of repo
    assert common.find_repo_root(tmp_repo) == tmp_repo

    # Subdirectory inside repo
    subdir = tmp_repo / "a" / "b" / "c"
    subdir.mkdir(parents=True)
    assert common.find_repo_root(subdir) == tmp_repo

    # File inside repo
    test_file = subdir / "file.txt"
    test_file.write_text("content", encoding="utf-8")
    assert common.find_repo_root(test_file) == tmp_repo

    # file:// URI
    file_uri = f"file://{subdir.resolve()}"
    assert common.find_repo_root(file_uri) == tmp_repo

    # Non-repo directory outside tmp_repo
    non_repo = tmp_path / "non_repo"
    non_repo.mkdir()
    assert common.find_repo_root(non_repo) is None


def test_find_repo_root_fallback(tmp_path: Path) -> None:
    """Verify find_repo_root falls back to runner when .git is not a direct directory entry."""
    fake_repo = tmp_path / "virtual_repo"
    fake_repo.mkdir()
    runner = FakeRunner()
    runner.set_response(["git", "rev-parse", "--show-toplevel"], stdout=str(fake_repo.resolve()))

    assert common.find_repo_root(fake_repo, runner=runner) == fake_repo.resolve()


def test_workspace_dir_resolution(tmp_repo: Path) -> None:
    """Verify workspace_dir precedence: new plugin path over legacy skills path."""
    new_ws = tmp_repo / common.NEW_WORKSPACE_REL
    legacy_ws = tmp_repo / common.LEGACY_WORKSPACE_REL

    # Neither exists: defaults to new path
    assert common.workspace_dir(tmp_repo) == new_ws

    # Only legacy exists: returns legacy path
    legacy_ws.mkdir(parents=True)
    assert common.workspace_dir(tmp_repo) == legacy_ws

    # Both exist: returns new path
    new_ws.mkdir(parents=True)
    assert common.workspace_dir(tmp_repo) == new_ws


def test_workspace_dir_dogfood() -> None:
    """Verify workspace_dir on this repository resolves to the active legacy workspace."""
    repo_root = common.find_repo_root(Path(__file__).resolve())
    assert repo_root is not None
    ws = common.workspace_dir(repo_root)
    assert ws.exists()
    assert ws == repo_root / common.LEGACY_WORKSPACE_REL


def test_daemon_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify daemon_home honors PA_DAEMON_HOME and falls back to default ~/.gemini."""
    # When PA_DAEMON_HOME is set
    custom_home = tmp_path / "custom_daemon_home"
    monkeypatch.setenv("PA_DAEMON_HOME", str(custom_home))
    assert common.daemon_home() == custom_home.resolve()

    # When PA_DAEMON_HOME is unset
    monkeypatch.delenv("PA_DAEMON_HOME", raising=False)
    fake_user_home = tmp_path / "fake_home"
    fake_user_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_user_home))
    expected = fake_user_home.resolve() / ".gemini" / "config" / "plugins" / "pa-daemon"
    assert common.daemon_home() == expected


def test_is_repo_enrolled(daemon_home: Path, tmp_repo: Path, tmp_path: Path) -> None:
    """Verify is_repo_enrolled handles missing/malformed registries and correctly detects repos."""
    # Empty inputs
    assert not common.is_repo_enrolled([])

    # Missing registry file
    assert not common.is_repo_enrolled([tmp_repo])

    registry_file = daemon_home / "state" / "registry.json"
    registry_file.parent.mkdir(parents=True, exist_ok=True)

    # Malformed JSON
    registry_file.write_text("not json", encoding="utf-8")
    assert not common.is_repo_enrolled([tmp_repo])

    # Valid registry with unenrolled repo
    unenrolled_repo = tmp_path / "unenrolled"
    unenrolled_repo.mkdir()
    registry_data = {
        "schema_version": 1,
        "repos": {
            str(tmp_repo.resolve()): {
                "slug": "tmp-repo",
                "enrolled_at": "2026-10-16T18:00:00Z",
                "workspace_dir": str(common.workspace_dir(tmp_repo)),
            }
        },
    }
    registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

    assert not common.is_repo_enrolled([unenrolled_repo])
    assert common.is_repo_enrolled([tmp_repo])

    # Subdirectory of enrolled repo
    sub = tmp_repo / "src" / "pkg"
    sub.mkdir(parents=True)
    assert common.is_repo_enrolled([sub])

    # file:// URI of enrolled repo
    assert common.is_repo_enrolled([f"file://{sub.resolve()}"])

    # Performance check: must run in < 1 ms per call
    start = time.perf_counter()
    for _ in range(50):
        common.is_repo_enrolled([sub])
    elapsed_ms = (time.perf_counter() - start) * 1000 / 50
    assert elapsed_ms < 1.0, f"is_repo_enrolled too slow: {elapsed_ms:.3f} ms"


def test_read_transcript(tmp_path: Path) -> None:
    """Verify read_transcript handles missing files, malformed lines, and extracts steps."""
    # Missing file
    assert common.read_transcript(tmp_path / "nonexistent.jsonl") == []

    # Valid and malformed lines
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({"step_index": 0, "type": "USER_INPUT", "content": "hi"}),
        "   ",
        "invalid json line",
        json.dumps({"step_index": 1, "type": "CHECKPOINT", "content": "cp1"}),
        json.dumps("not a dict"),
        json.dumps({"step_index": 2, "type": "MODEL_RESPONSE", "content": "ok"}),
    ]
    transcript_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    steps = common.read_transcript(transcript_file)
    assert len(steps) == 3
    assert steps[0]["step_index"] == 0
    assert steps[1]["type"] == "CHECKPOINT"
    assert steps[2]["step_index"] == 2


def test_latest_checkpoint_step() -> None:
    """Verify latest_checkpoint_step identifies highest index across variations."""
    # Empty steps
    assert common.latest_checkpoint_step([]) is None

    # No checkpoint steps
    steps = [
        {"step_index": 0, "type": "USER_INPUT"},
        {"step_index": 1, "type": "MODEL_OUTPUT"},
    ]
    assert common.latest_checkpoint_step(steps) is None

    # With numeric step_index
    steps = [
        {"step_index": 0, "type": "USER_INPUT"},
        {"step_index": 5, "type": "CHECKPOINT"},
        {"step_index": 12, "type": "CORTEX_STEP_TYPE_CHECKPOINT"},
        {"step_index": 15, "type": "MODEL_OUTPUT"},
    ]
    assert common.latest_checkpoint_step(steps) == 12

    # String numeric step_index
    steps = [
        {"step_index": "7", "type": "CHECKPOINT"},
        {"step_index": "20", "type": "CORTEX_STEP_TYPE_CHECKPOINT"},
    ]
    assert common.latest_checkpoint_step(steps) == 20

    # Fallback to list index when step_index missing
    steps = [
        {"type": "USER_INPUT"},
        {"type": "CHECKPOINT"},
    ]
    assert common.latest_checkpoint_step(steps) == 1


def test_render_template() -> None:
    """Verify render_template replaces placeholders and raises KeyError on missing keys."""
    template = "Hello {{ name }}, welcome to {{ project }}! Escaped: {{  spaces  }}."
    rendered = common.render_template(
        template,
        {"name": "Alice", "project": "PA", "spaces": "clean"},
    )
    assert rendered == "Hello Alice, welcome to PA! Escaped: clean."

    with pytest.raises(KeyError, match="missing"):
        common.render_template("Hello {{ missing }}", {})


def test_templates_dir() -> None:
    """Verify templates_dir returns the expected templates path."""
    tdir = common.templates_dir()
    assert tdir.name == "templates"
    assert "principal-architect" in str(tdir)


def test_fake_runner_scripting(fake_runner: FakeRunner) -> None:
    """Verify FakeRunner records calls and matches prefix responses."""
    fake_runner.set_response(["git", "status"], returncode=0, stdout="clean")
    fake_runner.set_response(["gh", "auth", "status"], returncode=1, stderr="unauthenticated")

    res1 = fake_runner(["git", "status", "--short"])
    assert res1.returncode == 0
    assert res1.stdout == "clean"

    res2 = fake_runner(["gh", "auth", "status"])
    assert res2.returncode == 1
    assert res2.stderr == "unauthenticated"

    assert len(fake_runner.calls) == 2
    assert fake_runner.calls[0] == ["git", "status", "--short"]


# =============================================================================
# StateDB & Registry Tests (WO-01.4)
# =============================================================================

from state_db import SCHEMA_VERSION, TABLES, Registry, StateDB, utc_now_iso


def test_state_db_constants() -> None:
    """Verify TABLES tuple and SCHEMA_VERSION."""
    assert TABLES == (
        "repo_config",
        "sessions",
        "verification_receipts",
        "escalations",
        "attention_queue",
    )
    assert SCHEMA_VERSION == 1
    ts = utc_now_iso()
    assert ts.endswith("Z")
    assert "T" in ts


def test_state_db_table_schemas_and_pragmas(tmp_path: Path) -> None:
    """Verify PRAGMA journal_mode, busy_timeout, user_version, and table schemas."""
    db_file = tmp_path / "subdir" / "state.db"
    with StateDB(db_file) as db:
        # Check pragmas
        cur = db.conn.execute("PRAGMA journal_mode;")
        assert cur.fetchone()[0].lower() == "wal"

        cur = db.conn.execute("PRAGMA busy_timeout;")
        assert cur.fetchone()[0] == 5000

        cur = db.conn.execute("PRAGMA user_version;")
        assert cur.fetchone()[0] == 1

        # Check table schemas
        expected_columns = {
            "repo_config": {"key", "value"},
            "sessions": {
                "conversation_id",
                "role",
                "programme_id",
                "pr_id",
                "wo_id",
                "attempt_num",
                "structural_failures",
                "pinned",
                "last_checkpoint_step",
                "created_at",
                "updated_at",
            },
            "verification_receipts": {
                "receipt_id",
                "wo_id",
                "pr_id",
                "cmd",
                "exit_code",
                "tree_hash",
                "git_head_sha",
                "valid",
                "created_at",
            },
            "escalations": {
                "escalation_id",
                "level",
                "source_role",
                "target_role",
                "pr_id",
                "wo_id",
                "blocker_type",
                "reason_code",
                "requested_files_json",
                "summary",
                "status",
                "github_issue_or_comment_url",
                "created_at",
                "resolved_at",
            },
            "attention_queue": {
                "item_id",
                "priority",
                "kind",
                "pr_id",
                "wo_id",
                "title",
                "action_payload_json",
                "status",
                "created_at",
            },
        }

        for table, cols in expected_columns.items():
            cur = db.conn.execute(f"PRAGMA table_info({table});")
            actual_cols = {row[1] for row in cur.fetchall()}
            assert actual_cols == cols, f"Mismatch in columns for {table}: {actual_cols} != {cols}"

    # Verify idempotency on reopen
    with StateDB(db_file) as db:
        db.init()
        cur = db.conn.execute("PRAGMA user_version;")
        assert cur.fetchone()[0] == 1


def test_state_db_repo_config(tmp_path: Path) -> None:
    """Verify repo_config get_config default, set_config insert/upsert, and get_all_config."""
    with StateDB(tmp_path / "test.db") as db:
        assert db.get_config("missing") is None
        assert db.get_config("missing", "default_val") == "default_val"

        db.set_config("execution_mode", "monitored")
        assert db.get_config("execution_mode") == "monitored"

        # Upsert
        db.set_config("execution_mode", "autonomous")
        assert db.get_config("execution_mode") == "autonomous"

        db.set_config("vcs_mode", "github")
        all_cfg = db.get_all_config()
        assert all_cfg == {
            "execution_mode": "autonomous",
            "vcs_mode": "github",
        }


def test_state_db_sessions(tmp_path: Path) -> None:
    """Verify sessions bind_session insert/upsert, get_session, and update_session."""
    with StateDB(tmp_path / "test.db") as db:
        cid = "conv-123"
        assert db.get_session(cid) is None

        # Bind session
        row = db.bind_session(
            cid,
            role="pa-engineer",
            programme_id="prog-1",
            pr_id="PR-01",
            wo_id="WO-01.4",
            attempt_num=1,
            structural_failures=0,
            pinned=True,
            last_checkpoint_step=42,
        )
        assert row["conversation_id"] == cid
        assert row["role"] == "pa-engineer"
        assert row["pinned"] == 1
        assert row["last_checkpoint_step"] == 42
        created_at = row["created_at"]
        assert created_at is not None

        # Upsert session
        row2 = db.bind_session(
            cid,
            role="pa-engineer",
            pr_id="PR-01",
            wo_id="WO-01.4",
            attempt_num=2,
            structural_failures=1,
            pinned=False,
            last_checkpoint_step=45,
        )
        assert row2["attempt_num"] == 2
        assert row2["structural_failures"] == 1
        assert row2["pinned"] == 0
        assert row2["created_at"] == created_at

        # Update session
        updated = db.update_session(cid, attempt_num=3, pinned=True)
        assert updated is not None
        assert updated["attempt_num"] == 3
        assert updated["pinned"] == 1
        assert updated["updated_at"] >= row2["updated_at"]

        # Update nonexistent
        assert db.update_session("nonexistent", attempt_num=1) is None

        # Invalid field
        with pytest.raises(ValueError, match="Invalid sessions column"):
            db.update_session(cid, invalid_column="foo")

        # Immutable field
        with pytest.raises(ValueError, match="Cannot update immutable column"):
            db.update_session(cid, created_at="foo")


def test_state_db_verification_receipts(tmp_path: Path) -> None:
    """Verify verification_receipts insert, query, filter, and invalidation."""
    with StateDB(tmp_path / "test.db") as db:
        r1 = db.insert_receipt(
            wo_id="WO-01.4",
            pr_id="PR-01",
            cmd="pytest",
            exit_code=0,
            tree_hash="hash_a",
            git_head_sha="sha_a",
        )
        assert r1["receipt_id"].startswith("rcpt_")
        assert r1["valid"] == 1

        r2 = db.insert_receipt(
            wo_id="WO-01.4",
            pr_id="PR-01",
            cmd="pytest",
            exit_code=0,
            tree_hash="hash_b",
            git_head_sha="sha_b",
        )

        # latest_valid_receipt without tree_hash returns r2
        latest = db.latest_valid_receipt("WO-01.4")
        assert latest is not None
        assert latest["receipt_id"] == r2["receipt_id"]

        # latest_valid_receipt with tree_hash matches specific hash
        match_a = db.latest_valid_receipt("WO-01.4", tree_hash="hash_a")
        assert match_a is not None
        assert match_a["receipt_id"] == r1["receipt_id"]

        # Nonexistent tree_hash
        assert db.latest_valid_receipt("WO-01.4", tree_hash="nonexistent") is None

        # Invalidate receipts
        count = db.invalidate_receipts("WO-01.4")
        assert count == 2
        assert db.latest_valid_receipt("WO-01.4") is None


def test_state_db_escalations(tmp_path: Path) -> None:
    """Verify escalations insert, query with filters, and resolve."""
    with StateDB(tmp_path / "test.db") as db:
        e1 = db.insert_escalation(
            level="tier_3_to_tier_2",
            source_role="pa-engineer",
            target_role="pa-principal-architect",
            pr_id="PR-01",
            wo_id="WO-01.4",
            blocker_type="boundary_expansion",
            reason_code="EXTRA_FILE_NEEDED",
            requested_files=["foo.py", "bar.py"],
            summary="Need extra files",
        )
        assert e1["escalation_id"].startswith("esc_")
        assert json.loads(e1["requested_files_json"]) == ["foo.py", "bar.py"]
        assert e1["status"] == "OPEN"
        assert e1["resolved_at"] is None

        e2 = db.insert_escalation(
            level="tier_2_to_tier_1",
            source_role="pa-principal-architect",
            target_role="pa-chief-architect",
            pr_id="PR-01",
            wo_id=None,
            summary="Charter amendment needed",
        )

        open_all = db.open_escalations()
        assert len(open_all) == 2

        # Filter by wo_id
        open_wo = db.open_escalations(wo_id="WO-01.4")
        assert len(open_wo) == 1
        assert open_wo[0]["escalation_id"] == e1["escalation_id"]

        # Filter by target_role
        open_chief = db.open_escalations(target_role="pa-chief-architect")
        assert len(open_chief) == 1
        assert open_chief[0]["escalation_id"] == e2["escalation_id"]

        # Resolve escalation
        resolved = db.resolve_escalation(e1["escalation_id"])
        assert resolved is not None
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_at"] is not None

        # Check open count after resolution
        assert len(db.open_escalations(wo_id="WO-01.4")) == 0
        assert len(db.open_escalations()) == 1

        # Resolve nonexistent
        assert db.resolve_escalation("nonexistent") is None


def test_state_db_attention_queue(tmp_path: Path) -> None:
    """Verify attention_queue enqueue, list_open priority order, and dequeue."""
    with StateDB(tmp_path / "test.db") as db:
        # Enqueue with different priorities (lower number = higher priority)
        item_low = db.enqueue(
            kind="info",
            title="Low priority item",
            priority=20,
            pr_id="PR-01",
        )
        item_high = db.enqueue(
            kind="blocker",
            title="High priority item",
            priority=5,
            pr_id="PR-01",
            action_payload={"reason": "need approval"},
        )
        item_other_pr = db.enqueue(
            kind="review",
            title="PR-02 item",
            priority=10,
            pr_id="PR-02",
        )

        # list_open for PR-01
        pr1_items = db.list_open(pr_id="PR-01")
        assert len(pr1_items) == 2
        assert pr1_items[0]["item_id"] == item_high["item_id"]
        assert pr1_items[1]["item_id"] == item_low["item_id"]
        assert json.loads(pr1_items[0]["action_payload_json"]) == {"reason": "need approval"}

        # list_open all
        all_items = db.list_open()
        assert len(all_items) == 3
        assert [i["item_id"] for i in all_items] == [
            item_high["item_id"],
            item_other_pr["item_id"],
            item_low["item_id"],
        ]

        # Dequeue
        dq = db.dequeue(item_high["item_id"])
        assert dq is not None
        assert dq["status"] == "RESOLVED"
        assert len(db.list_open(pr_id="PR-01")) == 1

        # Dequeue nonexistent
        assert db.dequeue("nonexistent") is None


def test_registry_operations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Registry register, idempotency, lookup, list, unregister, and common.is_repo_enrolled."""
    daemon_dir = tmp_path / "daemon_home"
    monkeypatch.setenv("PA_DAEMON_HOME", str(daemon_dir))

    reg = Registry()
    assert reg.path == daemon_dir / "state" / "registry.json"
    assert reg.list() == {}

    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    (repo1 / ".git").mkdir()

    # Register repo1
    entry = reg.register(repo1)
    real_repo1 = str(repo1.resolve())
    assert entry["slug"] == "repo1"
    assert entry["enrolled_at"] is not None
    assert real_repo1 in reg.list()

    # Verify common.is_repo_enrolled returns True
    assert common.is_repo_enrolled([repo1])

    # Idempotent re-register preserves enrolled_at
    time.sleep(0.01)
    entry2 = reg.register(repo1)
    assert entry2["enrolled_at"] == entry["enrolled_at"]

    # Lookup
    lookup_res = reg.lookup(repo1)
    assert lookup_res is not None
    assert lookup_res["slug"] == "repo1"

    # Unregister
    assert reg.unregister(repo1) is True
    assert not common.is_repo_enrolled([repo1])
    assert reg.lookup(repo1) is None
    assert reg.unregister(repo1) is False


def test_registry_missing_or_corrupt_file(tmp_path: Path) -> None:
    """Verify Registry handles corrupt JSON gracefully by resetting to empty."""
    reg_file = tmp_path / "state" / "registry.json"
    reg_file.parent.mkdir(parents=True, exist_ok=True)
    reg_file.write_text("corrupted json content", encoding="utf-8")

    reg = Registry(reg_file)
    assert reg.list() == {}
    assert reg.lookup(tmp_path) is None

    # Register should overwrite cleanly
    repo = tmp_path / "my_repo"
    repo.mkdir()
    reg.register(repo)
    assert str(repo.resolve()) in reg.list()
