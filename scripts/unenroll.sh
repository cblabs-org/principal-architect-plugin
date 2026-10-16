#!/usr/bin/env bash
# scripts/unenroll.sh - Convenience wrapper around `pa unenroll`
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -x "${REPO_ROOT}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python3"
else
  PYTHON_BIN="python3"
fi

exec "${PYTHON_BIN}" "${REPO_ROOT}/daemon/workspace-plugin/principal-architect/scripts/pa_cli.py" unenroll "$@"
