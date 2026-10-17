#!/bin/sh
# Principal Architect Plugin (c) 2026 Matt McNeill
# https://github.com/matthewmcneill/principal-architect-plugin
# SPDX-License-Identifier: Apache-2.0
#
# Module: daemon/bin/run-pa-hook.sh
#
# Responsibility:
#   Portable POSIX shell wrapper for Principal Architect lifecycle hooks
#   (`PreInvocation`, `PreToolUse`, `PostToolUse`, `Stop`). Resolves `PA_DAEMON_HOME`
#   and `PLUGIN_ROOT` dynamically relative to its own directory, clears macOS
#   Gatekeeper quarantine attributes on first run after a browser `.zip` download,
#   selects `${PA_DAEMON_HOME}/.venv/bin/python3` when present (falling back to
#   `python3` on `PATH`), and guarantees fail-open `{"decision":"allow"}` output
#   on `PreToolUse` if the hook script or interpreter is temporarily unavailable.
#
# CLI / Environment Interface:
#   Usage: run-pa-hook.sh <script_name.py> [args...]

# --- Step 1: Resolve daemon and workspace plugin directories relative to this script ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DAEMON_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
export PA_DAEMON_HOME="${PA_DAEMON_HOME:-${DAEMON_DIR}}"
export PLUGIN_ROOT="${PLUGIN_ROOT:-${PA_DAEMON_HOME}/workspace-plugin/principal-architect}"

HOOK_SCRIPT="${1:-}"
if [ -n "${HOOK_SCRIPT}" ]; then
  shift
fi
TARGET_PY="${PLUGIN_ROOT}/scripts/${HOOK_SCRIPT}"

# --- Step 2: Strip macOS Gatekeeper quarantine attribute if present ---
if [ "$(uname -s)" = "Darwin" ] && command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "${PA_DAEMON_HOME}" 2>/dev/null || true
fi

# --- Step 3: Select Python interpreter and fail-open if target script is missing ---
if [ -x "${PA_DAEMON_HOME}/.venv/bin/python3" ]; then
  PYTHON_BIN="${PA_DAEMON_HOME}/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  PYTHON_BIN=""
fi

if [ -z "${HOOK_SCRIPT}" ] || [ ! -f "${TARGET_PY}" ] || [ -z "${PYTHON_BIN}" ]; then
  case "${HOOK_SCRIPT}" in
    *pre_tool_gate*)
      echo '{"decision":"allow","reason":"fail-open: hook script or python3 unavailable"}'
      exit 0
      ;;
  esac
  echo '{}'
  exit 0
fi

exec "${PYTHON_BIN}" "${TARGET_PY}" "$@"
