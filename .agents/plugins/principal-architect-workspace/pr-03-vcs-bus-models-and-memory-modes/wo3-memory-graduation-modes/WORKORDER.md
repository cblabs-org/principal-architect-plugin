---
schema_version: 1
wo_id: WO-03.3
pr_id: PR-03
title: Mutually exclusive external vs. builtin memory graduation engine (memory_grad.py)
  and byte-stability tests
complexity: standard
status: COMPLETED
allowed_files:
- daemon/workspace-plugin/principal-architect/scripts/memory_grad.py
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
spec_hash: 093f5c61df1b701141ae83bd6ce4772f77493415a0a0deb5ef53b02e49f27573
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: rcpt_c47bd0bfb4fc
  commit_sha: null
  files_modified:
  - daemon/workspace-plugin/principal-architect/scripts/memory_grad.py
  - tests/test_memory_modes.py
  verification_summary: "108 passed in 41.32s; ruff check daemon tests: All checks passed!"
  out_of_scope_findings: []
  escalation_request: null
  decisions_made:
  - "Used bounded <!-- pa:graduation-summary start --> ... <!-- pa:graduation-summary end --> markers in PROJECT.md Part III (## 4.) with deterministic completed_date so repeated graduation runs in both external and builtin modes are 100% byte-for-byte stable."
  - "Enforced strict zero-touch on <ws_dir>/memory/ when memory_mode == 'external', returning immediately after updating PROJECT.md and PROGRAM.md."
  dead_ends: []
---

