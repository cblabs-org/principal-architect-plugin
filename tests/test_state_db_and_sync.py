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
