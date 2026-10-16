"""Initial test suite for schemas and plugin manifests."""

import json
from pathlib import Path

import pydantic
import yaml


def test_dependencies_importable():
    """Verify runtime dependencies are installed and importable."""
    assert pydantic.__version__.startswith("2.")
    assert yaml.__version__ is not None


def test_daemon_manifests_valid():
    """Verify plugin manifests exist and have correct metadata."""
    repo_root = Path(__file__).resolve().parent.parent

    daemon_manifest = repo_root / "daemon" / "plugin.json"
    assert daemon_manifest.is_file(), "daemon/plugin.json must exist"
    daemon_data = json.loads(daemon_manifest.read_text(encoding="utf-8"))
    assert daemon_data["name"] == "pa-daemon"
    assert daemon_data["version"] == "0.1.0"

    workspace_manifest = (
        repo_root
        / "daemon"
        / "workspace-plugin"
        / "principal-architect"
        / "plugin.json"
    )
    assert workspace_manifest.is_file(), "workspace plugin.json must exist"
    workspace_data = json.loads(workspace_manifest.read_text(encoding="utf-8"))
    assert workspace_data["name"] == "principal-architect"
    assert workspace_data["version"] == "0.1.0"
