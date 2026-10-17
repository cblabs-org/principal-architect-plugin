#!/usr/bin/env bash
# Principal Architect Plugin (c) 2026 Matt McNeill
# https://github.com/matthewmcneill/principal-architect-plugin
# SPDX-License-Identifier: Apache-2.0
#
# Module: scripts/install.sh
#
# Responsibility:
#   Installs or upgrades the `pa-daemon` global plugin bundle and the `pa` CLI
#   symlink (`SPEC.md` §4.1, PR-04 Charter G3 & R6). Updates `PA_DAEMON_HOME`
#   in-place (never deleting the top-level directory inode while Antigravity is
#   running), preserves any existing `<PA_DAEMON_HOME>/state/registry.json` and
#   state files across upgrades, stamps the Git version into both `plugin.json`
#   manifests, strips `__pycache__` artifacts, provisions `<PA_DAEMON_HOME>/.venv`
#   when system `python3` lacks `pydantic` or `pyyaml`, links `bin/pa` into
#   `<PA_BIN_DIR>/pa`, and enables the plugin and `pa_cockpit` sidecar in the
#   Antigravity Language Server when reachable.
#
# CLI / Environment Interface:
#   Usage: ./scripts/install.sh
#   Environment Variables:
#     - PA_DAEMON_HOME: Target daemon installation directory (default: `$HOME/.gemini/config/plugins/pa-daemon`).
#     - PA_BIN_DIR: Target binary symlink directory (default: `$HOME/.local/bin`).
#     - VERSION: Optional explicit semantic version string override.
#     - ANTIGRAVITY_LS_ADDRESS: Optional host:port for Language Server RPC registration.
#     - ANTIGRAVITY_CSRF_TOKEN: Optional CSRF token for `JetboxWriteState` RPC registration.
set -euo pipefail

# --- Step 1: Resolve source paths, target installation directories, and version string ---
# Directory containing this installation script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Absolute path to the repository root directory.
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Destination directory for the installed `pa-daemon` plugin bundle.
PA_DAEMON_HOME="${PA_DAEMON_HOME:-$HOME/.gemini/config/plugins/pa-daemon}"
# Destination directory on PATH for the `pa` CLI executable symlink.
PA_BIN_DIR="${PA_BIN_DIR:-$HOME/.local/bin}"

if [[ -z "${VERSION:-}" ]]; then
  # Raw version description from Git tags, falling back to 0.1.0 when untagged.
  RAW_VERSION="$(git -C "${REPO_ROOT}" describe --tags --always --dirty 2>/dev/null || echo "0.1.0")"
  if [[ "${RAW_VERSION}" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+ ]]; then
    VERSION="${RAW_VERSION#v}"
  else
    VERSION="0.1.0"
  fi
fi

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

# --- Step 3: Copy `daemon/` bundle in-place into `PA_DAEMON_HOME` and strip caches ---
mkdir -p "${PA_DAEMON_HOME}"
rm -rf "${PA_DAEMON_HOME}/bin" \
       "${PA_DAEMON_HOME}/sidecars" \
       "${PA_DAEMON_HOME}/skills" \
       "${PA_DAEMON_HOME}/workspace-plugin"
cp -a "${REPO_ROOT}/daemon/." "${PA_DAEMON_HOME}/"

# Strip any cached bytecode directories copied from the working tree
find "${PA_DAEMON_HOME}" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# --- Step 4: Stamp resolved semantic version into daemon and workspace plugin.json ---
python3 - "${PA_DAEMON_HOME}" "${VERSION}" <<'PYEOF'
import json
import pathlib
import sys

daemon_home = pathlib.Path(sys.argv[1])
version = sys.argv[2]

for rel in ("plugin.json", "workspace-plugin/principal-architect/plugin.json"):
    manifest_path = daemon_home / rel
    if manifest_path.is_file():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["version"] = version
        manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PYEOF

# --- Step 5: Restore backed-up daemon state and initialize default `registry.json` ---
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

# --- Step 6: Ensure Python dependencies (`pydantic`, `pyyaml`) in daemon `.venv` if needed ---
if [[ -z "${PA_SKIP_VENV:-}" ]]; then
  if [[ -x "${PA_DAEMON_HOME}/.venv/bin/python3" ]] && "${PA_DAEMON_HOME}/.venv/bin/python3" -c "import pydantic, yaml" >/dev/null 2>&1; then
    :
  elif python3 -c "import pydantic, yaml" >/dev/null 2>&1; then
    :
  elif command -v uv >/dev/null 2>&1; then
    echo "Provisioning daemon virtual environment at ${PA_DAEMON_HOME}/.venv (via uv)..."
    uv venv "${PA_DAEMON_HOME}/.venv" >/dev/null 2>&1 && \
      uv pip install --python "${PA_DAEMON_HOME}/.venv/bin/python3" "pydantic>=2,<3" "pyyaml>=6" >/dev/null 2>&1 || true
  elif python3 -c "import ensurepip" >/dev/null 2>&1; then
    echo "Provisioning daemon virtual environment at ${PA_DAEMON_HOME}/.venv (via python3 -m venv)..."
    python3 -m venv "${PA_DAEMON_HOME}/.venv" >/dev/null 2>&1 && \
      "${PA_DAEMON_HOME}/.venv/bin/pip" install --quiet "pydantic>=2,<3" "pyyaml>=6" >/dev/null 2>&1 || true
  fi
fi

# --- Step 7: Set executable permissions, strip macOS quarantine, and link `pa` CLI wrapper ---
chmod +x "${PA_DAEMON_HOME}/workspace-plugin/principal-architect/scripts/"*.py
if [[ -d "${PA_DAEMON_HOME}/bin" ]]; then
  chmod +x "${PA_DAEMON_HOME}/bin/"* 2>/dev/null || true
fi
chmod +x "${REPO_ROOT}/scripts/enroll.sh" "${REPO_ROOT}/scripts/unenroll.sh"

if [[ "$(uname -s)" == "Darwin" ]] && command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "${PA_DAEMON_HOME}" 2>/dev/null || true
fi

mkdir -p "${PA_BIN_DIR}"
ln -sf "${PA_DAEMON_HOME}/bin/pa" "${PA_BIN_DIR}/pa"

# --- Step 8: Enable `pa-daemon` and `pa_cockpit` in Antigravity Language Server if reachable ---
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

echo "Installed principal-architect-plugin (${VERSION}):"
echo "  PA_DAEMON_HOME: ${PA_DAEMON_HOME}"
echo "  pa CLI:         ${PA_BIN_DIR}/pa"
