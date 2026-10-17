---
schema_version: 1
wo_id: WO-03.1
pr_id: PR-03
title: Local-Git floor (VcsBus protocol, LocalGitBus stacked branches, commit trailers,
  AUDIT-round-K.md, DEFERRED_BACKLOG.md, sync_state, restack)
complexity: architect
status: COMPLETED
allowed_files:
- daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py
- tests/test_github_and_local_git_bus.py
- tests/test_memory_modes.py
forbidden_files:
- SPEC.md
- docs/positioning-paper.md
- .agents/skills/principal-architect-workspace/pr-03-vcs-bus-models-and-memory-modes/PROJECT.md
- .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py
  tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py
  tests/test_memory_modes.py && ./.venv/bin/ruff check daemon tests
max_attempts: 5
max_structural_failures: 2
spec_hash: f09f182367f622e97389ac178f2341c2ada87fd0f577133558eaecf1f0e19bae
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: rcpt_2b45270c49ce
  commit_sha: 55a63af495e9592542be5e93c52e724dea802f39
  files_modified:
  - daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py
  - tests/test_github_and_local_git_bus.py
  - tests/test_memory_modes.py
  verification_summary: "95 passed in pytest verification floor (17 schemas, 34 state_db_and_sync, 34 hooks, 9 local_git_bus, 1 memory_modes); ruff check clean."
  out_of_scope_findings: []
  escalation_request: null
  decisions_made:
  - "Implemented LocalGitBus and VcsBus protocol in scripts/vcs_sync.py with injectable runner, commit trailer formatting/parsing, machine-parseable <!-- pa:audit --> comment formatting/parsing, audit round persistence up to round 5, deferred backlog writer, state.db rebuild in sync_state, and git rebase --update-refs restacking (including branch discovery from refs/heads/ when invoked from main)."
  dead_ends: []
---

