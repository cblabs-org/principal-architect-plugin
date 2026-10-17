#!/usr/bin/env bash
# scripts/install.sh - Install principal-architect-plugin daemon and `pa` CLI symlink.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PA_DAEMON_HOME="${PA_DAEMON_HOME:-$HOME/.gemini/config/plugins/pa-daemon}"
PA_BIN_DIR="${PA_BIN_DIR:-$HOME/.local/bin}"

TMP_STATE_BACKUP=""
cleanup() {
  if [[ -n "${TMP_STATE_BACKUP}" && -d "${TMP_STATE_BACKUP}" ]]; then
    rm -rf "${TMP_STATE_BACKUP}"
  fi
}
trap cleanup EXIT

# Preserve existing <PA_DAEMON_HOME>/state/ across upgrades/re-installs
if [[ -d "${PA_DAEMON_HOME}/state" ]]; then
  TMP_STATE_BACKUP="$(mktemp -d -t pa-daemon-state-XXXXXX)"
  cp -a "${PA_DAEMON_HOME}/state/." "${TMP_STATE_BACKUP}/"
fi

rm -rf "${PA_DAEMON_HOME}"
mkdir -p "${PA_DAEMON_HOME}"
cp -a "${REPO_ROOT}/daemon/." "${PA_DAEMON_HOME}/"

# Strip any cached bytecode directories copied from the working tree
find "${PA_DAEMON_HOME}" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

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

chmod +x "${PA_DAEMON_HOME}/workspace-plugin/principal-architect/scripts/"*.py
chmod +x "${REPO_ROOT}/scripts/enroll.sh" "${REPO_ROOT}/scripts/unenroll.sh"

mkdir -p "${PA_BIN_DIR}"
ln -sf "${PA_DAEMON_HOME}/workspace-plugin/principal-architect/scripts/pa_cli.py" "${PA_BIN_DIR}/pa"

echo "Installed principal-architect-plugin:"
echo "  PA_DAEMON_HOME: ${PA_DAEMON_HOME}"
echo "  pa CLI:         ${PA_BIN_DIR}/pa"
