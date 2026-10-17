#!/usr/bin/env bash
# Principal Architect Plugin (c) 2026 Matt McNeill
# https://github.com/matthewmcneill/principal-architect-plugin
# SPDX-License-Identifier: Apache-2.0
#
# Module: scripts/dev-bootstrap.sh
#
# Responsibility:
#   Idempotently provisions a local `.venv` Python virtual environment at the
#   repository root and installs the package in editable mode with development
#   and test dependencies (`-e ".[dev]"`). Cascades through three provisioning
#   strategies (`uv`, `python3 -m venv` with `ensurepip`, and `get-pip.py`
#   fallback) so bootstrap succeeds across minimal or restricted developer
#   machines.
#
# CLI / Environment Interface:
#   Usage: ./scripts/dev-bootstrap.sh
#   Creates: ./.venv/bin/{python3,pip,pytest,ruff}
set -euo pipefail

# --- Step 1: Resolve repository root and virtual environment binary paths ---
# Directory containing this bootstrap script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Absolute path to the repository root directory.
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Target virtual environment directory inside the repository root.
VENV_DIR="${REPO_ROOT}/.venv"
# Virtual environment Python 3 interpreter binary.
VENV_PYTHON="${VENV_DIR}/bin/python3"
# Virtual environment pip installer binary.
VENV_PIP="${VENV_DIR}/bin/pip"
# Virtual environment pytest runner binary.
VENV_PYTEST="${VENV_DIR}/bin/pytest"
# Virtual environment ruff linter binary.
VENV_RUFF="${VENV_DIR}/bin/ruff"

# --- Step 2: Fast-exit if the virtual environment is already provisioned ---
if [[ -x "${VENV_PYTHON}" && -x "${VENV_PYTEST}" && -x "${VENV_RUFF}" ]]; then
  if "${VENV_PYTHON}" -c "import pydantic, yaml, pytest" >/dev/null 2>&1; then
    # Ensure editable install is current without network/re-download
    "${VENV_PIP}" install --no-deps --no-build-isolation -e . >/dev/null 2>&1 || true
    echo "Developer environment already provisioned."
    echo "Activate with: source .venv/bin/activate"
    exit 0
  fi
fi

echo "Provisioning developer environment in ${VENV_DIR}..."

# --- Step 3: Strategy 1 — Provision via `uv` when available ---
if command -v uv >/dev/null 2>&1; then
  echo "Strategy 1: Using uv..."
  if [[ ! -d "${VENV_DIR}" ]]; then
    uv venv .venv
  fi
  uv pip install -e ".[dev]"
  echo "Activate with: source .venv/bin/activate"
  exit 0
fi

# --- Step 4: Strategy 2 — Provision via standard `python3 -m venv` (ensurepip) ---
if python3 -c "import ensurepip" >/dev/null 2>&1; then
  echo "Strategy 2: Using python3 -m venv (ensurepip)..."
  if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv .venv
  fi
  "${VENV_PIP}" install --upgrade pip setuptools wheel
  "${VENV_PIP}" install -e ".[dev]"
  echo "Activate with: source .venv/bin/activate"
  exit 0
fi

# --- Step 5: Strategy 3 — Fallback to `--without-pip` and `get-pip.py` ---
echo "Strategy 3: Using python3 -m venv --without-pip and get-pip.py..."
if [[ ! -x "${VENV_PYTHON}" ]]; then
  rm -rf "${VENV_DIR}"
  python3 -m venv --without-pip .venv
fi

# Temporary file holding the downloaded PyPA get-pip.py bootstrapper.
TMP_GET_PIP="$(mktemp -t get-pip-XXXXXX.py)"
trap 'rm -f "${TMP_GET_PIP}"' EXIT

echo "Downloading get-pip.py..."
if command -v curl >/dev/null 2>&1; then
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "${TMP_GET_PIP}"
else
  python3 -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '${TMP_GET_PIP}')"
fi

echo "Bootstrapping pip inside virtual environment..."
"${VENV_PYTHON}" "${TMP_GET_PIP}" --no-setuptools --no-wheel >/dev/null 2>&1 || "${VENV_PYTHON}" "${TMP_GET_PIP}"

echo "Installing build prerequisites and editable dependencies..."
"${VENV_PIP}" install setuptools wheel
"${VENV_PIP}" install --no-build-isolation -e ".[dev]"

echo "Developer environment provisioned successfully."
echo "Activate with: source .venv/bin/activate"
exit 0
