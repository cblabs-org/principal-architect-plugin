---
schema_version: 1
wo_id: WO-01.4
pr_id: PR-01
title: "Repo-local SQLite StateDB (WAL, 5 SPEC §6.5 tables) and global atomic Registry"
complexity: standard
status: IN_PROGRESS
allowed_files:
  - daemon/workspace-plugin/principal-architect/scripts/state_db.py
  - tests/test_state_db_and_sync.py
forbidden_files:
  - SPEC.md
  - docs/positioning-paper.md
  - .agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/PROJECT.md
  - .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: "./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests"
max_attempts: 5
max_structural_failures: 2
spec_hash: "56d01cfbe1367df324c72d3253e80fa32e464226e4046be565a9985ee44973ef"
completion: null
---

# WO-01.4 — Repo-Local SQLite `StateDB` & Global Atomic `Registry`

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-01` (`pr-01-core-schemas-and-enrollment`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T18:50:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/workspace-plugin/principal-architect/scripts/state_db.py` providing `TABLES`, `StateDB` (WAL mode, `busy_timeout=5000`, `PRAGMA user_version = 1`, idempotent creation of the 5 SPEC §6.5 tables with exact column sets, context-manager support, and typed transactional accessors), and `Registry` (atomic temp-file + `os.replace` management of `<daemon_home>/state/registry.json`), verified by unit tests in `tests/test_state_db_and_sync.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/state_db.py`
  - `tests/test_state_db_and_sync.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/wo4-state-db-and-registry/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh`. Commit only on the currently checked-out branch `pr-01-core-schemas-and-enrollment/wo4-state-db-and-registry` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/state_db.py` (Charter G5, R5, §2.2, SPEC §6.5):**
  1. **Constants:**
     - `TABLES: tuple[str, ...] = ("repo_config", "sessions", "verification_receipts", "escalations", "attention_queue")`
     - `SCHEMA_VERSION: int = 1`
     - Helper `utc_now_iso() -> str`: returns `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")`.
  2. **`StateDB(path: str | Path)`:**
     - Store `self.path = Path(path)`, create parent directories (`self.path.parent.mkdir(parents=True, exist_ok=True)`), open `sqlite3.connect(str(self.path))` with `row_factory = sqlite3.Row`.
     - Execute `PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout=5000;` on connection open.
     - Support context-manager protocol (`__enter__ -> StateDB`, `__exit__` closes connection, `close()` method).
     - `init() -> None` (called automatically in `__init__` and safe/idempotent to call again): inside `with self.conn:`, create the 5 tables with `CREATE TABLE IF NOT EXISTS` using the exact columns of SPEC §6.5:
       1. `repo_config`: `key TEXT PRIMARY KEY, value TEXT`
       2. `sessions`: `conversation_id TEXT PRIMARY KEY, role TEXT, programme_id TEXT, pr_id TEXT, wo_id TEXT, attempt_num INTEGER, structural_failures INTEGER, pinned INTEGER, last_checkpoint_step INTEGER, created_at TEXT, updated_at TEXT`
       3. `verification_receipts`: `receipt_id TEXT PRIMARY KEY, wo_id TEXT, pr_id TEXT, cmd TEXT, exit_code INTEGER, tree_hash TEXT, git_head_sha TEXT, valid INTEGER, created_at TEXT`
       4. `escalations`: `escalation_id TEXT PRIMARY KEY, level TEXT, source_role TEXT, target_role TEXT, pr_id TEXT, wo_id TEXT, blocker_type TEXT, reason_code TEXT, requested_files_json TEXT, summary TEXT, status TEXT, github_issue_or_comment_url TEXT, created_at TEXT, resolved_at TEXT`
       5. `attention_queue`: `item_id TEXT PRIMARY KEY, priority INTEGER, kind TEXT, pr_id TEXT, wo_id TEXT, title TEXT, action_payload_json TEXT, status TEXT, created_at TEXT`
       - Also set `PRAGMA user_version = 1`.
     - **Typed Accessors (all writes in transactions via `with self.conn:`, returning plain `dict[str, Any]` for row results):**
       - **`repo_config`:**
         - `get_config(key: str, default: str | None = None) -> str | None`
         - `set_config(key: str, value: str) -> None` (`INSERT INTO repo_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value`)
         - `get_all_config() -> dict[str, str]`
       - **`sessions`:**
         - `bind_session(conversation_id: str, role: str, *, programme_id: str | None = None, pr_id: str | None = None, wo_id: str | None = None, attempt_num: int = 1, structural_failures: int = 0, pinned: bool | int = 0, last_checkpoint_step: int | None = None) -> dict[str, Any]` (upserts session, setting `created_at` on insert and `updated_at` on insert/update, returning the stored row as `dict`).
         - `get_session(conversation_id: str) -> dict[str, Any] | None`
         - `update_session(conversation_id: str, **fields: Any) -> dict[str, Any] | None` (validates field names against allowed `sessions` columns, updates `updated_at = utc_now_iso()`, returns updated row or `None` if not found).
       - **`verification_receipts`:**
         - `insert_receipt(*, wo_id: str, pr_id: str, cmd: str, exit_code: int, tree_hash: str, git_head_sha: str | None = None, valid: bool | int = 1, receipt_id: str | None = None) -> dict[str, Any]` (if `receipt_id` is None, generates `"rcpt_" + uuid4().hex[:12]` or deterministic prefix, inserts row with `created_at`, returns stored row as `dict`).
         - `invalidate_receipts(wo_id: str) -> int` (`UPDATE verification_receipts SET valid = 0 WHERE wo_id = ? AND valid = 1`, returning rowcount).
         - `latest_valid_receipt(wo_id: str, tree_hash: str | None = None) -> dict[str, Any] | None` (returns most recent `valid = 1` receipt for `wo_id`, optionally matching `tree_hash`, ordered by `created_at DESC, rowid DESC`).
       - **`escalations`:**
         - `insert_escalation(*, level: str, source_role: str, target_role: str, pr_id: str | None = None, wo_id: str | None = None, blocker_type: str = "other", reason_code: str = "UNSPECIFIED", requested_files: Sequence[str] | str | None = None, summary: str = "", status: str = "OPEN", github_issue_or_comment_url: str | None = None, escalation_id: str | None = None) -> dict[str, Any]` (serializes `requested_files` to JSON string if sequence, generates `escalation_id = "esc_" + uuid4().hex[:12]` if None, sets `created_at`, `resolved_at = None`, returns stored row as `dict`).
         - `resolve_escalation(escalation_id: str, status: str = "RESOLVED") -> dict[str, Any] | None` (sets `status` and `resolved_at = utc_now_iso()`, returns updated row or `None`).
         - `open_escalations(*, pr_id: str | None = None, wo_id: str | None = None, target_role: str | None = None) -> list[dict[str, Any]]` (returns rows with `status = 'OPEN'` matching optional filters, ordered by `created_at ASC, rowid ASC`).
       - **`attention_queue`:**
         - `enqueue(*, kind: str, title: str, priority: int = 10, pr_id: str | None = None, wo_id: str | None = None, action_payload: Mapping[str, Any] | str | None = None, status: str = "OPEN", item_id: str | None = None) -> dict[str, Any]` (serializes `action_payload` to JSON string if mapping, generates `item_id = "attn_" + uuid4().hex[:12]` if None, sets `created_at`, returns stored row as `dict`).
         - `dequeue(item_id: str, status: str = "RESOLVED") -> dict[str, Any] | None` (updates `status`, returns updated row or `None`).
         - `list_open(*, pr_id: str | None = None) -> list[dict[str, Any]]` (returns rows with `status = 'OPEN'`, ordered by `priority ASC, created_at ASC, rowid ASC`).
  3. **`Registry(path: str | Path | None = None)`:**
     - Defaults `self.path` to `common.daemon_home() / "state" / "registry.json"` when `path is None`.
     - File format (Charter R5): `{"schema_version": 1, "repos": {"<abs-repo-root>": {"slug": str, "enrolled_at": str, "workspace_dir": str}}}`.
     - Atomic write helper: creates `self.path.parent`, writes JSON to `tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=str(self.path.parent), delete=False, prefix=".registry.", suffix=".tmp")`, flushes + `os.fsync`, closes, and replaces `self.path` via `os.replace(tmp_name, self.path)`.
     - Methods:
       - `register(repo_root: str | Path, *, workspace_dir: str | Path | None = None, slug: str | None = None) -> dict[str, Any]`: resolves `real_root = os.path.realpath(repo_root)`, defaults `workspace_dir` to `str(common.workspace_dir(real_root))` and `slug` to `Path(real_root).name`, preserves existing `enrolled_at` if already registered (idempotent!) or sets `utc_now_iso()`, writes atomically, and returns the repo metadata dict.
       - `unregister(repo_root: str | Path) -> bool`: removes `os.path.realpath(repo_root)` from `"repos"` if present, writes atomically, and returns `True` if an entry was removed else `False`.
       - `lookup(repo_root: str | Path) -> dict[str, Any] | None`: returns the entry for `os.path.realpath(repo_root)` or `None`.
       - `list() -> dict[str, dict[str, Any]]`: returns a copy of the `"repos"` mapping (`{"<abs-repo-root>": {...}}`).
