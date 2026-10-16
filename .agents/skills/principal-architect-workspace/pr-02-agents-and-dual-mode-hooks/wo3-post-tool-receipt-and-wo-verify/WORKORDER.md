---
schema_version: 1
wo_id: WO-02.3
pr_id: PR-02
title: "PostToolUse receipt invalidation/stamping, deterministic compute_tree_hash, and pa wo verify CLI"
complexity: standard
status: PENDING
allowed_files:
  - daemon/workspace-plugin/principal-architect/scripts/post_tool_receipt.py
  - daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
  - tests/test_hooks_monitored_vs_autonomous.py
forbidden_files:
  - SPEC.md
  - docs/positioning-paper.md
  - .agents/skills/principal-architect-workspace/pr-02-agents-and-dual-mode-hooks/PROJECT.md
  - .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: "./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests"
max_attempts: 5
max_structural_failures: 2
spec_hash: ae7f73c776898f4d46228d05443d4c97c0b974694cc93963363fd2bcbd7ed6d6
completion: null
---

# WO-02.3 — `PostToolUse` Receipt Engine, Deterministic `compute_tree_hash`, and `pa wo verify` CLI

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-02` (`pr-02-agents-and-dual-mode-hooks`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T20:05:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement:
1. `daemon/workspace-plugin/principal-architect/scripts/post_tool_receipt.py`:
   - `< 1 ms` unenrolled fast-exit (`common.is_repo_enrolled`) with zero top-level imports of `pydantic`, `yaml`, or `schemas` (Charter G2 & R1).
   - `compute_tree_hash(repo_root: str | Path, allowed_files: Sequence[str]) -> str` per Charter R4 (`<rel_posix_path>\0<len>\0<raw_bytes>\n` SHA-256 over sorted existing files matching `allowed_files`, excluding `.git/` and `.state/`).
   - `evaluate_post_tool(payload: Mapping[str, Any], *, repo_root: Path | str | None = None) -> dict[str, Any]` and `main() -> int` implementing SPEC §7.3 (receipt invalidation on file/mutating-command edits, receipt stamping when `verification_command` exits `0`, and `attempt_num` + `structural_failures` tracking on non-zero exit).
2. `pa wo verify <WO-ID> [--path <repo_path>]` in `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py` implementing SPEC §8 and Charter R7.
3. Comprehensive unit and subprocess tests in `tests/test_hooks_monitored_vs_autonomous.py`.

## 2. Boundary Box & Invariants

- **Allowed Files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/post_tool_receipt.py`
  - `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`
  - `tests/test_hooks_monitored_vs_autonomous.py`
- **Forbidden Files (`forbidden_files`):**
  - `SPEC.md`, `docs/positioning-paper.md`, `PROJECT.md`, `PROGRAM.md`, and any file outside `allowed_files` (except Part II of this `WORKORDER.md`).
- **Architectural Invariants:**
  - **Lazy Imports & `< 1 ms` Fast-Exit (Charter R1):** Neither `post_tool_receipt.py` nor `pa_cli.py` may import `pydantic`, `yaml`, or `schemas` at module top-level. Import `schemas` lazily inside functions only after confirming the repository is enrolled (or inside `_cmd_wo_verify`).
  - **Single Shared `compute_tree_hash` (Charter R4):** `compute_tree_hash(repo_root, allowed_files) -> str` in `post_tool_receipt.py` must be the single authoritative implementation called by `post_tool_receipt.py`, `pa wo verify`, and (in `WO-02.4`) `stop_gate.py`.
  - **Additive-Only Changes to `pa_cli.py` (Charter R8):** Preserve all existing PR-01 commands (`enroll`, `unenroll`, `status`, `mode`), signatures, and `COMMAND_MODULES` extension mechanism so `tests/test_state_db_and_sync.py` stays 100% green.
  - **Hygiene (I10):** Zero internal identifiers, machine-specific absolute paths, or personal emails in code, comments, or tests.