# WO-03.1 — Local-Git Floor (`vcs_sync.py`: `VcsBus` & `LocalGitBus`)

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-03` (`pr-03-vcs-bus-models-and-memory-modes`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T21:37:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py` providing the `VcsBus` protocol/base and `LocalGitBus` (stacked branch create/checkout `create_or_checkout_branch`, commit trailer helpers `read_commit_trailers` / `read_trailers` / `format_commit_with_trailers`, `format_pa_audit_comment` / `parse_pa_audit_comment`, `write_audit_round` validating `AuditReport` up to `max_audit_rounds: 5` and committing `AUDIT-round-<K>.md` with trailer `PA-Audit-Verdict: <verdict> (<head_sha>)`, `append_deferred_backlog` writing/appending `<workspace_dir>/DEFERRED_BACKLOG.md`, `sync_state` rebuilding `state.db` from local trailers and committed `WORKORDER.md`/`AUDIT-round-*.md`, and `restack_branches` via `git rebase --update-refs`), plus initial unit tests in `tests/test_github_and_local_git_bus.py` and placeholder tests in `tests/test_memory_modes.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py`
  - `tests/test_github_and_local_git_bus.py`
  - `tests/test_memory_modes.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-03-vcs-bus-models-and-memory-modes/wo1-local-git-bus/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh` on the workspace repository. Commit only on the currently checked-out branch `pr-03-vcs-bus-models-and-memory-modes/wo1-local-git-bus` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R7):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py`:**
  1. **Commit Trailer Helpers (`format_commit_with_trailers`, `read_commit_trailers`, `read_trailers`):**
     - `format_commit_with_trailers(subject: str, body: str | None = None, trailers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None) -> str`:
       - Formats a commit message with `subject.strip()`, optional `body.strip()`, and `Key: Value` trailer lines at the bottom separated by a blank line.
     - `read_commit_trailers(repo_root: str | Path, *, rev_range: str | None = None, max_count: int | None = None, runner: common.Runner = common.run) -> list[dict[str, Any]]` (and alias `read_trailers = read_commit_trailers`):
       - Runs `git log` in `repo_root` (with optional `rev_range` and `-n <max_count>`) extracting commit hash `%H`, subject `%s`, `PA-WorkOrder`, `PA-Verified-Hash`, and `PA-Audit-Verdict`.
       - Parses `PA-Audit-Verdict` values of the form `<VERDICT> (<head_sha>)` or `<VERDICT>` into `"audit_verdict"` and `"audit_head_sha"`.
       - Returns a list of dicts: `{"sha": sha, "subject": subject, "wo_id": wo_id_or_none, "verified_hash": verified_hash_or_none, "audit_verdict": verdict_or_none, "audit_head_sha": audit_head_sha_or_none}`.
  2. **Audit Comment Header Parser & Formatter (`parse_pa_audit_comment`, `format_pa_audit_comment`, Charter R2 & SPEC §11.3):**
     - Support the machine-parseable HTML comment block:
       `<!-- pa:audit pr_id=<PR-ID> round=<K> head_sha=<SHA> verdict=<VERDICT> blocking=<B> major=<M> minor=<N> -->`
       (and also support multi-line `<!-- pa:audit\n...\n-->` YAML/key-value blocks).
     - `format_pa_audit_comment(report: schemas.AuditReport, body_markdown: str | None = None) -> str`:
       - Counts `blocking` (`id.startswith("BLOCKING-")`) and `non_blocking` / `major` / `minor` findings in `report.findings`.
       - Emits the `<!-- pa:audit pr_id=... round=... head_sha=... verdict=... blocking=... major=... minor=... -->` comment line, `**Audit Verdict:** <VERDICT> (<B> blocking, <M> non-blocking)` if not already present in `body_markdown`, and the audit summary/findings markdown.
     - `parse_pa_audit_comment(text: str) -> dict[str, Any] | None`:
       - Extracts `pr_id`, `audit_round` (`int`), `head_sha`, `verdict` (`"APPROVED"` or `"CHANGES_REQUESTED"`), `blocking` (`int`), `major` (`int`), `minor` (`int`), and any embedded `findings` from a `<!-- pa:audit ... -->` block or YAML frontmatter in `text`. Returns `None` if no valid `pa:audit` marker is present.
  3. **Audit Round Persistence (`write_audit_round`, Charter G1 & R2):**
     - `write_audit_round(repo_root: str | Path, pr_id: str, audit_source: str | Path | schemas.AuditReport | schemas.Document[schemas.AuditReport] | Mapping[str, Any], *, commit: bool = True, runner: common.Runner = common.run) -> Path`:
       - Resolves `real_root = Path(os.path.realpath(repo_root))` and `ws_dir = common.workspace_dir(real_root)`.
       - Loads/validates `AuditReport` via `schemas.load_audit` (if path or Markdown text with frontmatter) or `schemas.AuditReport.model_validate` (if dict/model). Enforces `1 <= report.audit_round <= 5` (`max_audit_rounds: 5`, raising `ValueError` if violated) and verifies `report.pr_id.upper() == pr_id.upper()`.
       - Locates the PR directory under `ws_dir` (`pr-*/PROJECT.md` matching `pr_id`, or `ws_dir / f"pr-{pr_id.lower()}"`).
       - Ensures the `AUDIT-round-<K>.md` sections include the `<!-- pa:audit ... -->` comment and `**Audit Verdict:** <verdict> ...` line, and writes `<pr_dir>/AUDIT-round-<K>.md` via `schemas.dump_document(report, sections)`.
       - If `<pr_dir>/PROJECT.md` exists and is loadable via `schemas.load_project`, updates `proj_doc.spec.status` to `schemas.PRState.AUDIT_APPROVED` (when `report.verdict == "APPROVED"`) or `schemas.PRState.CHANGES_REQUESTED` (when `report.verdict == "CHANGES_REQUESTED"`), preserving Part I `charter_hash` intact.
       - If `commit=True`, runs `git add` on `AUDIT-round-<K>.md` (and `PROJECT.md` if updated) and commits with message:
         `audit(<pr_id.lower()>): round <K> — <report.verdict>\n\nPA-Audit-Verdict: <report.verdict> (<report.head_sha>)`
       - Returns the `Path` to `AUDIT-round-<K>.md`.
  4. **Deferred Backlog Writer (`append_deferred_backlog`, Charter G1 & SPEC §8):**
     - `append_deferred_backlog(repo_root: str | Path, *, title: str, summary: str = "", pr_id: str | None = None, wo_id: str | None = None, labels: Sequence[str] = ("pa:deferred",), file_path: str | None = None) -> Path`:
       - Writes/appends a dated Markdown bullet/section to `<workspace_dir>/DEFERRED_BACKLOG.md` containing `title`, `pr_id`, `wo_id`, `labels`, `file_path`, and `summary`. Returns the `Path` to `DEFERRED_BACKLOG.md`.
  5. **State Reconciliation (`sync_state`, Charter G1 & SPEC §8):**
     - `sync_state(repo_root: str | Path, *, runner: common.Runner = common.run) -> dict[str, Any]`:
       - Scans `read_commit_trailers(repo_root, runner=runner)`, all `pr-*/PROJECT.md`, `pr-*/wo*/WORKORDER.md`, and `pr-*/AUDIT-round-*.md` under `common.workspace_dir(repo_root)`.
       - Opens `StateDB` at `<workspace_dir>/.state/state.db` and:
         - Reconciles `verification_receipts` for every Work Order that is `COMPLETED` in `WORKORDER.md` or has a `PA-Verified-Hash` commit trailer (computing `tree_hash` via `post_tool_receipt.compute_tree_hash` if needed, inserting/updating a valid receipt row).
         - Updates `PROJECT.md` `work_orders` summary rows (`status`, `attempts`, `commit_sha`) from committed `WORKORDER.md` and git trailers if out of date (without touching Part I `charter_hash`).
         - Reconciles latest `AUDIT-round-*.md` verdict and `last_audit_<PR-ID>` JSON metadata in `repo_config` (`db.set_config(f"latest_audit:{pr_id}", json.dumps(...))`) and updates `last_vcs_sync_at`.
       - Returns `{"vcs_mode": vcs_mode, "synced_receipts": count_receipts, "synced_audits": count_audits, "synced_wos": count_wos, "trailers_found": len(trailers)}`.
  6. **Stacked Branch Management & Restacking (`create_or_checkout_branch`, `restack_branches`, `VcsBus`, `LocalGitBus`):**
     - `create_or_checkout_branch(repo_root: str | Path, branch: str, base_branch: str = "main", *, runner: common.Runner = common.run) -> str`:
       - Checks if `branch` already exists (`git show-ref --verify --quiet refs/heads/<branch>`). If it exists, runs `git checkout <branch>`; otherwise runs `git checkout -b <branch> <base_branch>`. Raises `RuntimeError` if git fails. Returns current `HEAD` SHA.
     - `restack_branches(repo_root: str | Path, *, pr_id: str | None = None, onto_branch: str | None = None, runner: common.Runner = common.run) -> dict[str, Any]`:
       - Resolves target PR(s) from `PROGRAM.md` / `pr-*/PROJECT.md`. For each target PR branch (or current branch if none specified), runs `git rebase --update-refs <onto_or_base_branch> <branch>` via `runner` and returns `{"restacked": [...], "commands": [...]}`.
     - Define `VcsBus(Protocol)` and `LocalGitBus` wrapping these functions cleanly with `self.repo_root` and `self.runner`, plus `get_vcs_bus(repo_root, *, vcs_mode=None, runner=common.run)` (returning `LocalGitBus` in `WO-03.1`; `WO-03.2` will add `GitHubBus`).
- [ ] **`tests/test_github_and_local_git_bus.py` & `tests/test_memory_modes.py`:**
  - In `tests/test_github_and_local_git_bus.py`, write comprehensive tests for `LocalGitBus` against `tmp_repo` with no `gh` binary required:
    1. Stacked branch creation (`create_or_checkout_branch` creating `feat/pr-01` from `main` and `pr-01/wo1` from `feat/pr-01`, plus idempotent checkout of existing branch).
    2. `format_commit_with_trailers` and `read_commit_trailers` / `read_trailers` parsing `PA-WorkOrder`, `PA-Verified-Hash`, and `PA-Audit-Verdict` trailers from real commits in `tmp_repo`.
    3. `format_pa_audit_comment` and `parse_pa_audit_comment` round-tripping `<!-- pa:audit ... -->` metadata.
    4. `write_audit_round` validating `AuditReport`, writing `AUDIT-round-1.md`, updating `PROJECT.md` status (`AUDIT_APPROVED` / `CHANGES_REQUESTED`) while preserving `charter_hash`, committing with `PA-Audit-Verdict: APPROVED (<sha>)`, and rejecting `audit_round > 5`.
    5. `append_deferred_backlog` creating and appending entries to `<workspace_dir>/DEFERRED_BACKLOG.md`.
    6. `sync_state` rebuilding `.state/state.db` (`verification_receipts`, `latest_audit:PR-01`, `last_vcs_sync_at`) from committed `WORKORDER.md`, `AUDIT-round-1.md`, and git trailers after `.state/state.db` is deleted.
    7. `restack_branches` advancing a stacked branch onto an updated `main` commit using `git rebase --update-refs`.
  - In `tests/test_memory_modes.py`, create a clean initial smoke test file so the PR-03 verification floor collects and passes (`WO-03.3` will populate the full `memory_grad.py` test suite).

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 `tree_hash` over `allowed_files` (`post_tool_receipt.compute_tree_hash`), update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (leaving Part I untouched so `spec_hash` remains valid), and commit on `pr-03-vcs-bus-models-and-memory-modes/wo1-local-git-bus` with message:
   ```text
   WO-03.1: local-git bus (VcsBus, LocalGitBus, trailers, audit rounds, sync_state, restack)

   PA-WorkOrder: WO-03.1
   PA-Verified-Hash: <tree_hash>
   ```
   *(Or run `./.venv/bin/python daemon/workspace-plugin/principal-architect/scripts/pa_cli.py wo verify WO-03.1` after updating Part II `## Completion Report`!)*
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report rather than filing issues directly.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