# WO-03.3 — Mutually Exclusive `external` vs. `builtin` Memory Graduation (`memory_grad.py`)

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-03` (`pr-03-vcs-bus-models-and-memory-modes`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T21:37:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/workspace-plugin/principal-architect/scripts/memory_grad.py` providing `graduate(repo_root, pr_id, *, memory_mode=None, completed_date=None) -> dict[str, Any]` enforcing the strict mutual-exclusion boundary between `external` (`repo-memory`) and `builtin` memory graduation modes (Charter G3 & R5, Invariant I6, `SPEC.md` §9), and write comprehensive unit and byte-stability tests in `tests/test_memory_modes.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/memory_grad.py`
  - `tests/test_memory_modes.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-03-vcs-bus-models-and-memory-modes/wo3-memory-graduation-modes/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh` on the workspace repository. Commit only on the currently checked-out branch `pr-03-vcs-bus-models-and-memory-modes/wo3-memory-graduation-modes` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R7):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/memory_grad.py`:**
  1. **Core Entrypoint (`graduate`):**
     - `graduate(repo_root: str | Path, pr_id: str, *, memory_mode: str | None = None, completed_date: str | None = None) -> dict[str, Any]`
     - Resolve `real_root = Path(os.path.realpath(repo_root))` and `ws_dir = common.workspace_dir(real_root)`.
     - Resolve `memory_mode`: if `memory_mode is None`, check `<ws_dir>/.state/state.db` (`db.get_config("memory_mode")`), falling back to `"builtin"`. Validate `resolved_mode in ("external", "builtin")` (raise `ValueError` otherwise).
     - Locate `<pr_dir>/PROJECT.md` for `pr_id` under `ws_dir` (matching `charter.pr_id.upper() == pr_id.upper()` or directory name `pr-{pr_id.lower()}*`). Load `proj_doc = schemas.load_project(proj_md)`.
     - Resolve `completed_date`: if not provided, use deterministic `YYYY-MM-DD` from `proj_doc.spec.approved_at[:10]` if present, or `datetime.now(timezone.utc).strftime("%Y-%m-%d")`.
     - Update `proj_doc.spec.status = schemas.PRState.GRADUATED`.
     - Update `PROJECT.md` Part III (`## 4.` section) idempotently using a bounded marker block `<!-- pa:graduation-summary start --> ... <!-- pa:graduation-summary end -->`:
       - Include a compact Work Order table (`WO-ID`, `status`, `attempts`, `commit_sha`), latest audit verdict/round (if any `AUDIT-round-*.md` exists in `pr_dir`), and graduation mode (`external` or `builtin`).
       - Write `PROJECT.md` via `schemas.dump_document(proj_doc.spec, proj_doc.sections)` and verify `schemas.verify_charter_hash(proj_md)` if `charter_locked` and `charter_hash` are set!
     - If `PROGRAM.md` exists under `ws_dir / "programme-*"`, update the matching `PRNodeSpec` entry (`pr_node.status = schemas.PRState.GRADUATED`) and save `PROGRAM.md` idempotently.
  2. **Mode A — `memory_mode == "external"` (`repo-memory` active, SPEC §9.1 & Charter R5):**
     - **Strict Boundary Invariant (I6):** Do **NOT** create `<ws_dir>/memory/`, and do **NOT** create, read, or modify `MEMORY.md`, `MODULE_INDEX.md`, or `PROJECT_INDEX.md` even if `<ws_dir>/memory/` already exists on disk!
     - Return `{"pr_id": canonical_pr_id, "slug": slug, "memory_mode": "external", "status": "GRADUATED", "project_md": str(proj_md), "memory_files_touched": [], "rolled_off_prs": []}`.
  3. **Mode B — `memory_mode == "builtin"` (Built-in 3-file index, SPEC §9.2 & Charter R5):**
     - Ensure `mem_dir = ws_dir / "memory"` exists. If `MEMORY.md`, `MODULE_INDEX.md`, or `PROJECT_INDEX.md` do not exist yet, initialize them from `common.templates_dir()` (`MEMORY.md.tpl`, `MODULE_INDEX.md.tpl`, `PROJECT_INDEX.md.tpl` with `updated_at=completed_date`).
     - **`MEMORY.md` updates:**
       - Remove any row in `## Active Projects` referencing `slug` or `canonical_pr_id`.
       - Construct the completed row: `| [<slug>](../<pr_dir.name>/PROJECT.md) | <completed_date> | <modules_summary> | <key_outcome> |`.
       - In `## Recently Completed (last 5)`, insert or update this row at the top of the table (deduplicating any existing row for `[<slug>]` or `<slug>` so repeated calls are 100% idempotent and byte-stable).
       - **5-PR Window Roll-Off:** Keep at most `5` project rows in `## Recently Completed (last 5)`. Any rows beyond index 5 (`overflow_rows = rows[5:]`) are removed from `MEMORY.md` and collected for roll-off into `PROJECT_INDEX.md`.
       - Update `## Older Projects` count/line if appropriate and keep `<!-- Last updated: ... -->` deterministic (`completed_date`) so running `graduate` twice produces **byte-identical** `MEMORY.md`.
     - **`PROJECT_INDEX.md` updates:**
       - For each PR row that rolled off the 5-PR window in `MEMORY.md` (and/or ensure rolled-off rows are archived), insert/update a row in `PROJECT_INDEX.md` (`| [<ro_slug>](../<ro_dir>/PROJECT.md) | <ro_completed> | <ro_scope> | <ro_completed> | [PROJECT.md](../<ro_dir>/PROJECT.md) |`) if not already present in `PROJECT_INDEX.md` (preserving chronological order and idempotency).
     - **`MODULE_INDEX.md` updates:**
       - For each module in `proj_doc.spec.charter.allowed_modules`:
         - Normalize module key/heading (e.g. `## <module>`) or match existing `## <domain>` section in `MODULE_INDEX.md` whose heading mentions the module name/path; if no matching `## ` section exists for `<module>`, create a `## <module>` section with table header `| Project | Scope | Context |\n|---|---|---|`.
         - Idempotently insert or update the row `| [<slug>](../<pr_dir.name>/PROJECT.md) | <title_or_scope> | [PROJECT.md](../<pr_dir.name>/PROJECT.md) |` under that section (never duplicating the row for `<slug>` within the same section).
     - Return `{"pr_id": canonical_pr_id, "slug": slug, "memory_mode": "builtin", "status": "GRADUATED", "project_md": str(proj_md), "memory_files_touched": [str(memory_md), str(module_index_md), str(project_index_md)], "rolled_off_prs": rolled_off_slugs}`.
