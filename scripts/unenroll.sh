#!/usr/bin/env bash
# Principal Architect Plugin (c) 2026 Matt McNeill
# https://github.com/matthewmcneill/principal-architect-plugin
# SPDX-License-Identifier: Apache-2.0
#
# Module: scripts/unenroll.sh
#
# Responsibility:
#   Convenience CLI wrapper around `pa_cli.py unenroll`. Resolves the repository
#   virtual environment Python interpreter (`.venv/bin/python3` when present,
#   falling back to `python3` on `PATH`) and forwards all positional arguments
#   to unenroll a target repository from the global Principal Architect registry
#   while preserving committed workspace artifacts.
#
# CLI / Environment Interface:
#   Usage: ./scripts/unenroll.sh [PATH]
set -euo pipefail

# Directory containing this wrapper script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Absolute path to the repository root directory.
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Prefer the repository `.venv` Python interpreter when provisioned.
if [[ -x "${REPO_ROOT}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python3"
else
  PYTHON_BIN="python3"
fi

exec "${PYTHON_BIN}" "${REPO_ROOT}/daemon/workspace-plugin/principal-architect/scripts/pa_cli.py" unenroll "$@"