## 3. Concrete Implementation Checklist

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/post_tool_receipt.py`:**
  - Top-level imports: stdlib (`hashlib`, `json`, `os`, `re`, `subprocess`, `sys`, `collections.abc`, `pathlib.Path`, `typing.Any`) plus `common`, `escalation`, `state_db`, and `pre_tool_gate` (NO top-level `pydantic`, `yaml`, or `schemas`!).
  - **`compute_tree_hash(repo_root: str | Path, allowed_files: Sequence[str]) -> str`:**
    - Resolve `real_root = Path(os.path.realpath(repo_root))`.
    - Walk `real_root` using `os.walk(real_root)`:
      - Prune any directory named `".git"` or `".state"` from `dirnames` in-place (`dirnames[:] = [d for d in dirnames if d not in (".git", ".state")]`).
      - For each regular file (`fpath = Path(dirpath) / fname` where `fpath.is_file()` and not a broken symlink), compute its normalized POSIX path relative to `real_root` (`rel_posix = fpath.relative_to(real_root).as_posix()`).
      - Skip any path where `".git"` or `".state"` is in `rel_posix.split("/")`.
      - If `pre_tool_gate.matches_any_pattern(rel_posix, allowed_files)` is `True`, collect `(rel_posix, fpath)`.
    - Sort collected entries by `rel_posix` ascending (`sorted(..., key=lambda item: item[0])`).
    - Feed each file into `hasher = hashlib.sha256()` using the exact Charter R4 frame:
      ```python
      raw_bytes = fpath.read_bytes()
      header = f"{rel_posix}\0{len(raw_bytes)}\0".encode("utf-8")
      hasher.update(header)
      hasher.update(raw_bytes)
      hasher.update(b"\n")
      ```
    - Return `hasher.hexdigest()`.
  - **`evaluate_post_tool(payload: Mapping[str, Any], *, repo_root: Path | str | None = None) -> dict[str, Any]`:**
    - Fast-exit check:
      - If `repo_root is None`:
        - `workspace_paths = escalation.extract_workspace_paths(payload)`
        - If `not common.is_repo_enrolled(workspace_paths)`: return `{}` immediately without importing `schemas`!
        - Resolve `repo_root = common.find_repo_root(Path(workspace_paths[0]))`. If `repo_root is None`: return `{}`.
      - `real_root = Path(os.path.realpath(repo_root))`
      - `ws_dir = common.workspace_dir(real_root)`
      - `db_file = ws_dir / ".state" / "state.db"`
      - If `not db_file.is_file()`: return `{}`.
    - Open `state_db.StateDB(db_file) as db`:
      - Extract `conv_id = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()`.
      - If `not conv_id`: return `{}`.
      - `session = db.get_session(conv_id)`
      - If `session is None`: return `{}`.
      - Normalize role via `role = pre_tool_gate._normalize_role(str(session.get("role") or ""))`.
      - Only process `role == "engineer"` (`if role != "engineer": return {}`).
      - Extract `wo_id = str(session.get("wo_id") or "").strip()` and `pr_id = str(session.get("pr_id") or "").strip()`.
      - Extract `(tool_name, args) = pre_tool_gate._extract_tool_name_and_args(payload)`.
      - **1. File Mutation Tool -> Invalidate Receipts (SPEC §7.3.1):**
        - If `tool_name in pre_tool_gate.FILE_MUTATION_TOOLS`:
          - If `wo_id`: `db.invalidate_receipts(wo_id)`
          - Return `{}`.
      - **2. `run_command` Tool -> Stamp Receipt / Track Failures / Invalidate on Mutating Command (SPEC §7.3.1 & §7.3.2):**
        - If `tool_name == "run_command"`:
          - Extract `cmd_str = pre_tool_gate._extract_command_str(args)`.
          - If `not cmd_str`: return `{}`.
          - If `re.search(r"\bpa(?:\s+|_cli\.py\s+)wo\s+verify\b", cmd_str)`:
            - `pa wo verify` manages receipt stamping and committing directly; do not invalidate its receipt afterwards! Return `{}`.
          - Lazily import `schemas` and locate the bound `WORKORDER.md` (`wo_doc = pre_tool_gate._find_workorder_doc(ws_dir, wo_id=wo_id, pr_id=pr_id)`).
          - Check if `wo_doc is not None` and `wo_doc.spec.verification_command.strip()` is non-empty and `wo_doc.spec.verification_command.strip() in cmd_str`:
            - Extract tool outcome from `payload`:
              - Inspect `payload` and `toolResult` (if `isinstance(payload.get("toolResult"), Mapping)`) for:
                - `exit_code`: integer from `exitCode`, `exit_code`, `returncode`, or `returnCode` if present;
                - `error_val`: string from `error`, `toolError`, or `toolResult.get("error")`;
                - `output_text`: combined string from `output`, `toolOutput`, `result`, `stdout`, `stderr` on `payload` and `toolResult`, plus `error_val`.
              - Also check if `output_text` contains `Command exited with code (\d+)` (standard Antigravity `run_command` output format!): if `exit_code is None` and that regex matches, parse `int(m.group(1))`.
              - Determine `succeeded`:
                - If `exit_code is not None`: `succeeded = (int(exit_code) == 0) and not bool(str(error_val or "").strip())`
                - Else: `succeeded = not bool(str(error_val or "").strip())`
              - `resolved_wo_id = wo_id or wo_doc.spec.wo_id`
              - `resolved_pr_id = pr_id or wo_doc.spec.pr_id`
              - **If `succeeded` (`exit_code == 0`):**
                - Compute `t_hash = compute_tree_hash(real_root, wo_doc.spec.allowed_files)`.
                - Resolve `git_head = pre_tool_gate._get_current_head_sha(real_root)`.
                - `receipt_id = f"rcpt_{t_hash[:12]}"`
                - `db.invalidate_receipts(resolved_wo_id)`
                - `db.insert_receipt(wo_id=resolved_wo_id, pr_id=resolved_pr_id, cmd=wo_doc.spec.verification_command, exit_code=0, tree_hash=t_hash, git_head_sha=git_head or None, valid=1, receipt_id=receipt_id)`
                - Return `{}`.
              - **If `not succeeded` (non-zero exit code or non-empty `error`):**
                - `db.invalidate_receipts(resolved_wo_id)`
                - `max_att = int(wo_doc.spec.max_attempts) if wo_doc is not None else 5`
                - `cur_att = int(session.get("attempt_num") or 0)`
                - `new_att = min(cur_att + 1, max_att)` if `cur_att < max_att` else `cur_att` (Wait: ensure that if `cur_att` starts at `1` on Turn 1 or `0`, each failed verification increments `attempt_num` by `1` up to `max_attempts`, e.g., `min(int(session.get("attempt_num") or 0) + 1, max_att)`).
                - `cur_struct = int(session.get("structural_failures") or 0)`
                - `new_struct = cur_struct + 1 if escalation.is_structural_blocker(output_text) else cur_struct`
                - `db.update_session(conv_id, attempt_num=new_att, structural_failures=new_struct)`
                - Return `{}`.
          - **Otherwise (`cmd_str` is NOT `verification_command`):**
            - If `cmd_str` is a mutating shell command (e.g., `_is_mutating_worker_command(cmd_str)` is `True` — anything that writes/redirects files, runs `rm`, `mv`, `cp`, `touch`, `mkdir`, `sed -i`, `git add`, `git reset`, `git checkout`, `python`, `pytest` is read-only unless redirecting), call `db.invalidate_receipts(wo_id)` if `wo_id`.
            - Return `{}`.
  - **`main() -> int`:**
    - Reads hook payload via `escalation.read_hook_input()`, calls `evaluate_post_tool(payload)`, writes output via `escalation.write_hook_output(result)`, and returns `0` (catching any unexpected exception, logging to `sys.stderr`, and emitting `{}` with exit `0`).
- [ ] **`pa wo verify <WO-ID>` in `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`:**
  - Add a `wo` subcommand parser in `build_parser()` (`p_wo = subparsers.add_parser("wo", help="Work Order lifecycle commands.")`, `wo_subparsers = p_wo.add_subparsers(dest="wo_command", metavar="<subcommand>")`) with `verify`:
    - `p_wo_verify = wo_subparsers.add_parser("verify", help="Verify Work Order scope hygiene, run verification_command, stamp receipt, and commit.")`
    - `p_wo_verify.add_argument("wo_id", help="Work Order ID (e.g., WO-02.3).")`
    - `p_wo_verify.add_argument("--path", default=".", help="Path to the target repository (default: current directory).")`
    - `p_wo_verify.set_defaults(_handler=_cmd_wo_verify)`
  - Implement `_cmd_wo_verify(args: argparse.Namespace, *, runner: common.Runner = common.run) -> int`:
    - Lazy-import `schemas`, `pre_tool_gate`, and `post_tool_receipt` inside `_cmd_wo_verify` so `pa_cli.py` stays stdlib-only at module top-level.
    - Resolve `repo_root = common.find_repo_root(Path(args.path).expanduser(), runner=runner)`. Return `2` if not a git repo.
    - Locate matching `WORKORDER.md` (`wo_doc`) for `args.wo_id` in `ws_dir = common.workspace_dir(repo_root)` (and locate parent `PROJECT.md` at `wo_doc.path.parent.parent / "PROJECT.md"` if present). If `wo_doc` is not found, print error to `sys.stderr` and return `1`.
    - **Step 1: Check `spec_hash` & `git status --porcelain` Scope Hygiene:**
      - If `wo_doc.spec.spec_hash` is set and `not schemas.verify_spec_hash(wo_doc.path)`:
        - Print error (`"Error: WORKORDER.md Part I spec_hash verification failed..."`) to `sys.stderr` and return `1`.
      - Run `runner(["git", "status", "--porcelain", "-uall"], cwd=repo_root)`.
      - Parse dirty/untracked repo-relative POSIX paths from `stdout` (handling `XY path` and `R  old -> new` porcelain lines).
      - Ignore ephemeral runtime files (`.agents/plugins.json` and any path containing `/.state/`).
      - Compute `wo_rel_posix = wo_doc.path.resolve().relative_to(repo_root.resolve()).as_posix()`.
      - For every dirty/untracked file `rel_p`:
        - Allow if `rel_p == wo_rel_posix`.
        - Otherwise, check `not pre_tool_gate.matches_any_pattern(rel_p, wo_doc.spec.forbidden_files)` and `pre_tool_gate.matches_any_pattern(rel_p, wo_doc.spec.allowed_files)`.
        - If any dirty/untracked file violates scope hygiene, print an error listing the out-of-scope file(s) to `sys.stderr` and return `1`.
    - **Step 2: Execute `verification_command`:**
      - Run `ver_res = runner(["/bin/sh", "-c", wo_doc.spec.verification_command], cwd=repo_root, timeout=300.0)`.
      - If `ver_res.returncode != 0`:
        - Print `ver_res.stdout` and `ver_res.stderr` to `sys.stderr` and return `1`.
    - **Step 3: Stamp Cryptographic Receipt in `.state/state.db` and `WORKORDER.md` Part II:**
      - Compute `t_hash = post_tool_receipt.compute_tree_hash(repo_root, wo_doc.spec.allowed_files)`.
      - `receipt_id = f"rcpt_{t_hash[:12]}"`
      - Resolve `pre_head_res = runner(["git", "rev-parse", "HEAD"], cwd=repo_root)` (`pre_head_sha = pre_head_res.stdout.strip() if pre_head_res.returncode == 0 else None`).
      - Determine `files_modified`: sorted list of repo-relative POSIX paths matching `wo_doc.spec.allowed_files` that were modified/added in `git status --porcelain` (or if already staged/clean, all existing files matching `wo_doc.spec.allowed_files`).
      - Build a succinct 1-line `verification_summary` (`<= 280` chars) from `ver_res.stdout` (or preserve existing `wo_doc.spec.completion.verification_summary` if already populated by the Worker, or summarize the last non-empty line of `ver_res.stdout` + command exit 0).
      - Preserve any existing `attempt_num`, `decisions_made`, `dead_ends`, `out_of_scope_findings`, and `escalation_request` from `wo_doc.spec.completion` if already present, setting:
        - `wo_doc.spec.status = schemas.WorkOrderStatus.COMPLETED`
        - `wo_doc.spec.completion = schemas.CompletionReport(status=schemas.WorkOrderStatus.COMPLETED, attempt_num=existing_attempt_num, receipt_id=receipt_id, commit_sha=pre_head_sha, files_modified=files_modified, verification_summary=summary_str, out_of_scope_findings=..., escalation_request=..., decisions_made=..., dead_ends=...)`
      - Write `wo_doc.path` via `schemas.dump_document(wo_doc.spec, wo_doc.sections)` and assert `schemas.verify_spec_hash(wo_doc.path)` is `True`.
      - If parent `PROJECT.md` exists (`proj_md = wo_doc.path.parent.parent / "PROJECT.md"` and `proj_md.is_file()`):
        - Load `proj_doc = schemas.load_project(proj_md)`.
        - Find matching `row` in `proj_doc.spec.work_orders` (`row.id == wo_doc.spec.wo_id`), update `row.status = schemas.WorkOrderStatus.COMPLETED`, `row.attempts = max(row.attempts, existing_attempt_num)`, and `row.commit_sha = pre_head_sha`, write `proj_md` via `schemas.dump_document(proj_doc.spec, proj_doc.sections)`, and verify `schemas.verify_charter_hash(proj_md)` if `proj_doc.spec.charter.charter_locked`.
    - **Step 4: Commit `allowed_files` + `WORKORDER.md` (and `PROJECT.md` if updated) and Record Receipt in `state.db`:**
      - Stage `allowed_files` (any dirty/existing files matching `allowed_files`), `wo_rel_posix`, and (if updated) `proj_rel_posix` via `runner(["git", "add", "--", *paths_to_stage], cwd=repo_root)`.
      - Commit with message:
        ```text
        <WO-ID>: <title>

        PA-WorkOrder: <WO-ID>
        PA-Verified-Hash: <tree_hash>
        ```
        via `runner(["git", "commit", "-m", commit_msg], cwd=repo_root)`. If `commit` returns non-zero, print `stderr` to `sys.stderr` and return `1`.
      - Read new `HEAD` SHA via `head_res = runner(["git", "rev-parse", "HEAD"], cwd=repo_root)` (`new_head_sha = head_res.stdout.strip() if head_res.returncode == 0 else pre_head_sha`).
      - Open `state_db.StateDB(ws_dir / ".state" / "state.db") as db`:
        - `db.invalidate_receipts(wo_doc.spec.wo_id)`
        - `db.insert_receipt(wo_id=wo_doc.spec.wo_id, pr_id=wo_doc.spec.pr_id, cmd=wo_doc.spec.verification_command, exit_code=0, tree_hash=t_hash, git_head_sha=new_head_sha, valid=1, receipt_id=receipt_id)`
      - Print summary to `sys.stderr` and return `0`.
    - Also in `pa_cli._cmd_status`: when reconciling `commit_sha` from `git_trailers` (around line 556 and 591), if `row.id in git_trailers` and `t_sha` is present, prefer `t_sha` (the actual commit SHA bearing the `PA-WorkOrder: <WO-ID>` trailer!) so `pa status` always reports the exact WO commit SHA!
- [ ] **`tests/test_hooks_monitored_vs_autonomous.py`:**
  - Add unit and subprocess tests for `post_tool_receipt.py` and `pa wo verify`:
    1. **Unenrolled fast-exit & import purity test for `post_tool_receipt.py` (Charter G2 & R1):**
       - Subprocess call on unenrolled directory outputs `{}` and exits `0`.
       - In-process timing `< 1.0 ms` and subprocess `sys.modules` check confirms `pydantic`, `yaml`, and `schemas` are NOT imported on the unenrolled path.
    2. **`compute_tree_hash` determinism & exclusion test (Charter R4):**
       - Same file contents produce identical SHA-256 `tree_hash` regardless of traversal order.
       - Modifying a byte in an allowed file changes `tree_hash`.
       - Modifying files outside `allowed_files` or inside `.git/` / `.state/` does NOT change `tree_hash`.
    3. **`PostToolUse` receipt lifecycle test (Charter G4, SPEC §7.3):**
       - Edit file (`write_to_file` / `edit_file`) -> runs `verification_command` exiting `0` -> `db.latest_valid_receipt(wo_id, tree_hash)` returns a `valid=1` receipt with matching `tree_hash`.
       - Subsequent file edit (`edit_file`) or mutating shell command (`rm` / redirect) invalidates the receipt (`valid=0`, `db.latest_valid_receipt(wo_id)` is `None`).
       - Running `verification_command` with non-zero exit code increments `attempt_num` in `sessions` (e.g. `1 -> 2`) and leaves receipts invalid.
       - Running `verification_command` that fails with a structural blocker message (e.g. `"Hardware is currently tied to another process"`) increments BOTH `attempt_num` and `structural_failures` in `sessions`!
    4. **`pa wo verify <WO-ID>` end-to-end tests (Charter R7, SPEC §8):**
       - Rejects (exit `1`) when an untracked or modified file exists outside `allowed_files` (scope hygiene failure).
       - Rejects (exit `1`) when `WORKORDER.md` Part I `spec_hash` has been tampered with.
       - Rejects (exit `1`) when `verification_command` exits non-zero.
       - Succeeds (exit `0`) when scope is clean and `verification_command` exits `0`: stamps `verification_receipts` (`valid=1`, matching `tree_hash`), updates `WORKORDER.md` Part II (`status: COMPLETED`, `receipt_id`, `commit_sha`, `files_modified`, `verification_summary`) while preserving `spec_hash`, updates `PROJECT.md` while preserving `charter_hash`, and creates a Git commit with `<WO-ID>: <title>` and trailers `PA-WorkOrder: <WO-ID>` + `PA-Verified-Hash: <tree_hash>`, leaving `git status --porcelain` completely clean.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 hash over `allowed_files`, update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-02-agents-and-dual-mode-hooks/wo3-post-tool-receipt-and-wo-verify` with message:
   ```text
   WO-02.3: PostToolUse receipt engine, compute_tree_hash, and pa wo verify CLI

   PA-WorkOrder: WO-02.3
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->
