#!/usr/bin/env bash
# Principal Architect Plugin (c) 2026 Matt McNeill
# https://github.com/matthewmcneill/principal-architect-plugin
# SPDX-License-Identifier: Apache-2.0
#
# Module: scripts/install-release.sh
#
# Responsibility:
#   Downloads the `pa-daemon.zip` release bundle from GitHub Releases, extracts
#   it in-place into `~/.gemini/config/plugins/pa-daemon/` while preserving any
#   existing `state/registry.json`, provisions `<PA_DAEMON_HOME>/.venv` when
#   system `python3` lacks `pydantic` or `pyyaml`, strips macOS Gatekeeper
#   quarantine attributes, and links the `bin/pa` CLI wrapper into `~/.local/bin/pa`.
#
# CLI / Environment Interface:
#   Usage: curl -fsSL https://raw.githubusercontent.com/matthewmcneill/principal-architect-plugin/main/scripts/install-release.sh | bash
#   Environment Variables:
#     - PA_REPO: GitHub owner/repo (default: `matthewmcneill/principal-architect-plugin`).
#     - PA_VERSION: Release tag to install (default: `latest`).
#     - PA_DAEMON_HOME: Target daemon plugin directory (default: `$HOME/.gemini/config/plugins/pa-daemon`).
#     - PA_BIN_DIR: Target CLI symlink directory (default: `$HOME/.local/bin`).
set -euo pipefail

# --- Step 1: Resolve target repository, release tag, and installation paths ---
# GitHub repository coordinates hosting the release assets.
PA_REPO="${PA_REPO:-matthewmcneill/principal-architect-plugin}"
# Release tag to download ("latest" or an explicit tag such as "v0.1.0").
PA_VERSION="${PA_VERSION:-latest}"
# Target installation directory for `pa-daemon`.
PA_DAEMON_HOME="${PA_DAEMON_HOME:-$HOME/.gemini/config/plugins/pa-daemon}"
# Target directory on PATH for the `pa` CLI symlink.
PA_BIN_DIR="${PA_BIN_DIR:-$HOME/.local/bin}"

# Zip asset filename published on GitHub Releases.
ASSET_NAME="pa-daemon.zip"
if [[ "${PA_VERSION}" == "latest" ]]; then
  DOWNLOAD_URL="https://github.com/${PA_REPO}/releases/latest/download/${ASSET_NAME}"
else
  DOWNLOAD_URL="https://github.com/${PA_REPO}/releases/download/${PA_VERSION}/${ASSET_NAME}"
fi

# Temporary staging directory for download and state preservation.
TMP_WORK_DIR="$(mktemp -d -t pa-release-install-XXXXXX)"
cleanup() {
  if [[ -n "${TMP_WORK_DIR}" && -d "${TMP_WORK_DIR}" ]]; then
    rm -rf "${TMP_WORK_DIR}"
  fi
}
trap cleanup EXIT

# --- Step 2: Download and extract the `pa-daemon.zip` archive into staging ---
ZIP_PATH="${TMP_WORK_DIR}/${ASSET_NAME}"
echo "Downloading ${ASSET_NAME} (${PA_VERSION}) from ${DOWNLOAD_URL}..."
curl -fsSL "${DOWNLOAD_URL}" -o "${ZIP_PATH}"

UNPACK_DIR="${TMP_WORK_DIR}/unpack"
mkdir -p "${UNPACK_DIR}"
python3 - "${ZIP_PATH}" "${UNPACK_DIR}" <<'PYEOF'
import sys
import zipfile

zip_path, unpack_dir = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(zip_path, "r") as zf:
    zf.extractall(unpack_dir)
PYEOF

# --- Step 3: Back up existing daemon state and copy extracted bundle in-place ---
STATE_BACKUP="${TMP_WORK_DIR}/state_backup"
if [[ -d "${PA_DAEMON_HOME}/state" ]]; then
  mkdir -p "${STATE_BACKUP}"
  cp -a "${PA_DAEMON_HOME}/state/." "${STATE_BACKUP}/"
fi

mkdir -p "${PA_DAEMON_HOME}"
rm -rf "${PA_DAEMON_HOME}/bin" \
       "${PA_DAEMON_HOME}/sidecars" \
       "${PA_DAEMON_HOME}/skills" \
       "${PA_DAEMON_HOME}/workspace-plugin"
cp -a "${UNPACK_DIR}/pa-daemon/." "${PA_DAEMON_HOME}/"

# --- Step 4: Restore daemon state and ensure `state/registry.json` exists ---
mkdir -p "${PA_DAEMON_HOME}/state"
if [[ -d "${STATE_BACKUP}" ]]; then
  cp -a "${STATE_BACKUP}/." "${PA_DAEMON_HOME}/state/"
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

# --- Step 5: Ensure Python dependencies (`pydantic`, `pyyaml`) in daemon `.venv` if needed ---
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

# --- Step 6: Set executable bits, strip macOS quarantine, and link `pa` CLI wrapper ---
chmod +x "${PA_DAEMON_HOME}/workspace-plugin/principal-architect/scripts/"*.py
if [[ -d "${PA_DAEMON_HOME}/bin" ]]; then
  chmod +x "${PA_DAEMON_HOME}/bin/"* 2>/dev/null || true
fi

if [[ "$(uname -s)" == "Darwin" ]] && command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "${PA_DAEMON_HOME}" 2>/dev/null || true
fi

mkdir -p "${PA_BIN_DIR}"
ln -sf "${PA_DAEMON_HOME}/bin/pa" "${PA_BIN_DIR}/pa"

echo "Installed principal-architect-plugin (${PA_VERSION}):"
echo "  PA_DAEMON_HOME: ${PA_DAEMON_HOME}"
echo "  pa CLI:         ${PA_BIN_DIR}/pa"