- [ ] **`tests/test_memory_modes.py`:**
  - Replace the placeholder smoke test with comprehensive unit and integration tests covering:
    1. **`external` mode zero-touch when `memory/` does not exist:** Run `graduate(tmp_repo, "PR-01", memory_mode="external")` when `<ws_dir>/memory/` does not exist; assert `<ws_dir>/memory/` is NOT created, `PROJECT.md` `status == GRADUATED`, Part I `charter_hash` remains valid, and Part III contains the succinct mechanical graduation summary.
    2. **`external` mode zero-mutation when `memory/` already exists:** Populate `<ws_dir>/memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}` with sentinel bytes, run `graduate(tmp_repo, "PR-01", memory_mode="external")`, and assert all 3 files in `memory/` are byte-for-byte unchanged (`sha256` before == `sha256` after).
    3. **`external` mode idempotency:** Run `graduate` twice in `external` mode and assert `PROJECT.md` is byte-for-byte identical after the second run.
    4. **`builtin` mode active-to-completed transition & `MODULE_INDEX.md` population:** Seed `MEMORY.md` with `pr-01` in `## Active Projects`, run `graduate(tmp_repo, "PR-01", memory_mode="builtin", completed_date="2026-10-16")`, and assert `pr-01` is removed from `## Active Projects`, added as the first row in `## Recently Completed (last 5)`, and recorded under each of its `allowed_modules` in `MODULE_INDEX.md`.
    5. **`builtin` mode 5-PR window roll-off into `PROJECT_INDEX.md`:** Graduate 6 PRs (`PR-01` through `PR-06`) sequentially in `builtin` mode; assert `MEMORY.md` `## Recently Completed (last 5)` contains exactly 5 PRs (`PR-06` down to `PR-02`) and `PR-01` has rolled off into `PROJECT_INDEX.md` (`rolled_off_prs == ["pr-01-alpha"]`). Graduate `PR-07` and assert `PR-02` also rolls off into `PROJECT_INDEX.md`.
    6. **`builtin` mode byte-stability on repeated runs:** Run `graduate(tmp_repo, "PR-06", memory_mode="builtin", completed_date="2026-10-16")` a second time and assert `MEMORY.md`, `MODULE_INDEX.md`, `PROJECT_INDEX.md`, and `PROJECT.md` are **byte-for-byte identical** between run 1 and run 2 (no duplicate rows, no shifting timestamps).
    7. **`state.db` config lookup:** Verify `graduate(tmp_repo, "PR-01")` automatically reads `memory_mode` (`"external"` vs `"builtin"`) from `.state/state.db` when `memory_mode=None`.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 `tree_hash` over `allowed_files` (`post_tool_receipt.compute_tree_hash`), update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (leaving Part I untouched so `spec_hash` remains valid), and commit on `pr-03-vcs-bus-models-and-memory-modes/wo3-memory-graduation-modes` with message:
   ```text
   WO-03.3: mutually exclusive external vs. builtin memory graduation (memory_grad.py)

   PA-WorkOrder: WO-03.3
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report rather than filing issues directly.

## Completion Report

- **Status:** `COMPLETED` (Attempt 1/5)
- **Receipt ID:** `rcpt_c47bd0bfb4fc` (`tree_hash`: `c47bd0bfb4fccb16d49a14ba7d2e02982c89908a177d06cb33d877006cfd74ff`)
- **Files Modified:**
  - `daemon/workspace-plugin/principal-architect/scripts/memory_grad.py`
  - `tests/test_memory_modes.py`
- **Verification Summary:** `108 passed in 41.32s; ruff check daemon tests: All checks passed!`
- **Decisions Made:**
  - Used a bounded `<!-- pa:graduation-summary start --> ... <!-- pa:graduation-summary end -->` block in `PROJECT.md` Part III (`## 4.`) keyed by deterministic `completed_date` (`YYYY-MM-DD`) so repeated invocations of `graduate()` in both `external` and `builtin` modes are 100% byte-for-byte identical.
  - Enforced the strict `external` mode zero-touch boundary (Invariant I6): when `memory_mode == "external"`, `<ws_dir>/memory/` is never created and `MEMORY.md`, `MODULE_INDEX.md`, and `PROJECT_INDEX.md` are never created, read, or modified.
  - Implemented 5-PR window roll-off in `builtin` mode (`MAX_RECENT_COMPLETED = 5`), archiving overflow rows into `PROJECT_INDEX.md` in chronological order and idempotently updating `MODULE_INDEX.md` sections for `charter.allowed_modules`.
