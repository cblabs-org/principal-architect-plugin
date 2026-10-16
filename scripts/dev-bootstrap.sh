#!/usr/bin/env bash
# scripts/dev-bootstrap.sh - Idempotently provisions ./.venv and installs -e ".[dev]"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

VENV_DIR="${REPO_ROOT}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python3"
VENV_PIP="${VENV_DIR}/bin/pip"
VENV_PYTEST="${VENV_DIR}/bin/pytest"
VENV_RUFF="${VENV_DIR}/bin/ruff"

# Check if environment is already fully provisioned
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

# Strategy 1: uv
if command -v uv >/dev/null 2>&1; then
  echo "Strategy 1: Using uv..."
  if [[ ! -d "${VENV_DIR}" ]]; then
    uv venv .venv
  fi
  uv pip install -e ".[dev]"
  echo "Activate with: source .venv/bin/activate"
  exit 0
fi

# Strategy 2: python3 -m venv with ensurepip
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

# Strategy 3: python3 -m venv --without-pip + get-pip.py fallback
echo "Strategy 3: Using python3 -m venv --without-pip and get-pip.py..."
if [[ ! -x "${VENV_PYTHON}" ]]; then
  rm -rf "${VENV_DIR}"
  python3 -m venv --without-pip .venv
fi

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
