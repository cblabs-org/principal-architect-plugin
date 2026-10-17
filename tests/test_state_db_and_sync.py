"""Principal Architect Plugin (c) 2026 Matt McNeill
https://github.com/matthewmcneill/principal-architect-plugin
SPDX-License-Identifier: Apache-2.0

Module: tests/test_state_db_and_sync.py

Responsibility:
    Unit, integration, and dogfood tests for the zero-dependency stdlib foundation
    (`common.py`), SQLite WAL state database and global repository registry
    (`state_db.py`), and `pa_cli.py` enrollment, migration, mode, sync, and status
    subcommands.

Test Suite Coverage Summary:
    1. Stdlib Foundations (`common.py`):
       - `test_sqlite_available`, `test_common_import_purity`: Verify stdlib-only
         imports (zero `pydantic`/`yaml` leakage) and SQLite WAL support.
       - `test_find_repo_root`, `test_find_repo_root_fallback`,
         `test_workspace_dir_resolution`, `test_workspace_dir_dogfood`: Verify Git
         root discovery, `file://` URI handling, and workspace path precedence.
       - `test_daemon_home`, `test_is_repo_enrolled`: Verify `PA_DAEMON_HOME`
         resolution and `< 1 ms` enrollment checks.
       - `test_read_transcript`, `test_latest_checkpoint_step`,
         `test_render_template`, `test_templates_dir`, `test_fake_runner_scripting`:
         Verify transcript JSONL parsing, Mustache template rendering, and `FakeRunner`.
    2. SQLite WAL `StateDB` & Global `Registry` (`state_db.py`):
       - `test_state_db_constants`, `test_state_db_table_schemas_and_pragmas`: Verify
         WAL journal mode, `busy_timeout = 5000`, `user_version = 1`, and 5 table schemas.
       - `test_state_db_repo_config`, `test_state_db_sessions`,
         `test_state_db_verification_receipts`, `test_state_db_escalations`,
         `test_state_db_attention_queue`: Verify CRUD, filtering, receipt invalidation,
         and priority ordering across all 5 tables.
       - `test_registry_operations`, `test_registry_missing_or_corrupt_file`: Verify
         idempotent registration, lookup, unregistration, and corrupt-file recovery.
    3. `pa` CLI Lifecycle, Enrollment, Migration & Dogfood (`pa_cli.py`):
       - `test_pa_cli_lazy_import_purity`, `test_pa_cli_command_modules_extension`:
         Verify lazy schema imports and dynamic subcommand registration.
       - `test_enroll_explicit_2x2_matrix`, `test_enroll_autodetect_memory_and_vcs_modes`,
         `test_enroll_manifests_idempotency_and_memory_preservation`: Verify `(external |
         builtin) x (github | local_git)` enrollment and manifest generation.
       - `test_enroll_legacy_migration_tracked_untracked_and_conflict`,
         `test_enroll_non_git_directory_and_unenroll_via_wrappers`,
         `test_pa_migrate_and_enroll_with_migrate_and_repo_memory_bridge`: Verify legacy
         workspace migration, `enroll.sh`/`unenroll.sh` wrappers, and `repo-memory` seeding.
       - `test_pa_mode_get_set_and_invalid`, `test_pa_status_synthetic_and_dogfood`,
         `test_dogfood_self_enroll_sync_and_status_on_repo_workspace`: Verify `pa mode`,
         `pa sync`, and `pa status --json` against synthetic and live dogfood workspaces.
"""

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
    """Verify workspace_dir on this repository resolves to the migrated plugins workspace."""
    repo_root = common.find_repo_root(Path(__file__).resolve())
    assert repo_root is not None
    ws = common.workspace_dir(repo_root)
    assert ws.exists()
    assert ws == repo_root / common.NEW_WORKSPACE_REL
    assert not (repo_root / common.LEGACY_WORKSPACE_REL).exists()


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


# =============================================================================
# pa_cli.py (enroll, unenroll, status, mode), Wrapper Scripts & README (WO-01.6)
# =============================================================================

import types as py_types

import pa_cli


