---
schema_version: 1
wo_id: WO-01.1
pr_id: PR-01
title: "Developer toolchain bootstrap, pyproject.toml, plugin manifests, and test floor skeleton"
complexity: standard
status: IN_PROGRESS
allowed_files:
  - pyproject.toml
  - .gitignore
  - scripts/dev-bootstrap.sh
  - daemon/plugin.json
  - daemon/.gitignore
  - daemon/workspace-plugin/principal-architect/plugin.json
  - daemon/workspace-plugin/principal-architect/scripts/__init__.py
  - tests/conftest.py
  - tests/test_schemas.py
  - tests/test_state_db_and_sync.py
forbidden_files:
  - SPEC.md
  - docs/positioning-paper.md
  - .agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/PROJECT.md
  - .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: "./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests"
max_attempts: 5
max_structural_failures: 2
spec_hash: "c1eb7cb302d055459f145ec8e2e2f5434d14fae92152c07e2920432b77b00f0b"
completion: null
---

# WO-01.1 — Developer Toolchain Bootstrap & Package Skeleton

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-01` (`pr-01-core-schemas-and-enrollment`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T18:50:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Deliver the reproducible developer toolchain bootstrap (`scripts/dev-bootstrap.sh`) that creates `./.venv` and installs `-e .[dev]` on hosts with or without `pip`/`ensurepip`, alongside `pyproject.toml`, root and `daemon/` `.gitignore` files, the split-daemon plugin manifests (`daemon/plugin.json` and `daemon/workspace-plugin/principal-architect/plugin.json`), `scripts/__init__.py`, and initial smoke test files so the PR-01 verification floor (`./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests`) runs cleanly and exits `0`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `pyproject.toml`
  - `.gitignore`
  - `scripts/dev-bootstrap.sh`
  - `daemon/plugin.json`
  - `daemon/.gitignore`
  - `daemon/workspace-plugin/principal-architect/plugin.json`
  - `daemon/workspace-plugin/principal-architect/scripts/__init__.py`
  - `tests/conftest.py`
  - `tests/test_schemas.py`
  - `tests/test_state_db_and_sync.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/wo1-dev-bootstrap-and-package-skeleton/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh`. Commit only on the currently checked-out branch `pr-01-core-schemas-and-enrollment/wo1-dev-bootstrap-and-package-skeleton` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`pyproject.toml`:**
  - Configure `[build-system]` using `setuptools>=68` (`build-backend = "setuptools.build_meta"`).
  - Configure `[project]` with `name = "principal-architect-plugin"`, `version = "0.1.0"`, `description = "Mechanically enforced multi-tier orchestration plugin for Principal Architect workflows"`, `readme = "README.md"` (only if present, or omit `readme` so `pip install -e .[dev]` succeeds before `README.md` lands in `WO-01.6`!), `requires-python = ">=3.11"`, `dependencies = ["pydantic>=2,<3", "pyyaml>=6"]`, and `[project.optional-dependencies] dev = ["pytest>=8.0", "ruff>=0.4"]`.
  - Configure `[tool.setuptools.packages.find]` with `where = ["daemon/workspace-plugin/principal-architect"]` and `include = ["scripts*"]` so editable installs (`pip install -e ".[dev]"`) succeed cleanly.
  - Configure `[tool.pytest.ini_options]` with `testpaths = ["tests"]` and `pythonpath = ["daemon/workspace-plugin/principal-architect/scripts"]`.
  - Configure `[tool.ruff]` with `target-version = "py311"` and `line-length = 100`.
- [ ] **`.gitignore` (repository root):**
  - Ignore `.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`, `.eggs/`, `build/`, `dist/`, `*.db`, `*.db-shm`, `*.db-wal`, `.agents/plugins.json`, and `daemon/state/`.
- [ ] **`daemon/.gitignore`:**
  - Ignore `state/`, `__pycache__/`, `*.py[cod]`, and `*.egg-info/`.
- [ ] **`daemon/plugin.json`:**
  - Valid JSON object with `"name": "pa-daemon"`, `"version": "0.1.0"`, and `"description": "Principal Architect global daemon and AuxPane Cockpit plugin"`.
- [ ] **`daemon/workspace-plugin/principal-architect/plugin.json`:**
  - Valid JSON object with `"name": "principal-architect"`, `"version": "0.1.0"`, and `"description": "Principal Architect workspace orchestration plugin"`.
- [ ] **`daemon/workspace-plugin/principal-architect/scripts/__init__.py`:**
  - Module docstring and `__version__ = "0.1.0"`.
- [ ] **`scripts/dev-bootstrap.sh` (mark executable `chmod +x`):**
  - Bash script (`#!/usr/bin/env bash`, `set -euo pipefail`) that resolves the repository root relative to `BASH_SOURCE[0]` and idempotently provisions `./.venv` and installs `-e ".[dev]"`:
    1. If `./.venv/bin/python3`, `./.venv/bin/pytest`, and `./.venv/bin/ruff` exist and `./.venv/bin/python3 -c "import pydantic, yaml, pytest"` exits `0`, ensure `-e .` is linked (`./.venv/bin/pip install --no-deps --no-build-isolation -e . >/dev/null 2>&1 || true`), print the activation hint (`source .venv/bin/activate`), and exit `0` (fast idempotent no-op on re-run).
    2. Otherwise choose in order:
       - **Strategy 1 (`uv`):** If `command -v uv >/dev/null 2>&1`, run `uv venv .venv` (if `.venv` missing) and `uv pip install -e ".[dev]"`.
       - **Strategy 2 (`python3 -m venv` with `ensurepip`):** Else if `python3 -c "import ensurepip" >/dev/null 2>&1`, run `python3 -m venv .venv` and `./.venv/bin/pip install --upgrade pip setuptools wheel && ./.venv/bin/pip install -e ".[dev]"`.
       - **Strategy 3 (`python3 -m venv --without-pip` + `get-pip.py`):** Else run `python3 -m venv --without-pip .venv`, download `https://bootstrap.pypa.io/get-pip.py` to a temporary file (using `curl -fsSL` or `python3 -c "import urllib.request..."`), execute `./.venv/bin/python3 "$tmp_get_pip"`, and run `./.venv/bin/pip install setuptools wheel && ./.venv/bin/pip install --no-build-isolation -e ".[dev]"`.
    3. If all strategies fail, print an actionable diagnostic to stderr and exit `1`.
    4. On success, print ` Activate with: source .venv/bin/activate` and exit `0`.
