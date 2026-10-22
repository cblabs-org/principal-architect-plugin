"""Principal Architect Plugin (c) 2026 Matt McNeill
https://github.com/matthewmcneill/principal-architect-plugin
SPDX-License-Identifier: Apache-2.0
Module: daemon/workspace-plugin/principal-architect/scripts/models.py

Complexity-based model routing, retry step-up, architect model selection, and IDE Language Server
RPC client for the Split-Authority software delivery workflow.

In the Three-Tier Split-Authority architecture (Chief Architect -> Principal Architect ->
Execution Worker / Cold-Firewall Auditor / Interactive Debugger), each Work Order declares a
complexity classification (`mechanical`, `standard`, `architect`, or `interactive`). This module
routes initial execution attempts to cost- and latency-appropriate model tiers, steps up one tier
after two consecutive verification failures without ever downgrading a frontier parent model,
resolves the preferred Architect model from workspace state or the IDE model catalog, and bridges
conversation lifecycle operations (`StartConversation`, `SetPinned`, `SendMessage`) to the
Antigravity IDE Language Server with a deterministic headless fallback.

Exported API Summary
--------------------
Constants & Type Aliases:
- `ARCHITECT_MODEL_PREFERENCE`: Ordered tuple of preferred frontier model identifiers for Chief
  and Principal Architect sessions (`gemini-3.1-pro-high`, `claude-opus-4-6-thinking`,
  `gemini-3.1-pro-low`).
- `TransportFn`: Callable type alias `(endpoint, payload, headers) -> response_dict` for custom or
  mock Language Server RPC transport injection.

Functions:
- `step_up(tier: str) -> str`: Promote a model tier by one step (`flash_lite -> flash -> inherit ->
  inherit`), never returning `"pro"`.
- `route(complexity: str | Any, attempt: int = 1, parent_model: str = "inherit") -> str`: Resolve
  the target model tier for a Work Order complexity and 1-indexed attempt number.
- `select_architect_model(catalog=None, *, preferred=None, repo_root=None, runner=common.run) ->
  str`: Resolve the preferred Architect model from explicit override, `.state/state.db`
  configuration, or catalog matching against `ARCHITECT_MODEL_PREFERENCE`.

Classes:
- `LanguageServerClient`: Antigravity IDE Language Server JSON-RPC client with graceful headless
  bridge-prompt fallback.
  - **Lifecycle / Constructors**:
    - `__init__(*, address=None, csrf_token=None, transport=None, timeout=3.0) -> None`: Initialize
      client connection parameters from explicit arguments or environment variables.
    - `is_connected() -> bool`: Return `True` when a custom transport or both Language Server
      address and CSRF token are configured.
  - **Language Server RPC Methods**:
    - `start_conversation(*, title, prompt, role="pa", model=None, workspace_root=None, pin=True)
      -> dict[str, Any]`: Start a new IDE conversation (and optionally JIT-pin it) or return a
      headless bridge-prompt payload.
    - `set_pinned(conversation_id, pinned=True) -> dict[str, Any]`: Pin or unpin an existing IDE
      conversation, degrading cleanly when headless.
    - `send_message(conversation_id, message) -> dict[str, Any]`: Deliver a message to an existing
      IDE conversation or return a headless bridge-prompt fallback.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

# Absolute path to this script's directory so sibling modules can be imported directly.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import state_db

# Ordered frontier model preference tuple for Chief and Principal Architect sessions (SPEC §5.3).
ARCHITECT_MODEL_PREFERENCE: tuple[str, ...] = (
    "gemini-3.1-pro-high",
    "claude-opus-4-6-thinking",
    "gemini-3.1-pro-low",
)

# Single-step model tier promotion table; top tier stays at 'inherit' to avoid downgrading a frontier Pro or Opus model.
_STEP_UP_MAP: dict[str, str] = {
    "flash_lite": "flash",
    "flash": "inherit",
    "inherit": "inherit",
}

# Base model tier mapping for Work Order complexity classifications on attempts 1 and 2.
_COMPLEXITY_BASE_TIER: dict[str, str] = {
    "mechanical": "flash_lite",
    "standard": "flash",
    "architect": "inherit",
    "interactive": "inherit",
}

# Pluggable RPC transport signature: (endpoint_path, json_payload, http_headers) -> response_dict.
TransportFn = Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]


def step_up(tier: str) -> str:
    """Step up one model tier (`flash_lite -> flash -> inherit -> inherit`).

    Never returns `"pro"` so a parent running on a frontier Pro or Opus model is never downgraded.

    Args:
        tier: Current model tier identifier (`"flash_lite"`, `"flash"`, or `"inherit"`).

    Returns:
        The promoted model tier string.

    Raises:
        ValueError: If `tier` is not a string or is not a recognized tier name.
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

    Args:
        complexity: Work Order complexity tier string or `WorkOrderComplexity` enum instance.
        attempt: 1-indexed execution attempt number (must be an integer `>= 1`).
        parent_model: Parent session model tier (reserved for caller compatibility; defaults to
            `"inherit"`).

    Returns:
        Resolved subagent model tier string (`"flash_lite"`, `"flash"`, or `"inherit"`).

    Raises:
        ValueError: If `attempt` is not a positive integer or `complexity` is unrecognized.
    """
    # --- Step 1: Validate attempt number and normalize complexity value ---
    _ = parent_model
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError(f"attempt must be an integer >= 1, got {attempt!r}")

    raw_val = getattr(complexity, "value", complexity)
    if not isinstance(raw_val, str):
        raise ValueError(f"Unknown complexity tier: {complexity!r}")  # noqa: TRY004

    norm_comp = raw_val.strip().lower()
    if norm_comp not in _COMPLEXITY_BASE_TIER:
        raise ValueError(f"Unknown complexity tier: {complexity!r}")

    # --- Step 2: Resolve base tier and apply retry step-up on attempt >= 3 ---
    base_tier = _COMPLEXITY_BASE_TIER[norm_comp]
    if attempt >= 3:
        return step_up(base_tier)
    return base_tier


def _match_in_catalog(candidate: str, catalog: Sequence[str]) -> str | None:
    """Return the matching catalog entry for `candidate` (exact or case-insensitive substring).

    Args:
        candidate: Preferred model name to search for.
        catalog: Ordered sequence of available model identifiers reported by the host environment.

    Returns:
        The matching catalog entry string if found, or `None` if no match exists.
    """
    # --- Step 1: Normalize candidate string ---
    cand_norm = candidate.strip()
    if not cand_norm:
        return None
    cand_low = cand_norm.lower()

    # --- Step 2: Check for exact case-sensitive match ---
    for entry in catalog:
        if entry == cand_norm:
            return entry

    # --- Step 3: Check for case-insensitive exact match ---
    for entry in catalog:
        if entry.lower() == cand_low:
            return entry

    # --- Step 4: Fall back to case-insensitive substring match ---
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
    """Select the architect model from `preferred`, `state.db`, `catalog`, or default preference.

    Args:
        catalog: Optional sequence of available model identifiers from the host environment.
        preferred: Optional explicit model preference override.
        repo_root: Optional repository root path used to inspect `.state/state.db` for a persisted
            `architect_model` configuration key.
        runner: Subprocess runner callable passed to `common.find_repo_root`.

    Returns:
        The selected architect model identifier string.
    """
    # --- Step 1: Normalize the optional model catalog ---
    catalog_list: list[str] = []
    if catalog is not None:
        for item in catalog:
            val = str(item).strip()
            if val:
                catalog_list.append(val)

    # --- Step 2: Resolve explicit preference or read persisted config from state.db ---
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

    # --- Step 3: Match explicit/config preference against catalog if provided ---
    if pref:
        if not catalog_list:
            return pref
        matched_pref = _match_in_catalog(pref, catalog_list)
        if matched_pref is not None:
            return matched_pref

    # --- Step 4: Match ARCHITECT_MODEL_PREFERENCE against catalog or return top default ---
    if catalog_list:
        for candidate in ARCHITECT_MODEL_PREFERENCE:
            matched = _match_in_catalog(candidate, catalog_list)
            if matched is not None:
                return matched
        return catalog_list[0]

    return ARCHITECT_MODEL_PREFERENCE[0]


class LanguageServerClient:
    """Antigravity IDE Language Server RPC client with graceful headless fallback.

    Attributes:
        address: Normalized Language Server host/URL from `ANTIGRAVITY_LS_ADDRESS` or constructor.
        csrf_token: Normalized CSRF token from `ANTIGRAVITY_CSRF_TOKEN` or constructor.
        transport: Optional custom RPC callable used for testing or non-HTTP transports.
        timeout: HTTP request timeout in seconds for Language Server RPC calls.
    """

    def __init__(
        self,
        *,
        address: str | None = None,
        csrf_token: str | None = None,
        transport: TransportFn | None = None,
        timeout: float = 3.0,
    ) -> None:
        """Initialize the Language Server client from explicit arguments or environment variables.

        Args:
            address: Optional Language Server address (`host:port` or `http(s)://host:port`).
                Defaults to the `ANTIGRAVITY_LS_ADDRESS` environment variable.
            csrf_token: Optional CSRF token for authenticating Language Server requests. Defaults
                to the `ANTIGRAVITY_CSRF_TOKEN` environment variable.
            transport: Optional custom callable `(endpoint, payload, headers) -> dict` overriding
                the default `urllib.request` HTTP transport.
            timeout: Socket timeout in seconds for HTTP RPC calls (default `3.0`).
        """
        # --- Step 1: Resolve raw connection strings from arguments or environment ---
        raw_addr = (
            address if address is not None else os.environ.get("ANTIGRAVITY_LS_ADDRESS", "")
        )
        raw_token = (
            csrf_token
            if csrf_token is not None
            else os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "")
        )
        # --- Step 2: Store normalized instance attributes ---
        self.address: str = str(raw_addr).strip()  # Language Server host:port or base URL
        self.csrf_token: str = str(raw_token).strip()  # x-codeium-csrf-token header value
        self.transport: TransportFn | None = transport  # Optional injected RPC transport
        self.timeout: float = float(timeout)  # HTTP request timeout in seconds

    def is_connected(self) -> bool:
        """Return `True` if a custom transport or both LS address and CSRF token are configured.

        Returns:
            `True` when RPC calls can be attempted, or `False` when running in headless mode.
        """
        if self.transport is not None:
            return True
        return bool(self.address) and bool(self.csrf_token)

    def _call_rpc(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke a Language Server JSON-RPC endpoint via custom transport or `urllib`.

        Args:
            endpoint: Service method path (e.g.
                `"exa.language_server_pb.LanguageServerService/StartConversation"`).
            payload: JSON-serializable request dictionary.

        Returns:
            Decoded JSON response dictionary (or empty dict if the response body is empty).

        Raises:
            OSError: If neither `transport` nor both `address` and `csrf_token` are configured, or
                if the underlying HTTP request fails.
        """
        # --- Step 1: Build authentication headers and check for injected transport ---
        headers = {
            "Content-Type": "application/json",
            "x-codeium-csrf-token": self.csrf_token,
        }
        if self.transport is not None:
            res = self.transport(endpoint, payload, headers)
            return dict(res) if isinstance(res, Mapping) else {}

        if not self.address or not self.csrf_token:
            raise OSError("Language Server address or CSRF token not configured")

        # --- Step 2: Normalize base URL and construct POST request ---
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
        # --- Step 3: Execute HTTP POST and decode JSON response ---
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
        """Start a new IDE conversation (and optionally JIT-pin it), or return a headless fallback.

        Args:
            title: Display title for the newly created conversation.
            prompt: Initial prompt injected into the conversation.
            role: Split-Authority role slug (e.g. `"ca"`, `"pa"`, `"engineer"`, `"auditor"`).
            model: Optional explicit model identifier; defaults to `select_architect_model`.
            workspace_root: Optional repository root path associated with the conversation.
            pin: Whether to immediately pin the conversation in the IDE sidebar (`True` by default).

        Returns:
            Dictionary describing connection state, `conversation_id`, `pinned` status, resolved
            `model`, `bridge_prompt`, and `fallback` mode (`None` or `"bridge_prompt"`).
        """
        # --- Step 1: Resolve target model identifier ---
        resolved_model = (
            model.strip()
            if isinstance(model, str) and model.strip()
            else select_architect_model(repo_root=workspace_root)
        )
        # --- Step 2: Attempt agentapi CLI or Language Server StartConversation RPC ---
        if self.is_connected():
            if self.transport is None and "PYTEST_CURRENT_TEST" not in os.environ:
                agentapi_bin = shutil.which("agentapi") or common.agentapi_bin()
                if agentapi_bin:
                    try:
                        tier_flag = "pro"
                        if resolved_model in ("flash_lite", "flash"):
                            tier_flag = resolved_model
                        cmd = [
                            agentapi_bin,
                            "new-conversation",
                            f"--model={tier_flag}",
                            f"--title={title}",
                            prompt,
                        ]
                        proc = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=15.0,
                            check=False,
                        )
                        if proc.returncode == 0 and proc.stdout:
                            uuid_match = re.search(
                                r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
                                proc.stdout,
                            )
                            if uuid_match:
                                conv_id = uuid_match.group(1)
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
                    except (OSError, subprocess.SubprocessError):
                        pass

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

        # --- Step 3: Degrade gracefully to headless bridge-prompt metadata ---
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
        """Pin or unpin an existing IDE conversation, falling back cleanly when headless.

        Args:
            conversation_id: Target IDE conversation UUID or identifier.
            pinned: `True` to pin the conversation in the sidebar, `False` to unpin.

        Returns:
            Dictionary with `connected`, `conversation_id`, `pinned`, and optional `fallback`.
        """
        # --- Step 1: Attempt SetPinned / UpdateConversationAnnotations RPC when connected ---
        conv_id = str(conversation_id).strip()
        if self.is_connected() and conv_id and not conv_id.startswith("headless-"):
            if self.transport is None and "PYTEST_CURRENT_TEST" not in os.environ:
                try:
                    self._call_rpc(
                        "exa.language_server_pb.LanguageServerService/UpdateConversationAnnotations",
                        {
                            "cascadeIds": [conv_id],
                            "annotations": {"pinned": "true" if pinned else "false"},
                            "mergeAnnotations": True,
                        },
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

        # --- Step 2: Return headless fallback status ---
        return {
            "connected": False,
            "conversation_id": conv_id,
            "pinned": False,
            "fallback": "headless",
        }

    def send_message(self, conversation_id: str, message: str) -> dict[str, Any]:
        """Send a message to an existing IDE conversation, or return a bridge-prompt fallback.

        Args:
            conversation_id: Target IDE conversation UUID or identifier.
            message: Prompt or wakeup message text to inject.

        Returns:
            Dictionary with `connected`, `conversation_id`, `delivered`, and (on fallback)
            `bridge_prompt` and `fallback`.
        """
        # --- Step 1: Attempt agentapi or SendMessage RPC when connected and non-headless ---
        conv_id = str(conversation_id).strip()
        if self.is_connected() and conv_id and not conv_id.startswith("headless-"):
            if self.transport is None and "PYTEST_CURRENT_TEST" not in os.environ:
                agentapi_bin = shutil.which("agentapi") or common.agentapi_bin()
                if agentapi_bin:
                    try:
                        proc = subprocess.run(
                            [agentapi_bin, "send-message", conv_id, message],
                            capture_output=True,
                            text=True,
                            timeout=15.0,
                            check=False,
                        )
                        if proc.returncode == 0:
                            return {
                                "connected": True,
                                "conversation_id": conv_id,
                                "delivered": True,
                            }
                    except (OSError, subprocess.SubprocessError):
                        pass

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

        # --- Step 2: Return bridge-prompt fallback when offline or RPC fails ---
        return {
            "connected": False,
            "conversation_id": conv_id,
            "delivered": False,
            "bridge_prompt": message,
            "fallback": "bridge_prompt",
        }