def test_pa_cli_lazy_import_purity(tmp_repo: Path, daemon_home: Path) -> None:
    """Verify importing pa_cli and running --help or mode does NOT import pydantic, yaml, or schemas."""
    scripts_dir = str(Path(pa_cli.__file__).resolve().parent)
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{scripts_dir}:{existing_pythonpath}" if existing_pythonpath else scripts_dir

    code = (
        "import sys, pa_cli\n"
        "assert 'pydantic' not in sys.modules\n"
        "assert 'yaml' not in sys.modules\n"
        "assert 'schemas' not in sys.modules\n"
        "assert pa_cli.main(['--help']) == 0\n"
        f"assert pa_cli.main(['mode', '--path', {str(tmp_repo)!r}]) == 0\n"
        "assert 'pydantic' not in sys.modules\n"
        "assert 'yaml' not in sys.modules\n"
        "assert 'schemas' not in sys.modules\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert res.returncode == 0, f"Lazy import check failed:\nstdout: {res.stdout}\nstderr: {res.stderr}"

    # Verify direct script execution works without PYTHONPATH
    clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    script_res = subprocess.run(
        [str(Path(pa_cli.__file__).resolve()), "--help"],
        capture_output=True,
        text=True,
        env=clean_env,
        check=False,
    )
    assert script_res.returncode == 0
    assert "enroll" in script_res.stdout


def test_pa_cli_command_modules_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify build_parser() dynamically registers subcommands from COMMAND_MODULES."""
    ext_mod = py_types.ModuleType("_test_pa_ext_mod")

    def _register(subparsers: object) -> None:
        sub = subparsers.add_parser("custom-ext", help="Custom extension command")  # type: ignore[attr-defined]
        sub.set_defaults(func=lambda _args, **_kw: 42)

    ext_mod.register = _register  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "_test_pa_ext_mod", ext_mod)
    monkeypatch.setattr(pa_cli, "COMMAND_MODULES", ["_test_pa_ext_mod"])

    assert pa_cli.main(["custom-ext"]) == 42
    assert pa_cli.main([]) == 1
    assert pa_cli.main(["--unknown-flag"]) == 1


@pytest.mark.parametrize("mem_mode", ["external", "builtin"])
@pytest.mark.parametrize("vcs_mode", ["github", "local_git"])
def test_enroll_explicit_2x2_matrix(
    tmp_path: Path,
    daemon_home: Path,
    fake_runner: FakeRunner,
    mem_mode: str,
    vcs_mode: str,
) -> None:
    """Verify pa enroll across the explicit (external|builtin) x (github|local_git) 2x2 matrix."""
    repo = tmp_path / f"repo_{mem_mode}_{vcs_mode}"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)

    rc = pa_cli.main(
        [
            "enroll",
            str(repo),
            "--memory-mode",
            mem_mode,
            "--vcs-mode",
            vcs_mode,
        ],
        runner=fake_runner,
    )
    assert rc == 0

    ws_dir = repo.resolve() / common.NEW_WORKSPACE_REL
    assert ws_dir.is_dir()
    assert (ws_dir / ".gitignore").read_text(encoding="utf-8").strip() == ".state/"

    with StateDB(ws_dir / ".state" / "state.db") as db:
        assert db.get_config("memory_mode") == mem_mode
        assert db.get_config("vcs_mode") == vcs_mode
        assert db.get_config("execution_mode") == "monitored"

    mem_dir = ws_dir / "memory"
    if mem_mode == "builtin":
        assert (mem_dir / "MEMORY.md").is_file()
        assert (mem_dir / "MODULE_INDEX.md").is_file()
        assert (mem_dir / "PROJECT_INDEX.md").is_file()
        assert "{{" not in (mem_dir / "MEMORY.md").read_text(encoding="utf-8")
    else:
        assert not mem_dir.exists()

    # Check plugins.json and .git/info/exclude
    plugins_data = json.loads((repo / ".agents" / "plugins.json").read_text(encoding="utf-8"))
    assert plugins_data == {"entries": [{"path": str(daemon_home / "workspace-plugin")}]}
    exclude_text = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert ".agents/plugins.json" in exclude_text.splitlines()
    assert common.is_repo_enrolled([repo])


def test_enroll_autodetect_memory_and_vcs_modes(
    tmp_path: Path,
    daemon_home: Path,
    fake_runner: FakeRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify auto-detection of memory_mode (3 external signals + builtin) and vcs_mode (origin + gh)."""
    # 1. Default repo: no .memory, no origin -> builtin + local_git
    r1 = tmp_path / "r1"
    r1.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=r1, check=True, capture_output=True)
    fake_runner.set_response(["git", "remote", "get-url", "origin"], returncode=1)
    assert pa_cli.detect_memory_mode(r1) == "builtin"
    assert pa_cli.detect_vcs_mode(r1, runner=fake_runner) == "local_git"

    # 2. Signal 1: .memory directory exists -> external
    r2 = tmp_path / "r2"
    (r2 / ".memory").mkdir(parents=True)
    assert pa_cli.detect_memory_mode(r2) == "external"

    # 3. Signal 2: .agents/plugins.json references repo-memory -> external
    r3 = tmp_path / "r3"
    (r3 / ".agents").mkdir(parents=True)
    (r3 / ".agents" / "plugins.json").write_text(
        json.dumps({"entries": [{"path": "/opt/plugins/repo-memory-daemon/workspace-plugin"}]}),
        encoding="utf-8",
    )
    assert pa_cli.detect_memory_mode(r3) == "external"

    # 4. Signal 3: $HOME/.gemini/config/plugins/repo-memory-daemon/state/registry.json lists repo -> external
    r4 = tmp_path / "r4"
    r4.mkdir()
    rm_reg = (
        Path(os.environ["HOME"])
        / ".gemini"
        / "config"
        / "plugins"
        / "repo-memory-daemon"
        / "state"
        / "registry.json"
    )
    rm_reg.parent.mkdir(parents=True, exist_ok=True)
    rm_reg.write_text(
        json.dumps({"repos": {str(r4.resolve()): {"enrolled_at": "2026-10-16T00:00:00Z"}}}),
        encoding="utf-8",
    )
    assert pa_cli.detect_memory_mode(r4) == "external"

    # 5. VCS mode: github.com origin + gh auth status == 0 (honoring PA_GH_BIN)
    monkeypatch.setenv("PA_GH_BIN", "custom-gh")
    fake_runner.set_response(
        ["git", "remote", "get-url", "origin"],
        returncode=0,
        stdout="https://github.com/org/repo.git\n",
    )
    fake_runner.set_response(["custom-gh", "auth", "status"], returncode=0, stdout="Logged in")
    assert pa_cli.detect_vcs_mode(r1, runner=fake_runner) == "github"

    # If gh auth status fails -> local_git
    fake_runner.set_response(["custom-gh", "auth", "status"], returncode=1, stderr="Not logged in")
    assert pa_cli.detect_vcs_mode(r1, runner=fake_runner) == "local_git"


