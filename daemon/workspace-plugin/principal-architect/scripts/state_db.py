"""Repo-local SQLite StateDB and global atomic Registry.

Implements SPEC §6.5 (5 tables in WAL mode with busy_timeout=5000 and PRAGMA user_version=1)
and Charter R5 global repository registry with atomic file replacements.
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

TABLES: tuple[str, ...] = (
    "repo_config",
    "sessions",
    "verification_receipts",
    "escalations",
    "attention_queue",
)

SCHEMA_VERSION: int = 1


def utc_now_iso() -> str:
    """Return the current UTC timestamp formatted as ISO 8601 with trailing 'Z'."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class StateDB:
    """Repo-local SQLite state database in WAL mode for persistent workflow coordination."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self.init()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()

    def init(self) -> None:
        """Create the 5 SPEC §6.5 tables idempotently and set PRAGMA user_version=1."""
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
            self.conn.execute("PRAGMA user_version = 1;")

    # -------------------------------------------------------------------------
    # repo_config accessors
    # -------------------------------------------------------------------------

    def get_config(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a configuration string by key, returning default if not found."""
        cur = self.conn.execute("SELECT value FROM repo_config WHERE key = ?", (key,))
        row = cur.fetchone()
        if row is None:
            return default
        return str(row["value"])

    def set_config(self, key: str, value: str) -> None:
        """Insert or update a configuration key-value pair."""
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
        """Return all configuration pairs as a dictionary."""
        cur = self.conn.execute("SELECT key, value FROM repo_config ORDER BY key ASC")
        return {str(row["key"]): str(row["value"]) for row in cur.fetchall()}

    # -------------------------------------------------------------------------
    # sessions accessors
    # -------------------------------------------------------------------------

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
        """Upsert a session binding, setting created_at on insert and updated_at always."""
        now = utc_now_iso()
        pinned_int = 1 if pinned else 0
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
        res = self.get_session(conversation_id)
        assert res is not None
        return res

    def get_session(self, conversation_id: str) -> dict[str, Any] | None:
        """Fetch a session row as a dict, or None if not found."""
        cur = self.conn.execute(
            "SELECT * FROM sessions WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def update_session(self, conversation_id: str, **fields: Any) -> dict[str, Any] | None:
        """Update fields on an existing session, updating updated_at.

        Validates that all field names exist in sessions columns.
        Returns the updated row as a dict, or None if session does not exist.
        """
        for k in fields:
            if k not in self._SESSION_COLUMNS:
                raise ValueError(f"Invalid sessions column: '{k}'")
            if k in ("conversation_id", "created_at"):
                raise ValueError(f"Cannot update immutable column: '{k}'")

        cur = self.conn.execute(
            "SELECT conversation_id FROM sessions WHERE conversation_id = ?",
            (conversation_id,),
        )
        if cur.fetchone() is None:
            return None

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
        """Insert a verification receipt row, returning the stored row."""
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
        cur = self.conn.execute(
            "SELECT * FROM verification_receipts WHERE receipt_id = ?",
            (rid,),
        )
        row = cur.fetchone()
        assert row is not None
        return dict(row)

    def invalidate_receipts(self, wo_id: str) -> int:
        """Mark all currently valid receipts for wo_id as invalid (valid = 0).

        Returns the number of affected rows.
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
        """Return the most recent valid receipt for wo_id, optionally matching tree_hash."""
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
        """Insert an escalation record, returning the stored row."""
        eid = escalation_id or ("esc_" + uuid.uuid4().hex[:12])
        if requested_files is None:
            req_json = "[]"
        elif isinstance(requested_files, str):
            req_json = requested_files
        else:
            req_json = json.dumps(list(requested_files))

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
        """Resolve an escalation record, recording resolved_at timestamp."""
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
        """List open escalations matching optional filters, ordered by created_at, rowid."""
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

        sql = f"SELECT * FROM escalations WHERE {' AND '.join(clauses)} ORDER BY created_at ASC, rowid ASC"
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
        """Enqueue an item into the attention queue, returning the stored row."""
        iid = item_id or ("attn_" + uuid.uuid4().hex[:12])
        if action_payload is None:
            payload_json = "{}"
        elif isinstance(action_payload, str):
            payload_json = action_payload
        else:
            payload_json = json.dumps(dict(action_payload))

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
        cur = self.conn.execute(
            "SELECT * FROM attention_queue WHERE item_id = ?",
            (iid,),
        )
        row = cur.fetchone()
        assert row is not None
        return dict(row)

    def dequeue(self, item_id: str, status: str = "RESOLVED") -> dict[str, Any] | None:
        """Update an attention queue item's status, returning the updated row or None."""
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
        """List open attention queue items, ordered by priority ASC, created_at ASC, rowid ASC."""
        clauses = ["status = 'OPEN'"]
        params: list[Any] = []
        if pr_id is not None:
            clauses.append("pr_id = ?")
            params.append(pr_id)

        sql = f"SELECT * FROM attention_queue WHERE {' AND '.join(clauses)} ORDER BY priority ASC, created_at ASC, rowid ASC"
        cur = self.conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


class Registry:
    """Global enrollment registry manager maintaining `<daemon_home>/state/registry.json`.

    Uses atomic temporary-file + os.replace writes to guarantee consistency.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        if path is not None:
            self.path = Path(path)
        else:
            self.path = common.daemon_home() / "state" / "registry.json"

    def _load_data(self) -> dict[str, Any]:
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

        os.replace(tmp_name, self.path)

    def register(
        self,
        repo_root: str | Path,
        *,
        workspace_dir: str | Path | None = None,
        slug: str | None = None,
    ) -> dict[str, Any]:
        """Register a repository root idempotently, returning the repo metadata dict."""
        real_root = os.path.realpath(str(repo_root))
        ws_dir = (
            str(workspace_dir)
            if workspace_dir is not None
            else str(common.workspace_dir(real_root))
        )
        repo_slug = slug or Path(real_root).name

        data = self._load_data()
        repos = data.setdefault("repos", {})

        existing = repos.get(real_root)
        enrolled_at = (
            existing["enrolled_at"]
            if isinstance(existing, dict) and "enrolled_at" in existing
            else utc_now_iso()
        )

        entry = {
            "slug": repo_slug,
            "enrolled_at": enrolled_at,
            "workspace_dir": ws_dir,
        }
        repos[real_root] = entry
        self._write_data(data)
        return entry

    def unregister(self, repo_root: str | Path) -> bool:
        """Unregister a repository root.

        Returns True if an entry was removed, else False.
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
        """Look up registration metadata for a repository root, or None if unenrolled."""
        real_root = os.path.realpath(str(repo_root))
        data = self._load_data()
        entry = data.get("repos", {}).get(real_root)
        if isinstance(entry, dict):
            return dict(entry)
        return None

    def list(self) -> dict[str, dict[str, Any]]:
        """Return a copy of the enrolled repositories mapping."""
        data = self._load_data()
        repos = data.get("repos", {})
        return {str(k): dict(v) for k, v in repos.items() if isinstance(v, dict)}
