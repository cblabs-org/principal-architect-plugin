"""Principal Architect Plugin (c) 2026 Matt McNeill
https://github.com/matthewmcneill/principal-architect-plugin
SPDX-License-Identifier: Apache-2.0

Module: tests/conftest.py

Responsibility:
    Shared pytest fixtures and subprocess test doubles for the Principal Architect
    test suite. Provides isolated Git repositories, temporary daemon home
    directories with environment sandboxing, and a scriptable prefix-matching
    subprocess runner (`FakeRunner`) that falls back to `common.run`.

Exported Fixture & API Summary:
    Fixtures:
        - sample_fixture() -> bool: Baseline smoke-test fixture returning True.
        - tmp_repo(tmp_path) -> Path: Provision an initialized Git repository on
          branch `main` with a committed `README.md`.
        - daemon_home(tmp_path, monkeypatch) -> Path: Provision isolated `HOME` and
          `PA_DAEMON_HOME` directories and bind environment variables.
        - fake_runner() -> FakeRunner: Provide a fresh scriptable `FakeRunner`
          instance for mocking `git`, `gh`, or `repo-memory` CLI invocations.
    Classes:
        - FakeRunner: Callable subprocess runner double supporting longest-prefix
          canned responses with fallback to `common.run`.
            - __init__(fallback): Initialize call log, response map, and fallback.
            - set_response(prefix, *, returncode, stdout, stderr): Register a
              canned `CompletedProcess` for a command prefix.
            - __call__(cmd, *, cwd, env, timeout, input_text): Record command and
              return longest prefix match or delegate to `fallback`.
"""

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
    # --- Step 1: Create repository directory and initialize Git on branch `main` ---
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # --- Step 2: Seed initial README.md and create root commit ---
    readme = repo / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=repo, check=True, capture_output=True
    )

    # --- Step 3: Return canonical resolved repository path ---
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
        """Initialize the fake runner with an optional fallback runner.

        Args:
            fallback: Underlying `common.Runner` invoked when no canned prefix matches.
        """
        self.fallback = fallback  # Delegate runner used when no prefix response is registered.
        self.calls: list[list[str]] = []  # Ordered log of all argv lists passed to `__call__`.
        # Mapping from command prefix tuples to canned `CompletedProcess` responses.
        self._responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]] = {}

    def set_response(
        self,
        prefix: Sequence[str],
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        """Register a canned `CompletedProcess` result for commands matching `prefix`.

        Args:
            prefix: Leading command tokens to match against incoming invocations.
            returncode: Simulated process exit status code.
            stdout: Simulated standard output text.
            stderr: Simulated standard error text.
        """
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
        """Execute or intercept a subprocess command.

        Args:
            cmd: Command and argument sequence to execute.
            cwd: Optional working directory for the subprocess.
            env: Optional environment variable mapping.
            timeout: Maximum execution time in seconds.
            input_text: Optional standard input payload.

        Returns:
            A `subprocess.CompletedProcess[str]` from the longest matching canned
            prefix, or from `self.fallback` if no prefix matches.
        """
        # --- Step 1: Normalize command tokens and append to call history ---
        cmd_list = [str(c) for c in cmd]
        self.calls.append(cmd_list)

        # --- Step 2: Search registered responses for the longest matching prefix ---
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

        # --- Step 3: Delegate unmatched commands to the fallback runner ---
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
