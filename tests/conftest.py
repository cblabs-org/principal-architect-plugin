"""Shared pytest fixtures for principal-architect-plugin."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import common
import pytest


@pytest.fixture
def sample_fixture() -> bool:
    """Placeholder fixture for initial smoke tests."""
    return True


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create an isolated, initialized git repository on branch main with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    # Initialize repository
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True
    )

    # Write initial README and commit
    readme = repo / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=repo, check=True, capture_output=True
    )

    return repo.resolve()


@pytest.fixture
def daemon_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create isolated fake HOME and PA_DAEMON_HOME directories and set env vars."""
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    d_home = tmp_path / "pa-daemon"
    d_home.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(fake_home.resolve()))
    monkeypatch.setenv("PA_DAEMON_HOME", str(d_home.resolve()))

    return d_home.resolve()


class FakeRunner:
    """Scriptable runner for commands with fallback to common.run."""

    def __init__(self, fallback: common.Runner = common.run) -> None:
        self.fallback = fallback
        self.calls: list[list[str]] = []
        self._responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]] = {}

    def set_response(
        self,
        prefix: Sequence[str],
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        key = tuple(prefix)
        self._responses[key] = subprocess.CompletedProcess(
            args=list(prefix),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def __call__(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd_list = [str(c) for c in cmd]
        self.calls.append(cmd_list)

        # Look for longest matching prefix
        cmd_tuple = tuple(cmd_list)
        for prefix_len in range(len(cmd_tuple), 0, -1):
            sub = cmd_tuple[:prefix_len]
            if sub in self._responses:
                resp = self._responses[sub]
                return subprocess.CompletedProcess(
                    args=cmd_list,
                    returncode=resp.returncode,
                    stdout=resp.stdout,
                    stderr=resp.stderr,
                )

        return self.fallback(
            cmd,
            cwd=cwd,
            env=env,
            timeout=timeout,
            input_text=input_text,
        )


@pytest.fixture
def fake_runner() -> FakeRunner:
    """Fixture providing a scriptable FakeRunner instance."""
    return FakeRunner()
