#!/usr/bin/env bash
# scripts/uninstall.sh - Remove principal-architect-plugin daemon and `pa` CLI symlink.
set -euo pipefail

PA_DAEMON_HOME="${PA_DAEMON_HOME:-$HOME/.gemini/config/plugins/pa-daemon}"
PA_BIN_DIR="${PA_BIN_DIR:-$HOME/.local/bin}"

if [[ -e "${PA_BIN_DIR}/pa" || -L "${PA_BIN_DIR}/pa" ]]; then
  rm -f "${PA_BIN_DIR}/pa"
fi

if [[ -d "${PA_DAEMON_HOME}" ]]; then
  rm -rf "${PA_DAEMON_HOME}"
fi

echo "Uninstalled principal-architect-plugin:"
echo "  Removed PA_DAEMON_HOME: ${PA_DAEMON_HOME}"
echo "  Removed pa CLI:         ${PA_BIN_DIR}/pa"
