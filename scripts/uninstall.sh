#!/usr/bin/env bash
# Principal Architect Plugin (c) 2026 Matt McNeill
# https://github.com/matthewmcneill/principal-architect-plugin
# SPDX-License-Identifier: Apache-2.0
#
# Module: scripts/uninstall.sh
#
# Responsibility:
#   Idempotently removes the installed `pa-daemon` global plugin directory
#   (`PA_DAEMON_HOME`) and the `pa` CLI symlink (`PA_BIN_DIR/pa`) without
#   modifying any enrolled repository workspaces (`SPEC.md` §4.1).
#
# CLI / Environment Interface:
#   Usage: ./scripts/uninstall.sh
#   Environment Variables:
#     - PA_DAEMON_HOME: Installed daemon directory to remove (default: `$HOME/.gemini/config/plugins/pa-daemon`).
#     - PA_BIN_DIR: Directory containing the `pa` CLI symlink (default: `$HOME/.local/bin`).
set -euo pipefail

# Installed `pa-daemon` plugin directory path.
PA_DAEMON_HOME="${PA_DAEMON_HOME:-$HOME/.gemini/config/plugins/pa-daemon}"
# Directory containing the `pa` CLI executable symlink.
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