- [ ] **`tests/test_state_db_and_sync.py`:**
  - Add comprehensive unit tests for `StateDB` and `Registry`:
    - Verify `TABLES` order and exact column names on all 5 tables via `PRAGMA table_info(...)`.
    - Verify `PRAGMA journal_mode` is `"wal"`, `PRAGMA busy_timeout` is `5000`, and `PRAGMA user_version` is `1`.
    - Verify `init()` is idempotent when called multiple times or reopened on an existing database file, and context manager (`with StateDB(db_path) as db:`) closes cleanly.
    - Exercise every accessor:
      - `repo_config`: `get_config` default, `set_config` insert + upsert overwrite, `get_all_config`.
      - `sessions`: `bind_session` insert + upsert, `get_session`, `update_session` (valid fields, nonexistent ID -> `None`, invalid column -> `ValueError`).
      - `verification_receipts`: `insert_receipt`, `latest_valid_receipt` (with and without `tree_hash` filter), `invalidate_receipts` setting `valid = 0` so `latest_valid_receipt` returns `None`.
      - `escalations`: `insert_escalation` (with list `requested_files`), `open_escalations` (with `pr_id` and `target_role` filters), `resolve_escalation` removing it from `open_escalations`.
      - `attention_queue`: `enqueue` with different priorities, `list_open` priority ordering, `dequeue` removing item from `list_open`.
    - Exercise `Registry`: `register` (creating `registry.json` atomically, verifying `common.is_repo_enrolled` returns `True`), idempotent re-`register` preserving `enrolled_at`, `lookup`, `list`, `unregister` (returning `True` then `False` on repeat, and verifying `common.is_repo_enrolled` returns `False`), and resilience to missing/corrupt initial file.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute `tree_hash`, update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block — using strictly valid `CompletionReport` keys: `status`, `attempt_num`, `receipt_id`, `commit_sha`, `files_modified`, `verification_summary`, `out_of_scope_findings`, `escalation_request`, `decisions_made`, `dead_ends`) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-01-core-schemas-and-enrollment/wo4-state-db-and-registry` with message:
   ```text
   WO-01.4: Repo-local SQLite StateDB and global atomic Registry

   PA-WorkOrder: WO-01.4
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

_Pending execution by Tier 3 Worker (`WO-01.4`)._
