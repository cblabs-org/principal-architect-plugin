#!/bin/sh
# Principal Architect Plugin (c) 2026 Matt McNeill
# https://github.com/matthewmcneill/principal-architect-plugin
# SPDX-License-Identifier: Apache-2.0
#
# Module: daemon/sidecars/pa_cockpit/run-cockpit.sh
#
# Responsibility:
#   Sidecar launcher for the Principal Architect Cockpit HTTP + SSE server.
#   Selects the daemon `.venv/bin/python3` (with pydantic) when available,
#   falling back to `python3` on PATH.  This avoids the arch-mismatch issue
#   where `/usr/local/bin/python3` (x86_64 pydantic) crashes on arm64 Macs.
#
# CLI / Environment Interface:
#   Usage: run-cockpit.sh [cockpit.py args...]
#   Environment:
#     PA_DAEMON_HOME - Daemon home directory (auto-resolved from script location)
#     ANTIGRAVITY_SIDECAR_WEB_PORT - Port assigned by Antigravity sidecar framework

# --- Step 1: Resolve PA_DAEMON_HOME from script location ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Script lives at <daemon_home>/sidecars/pa_cockpit/run-cockpit.sh
DAEMON_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export PA_DAEMON_HOME="${PA_DAEMON_HOME:-${DAEMON_DIR}}"
for env_cand in "${PA_DAEMON_HOME}/bin/pa.env" "${PA_DAEMON_HOME}/bin/env.sh"; do
  if [ -f "${env_cand}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${env_cand}"
    set +a
  fi
done

COCKPIT_PY="${PA_DAEMON_HOME}/workspace-plugin/principal-architect/scripts/cockpit.py"

# --- Step 2: Select Python interpreter preferring the daemon venv ---
if [ -x "${PA_DAEMON_HOME}/.venv/bin/python3" ]; then
  PYTHON_BIN="${PA_DAEMON_HOME}/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "ERROR: No python3 found" >&2
  exit 1
fi

# --- Step 3: Launch cockpit server ---
if [ ! -f "${COCKPIT_PY}" ]; then
  echo "ERROR: cockpit.py not found at ${COCKPIT_PY}" >&2
  exit 1
fi

exec "${PYTHON_BIN}" "${COCKPIT_PY}" "$@"