def test_enroll_manifests_idempotency_and_memory_preservation(
    tmp_repo: Path,
    daemon_home: Path,
    fake_runner: FakeRunner,
) -> None:
    """Verify generated manifests, extra_skill/exclude_rule persistence, and non-destructive re-enroll."""
    fake_runner.set_response(["git", "remote", "get-url", "origin"], returncode=1)

    # First enroll with --extra-skill and --exclude-rule
    rc1 = pa_cli.main(
        [
            "enroll",
            str(tmp_repo),
            "--memory-mode",
            "builtin",
            "--extra-skill",
            "pio",
            "--extra-skill",
            "pio",  # duplicate should be deduplicated
            "--exclude-rule",
            "custom-rule-*",
        ],
        runner=fake_runner,
    )
    assert rc1 == 0

    ws_dir = tmp_repo / common.NEW_WORKSPACE_REL
    skills_manifest = json.loads((ws_dir / ".state" / "pa-skills.json").read_text(encoding="utf-8"))
    user_cfg = Path(os.path.realpath(Path.home())) / ".gemini" / "config"
    assert skills_manifest == {
        "entries": [
            {"path": str(tmp_repo / ".agents" / "skills")},
            {"path": str(user_cfg / "skills"), "include_only": ["pio"]},
        ]
    }

    rules_manifest = json.loads(
        (ws_dir / ".state" / "pa-worker-rules.json").read_text(encoding="utf-8")
    )
    assert rules_manifest == {
        "entries": [
            {
                "path": str(tmp_repo / ".agents" / "rules"),
                "exclude": ["01-plan-before-execute.md", "bug-fixer-*", "custom-rule-*"],
            }
        ]
    }

    # Customize MEMORY.md and switch mode to autonomous
    mem_md = ws_dir / "memory" / "MEMORY.md"
    mem_md.write_text("# Custom Memory Content\n", encoding="utf-8")
    assert pa_cli.main(["mode", "autonomous", "--path", str(tmp_repo)], runner=fake_runner) == 0

    reg_before = Registry().lookup(tmp_repo)
    assert reg_before is not None

    # Re-enroll without flags: must preserve MEMORY.md, execution_mode, enrolled_at, extra_skills, exclude_rules
    rc2 = pa_cli.main(["enroll", str(tmp_repo)], runner=fake_runner)
    assert rc2 == 0

    assert mem_md.read_text(encoding="utf-8") == "# Custom Memory Content\n"
    reg_after = Registry().lookup(tmp_repo)
    assert reg_after is not None
    assert reg_after["enrolled_at"] == reg_before["enrolled_at"]

    with StateDB(ws_dir / ".state" / "state.db") as db:
        assert db.get_config("execution_mode") == "autonomous"
        assert json.loads(db.get_config("extra_skills_json") or "[]") == ["pio"]
        assert json.loads(db.get_config("exclude_rules_json") or "[]") == ["custom-rule-*"]

    # Check no duplicate lines in .gitignore, .git/info/exclude, or .agents/plugins.json
    assert (ws_dir / ".gitignore").read_text(encoding="utf-8").splitlines() == [".state/"]
    exclude_lines = [
        ln
        for ln in (tmp_repo / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
        if ln.strip() == ".agents/plugins.json"
    ]
    assert len(exclude_lines) == 1
    plugins_entries = json.loads(
        (tmp_repo / ".agents" / "plugins.json").read_text(encoding="utf-8")
    )["entries"]
    assert len(plugins_entries) == 1


def test_enroll_legacy_migration_tracked_untracked_and_conflict(
    tmp_path: Path,
    daemon_home: Path,
    fake_runner: FakeRunner,
) -> None:
    """Verify legacy .agents/skills/principal-architect-workspace migration (tracked, untracked, conflict)."""
    fake_runner.set_response(["git", "remote", "get-url", "origin"], returncode=1)

    # 1. Tracked legacy workspace -> moved via git mv
    repo_tracked = tmp_path / "repo_tracked"
    repo_tracked.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_tracked, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_tracked, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo_tracked, check=True)

    legacy_dir = repo_tracked / common.LEGACY_WORKSPACE_REL
    legacy_dir.mkdir(parents=True)
    marker = legacy_dir / "marker.md"
    marker.write_text("tracked content\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_tracked, check=True)
    subprocess.run(["git", "commit", "-m", "Add legacy"], cwd=repo_tracked, check=True)

    assert pa_cli.main(["enroll", str(repo_tracked)], runner=fake_runner) == 0
    assert not legacy_dir.exists()
    assert (repo_tracked / common.NEW_WORKSPACE_REL / "marker.md").is_file()
    assert any(c[:2] == ["git", "mv"] for c in fake_runner.calls)

    # 2. Untracked legacy workspace -> moved via filesystem move
    repo_untracked = tmp_path / "repo_untracked"
    repo_untracked.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_untracked, check=True, capture_output=True)
    untracked_legacy = repo_untracked / common.LEGACY_WORKSPACE_REL
    untracked_legacy.mkdir(parents=True)
    (untracked_legacy / "note.md").write_text("untracked\n", encoding="utf-8")

    assert pa_cli.main(["enroll", str(repo_untracked)], runner=fake_runner) == 0
    assert not untracked_legacy.exists()
    assert (repo_untracked / common.NEW_WORKSPACE_REL / "note.md").is_file()

    # 3. Conflict: both legacy and new exist -> abort with exit code 2
    repo_conflict = tmp_path / "repo_conflict"
    repo_conflict.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_conflict, check=True, capture_output=True)
    (repo_conflict / common.LEGACY_WORKSPACE_REL).mkdir(parents=True)
    (repo_conflict / common.NEW_WORKSPACE_REL).mkdir(parents=True)

    rc_conflict = pa_cli.main(["enroll", str(repo_conflict)], runner=fake_runner)
    assert rc_conflict == 2