- [ ] **`tests/conftest.py`, `tests/test_schemas.py`, `tests/test_state_db_and_sync.py`:**
  - Create minimal, clean initial test modules that verify `daemon/plugin.json` (`name == "pa-daemon"`), `daemon/workspace-plugin/principal-architect/plugin.json` (`name == "principal-architect"`), and `import pydantic, yaml` so that `pytest tests/test_schemas.py tests/test_state_db_and_sync.py` collects and passes at the `WO-01.1` tip.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run `./scripts/dev-bootstrap.sh` twice (confirming both initial provisioning and idempotent re-run succeed).
2. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests
   ```
3. Compute the `tree_hash` (SHA-256 over the sorted `path + "\0" + sha256(file_bytes)` of all existing files in `allowed_files`), update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report`, and commit all changes on `pr-01-core-schemas-and-enrollment/wo1-dev-bootstrap-and-package-skeleton` with message:
   ```text
   WO-01.1: Developer toolchain bootstrap and package skeleton

   PA-WorkOrder: WO-01.1
   PA-Verified-Hash: <tree_hash>
   ```
4. **Issue Surfacing:** If you discover any concern outside your boundary box, surface it in `out_of_scope_findings` in your Completion Report — never file issues or edit out-of-scope files directly.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

_Pending execution by Tier 3 Worker (`WO-01.1`)._
