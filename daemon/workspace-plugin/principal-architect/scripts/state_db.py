"""Principal Architect Plugin (c) 2026 Matt McNeill
https://github.com/matthewmcneill/principal-architect-plugin
SPDX-License-Identifier: Apache-2.0
Module: daemon/workspace-plugin/principal-architect/scripts/state_db.py

Repo-local SQLite `StateDB` and global atomic repository enrollment `Registry`
for the Principal Architect Split-Authority workflow engine.

Implements SPEC §6.5 (7 tables in WAL mode with `busy_timeout=5000` and
`PRAGMA user_version=2`) and Charter R5 global repository registry with atomic
temporary-file replacements (`tempfile.NamedTemporaryFile` + `os.fsync` +
`os.replace`).

Exported API Summary:
- TABLES: Ordered tuple of the 7 canonical SQLite table names in `state.db`.
- SCHEMA_VERSION: Integer schema version (`PRAGMA user_version`) for `state.db`.
- utc_now_iso: Return the current UTC timestamp formatted as ISO 8601 with trailing `'Z'`.
- StateDB: Repo-local SQLite state database in WAL mode for persistent workflow coordination.
  - Lifecycle / Constructors:
    - StateDB.__init__: Open or create `state.db`, enable WAL and busy_timeout, and initialize schema.
    - StateDB.close: Close the underlying SQLite connection.
  - Context Manager Protocol:
    - StateDB.__enter__: Enter the context manager and return `self`.
    - StateDB.__exit__: Exit the context manager and close the SQLite connection.
  - Schema & Mode Management:
    - StateDB.init: Create the 7 SPEC §6.5 tables idempotently and set `PRAGMA user_version`.
    - StateDB.get_config: Retrieve a configuration string by key from `repo_config`.
    - StateDB.set_config: Insert or update a configuration key-value pair in `repo_config`.
    - StateDB.get_all_config: Return all key-value pairs from `repo_config` as a dictionary.
  - Session Binding API:
    - StateDB._SESSION_COLUMNS: Frozenset of valid column names in the `sessions` table.
    - StateDB.bind_session: Upsert a conversation role binding in `sessions`.
    - StateDB.get_session: Fetch a session row dictionary by `conversation_id`.
    - StateDB.update_session: Update mutable columns on an existing `sessions` row.
  - Verification Receipts API:
    - StateDB.insert_receipt: Insert a cryptographic verification receipt row.
    - StateDB.invalidate_receipts: Mark all currently valid receipts for a `wo_id` as invalid.
    - StateDB.latest_valid_receipt: Return the most recent valid receipt for a `wo_id`.
  - Escalations API:
    - StateDB.insert_escalation: Insert an upward escalation record into `escalations`.
    - StateDB.resolve_escalation: Mark an escalation record resolved with a UTC timestamp.
    - StateDB.open_escalations: List open escalations matching optional PR/WO/role filters.
  - Write Queue API:
    - StateDB.enqueue: Insert a prioritized item into `attention_queue`.
    - StateDB.dequeue: Update an `attention_queue` item's status (default `"RESOLVED"`).
    - StateDB.list_open: List open `attention_queue` items ordered by priority and creation time.
  - Session State API (WO dispatch tracking for compaction resilience):
    - StateDB.track_dispatch: Record or update a Work Order dispatch in `session_state`.
    - StateDB.track_completion: Record Work Order completion or escalation in `session_state`.
    - StateDB.get_session_state: Fetch all `session_state` rows for a conversation.
    - StateDB.record_decision: Record a session decision, dead_end, or pending_action.
    - StateDB.get_session_decisions: Fetch all `session_decisions` for a conversation.
  - PR Projection & Checkpoints API:
    - Tracked via `sessions.last_checkpoint_step` and `sessions.pr_id`/`wo_id` via `bind_session`,
      `get_session`, and `update_session`.
- Registry: Global enrollment registry manager maintaining `<daemon_home>/state/registry.json`.
  - Lifecycle / Constructors:
    - Registry.__init__: Initialize the registry manager bound to `registry.json`.
  - Own Public API:
    - Registry._load_data: Read and validate the registry JSON structure from disk.
    - Registry._write_data: Atomically write updated registry data via temp file + `os.replace`.
    - Registry.register: Idempotently enroll a git repository root in `registry.json`.
    - Registry.unregister: Remove a repository root from `registry.json`.
    - Registry.lookup: Retrieve registration metadata for a repository root, or `None`.
    - Registry.list: Return a dictionary copy of all enrolled repositories.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import types
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import common

# Canonical table names required in every repo-local `state.db` (SPEC §6.5).
TABLES: tuple[str, ...] = (
    "repo_config",
    "sessions",
    "verification_receipts",
    "escalations",
    "attention_queue",
    "session_state",
    "session_decisions",
)

# SQLite PRAGMA user_version integer identifying the current `state.db` schema revision.
SCHEMA_VERSION: int = 2


def utc_now_iso() -> str:
    """Return the current UTC timestamp formatted as ISO 8601 with a trailing `'Z'`.

    Returns:
        UTC timestamp string in `YYYY-MM-DDTHH:MM:SS.ffffffZ` format.
    """
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class StateDB:
    """Repo-local SQLite state database in WAL mode for persistent workflow coordination.

    Manages `repo_config`, `sessions`, `verification_receipts`, `escalations`,
    `attention_queue`, `session_state`, and `session_decisions` inside
    `<workspace_dir>/state.db` with `journal_mode=WAL` and `busy_timeout=5000`
    for concurrent hook and CLI access.
    """

    def __init__(self, path: str | Path) -> None:
        """Open or create the SQLite state database at `path` and initialize all tables.

        Args:
            path: Filesystem path to the SQLite database file (`state.db`).
        """
        # Resolved filesystem path to the SQLite database file.
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Active SQLite3 database connection configured with Row factory and WAL mode.
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self.init()

    def __enter__(self) -> Self:
        """Enter the context manager and return this `StateDB` instance.

        Returns:
            Self (`StateDB`).
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit the context manager and close the underlying SQLite connection.

        Args:
            exc_type: Exception class if an exception was raised inside the `with` block.
            exc_val: Exception instance if raised.
            exc_tb: Traceback object if an exception was raised.
        """
        self.close()

    def close(self) -> None:
        """Close the underlying SQLite database connection."""
        self.conn.close()

    def init(self) -> None:
        """Create the 7 SPEC §6.5 tables idempotently and set `PRAGMA user_version`."""
        # --- Step 1: Create repo_config and sessions tables idempotently ---
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS repo_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    conversation_id TEXT PRIMARY KEY,
                    role TEXT,
                    programme_id TEXT,
                    pr_id TEXT,
                    wo_id TEXT,
                    attempt_num INTEGER,
                    structural_failures INTEGER,
                    pinned INTEGER,
                    last_checkpoint_step INTEGER,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            # --- Step 2: Create verification_receipts, escalations, and attention_queue tables ---
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS verification_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    wo_id TEXT,
                    pr_id TEXT,
                    cmd TEXT,
                    exit_code INTEGER,
                    tree_hash TEXT,
                    git_head_sha TEXT,
                    valid INTEGER,
                    created_at TEXT
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS escalations (
                    escalation_id TEXT PRIMARY KEY,
                    level TEXT,
                    source_role TEXT,
                    target_role TEXT,
                    pr_id TEXT,
                    wo_id TEXT,
                    blocker_type TEXT,
                    reason_code TEXT,
                    requested_files_json TEXT,
                    summary TEXT,
                    status TEXT,
                    github_issue_or_comment_url TEXT,
                    created_at TEXT,
                    resolved_at TEXT
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attention_queue (
                    item_id TEXT PRIMARY KEY,
                    priority INTEGER,
                    kind TEXT,
                    pr_id TEXT,
                    wo_id TEXT,
                    title TEXT,
                    action_payload_json TEXT,
                    status TEXT,
                    created_at TEXT
                )
                """
            )
            # --- Step 3: Create session_state and session_decisions tables ---
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_state (
                    conversation_id TEXT NOT NULL,
                    wo_id           TEXT NOT NULL,
                    dispatch_status TEXT NOT NULL DEFAULT 'pending',
                    subagent_conv_id TEXT,
                    dispatched_at   TEXT,
                    completed_at    TEXT,
                    result_summary  TEXT,
                    PRIMARY KEY (conversation_id, wo_id)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_decisions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    decision_type   TEXT NOT NULL DEFAULT 'decision',
                    summary         TEXT NOT NULL,
                    created_at      TEXT NOT NULL
                )
                """
            )
            # --- Step 4: Stamp PRAGMA user_version only when not already set ---
            cur_ver_row = self.conn.execute("PRAGMA user_version;").fetchone()
            cur_ver = int(cur_ver_row[0]) if cur_ver_row is not None else 0
            if cur_ver != SCHEMA_VERSION:
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION};")

    # -------------------------------------------------------------------------
    # repo_config accessors
    # -------------------------------------------------------------------------

    def get_config(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a configuration string by key, returning `default` if not found.

        Args:
            key: Configuration key name in `repo_config`.
            default: Fallback value returned when `key` is not present.

        Returns:
            Stored string value for `key`, or `default` if absent.
        """
        cur = self.conn.execute("SELECT value FROM repo_config WHERE key = ?", (key,))
        row = cur.fetchone()
        if row is None:
            return default
        return str(row["value"])

    def set_config(self, key: str, value: str) -> None:
        """Insert or update a configuration key-value pair in `repo_config`.

        Args:
            key: Configuration key name.
            value: Configuration value to store as text.
        """
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO repo_config (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )

    def get_all_config(self) -> dict[str, str]:
        """Return all configuration key-value pairs from `repo_config` ordered by key.

        Returns:
            Dictionary mapping each configuration key to its string value.
        """
        cur = self.conn.execute("SELECT key, value FROM repo_config ORDER BY key ASC")
        return {str(row["key"]): str(row["value"]) for row in cur.fetchall()}

    # -------------------------------------------------------------------------
    # sessions accessors
    # -------------------------------------------------------------------------

    # Allowed column names in the `sessions` table used to validate dynamic UPDATE queries.
    _SESSION_COLUMNS: frozenset[str] = frozenset(
        {
            "conversation_id",
            "role",
            "programme_id",
            "pr_id",
            "wo_id",
            "attempt_num",
            "structural_failures",
            "pinned",
            "last_checkpoint_step",
            "created_at",
            "updated_at",
        }
    )

    def bind_session(
        self,
        conversation_id: str,
        role: str,
        *,
        programme_id: str | None = None,
        pr_id: str | None = None,
        wo_id: str | None = None,
        attempt_num: int = 1,
        structural_failures: int = 0,
        pinned: bool | int = 0,
        last_checkpoint_step: int | None = None,
    ) -> dict[str, Any]:
        """Upsert a session binding, setting `created_at` on insert and `updated_at` always.

        Args:
            conversation_id: Unique conversation UUID for the agent session.
            role: Assigned Split-Authority role (`"chief"`, `"pa"`, `"engineer"`, `"auditor"`,
                or `"debugger"`).
            programme_id: Optional programme identifier (`prog-*`).
            pr_id: Optional Pull Request identifier (`PR-*`).
            wo_id: Optional Work Order identifier (`WO-*`).
            attempt_num: 1-based execution attempt counter.
            structural_failures: Count of consecutive structural/hook failures.
            pinned: Whether the conversation is pinned in the UI (`bool` or `0`/`1`).
            last_checkpoint_step: Highest observed transcript checkpoint step index.

        Returns:
            Dictionary of the persisted `sessions` row.
        """
        # --- Step 1: Normalize timestamps and boolean flags ---
        now = utc_now_iso()
        pinned_int = 1 if pinned else 0

        # --- Step 2: Upsert the session record preserving original created_at on conflict ---
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO sessions (
                    conversation_id, role, programme_id, pr_id, wo_id,
                    attempt_num, structural_failures, pinned, last_checkpoint_step,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    role = excluded.role,
                    programme_id = excluded.programme_id,
                    pr_id = excluded.pr_id,
                    wo_id = excluded.wo_id,
                    attempt_num = excluded.attempt_num,
                    structural_failures = excluded.structural_failures,
                    pinned = excluded.pinned,
                    last_checkpoint_step = excluded.last_checkpoint_step,
                    updated_at = excluded.updated_at
                """,
                (
                    conversation_id,
                    role,
                    programme_id,
                    pr_id,
                    wo_id,
                    attempt_num,
                    structural_failures,
                    pinned_int,
                    last_checkpoint_step,
                    now,
                    now,
                ),
            )

        # --- Step 3: Fetch and return the stored session row ---
        res = self.get_session(conversation_id)
        assert res is not None
        return res

    def get_session(self, conversation_id: str) -> dict[str, Any] | None:
        """Fetch a session row as a dictionary, or `None` if not found.

        Args:
            conversation_id: Unique conversation UUID to look up.

        Returns:
            Dictionary of column values for `conversation_id`, or `None` if unbound.
        """
        cur = self.conn.execute(
            "SELECT * FROM sessions WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def update_session(self, conversation_id: str, **fields: Any) -> dict[str, Any] | None:
        """Update mutable fields on an existing session and refresh `updated_at`.

        Validates that all field names exist in `_SESSION_COLUMNS` and are not immutable.

        Args:
            conversation_id: Target session conversation UUID.
            **fields: Column-value pairs to update on the session row.

        Returns:
            Updated session row as a dictionary, or `None` if `conversation_id` does not exist.

        Raises:
            ValueError: If any key in `fields` is not a valid column or is immutable
                (`"conversation_id"` or `"created_at"`).
        """
        # --- Step 1: Validate all requested column names against the allowlist ---
        for k in fields:
            if k not in self._SESSION_COLUMNS:
                raise ValueError(f"Invalid sessions column: '{k}'")
            if k in ("conversation_id", "created_at"):
                raise ValueError(f"Cannot update immutable column: '{k}'")

        # --- Step 2: Check whether the target session exists ---
        cur = self.conn.execute(
            "SELECT conversation_id FROM sessions WHERE conversation_id = ?",
            (conversation_id,),
        )
        if cur.fetchone() is None:
            return None

        # --- Step 3: Normalize boolean fields, stamp updated_at, and execute UPDATE ---
        update_dict = dict(fields)
        if "pinned" in update_dict:
            update_dict["pinned"] = 1 if update_dict["pinned"] else 0
        update_dict["updated_at"] = utc_now_iso()

        set_clauses = [f"{col} = ?" for col in update_dict]
        values = list(update_dict.values())
        values.append(conversation_id)

        sql = f"UPDATE sessions SET {', '.join(set_clauses)} WHERE conversation_id = ?"
        with self.conn:
            self.conn.execute(sql, values)

        return self.get_session(conversation_id)

    # -------------------------------------------------------------------------
    # verification_receipts accessors
    # -------------------------------------------------------------------------

    def insert_receipt(
        self,
        *,
        wo_id: str,
        pr_id: str,
        cmd: str,
        exit_code: int,
        tree_hash: str,
        git_head_sha: str | None = None,
        valid: bool | int = 1,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert a cryptographic verification receipt row and return the stored dictionary.

        Args:
            wo_id: Work Order identifier (`WO-*`) for which verification ran.
            pr_id: Parent Pull Request identifier (`PR-*`).
            cmd: Exact verification shell command executed.
            exit_code: Process exit status code (`0` for passing verification).
            tree_hash: Git working-tree content digest stamped at verification time.
            git_head_sha: Optional current `HEAD` commit SHA.
            valid: Whether the receipt is currently valid (`True`/`1` vs `False`/`0`).
            receipt_id: Optional explicit receipt ID; auto-generates `rcpt_<hex>` when `None`.

        Returns:
            Dictionary containing the newly inserted `verification_receipts` row.
        """
        # --- Step 1: Generate receipt ID, normalize flags, and insert row ---
        rid = receipt_id or ("rcpt_" + uuid.uuid4().hex[:12])
        valid_int = 1 if valid else 0
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO verification_receipts (
                    receipt_id, wo_id, pr_id, cmd, exit_code,
                    tree_hash, git_head_sha, valid, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rid,
                    wo_id,
                    pr_id,
                    cmd,
                    exit_code,
                    tree_hash,
                    git_head_sha,
                    valid_int,
                    now,
                ),
            )

        # --- Step 2: Fetch and return the stored receipt row ---
        cur = self.conn.execute(
            "SELECT * FROM verification_receipts WHERE receipt_id = ?",
            (rid,),
        )
        row = cur.fetchone()
        assert row is not None
        return dict(row)

    def invalidate_receipts(self, wo_id: str) -> int:
        """Mark all currently valid receipts for `wo_id` as invalid (`valid = 0`).

        Called by `PostToolUse` hooks whenever a source file is edited after verification.

        Args:
            wo_id: Work Order identifier whose receipts should be invalidated.

        Returns:
            Number of receipt rows transitioned from `valid = 1` to `valid = 0`.
        """
        with self.conn:
            cur = self.conn.execute(
                "UPDATE verification_receipts SET valid = 0 WHERE wo_id = ? AND valid = 1",
                (wo_id,),
            )
            return cur.rowcount

    def latest_valid_receipt(
        self, wo_id: str, tree_hash: str | None = None
    ) -> dict[str, Any] | None:
        """Return the most recent valid receipt for `wo_id`, optionally matching `tree_hash`.

        Args:
            wo_id: Work Order identifier (`WO-*`) to query.
            tree_hash: Optional working-tree hash that the receipt must match.

        Returns:
            Most recent valid receipt row dictionary, or `None` if no matching valid receipt exists.
        """
        # --- Step 1: Query the newest valid receipt with or without tree_hash filtering ---
        if tree_hash is not None:
            cur = self.conn.execute(
                """
                SELECT * FROM verification_receipts
                WHERE wo_id = ? AND valid = 1 AND tree_hash = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (wo_id, tree_hash),
            )
        else:
            cur = self.conn.execute(
                """
                SELECT * FROM verification_receipts
                WHERE wo_id = ? AND valid = 1
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (wo_id,),
            )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    # -------------------------------------------------------------------------
    # escalations accessors
    # -------------------------------------------------------------------------

    def insert_escalation(
        self,
        *,
        level: str,
        source_role: str,
        target_role: str,
        pr_id: str | None = None,
        wo_id: str | None = None,
        blocker_type: str = "other",
        reason_code: str = "UNSPECIFIED",
        requested_files: Sequence[str] | str | None = None,
        summary: str = "",
        status: str = "OPEN",
        github_issue_or_comment_url: str | None = None,
        escalation_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert an escalation record into `escalations` and return the stored row.

        Args:
            level: Escalation transition level (e.g. `"WORKER_TO_PA"`, `"PA_TO_CHIEF"`).
            source_role: Role initiating the escalation (`"engineer"`, `"pa"`).
            target_role: Role receiving the escalation (`"pa"`, `"chief"`, `"human"`).
            pr_id: Optional associated Pull Request ID.
            wo_id: Optional associated Work Order ID.
            blocker_type: Blocker category (`"structural"`, `"boundary"`, `"charter"`, etc.).
            reason_code: Symbolic reason code for the escalation.
            requested_files: Sequence of file path strings or pre-encoded JSON array string.
            summary: Human-readable explanation of the blocker.
            status: Initial escalation status (defaults to `"OPEN"`).
            github_issue_or_comment_url: Optional URL linking to a GitHub PR comment or issue.
            escalation_id: Optional explicit ID; auto-generates `esc_<hex>` when `None`.

        Returns:
            Dictionary containing the newly inserted `escalations` row.
        """
        # --- Step 1: Normalize escalation ID and serialize requested_files to JSON ---
        eid = escalation_id or ("esc_" + uuid.uuid4().hex[:12])
        if requested_files is None:
            req_json = "[]"
        elif isinstance(requested_files, str):
            req_json = requested_files
        else:
            req_json = json.dumps(list(requested_files))

        # --- Step 2: Insert the escalation row into SQLite ---
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO escalations (
                    escalation_id, level, source_role, target_role,
                    pr_id, wo_id, blocker_type, reason_code,
                    requested_files_json, summary, status,
                    github_issue_or_comment_url, created_at, resolved_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eid,
                    level,
                    source_role,
                    target_role,
                    pr_id,
                    wo_id,
                    blocker_type,
                    reason_code,
                    req_json,
                    summary,
                    status,
                    github_issue_or_comment_url,
                    now,
                    None,
                ),
            )

        # --- Step 3: Fetch and return the stored escalation row ---
        cur = self.conn.execute(
            "SELECT * FROM escalations WHERE escalation_id = ?",
            (eid,),
        )
        row = cur.fetchone()
        assert row is not None
        return dict(row)

    def resolve_escalation(
        self, escalation_id: str, status: str = "RESOLVED"
    ) -> dict[str, Any] | None:
        """Resolve an escalation record and stamp `resolved_at` with the current UTC time.

        Args:
            escalation_id: Primary key of the escalation row to resolve.
            status: Terminal status string (defaults to `"RESOLVED"`).

        Returns:
            Updated escalation row dictionary, or `None` if `escalation_id` was not found.
        """
        # --- Step 1: Update status and resolved_at timestamp ---
        now = utc_now_iso()
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE escalations
                SET status = ?, resolved_at = ?
                WHERE escalation_id = ?
                """,
                (status, now, escalation_id),
            )
            if cur.rowcount == 0:
                return None

        # --- Step 2: Return the updated row dictionary ---
        cur = self.conn.execute(
            "SELECT * FROM escalations WHERE escalation_id = ?",
            (escalation_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def open_escalations(
        self,
        *,
        pr_id: str | None = None,
        wo_id: str | None = None,
        target_role: str | None = None,
    ) -> list[dict[str, Any]]:
        """List open escalations matching optional filters, ordered by `created_at, rowid`.

        Args:
            pr_id: Optional Pull Request ID filter.
            wo_id: Optional Work Order ID filter.
            target_role: Optional target authority role filter (`"pa"`, `"chief"`, `"human"`).

        Returns:
            Ordered list of matching open escalation row dictionaries.
        """
        clauses = ["status = 'OPEN'"]
        params: list[Any] = []
        if pr_id is not None:
            clauses.append("pr_id = ?")
            params.append(pr_id)
        if wo_id is not None:
            clauses.append("wo_id = ?")
            params.append(wo_id)
        if target_role is not None:
            clauses.append("target_role = ?")
            params.append(target_role)

        sql = (
            f"SELECT * FROM escalations WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at ASC, rowid ASC"
        )
        cur = self.conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    # -------------------------------------------------------------------------
    # attention_queue accessors
    # -------------------------------------------------------------------------

    def enqueue(
        self,
        *,
        kind: str,
        title: str,
        priority: int = 10,
        pr_id: str | None = None,
        wo_id: str | None = None,
        action_payload: Mapping[str, Any] | str | None = None,
        status: str = "OPEN",
        item_id: str | None = None,
    ) -> dict[str, Any]:
        """Enqueue an item into `attention_queue` and return the stored row dictionary.

        Args:
            kind: Category of attention item (e.g. `"plan_approval"`, `"boundary_escalation"`).
            title: Human-readable title displayed in the AuxPane / CLI attention queue.
            priority: Numeric priority (lower integer values sort higher; default `10`).
            pr_id: Optional associated Pull Request ID.
            wo_id: Optional associated Work Order ID.
            action_payload: Optional structured dictionary or JSON string with action context.
            status: Initial queue item status (defaults to `"OPEN"`).
            item_id: Optional explicit item ID; auto-generates `attn_<hex>` when `None`.

        Returns:
            Dictionary containing the newly inserted `attention_queue` row.
        """
        # --- Step 1: Generate item ID and serialize action_payload to JSON ---
        iid = item_id or ("attn_" + uuid.uuid4().hex[:12])
        if action_payload is None:
            payload_json = "{}"
        elif isinstance(action_payload, str):
            payload_json = action_payload
        else:
            payload_json = json.dumps(dict(action_payload))

        # --- Step 2: Insert the attention queue row into SQLite ---
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO attention_queue (
                    item_id, priority, kind, pr_id, wo_id,
                    title, action_payload_json, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iid,
                    priority,
                    kind,
                    pr_id,
                    wo_id,
                    title,
                    payload_json,
                    status,
                    now,
                ),
            )

        # --- Step 3: Fetch and return the stored attention_queue row ---
        cur = self.conn.execute(
            "SELECT * FROM attention_queue WHERE item_id = ?",
            (iid,),
        )
        row = cur.fetchone()
        assert row is not None
        return dict(row)

    def dequeue(self, item_id: str, status: str = "RESOLVED") -> dict[str, Any] | None:
        """Update an attention queue item's status, returning the updated row or `None`.

        Args:
            item_id: Primary key of the `attention_queue` item to update.
            status: New status string (defaults to `"RESOLVED"`).

        Returns:
            Updated attention item dictionary, or `None` if `item_id` does not exist.
        """
        with self.conn:
            cur = self.conn.execute(
                "UPDATE attention_queue SET status = ? WHERE item_id = ?",
                (status, item_id),
            )
            if cur.rowcount == 0:
                return None
        cur = self.conn.execute(
            "SELECT * FROM attention_queue WHERE item_id = ?",
            (item_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def list_open(self, *, pr_id: str | None = None) -> list[dict[str, Any]]:
        """List open attention queue items ordered by `priority ASC, created_at ASC, rowid ASC`.

        Args:
            pr_id: Optional Pull Request ID filter.

        Returns:
            Ordered list of open `attention_queue` row dictionaries.
        """
        clauses = ["status = 'OPEN'"]
        params: list[Any] = []
        if pr_id is not None:
            clauses.append("pr_id = ?")
            params.append(pr_id)

        sql = (
            f"SELECT * FROM attention_queue WHERE {' AND '.join(clauses)} "
            "ORDER BY priority ASC, created_at ASC, rowid ASC"
        )
        cur = self.conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    # -------------------------------------------------------------------------
    # session_state accessors (WO dispatch tracking for compaction resilience)
    # -------------------------------------------------------------------------

    def track_dispatch(
        self,
        conversation_id: str,
        wo_id: str,
        *,
        subagent_conv_id: str | None = None,
    ) -> dict[str, Any]:
        """Record or update a Work Order dispatch in session_state.

        Args:
            conversation_id: PA session conversation UUID.
            wo_id: Work Order identifier being dispatched.
            subagent_conv_id: Optional engineer subagent conversation UUID.

        Returns:
            Dictionary of the upserted session_state row.
        """
        # --- Step 1: Generate dispatched_at timestamp ---
        now = utc_now_iso()

        # --- Step 2: Upsert the dispatch row, updating on conflict ---
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO session_state (
                    conversation_id, wo_id, dispatch_status,
                    subagent_conv_id, dispatched_at
                )
                VALUES (?, ?, 'dispatched', ?, ?)
                ON CONFLICT(conversation_id, wo_id) DO UPDATE SET
                    dispatch_status = 'dispatched',
                    subagent_conv_id = excluded.subagent_conv_id,
                    dispatched_at = excluded.dispatched_at
                """,
                (conversation_id, wo_id, subagent_conv_id, now),
            )

        # --- Step 3: Fetch and return the stored row ---
        cur = self.conn.execute(
            "SELECT * FROM session_state WHERE conversation_id = ? AND wo_id = ?",
            (conversation_id, wo_id),
        )
        row = cur.fetchone()
        assert row is not None
        return dict(row)

    def track_completion(
        self,
        conversation_id: str,
        wo_id: str,
        *,
        status: str = "completed",
        result_summary: str | None = None,
    ) -> dict[str, Any]:
        """Record Work Order completion or escalation in session_state.

        Args:
            conversation_id: PA session conversation UUID.
            wo_id: Work Order identifier.
            status: Terminal status ('completed', 'escalated', 'blocked').
            result_summary: Optional one-line result description.

        Returns:
            Updated session_state row dictionary.
        """
        # --- Step 1: Generate completed_at timestamp ---
        now = utc_now_iso()

        # --- Step 2: Update the matching row with terminal status ---
        with self.conn:
            self.conn.execute(
                """
                UPDATE session_state
                SET dispatch_status = ?, completed_at = ?, result_summary = ?
                WHERE conversation_id = ? AND wo_id = ?
                """,
                (status, now, result_summary, conversation_id, wo_id),
            )

        # --- Step 3: Fetch and return the updated row ---
        cur = self.conn.execute(
            "SELECT * FROM session_state WHERE conversation_id = ? AND wo_id = ?",
            (conversation_id, wo_id),
        )
        row = cur.fetchone()
        assert row is not None
        return dict(row)

    def get_session_state(self, conversation_id: str) -> list[dict[str, Any]]:
        """Fetch all session_state rows for a conversation, ordered by dispatched_at.

        Args:
            conversation_id: PA session conversation UUID.

        Returns:
            List of session_state row dictionaries.
        """
        # --- Step 1: Query all dispatch rows for the conversation ---
        cur = self.conn.execute(
            """
            SELECT * FROM session_state
            WHERE conversation_id = ?
            ORDER BY dispatched_at ASC, rowid ASC
            """,
            (conversation_id,),
        )
        return [dict(row) for row in cur.fetchall()]

    # -------------------------------------------------------------------------
    # session_decisions accessors
    # -------------------------------------------------------------------------

    def record_decision(
        self,
        conversation_id: str,
        summary: str,
        *,
        decision_type: str = "decision",
    ) -> dict[str, Any]:
        """Record a session decision, dead_end, or pending_action.

        Args:
            conversation_id: Session conversation UUID.
            summary: One-line description of the decision or observation.
            decision_type: Category ('decision', 'dead_end', 'pending_action').

        Returns:
            Dictionary of the inserted session_decisions row.
        """
        # --- Step 1: Generate created_at timestamp ---
        now = utc_now_iso()

        # --- Step 2: Insert the decision row ---
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO session_decisions (
                    conversation_id, decision_type, summary, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, decision_type, summary, now),
            )
            row_id = cur.lastrowid

        # --- Step 3: Fetch and return the stored row ---
        cur = self.conn.execute(
            "SELECT * FROM session_decisions WHERE id = ?",
            (row_id,),
        )
        row = cur.fetchone()
        assert row is not None
        return dict(row)

    def get_session_decisions(self, conversation_id: str) -> list[dict[str, Any]]:
        """Fetch all session_decisions for a conversation, ordered by created_at.

        Args:
            conversation_id: Session conversation UUID.

        Returns:
            List of session_decisions row dictionaries.
        """
        # --- Step 1: Query all decision rows for the conversation ---
        cur = self.conn.execute(
            """
            SELECT * FROM session_decisions
            WHERE conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id,),
        )
        return [dict(row) for row in cur.fetchall()]


class Registry:
    """Global enrollment registry manager maintaining `<daemon_home>/state/registry.json`.

    Uses atomic temporary-file + `os.fsync` + `os.replace` writes so concurrent
    fast-exit hook checks (`common.is_repo_enrolled`) never observe partial JSON.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        """Initialize the `Registry` manager at `path` or the default daemon state path.

        Args:
            path: Optional explicit path to `registry.json`; defaults to
                `common.daemon_home() / "state" / "registry.json"`.
        """
        if path is not None:
            # Filesystem path to the global JSON enrollment registry file.
            self.path = Path(path)
        else:
            self.path = common.daemon_home() / "state" / "registry.json"

    def _load_data(self) -> dict[str, Any]:
        """Load and validate the registry JSON payload from `self.path`.

        Returns:
            Dictionary containing `"schema_version"` and `"repos"` mapping; falls back to
            an empty registry structure if the file is missing or corrupt.
        """
        if not self.path.is_file():
            return {"schema_version": 1, "repos": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "repos" in data and isinstance(data["repos"], dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"schema_version": 1, "repos": {}}

    def _write_data(self, data: Mapping[str, Any]) -> None:
        """Atomically persist `data` to `self.path` via a sibling temporary file and `os.replace`.

        Args:
            data: Complete registry dictionary to serialize as pretty-printed JSON.

        Raises:
            OSError: If writing, flushing, syncing, or replacing the registry file fails.
        """
        # --- Step 1: Ensure the parent state directory exists and open a sibling temp file ---
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(self.path.parent),
            delete=False,
            prefix=".registry.",
            suffix=".tmp",
        ) as tmp:
            tmp_name = tmp.name
            try:
                # --- Step 2: Serialize JSON and fsync file descriptor before atomic rename ---
                json.dump(data, tmp, indent=2)
                tmp.write("\n")
                tmp.flush()
                os.fsync(tmp.fileno())
            except BaseException:
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass
                raise

        # --- Step 3: Atomically replace the target registry file ---
        os.replace(tmp_name, self.path)

    def register(
        self,
        repo_root: str | Path,
        *,
        workspace_dir: str | Path | None = None,
        slug: str | None = None,
    ) -> dict[str, Any]:
        """Register a repository root idempotently and return its metadata dictionary.

        Preserves the original `enrolled_at` timestamp if the repository is already enrolled.

        Args:
            repo_root: Path to the git repository root directory.
            workspace_dir: Optional explicit workspace directory path; defaults to
                `common.workspace_dir(repo_root)`.
            slug: Optional human-readable slug; defaults to the repository directory basename.

        Returns:
            Enrollment metadata dictionary containing `"slug"`, `"enrolled_at"`, and
            `"workspace_dir"`.
        """
        # --- Step 1: Canonicalize repository root path, workspace path, and slug ---
        real_root = os.path.realpath(str(repo_root))
        ws_dir = (
            str(workspace_dir)
            if workspace_dir is not None
            else str(common.workspace_dir(real_root))
        )
        repo_slug = slug or Path(real_root).name

        # --- Step 2: Load current registry and preserve existing enrolled_at if present ---
        data = self._load_data()
        repos = data.setdefault("repos", {})

        existing = repos.get(real_root)
        enrolled_at = (
            existing["enrolled_at"]
            if isinstance(existing, dict) and "enrolled_at" in existing
            else utc_now_iso()
        )

        # --- Step 3: Persist updated entry atomically and return it ---
        entry = {
            "slug": repo_slug,
            "enrolled_at": enrolled_at,
            "workspace_dir": ws_dir,
        }
        repos[real_root] = entry
        self._write_data(data)
        return entry

    def unregister(self, repo_root: str | Path) -> bool:
        """Unregister a repository root from `registry.json`.

        Args:
            repo_root: Path to the git repository root directory to remove.

        Returns:
            `True` if an existing entry was removed; `False` if the repository was not enrolled.
        """
        real_root = os.path.realpath(str(repo_root))
        data = self._load_data()
        repos = data.get("repos", {})
        if real_root in repos:
            del repos[real_root]
            self._write_data(data)
            return True
        return False

    def lookup(self, repo_root: str | Path) -> dict[str, Any] | None:
        """Look up registration metadata for a repository root, or `None` if unenrolled.

        Args:
            repo_root: Path to the git repository root directory.

        Returns:
            Copy of the repository's enrollment metadata dictionary, or `None` if not enrolled.
        """
        real_root = os.path.realpath(str(repo_root))
        data = self._load_data()
        entry = data.get("repos", {}).get(real_root)
        if isinstance(entry, dict):
            return dict(entry)
        return None

    def list(self) -> dict[str, dict[str, Any]]:
        """Return a shallow copy of the enrolled repositories mapping.

        Returns:
            Dictionary mapping canonical repository root paths to their metadata dictionaries.
        """
        data = self._load_data()
        repos = data.get("repos", {})
        return {str(k): dict(v) for k, v in repos.items() if isinstance(v, dict)}