def test_enroll_non_git_directory_and_unenroll_via_wrappers(
    tmp_path: Path,
    daemon_home: Path,
) -> None:
    """Verify pa enroll runs git init on a non-git dir, and enroll.sh / unenroll.sh wrappers work."""
    plain_dir = tmp_path / "plain_dir"
    plain_dir.mkdir()

    # Pre-populate another plugin in .agents/plugins.json to ensure unenroll preserves it
    (plain_dir / ".agents").mkdir()
    (plain_dir / ".agents" / "plugins.json").write_text(
        json.dumps({"entries": [{"path": "/other/plugin"}]}),
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parent.parent
    enroll_sh = repo_root / "scripts" / "enroll.sh"
    unenroll_sh = repo_root / "scripts" / "unenroll.sh"

    res_enroll = subprocess.run(
        [str(enroll_sh), str(plain_dir), "--vcs-mode", "local_git", "--memory-mode", "builtin"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_enroll.returncode == 0, res_enroll.stderr
    assert (plain_dir / ".git").is_dir()
    assert common.is_repo_enrolled([plain_dir])

    # Unenroll via wrapper script
    res_unenroll = subprocess.run(
        [str(unenroll_sh), str(plain_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_unenroll.returncode == 0, res_unenroll.stderr
    assert not common.is_repo_enrolled([plain_dir])

    # Verify other plugin preserved in plugins.json and workspace files remain intact
    pdata = json.loads((plain_dir / ".agents" / "plugins.json").read_text(encoding="utf-8"))
    assert pdata == {"entries": [{"path": "/other/plugin"}]}
    assert (plain_dir / common.NEW_WORKSPACE_REL / "memory" / "MEMORY.md").is_file()

    # Nonexistent directory returns exit code 2
    assert pa_cli.main(["enroll", str(tmp_path / "does_not_exist")]) == 2


def test_pa_mode_get_set_and_invalid(
    tmp_repo: Path,
    daemon_home: Path,
    fake_runner: FakeRunner,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Verify pa mode get, set, and rejection of invalid values."""
    # Default before enrollment
    assert pa_cli.main(["mode", "--path", str(tmp_repo)], runner=fake_runner) == 0
    assert capsys.readouterr().out.strip() == "monitored"

    # Set autonomous
    assert pa_cli.main(["mode", "autonomous", "--path", str(tmp_repo)], runner=fake_runner) == 0
    assert capsys.readouterr().out.strip() == "autonomous"

    # Query after set
    assert pa_cli.main(["mode", "--path", str(tmp_repo)], runner=fake_runner) == 0
    assert capsys.readouterr().out.strip() == "autonomous"

    # Set monitored
    assert pa_cli.main(["mode", "monitored", "--path", str(tmp_repo)], runner=fake_runner) == 0
    assert capsys.readouterr().out.strip() == "monitored"

    # Invalid mode value returns exit code 1
    assert pa_cli.main(["mode", "invalid_value", "--path", str(tmp_repo)], runner=fake_runner) == 1
    err = capsys.readouterr().err
    assert "Invalid execution mode" in err

    # Non-repo path returns exit code 2
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()
    assert pa_cli.main(["mode", "--path", str(non_repo)], runner=fake_runner) == 2


def test_pa_status_synthetic_and_dogfood(
    tmp_repo: Path,
    daemon_home: Path,
    fake_runner: FakeRunner,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify pa status and pa status --json on synthetic repo and dogfood on this repository."""
    fake_runner.set_response(["git", "remote", "get-url", "origin"], returncode=1)
    assert pa_cli.main(["enroll", str(tmp_repo)], runner=fake_runner) == 0

    ws_dir = tmp_repo / common.NEW_WORKSPACE_REL
    prog_dir = ws_dir / "programme-demo"
    prog_dir.mkdir(parents=True)
    (prog_dir / "PROGRAM.md").write_text(
        common.render_template_file(
            "PROGRAM",
            {"programme_id": "prog-demo", "title": "Demo Programme", "base_branch": "main"},
        ),
        encoding="utf-8",
    )

    pr_dir = ws_dir / "pr-01-demo"
    pr_dir.mkdir(parents=True)
    (pr_dir / "PROJECT.md").write_text(
        common.render_template_file(
            "PROJECT",
            {
                "pr_id": "PR-01",
                "programme_id": "prog-demo",
                "slug": "pr-01-demo",
                "title": "Demo PR",
                "branch": "feat/pr-01-demo",
                "base_branch": "main",
                "allowed_module": "src/",
                "verification_command": "pytest",
            },
        ),
        encoding="utf-8",
    )

    wo_dir = pr_dir / "wo1-slice"
    wo_dir.mkdir(parents=True)
    (wo_dir / "WORKORDER.md").write_text(
        common.render_template_file(
            "WORKORDER",
            {
                "wo_id": "WO-01.1",
                "pr_id": "PR-01",
                "title": "Demo Work Order",
                "complexity": "standard",
                "allowed_file": "src/app.py",
                "verification_command": "pytest",
            },
        ),
        encoding="utf-8",
    )

    (pr_dir / "AUDIT-round-1.md").write_text(
        common.render_template_file(
            "AUDIT",
            {
                "pr_id": "PR-01",
                "audit_round": 1,
                "head_sha": "1234567890abcdef",
                "auditor_harness": "cli",
                "verdict": "APPROVED",
            },
        ),
        encoding="utf-8",
    )

    with StateDB(ws_dir / ".state" / "state.db") as db:
        db.enqueue(kind="plan_approval", title="Approve PR-01 Plan", priority=5, pr_id="PR-01")

    capsys.readouterr()
    assert pa_cli.main(["status", str(tmp_repo)], runner=fake_runner) == 0
    human_out = capsys.readouterr().out
    assert "prog-demo" in human_out
    assert "PR-01" in human_out
    assert "WO-01.1" in human_out
    assert "Approve PR-01 Plan" in human_out

    assert pa_cli.main(["status", str(tmp_repo), "--json"], runner=fake_runner) == 0
    json_out = capsys.readouterr().out
    parsed = json.loads(json_out)
    assert parsed["env"]["vcs_mode"] == "local_git"
    assert len(parsed["programmes"]) == 1
    assert len(parsed["prs"]) == 1
    assert parsed["prs"][0]["latest_audit"]["verdict"] == "APPROVED"
    assert len(parsed["attention_queue"]) == 1

    # Dogfood test: run pa status --json against this repository root
    this_repo = Path(__file__).resolve().parent.parent
    had_state_db_before = (common.workspace_dir(this_repo) / ".state" / "state.db").exists()
    assert pa_cli.main(["status", str(this_repo), "--json"]) == 0
    dogfood_raw = capsys.readouterr().out
    # Assert zero emoji characters in --json output
    assert all(ord(ch) < 0x1F300 for ch in dogfood_raw), "Emoji detected in status --json output"
    dogfood_data = json.loads(dogfood_raw)
    assert set(dogfood_data.keys()) == {"env", "programmes", "prs", "attention_queue"}
    assert dogfood_data["programmes"][0]["programme_id"] == "prog-principal-architect-plugin"
    pr01 = next(p for p in dogfood_data["prs"] if p["pr_id"] == "PR-01")
    assert set(pr01.keys()) >= {
        "pr_id",
        "slug",
        "title",
        "status",
        "branch",
        "base_branch",
        "github_pr",
        "charter_locked",
        "work_orders",
    }
    wo_ids = [w["id"] for w in pr01["work_orders"]]
    assert wo_ids == ["WO-01.1", "WO-01.2", "WO-01.3", "WO-01.4", "WO-01.5", "WO-01.6"]
    # Verify git trailer reconciliation populated verified_hash on completed WOs
    wo5 = next(w for w in pr01["work_orders"] if w["id"] == "WO-01.5")
    assert wo5["verified_hash"] == "f7e857f8de69f2abdd453e4df6b07e69cd7bde4f"
    # Verify running pa status did NOT newly create .state/state.db if absent beforehand
    assert (common.workspace_dir(this_repo) / ".state" / "state.db").exists() == had_state_db_before


def test_dogfood_self_enroll_sync_and_status_on_repo_workspace(
    tmp_repo: Path,
    daemon_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify full dogfood enroll, sync, status --json, charter_hash, and spec_hash across PR-01..PR-05."""
    import shutil

    import schemas

    this_repo = Path(__file__).resolve().parent.parent
    repo_ws = common.workspace_dir(this_repo)
    assert repo_ws == this_repo / common.NEW_WORKSPACE_REL

    target_ws = tmp_repo / common.NEW_WORKSPACE_REL
    shutil.copytree(repo_ws, target_ws, ignore=shutil.ignore_patterns(".state"))

    capsys.readouterr()
    assert (
        pa_cli.main(
            ["enroll", str(tmp_repo), "--vcs-mode", "local_git", "--memory-mode", "builtin"]
        )
        == 0
    )
    capsys.readouterr()

    assert pa_cli.main(["sync", str(tmp_repo)]) == 0
    sync_summary = json.loads(capsys.readouterr().out)
    assert sync_summary["synced_receipts"] >= 18
    assert sync_summary["synced_audits"] >= 4
    assert sync_summary["synced_wos"] >= 18

    assert pa_cli.main(["status", str(tmp_repo), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["programmes"][0]["programme_id"] == "prog-principal-architect-plugin"
    assert [p["pr_id"] for p in payload["prs"]] == ["PR-01", "PR-02", "PR-03", "PR-04", "PR-05"]

    prs_by_id = {p["pr_id"]: p for p in payload["prs"]}
    for pid in ("PR-01", "PR-02", "PR-03", "PR-04"):
        p = prs_by_id[pid]
        assert p["status"] == "GRADUATED"
        assert p["charter_locked"] is True
        assert p["latest_audit"]["verdict"] == "APPROVED"

    pr05 = prs_by_id["PR-05"]
    assert pr05["charter_locked"] is True
    assert len(pr05["work_orders"]) == 3

    proj_files = sorted(target_ws.glob("pr-*/PROJECT.md"))
    assert len(proj_files) == 5
    for proj_md in proj_files:
        assert schemas.verify_charter_hash(proj_md) is True

    wo_files = sorted(target_ws.glob("pr-*/wo*/WORKORDER.md"))
    assert len(wo_files) >= 21
    for wo_md in wo_files:
        assert schemas.verify_spec_hash(wo_md) is True

    had_state_db_before = (repo_ws / ".state" / "state.db").exists()
    assert pa_cli.main(["status", str(this_repo), "--json"]) == 0
    live_payload = json.loads(capsys.readouterr().out)
    assert [p["pr_id"] for p in live_payload["prs"]] == [
        "PR-01",
        "PR-02",
        "PR-03",
        "PR-04",
        "PR-05",
    ]
    assert (repo_ws / ".state" / "state.db").exists() == had_state_db_before


def test_pa_migrate_and_enroll_with_migrate_and_repo_memory_bridge(
    tmp_path: Path,
    daemon_home: Path,
    fake_runner: FakeRunner,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify pa migrate and pa enroll --migrate merge legacy workspace, rewrite paths, and bridge repo-memory."""
    import pa_cli

    repo = tmp_path / "repo_migrate"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    fake_runner.set_response(["git", "remote", "get-url", "origin"], returncode=1)

    # Create both legacy .agents/skills/principal-architect-workspace and partial .agents/plugins/principal-architect-workspace
    legacy_ws = repo / common.LEGACY_WORKSPACE_REL
    new_ws = repo / common.NEW_WORKSPACE_REL
    (legacy_ws / "memory").mkdir(parents=True)
    (legacy_ws / "memory" / "MEMORY.md").write_text(
        "# Legacy Memory\nPath: .agents/skills/principal-architect-workspace/memory/MEMORY.md\n",
        encoding="utf-8",
    )
    (legacy_ws / "memory" / "MODULE_INDEX.md").write_text("# Legacy Modules\n", encoding="utf-8")
    (legacy_ws / "memory" / "PROJECT_INDEX.md").write_text("# Legacy Projects\n", encoding="utf-8")

    # Create legacy skill directory .agents/skills/principal-architect
    legacy_skill_dir = repo / ".agents" / "skills" / "principal-architect"
    legacy_skill_dir.mkdir(parents=True)
    (legacy_skill_dir / "SKILL.md").write_text("# Legacy Skill\n", encoding="utf-8")

    # Create partial new_ws and .agents/memory/config.json + .memory to simulate external repo-memory
    new_ws.mkdir(parents=True)
    (repo / ".memory").mkdir(parents=True)
    rm_cfg = repo / ".agents" / "memory" / "config.json"
    rm_cfg.parent.mkdir(parents=True, exist_ok=True)
    rm_cfg.write_text(
        json.dumps(
            {
                "doc_seeds": [
                    "SPEC.md",
                    ".agents/skills/principal-architect-workspace/memory",
                ]
            }
        ),
        encoding="utf-8",
    )

    fake_rm_bin = tmp_path / "fake-repo-memory"
    fake_rm_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_rm_bin.chmod(0o755)
    monkeypatch.setenv("PA_REPO_MEMORY_BIN", str(fake_rm_bin))
    fake_runner.set_response([str(fake_rm_bin), "seed"], returncode=0, stdout="seeded WOs")
    fake_runner.set_response([str(fake_rm_bin), "seed-docs"], returncode=0, stdout="seeded docs")
    fake_runner.set_response([str(fake_rm_bin), "index"], returncode=0, stdout="indexed")

    capsys.readouterr()
    rc = pa_cli.main(["migrate", str(repo), "--json"], runner=fake_runner)
    assert rc == 0
    mig_out = json.loads(capsys.readouterr().out)
    assert mig_out["removed_legacy_skill"] is True
    assert not legacy_skill_dir.exists()
    assert not legacy_ws.exists()
    assert mig_out["rewritten_markdown_files"] == 1
    migrated_mem = (new_ws / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert ".agents/plugins/principal-architect-workspace/memory/MEMORY.md" in migrated_mem
    assert ".agents/skills/principal-architect-workspace" not in migrated_mem
    assert mig_out["repo_memory"]["config_updated"] is True
    assert mig_out["repo_memory"]["seeded"] is True
    assert mig_out["repo_memory"]["commands_run"] == [
        "repo-memory seed",
        "repo-memory seed-docs",
        "repo-memory index",
    ]
    updated_cfg = json.loads(rm_cfg.read_text(encoding="utf-8"))
    assert updated_cfg["doc_seeds"] == [
        "SPEC.md",
        ".agents/plugins/principal-architect-workspace/memory",
    ]

    # Also verify pa enroll --migrate --execution-mode autonomous --auto-approve-pr-plans
    rc_enroll = pa_cli.main(
        [
            "enroll",
            str(repo),
            "--migrate",
            "--execution-mode",
            "autonomous",
            "--auto-approve-pr-plans",
        ],
        runner=fake_runner,
    )
    assert rc_enroll == 0
    with StateDB(new_ws / ".state" / "state.db") as db:
        assert db.get_config("execution_mode") == "autonomous"
        assert db.get_config("auto_approve_pr_plans") == "true"
        assert db.get_config("memory_mode") == "external"