- **Status:** `COMPLETED` (Attempt 1/5)
- **Receipt ID:** `rcpt_2b45270c49ce` (`tree_hash`: `2b45270c49cef7c63b1343d6c2c78e72ec0363d0e09246414d57766bbcba96b5`)
- **Files Modified:**
  - `daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py`
  - `tests/test_github_and_local_git_bus.py`
  - `tests/test_memory_modes.py`
- **Verification Summary:** `95 passed` across `test_schemas.py`, `test_state_db_and_sync.py`, `test_hooks_monitored_vs_autonomous.py`, `test_github_and_local_git_bus.py`, and `test_memory_modes.py`; `ruff check daemon tests` clean (`All checks passed!`).
- **Decisions Made:**
  - Implemented `format_commit_with_trailers`, `read_commit_trailers` (with alias `read_trailers`), `format_pa_audit_comment`, `parse_pa_audit_comment`, `write_audit_round`, `append_deferred_backlog`, `sync_state`, `create_or_checkout_branch`, `restack_branches`, `VcsBus`, `LocalGitBus`, and `get_vcs_bus` in `scripts/vcs_sync.py`.
  - Ensured `write_audit_round`, `sync_state`, and `LocalGitBus.open_or_sync_pr` update `PROJECT.md` Part II/III fields without altering Part I `charter_hash`.
  - Enabled `_collect_restack_targets` to discover `feat/pr-*` branches from `refs/heads/` and inspect their committed `PROJECT.md` via `git show` when `restack_branches` is invoked while `main` is checked out.
- **Out-of-Scope Findings:** None.
