#!/usr/bin/env bash
# Principal Architect Plugin (c) 2026 Matt McNeill
# https://github.com/matthewmcneill/principal-architect-plugin
# SPDX-License-Identifier: Apache-2.0
#
# Module: scripts/install.sh
#
# Responsibility:
#   Installs or upgrades the `pa-daemon` global plugin bundle and the `pa` CLI
#   symlink (`SPEC.md` §4.1, PR-04 Charter G3 & R6). Preserves any existing
#   `<PA_DAEMON_HOME>/state/registry.json` and state files across upgrades,
#   strips `__pycache__` artifacts, links `pa_cli.py` into `<PA_BIN_DIR>/pa`,
#   and enables the plugin and `pa_cockpit` sidecar in the Antigravity Language
#   Server when reachable.
#
# CLI / Environment Interface:
#   Usage: ./scripts/install.sh
#   Environment Variables:
#     - PA_DAEMON_HOME: Target daemon installation directory (default: `$HOME/.gemini/config/plugins/pa-daemon`).
#     - PA_BIN_DIR: Target binary symlink directory (default: `$HOME/.local/bin`).
#     - ANTIGRAVITY_LS_ADDRESS: Optional host:port for Language Server RPC registration.
#     - ANTIGRAVITY_CSRF_TOKEN: Optional CSRF token for `JetboxWriteState` RPC registration.
set -euo pipefail

# --- Step 1: Resolve source paths and target installation directories ---
# Directory containing this installation script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Absolute path to the repository root directory.
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Destination directory for the installed `pa-daemon` plugin bundle.
PA_DAEMON_HOME="${PA_DAEMON_HOME:-$HOME/.gemini/config/plugins/pa-daemon}"
# Destination directory on PATH for the `pa` CLI executable symlink.
PA_BIN_DIR="${PA_BIN_DIR:-$HOME/.local/bin}"

# Temporary directory used to preserve `<PA_DAEMON_HOME>/state` across upgrades.
TMP_STATE_BACKUP=""
cleanup() {
  if [[ -n "${TMP_STATE_BACKUP}" && -d "${TMP_STATE_BACKUP}" ]]; then
    rm -rf "${TMP_STATE_BACKUP}"
  fi
}
trap cleanup EXIT

# --- Step 2: Back up existing daemon state prior to replacing bundle files ---
if [[ -d "${PA_DAEMON_HOME}/state" ]]; then
  TMP_STATE_BACKUP="$(mktemp -d -t pa-daemon-state-XXXXXX)"
  cp -a "${PA_DAEMON_HOME}/state/." "${TMP_STATE_BACKUP}/"
fi

# --- Step 3: Copy `daemon/` bundle into `PA_DAEMON_HOME` and strip bytecode caches ---
rm -rf "${PA_DAEMON_HOME}"
mkdir -p "${PA_DAEMON_HOME}"
cp -a "${REPO_ROOT}/daemon/." "${PA_DAEMON_HOME}/"

# Strip any cached bytecode directories copied from the working tree
find "${PA_DAEMON_HOME}" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# --- Step 4: Restore backed-up daemon state and initialize default `registry.json` ---
mkdir -p "${PA_DAEMON_HOME}/state"
if [[ -n "${TMP_STATE_BACKUP}" && -d "${TMP_STATE_BACKUP}" ]]; then
  cp -a "${TMP_STATE_BACKUP}/." "${PA_DAEMON_HOME}/state/"
fi

if [[ ! -f "${PA_DAEMON_HOME}/state/registry.json" ]]; then
  cat > "${PA_DAEMON_HOME}/state/registry.json" <<'EOF'
{
  "schema_version": 1,
  "repos": {},
  "repositories": []
}
EOF
fi

# --- Step 5: Set executable permissions and link `pa` CLI into `PA_BIN_DIR` ---
chmod +x "${PA_DAEMON_HOME}/workspace-plugin/principal-architect/scripts/"*.py
chmod +x "${REPO_ROOT}/scripts/enroll.sh" "${REPO_ROOT}/scripts/unenroll.sh"

mkdir -p "${PA_BIN_DIR}"
ln -sf "${PA_DAEMON_HOME}/workspace-plugin/principal-architect/scripts/pa_cli.py" "${PA_BIN_DIR}/pa"

# --- Step 6: Enable `pa-daemon` and `pa_cockpit` in Antigravity Language Server if reachable ---
# Address of the local Antigravity Language Server HTTP endpoint.
LS_ADDR="${ANTIGRAVITY_LS_ADDRESS:-localhost:5387}"
if [[ -n "${ANTIGRAVITY_CSRF_TOKEN:-}" ]] && curl -fsS "http://${LS_ADDR}/healthz" >/dev/null 2>&1; then
  echo "Enabling pa-daemon plugin and pa_cockpit sidecar via JetboxWriteState..."
  curl -sS -X POST \
    "http://${LS_ADDR}/exa.language_server_pb.LanguageServerService/JetboxWriteState" \
    -H "Content-Type: application/json" \
    -H "x-codeium-csrf-token: ${ANTIGRAVITY_CSRF_TOKEN}" \
    -d '{
      "userConfig": {
        "plugins": {
          "pa-daemon": { "enabled": true }
        },
        "sidecars": {
          "pa-daemon/pa_cockpit": { "enabled": true }
        }
      }
    }' >/dev/null 2>&1 || true
fi

echo "Installed principal-architect-plugin:"
echo "  PA_DAEMON_HOME: ${PA_DAEMON_HOME}"
echo "  pa CLI:         ${PA_BIN_DIR}/pa"
