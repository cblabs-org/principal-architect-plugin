"""Complexity-based model routing, retry step-up, architect model selection, and IDE client (`models.py`).

Implements SPEC §5.3 and PR-03 Charter G2 & R4:
- `ARCHITECT_MODEL_PREFERENCE = ("gemini-4-argon-high", "gemini-3.1-pro-high", "claude-opus-5-5-high")`
- `step_up(tier) -> str` stepping `"flash_lite" -> "flash" -> "inherit" -> "inherit"` and NEVER
  returning `"pro"` when stepping up from `"flash"` or `"inherit"`.
- `route(complexity, attempt=1, parent_model="inherit") -> str` mapping `"mechanical" -> "flash_lite"`,
  `"standard" -> "flash"`, `"architect" -> "inherit"`, `"interactive" -> "inherit"` on attempts 1-2
  and stepping up one tier via `step_up` on `attempt >= 3`.
- `select_architect_model(catalog=None, *, preferred=None, repo_root=None, runner=common.run) -> str`
  resolving the preferred architect model from explicit override, `.state/state.db` config, or catalog
  matching against `ARCHITECT_MODEL_PREFERENCE`.
- `LanguageServerClient` for starting conversations, JIT pinning/unpinning, and sending wakeup messages
  against `ANTIGRAVITY_LS_ADDRESS` + `ANTIGRAVITY_CSRF_TOKEN`, degrading gracefully to headless
  bridge-prompt dicts when no IDE is connected or when an RPC fails.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import state_db

ARCHITECT_MODEL_PREFERENCE: tuple[str, ...] = (
    "gemini-4-argon-high",
    "gemini-3.1-pro-high",
    "claude-opus-5-5-high",
)

_STEP_UP_MAP: dict[str, str] = {
    "flash_lite": "flash",
    "flash": "inherit",
    "inherit": "inherit",
}

_COMPLEXITY_BASE_TIER: dict[str, str] = {
    "mechanical": "flash_lite",
    "standard": "flash",
    "architect": "inherit",
    "interactive": "inherit",
}

TransportFn = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


def step_up(tier: str) -> str:
    """Step up one model tier (`flash_lite -> flash -> inherit -> inherit`).

    Never returns `"pro"` so a parent running on Argon or Opus is never downgraded.
    Raises `ValueError` for unrecognized tier names.
    """
    if not isinstance(tier, str):
        raise ValueError(f"Unrecognized model tier: {tier!r}")  # noqa: TRY004
    norm = tier.strip().lower()
    if norm not in _STEP_UP_MAP:
        raise ValueError(f"Unrecognized model tier: {tier!r}")
    return _STEP_UP_MAP[norm]


def route(
    complexity: str | Any,
    attempt: int = 1,
    parent_model: str = "inherit",
) -> str:
    """Route a Work Order complexity and attempt number (1-indexed) to a model tier.

    - Attempts 1-2 use the base tier (`mechanical -> flash_lite`, `standard -> flash`,
      `architect -> inherit`, `interactive -> inherit`).
    - Attempts 3+ (after 2 failed attempts) step up one tier via `step_up(base_tier)`.
    - Never returns `"pro"` when the architect/top tier is `"inherit"`.
    """
    _ = parent_model
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError(f"attempt must be an integer >= 1, got {attempt!r}")

    raw_val = getattr(complexity, "value", complexity)
    if not isinstance(raw_val, str):
        raise ValueError(f"Unknown complexity tier: {complexity!r}")  # noqa: TRY004

    norm_comp = raw_val.strip().lower()
    if norm_comp not in _COMPLEXITY_BASE_TIER:
        raise ValueError(f"Unknown complexity tier: {complexity!r}")

    base_tier = _COMPLEXITY_BASE_TIER[norm_comp]
    if attempt >= 3:
        return step_up(base_tier)
    return base_tier


def _match_in_catalog(candidate: str, catalog: Sequence[str]) -> str | None:
    """Return the matching catalog entry for `candidate` (exact or case-insensitive substring)."""
    cand_norm = candidate.strip()
    if not cand_norm:
        return None
    cand_low = cand_norm.lower()

    # 1. Exact match
    for entry in catalog:
        if entry == cand_norm:
            return entry

    # 2. Case-insensitive exact match
    for entry in catalog:
        if entry.lower() == cand_low:
            return entry

    # 3. Case-insensitive substring match
    for entry in catalog:
        entry_low = entry.lower()
        if cand_low in entry_low or entry_low in cand_low:
            return entry

    return None


def select_architect_model(
    catalog: Sequence[str] | None = None,
    *,
    preferred: str | None = None,
    repo_root: str | Path | None = None,
    runner: common.Runner = common.run,
) -> str:
    """Select the architect model from `preferred`, `state.db`, `catalog`, or default preference."""
    catalog_list: list[str] = []
    if catalog is not None:
        for item in catalog:
            val = str(item).strip()
            if val:
                catalog_list.append(val)

    pref = preferred.strip() if isinstance(preferred, str) and preferred.strip() else None
    if pref is None and repo_root is not None:
        try:
            real_root = common.find_repo_root(repo_root, runner=runner) or Path(
                os.path.realpath(repo_root)
            )
            ws_dir = common.workspace_dir(real_root)
            db_file = ws_dir / ".state" / "state.db"
            if db_file.is_file():
                with state_db.StateDB(db_file) as db:
                    cfg_model = db.get_config("architect_model")
                    if cfg_model and cfg_model.strip():
                        pref = cfg_model.strip()
        except OSError:
            pref = None

    if pref:
        if not catalog_list:
            return pref
        matched_pref = _match_in_catalog(pref, catalog_list)
        if matched_pref is not None:
            return matched_pref

    if catalog_list:
        for candidate in ARCHITECT_MODEL_PREFERENCE:
            matched = _match_in_catalog(candidate, catalog_list)
            if matched is not None:
                return matched
        return catalog_list[0]

    return ARCHITECT_MODEL_PREFERENCE[0]


class LanguageServerClient:
    """Antigravity IDE Language Server RPC client with graceful headless fallback."""

    def __init__(
        self,
        *,
        address: str | None = None,
        csrf_token: str | None = None,
        transport: TransportFn | None = None,
        timeout: float = 3.0,
    ) -> None:
        raw_addr = (
            address if address is not None else os.environ.get("ANTIGRAVITY_LS_ADDRESS", "")
        )
        raw_token = (
            csrf_token
            if csrf_token is not None
            else os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "")
        )
        self.address: str = str(raw_addr).strip()
        self.csrf_token: str = str(raw_token).strip()
        self.transport: TransportFn | None = transport
        self.timeout: float = float(timeout)

    def is_connected(self) -> bool:
        """Return True if a mock transport or both LS address and CSRF token are configured."""
        if self.transport is not None:
            return True
        return bool(self.address) and bool(self.csrf_token)

    def _call_rpc(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke a Language Server JSON RPC endpoint via custom transport or urllib."""
        headers = {
            "Content-Type": "application/json",
            "x-codeium-csrf-token": self.csrf_token,
        }
        if self.transport is not None:
            res = self.transport(endpoint, payload, headers)
            return dict(res) if isinstance(res, Mapping) else {}

        if not self.address or not self.csrf_token:
            raise OSError("Language Server address or CSRF token not configured")

        if self.address.startswith(("http://", "https://")):
            base_url = self.address.rstrip("/")
        else:
            base_url = f"http://{self.address.rstrip('/')}"
        url = f"{base_url}/{endpoint.lstrip('/')}"

        body_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw_bytes = resp.read()
        if not raw_bytes:
            return {}
        parsed = json.loads(raw_bytes.decode("utf-8"))
        return dict(parsed) if isinstance(parsed, Mapping) else {}

    def start_conversation(
        self,
        *,
        title: str,
        prompt: str,
        role: str = "pa",
        model: str | None = None,
        workspace_root: str | Path | None = None,
        pin: bool = True,
    ) -> dict[str, Any]:
        """Start a new IDE conversation (and optionally JIT-pin it), or return a headless bridge prompt."""
        resolved_model = (
            model.strip()
            if isinstance(model, str) and model.strip()
            else select_architect_model(repo_root=workspace_root)
        )
        if self.is_connected():
            try:
                payload = {
                    "title": title,
                    "prompt": prompt,
                    "role": role,
                    "model": resolved_model,
                    "workspaceRoot": str(workspace_root) if workspace_root else "",
                }
                resp = self._call_rpc(
                    "exa.language_server_pb.LanguageServerService/StartConversation",
                    payload,
                )
                conv_id = str(
                    resp.get("conversationId")
                    or resp.get("conversation_id")
                    or resp.get("cascadeId")
                    or resp.get("id")
                    or ""
                ).strip()
                if not conv_id:
                    conv_id = f"ls-{role}-{uuid.uuid4().hex[:8]}"

                pinned_state = False
                if pin:
                    pin_res = self.set_pinned(conv_id, True)
                    pinned_state = bool(pin_res.get("pinned", False))

                return {
                    "connected": True,
                    "conversation_id": conv_id,
                    "pinned": pinned_state,
                    "title": title,
                    "role": role,
                    "model": resolved_model,
                    "bridge_prompt": prompt,
                    "fallback": None,
                }
            except (
                OSError,
                urllib.error.URLError,
                ValueError,
                RuntimeError,
                KeyError,
                TypeError,
            ):
                pass

        return {
            "connected": False,
            "conversation_id": f"headless-{role}-{uuid.uuid4().hex[:8]}",
            "pinned": False,
            "title": title,
            "role": role,
            "model": resolved_model,
            "bridge_prompt": prompt,
            "fallback": "bridge_prompt",
        }

    def set_pinned(self, conversation_id: str, pinned: bool = True) -> dict[str, Any]:
        """Pin or unpin an existing IDE conversation, falling back cleanly when headless."""
        conv_id = str(conversation_id).strip()
        if self.is_connected() and conv_id and not conv_id.startswith("headless-"):
            try:
                self._call_rpc(
                    "exa.language_server_pb.LanguageServerService/SetPinned",
                    {"conversationId": conv_id, "pinned": bool(pinned)},
                )
                return {
                    "connected": True,
                    "conversation_id": conv_id,
                    "pinned": bool(pinned),
                }
            except (
                OSError,
                urllib.error.URLError,
                ValueError,
                RuntimeError,
                KeyError,
                TypeError,
            ):
                pass

        return {
            "connected": False,
            "conversation_id": conv_id,
            "pinned": False,
            "fallback": "headless",
        }

    def send_message(self, conversation_id: str, message: str) -> dict[str, Any]:
        """Send a message to an existing IDE conversation, or return a bridge-prompt fallback."""
        conv_id = str(conversation_id).strip()
        if self.is_connected() and conv_id and not conv_id.startswith("headless-"):
            try:
                self._call_rpc(
                    "exa.language_server_pb.LanguageServerService/SendMessage",
                    {"conversationId": conv_id, "message": message},
                )
                return {
                    "connected": True,
                    "conversation_id": conv_id,
                    "delivered": True,
                }
            except (
                OSError,
                urllib.error.URLError,
                ValueError,
                RuntimeError,
                KeyError,
                TypeError,
            ):
                pass

        return {
            "connected": False,
            "conversation_id": conv_id,
            "delivered": False,
            "bridge_prompt": message,
            "fallback": "bridge_prompt",
        }
