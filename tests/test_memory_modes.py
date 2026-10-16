"""Tests for mutually exclusive `external` vs. `builtin` memory graduation modes.

Initial smoke suite for WO-03.1; expanded with full `memory_grad.py` coverage in WO-03.3.
"""

from __future__ import annotations

from pathlib import Path

import common


def test_memory_modes_workspace_resolution_smoke(tmp_repo: Path) -> None:
    """Smoke test verifying workspace_dir resolution before memory_grad.py lands in WO-03.3."""
    ws_dir = common.workspace_dir(tmp_repo)
    assert ws_dir == tmp_repo / common.NEW_WORKSPACE_REL
    assert not (ws_dir / "memory").exists()
