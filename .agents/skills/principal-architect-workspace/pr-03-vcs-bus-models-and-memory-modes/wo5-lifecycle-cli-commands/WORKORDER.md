---
schema_version: 1
wo_id: WO-03.5
pr_id: PR-03
title: Complete pa CLI lifecycle commands (sync, programme init/charter, pr start/claim/open-or-sync/post-audit/sync-audit/graduate/restack,
  issue)
complexity: architect
status: PENDING
allowed_files:
- daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
- tests/test_github_and_local_git_bus.py
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
spec_hash: c38c36144eb54625c3eacd15f9b6bc562720253a14c2044ba713fe5ccd1a2193
completion: null
---

# WO-03.5 — Complete `pa` CLI Lifecycle Commands (`pa_cli.py`) & End-to-End Tests

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-03` (`pr-03-vcs-bus-models-and-memory-modes`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T21:37:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement all remaining `pa` CLI lifecycle commands in `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py` (`pa sync`, `pa programme init`, `pa programme charter`, `pa pr start`, `pa pr claim`, `pa pr open-or-sync`, `pa pr post-audit`, `pa pr sync-audit`, `pa pr graduate` enforcing R6, `pa pr restack`, and `pa issue create`) while preserving stdlib-only top-level lazy imports, and add comprehensive end-to-end CLI lifecycle tests (for both `local_git` and `github` modes, plus the R6 graduation gate) in `tests/test_github_and_local_git_bus.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`
  - `tests/test_github_and_local_git_bus.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-03-vcs-bus-models-and-memory-modes/wo5-lifecycle-cli-commands/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh` on the workspace repository. Commit only on the currently checked-out branch `pr-03-vcs-bus-models-and-memory-modes/wo5-lifecycle-cli-commands` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R7):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`:**
  - **CRITICAL (Charter R6 & Invariant I4):** Keep top-level imports in `pa_cli.py` strictly stdlib + `common` + `state_db`. Import `schemas`, `vcs_sync`, `models`, `memory_grad`, `pre_tool_gate`, `post_tool_receipt`, and `escalation` lazily inside subcommand handlers so `test_pa_cli_lazy_import_purity` continues to pass!
  1. **`pa sync [path] [--path .]` (`_cmd_sync`):**
     - Resolve `real_root = Path(os.path.realpath(repo_root))`.
     - Call `bus = vcs_sync.get_vcs_bus(real_root, runner=runner)` and `summary = bus.sync_state()`.
     - Print `json.dumps(summary, indent=2)` to stdout and return `0`.
  2. **`pa programme <subcommand>` (`init` & `charter`):**
     - **`pa programme init <slug> --title "..." [--base-branch main] [--path .]` (`_cmd_programme_init`):**
       - Normalize `clean_slug = re.sub(r"^(programme-|prog-)", "", slug.strip().lower())`, `programme_id = f"prog-{clean_slug}"`, and `prog_dir = ws_dir / f"programme-{clean_slug}"`.
       - Render `PROGRAM.md.tpl` (`programme_id`, `title`, `base_branch`) to `prog_dir / "PROGRAM.md"` if missing (or update `title`/`base_branch` via `schemas.load_program` + `schemas.dump_document`), and validate with `schemas.load_program`.
       - Start/bind the Tier 1 Chief Architect conversation via `models.LanguageServerClient().start_conversation(title=f"🏛️ [Chief] {title}", prompt=..., role="chief", workspace_root=real_root, pin=True)` and upsert the `chief` session in `.state/state.db`.
       - Print JSON `{"programme_id": programme_id, "program_md": str(prog_md), "conversation_id": ls_res["conversation_id"], "pinned": ls_res["pinned"]}` to stdout and return `0`.
     - **`pa programme charter <pr_id> [--slug ...] [--title "..."] [--branch ...] [--base-branch main] [--allowed-module ...] [--verification-command ...] [--depends-on ...] [--required-skill ...] [--programme-id ...] [--open-draft] [--path .]` (`_cmd_programme_charter`):**
       - Normalize `pr_id_canonical = pr_id.strip().upper()`, `slug` (default `f"{pr_id.strip().lower()}-feature"` or existing PR folder name), `branch` (default `f"feat/{slug}"`), `allowed_modules` (default `["src/"]` if none passed and new), `verification_floor` (default `["pytest"]` if none passed and new).
       - If `<ws_dir>/<slug>/PROJECT.md` does not exist yet, render `PROJECT.md.tpl` and load via `schemas.load_project`; otherwise load existing `PROJECT.md` and update `charter` fields from any passed CLI flags.
       - Compute `c_hash = schemas.compute_charter_hash(proj_doc)`, set `proj_doc.spec.charter.charter_locked = True` and `proj_doc.spec.charter.charter_hash = c_hash`, write `PROJECT.md`, and verify `schemas.verify_charter_hash(proj_md)`.
       - If a `PROGRAM.md` exists under `ws_dir / "programme-*/PROGRAM.md"`, add or update the corresponding `schemas.PRNodeSpec` entry in `prog_doc.spec.prs` and save `PROGRAM.md`.
       - If `--open-draft` is passed, call `bus = vcs_sync.get_vcs_bus(real_root, runner=runner)`, `bus.create_or_checkout_branch(branch, base_branch)`, and `bus.open_or_sync_pr(pr_id_canonical, draft=True)`.
       - Print JSON `{"pr_id": pr_id_canonical, "slug": slug, "project_md": str(proj_md), "charter_hash": c_hash, "charter_locked": True}` to stdout and return `0`.
  3. **`pa pr <subcommand>` (`start`, `claim`, `open-or-sync`, `post-audit`, `sync-audit`, `graduate`, `restack`):**
     - **`pa pr start <pr_id> [--slug ...] [--title "..."] [--branch ...] [--base-branch main] [--allowed-module ...] [--verification-command ...] [--path .]` (`_cmd_pr_start`):**
       - Locate `<pr_dir>/PROJECT.md` for `<pr_id>`. If not found and `--title` (or defaults) can scaffold a standalone PR, scaffold `<ws_dir>/<slug>/PROJECT.md` from `PROJECT.md.tpl`, stamp `charter_hash`, and lock Part I; if not found and no `--title` is provided, return `1`.
       - Call `bus = vcs_sync.get_vcs_bus(real_root, runner=runner)` and `head_sha = bus.create_or_checkout_branch(proj_doc.spec.charter.branch, proj_doc.spec.charter.base_branch)`.
       - Start/activate the Tier 2 PA conversation via `models.LanguageServerClient().start_conversation(title=f"📐 [{pr_id_canonical}] {proj_doc.spec.charter.title}", prompt=..., role="pa", workspace_root=real_root, pin=True)` and upsert the `pa` session in `state.db`.
       - Print JSON `{"pr_id": pr_id_canonical, "branch": proj_doc.spec.charter.branch, "base_branch": proj_doc.spec.charter.base_branch, "head_sha": head_sha, "conversation_id": ls_res["conversation_id"], "pinned": ls_res["pinned"], "bridge_prompt": ls_res["bridge_prompt"]}` and return `0`.
     - **`pa pr claim <pr_id> [--path .]` (`_cmd_pr_claim`):**
       - Call `bus = vcs_sync.get_vcs_bus(real_root, runner=runner)` and `sync_res = bus.sync_state()`.
       - Locate `<pr_dir>/PROJECT.md` for `<pr_id>` (return `1` if missing), ensure `<charter.branch>` is checked out via `bus.create_or_checkout_branch(proj_doc.spec.charter.branch, proj_doc.spec.charter.base_branch)`, reload `proj_doc = schemas.load_project(proj_md)`, and partition `proj_doc.spec.work_orders` into `completed_wos` and `pending_wos`.
       - Build a deterministic continuation prompt (`PA_ROLE: pa\nPR_ID: <pr_id_canonical>\n...`) summarizing completed vs remaining Work Orders, print JSON `{"pr_id": pr_id_canonical, "branch": proj_doc.spec.charter.branch, "completed_wos": completed_wos, "pending_wos": pending_wos, "continuation_prompt": prompt, "sync": sync_res}` to stdout, and return `0`.
     - **`pa pr open-or-sync <pr_id> [--draft] [--path .]` (`_cmd_pr_open_or_sync`):**
       - Call `bus = vcs_sync.get_vcs_bus(real_root, runner=runner)` and `res = bus.open_or_sync_pr(args.pr_id, draft=bool(args.draft))`. Print `json.dumps(res, indent=2)` and return `0` (catching `ValueError`/`RuntimeError` and printing to stderr with exit code `1`).
     - **`pa pr post-audit <pr_id> --file <audit.md> [--no-commit] [--path .]` (`_cmd_pr_post_audit`):**
       - Call `bus = vcs_sync.get_vcs_bus(real_root, runner=runner)` and `res = bus.post_audit(args.pr_id, Path(args.file).expanduser(), commit=not bool(args.no_commit))`. Print `json.dumps(res, indent=2)` and return `0` (or `1` on validation error).
     - **`pa pr sync-audit <pr_id> [--path .]` (`_cmd_pr_sync_audit`):**
       - Call `bus = vcs_sync.get_vcs_bus(real_root, runner=runner)` and `res = bus.sync_audit(args.pr_id)`. If `res is None`, print error to stderr and return `1`; else print `json.dumps(res, indent=2)` and return `0`.
     - **`pa pr graduate <pr_id> [--skip-floor] [--completed-date YYYY-MM-DD] [--path .]` (`_cmd_pr_graduate`):**
       - **Enforce Rule R6 (Graduation Audit Gate, Charter G4 & R3):**
         1. Locate `<pr_dir>/PROJECT.md` for `<pr_id>` and load `proj_doc = schemas.load_project(proj_md)`.
         2. Resolve current `HEAD` SHA via `runner(["git", "rev-parse", "HEAD"], cwd=real_root)`.
         3. Call `bus = vcs_sync.get_vcs_bus(real_root, runner=runner)` and `audit_meta = bus.sync_audit(pr_id_canonical)`.
         4. Verify that `audit_meta is not None` and `audit_meta.get("verdict") == "APPROVED"`.
         5. Check `audited_sha = str(audit_meta.get("head_sha") or "").strip()`:
            - `audited_sha` is valid for `current_head_sha` if:
              (a) `audited_sha == current_head_sha` (or prefix match `current_head_sha.startswith(audited_sha)` with `len(audited_sha) >= 7`), OR
              (b) `HEAD` is the `audit(...)` commit that recorded `AUDIT-round-<K>.md`: `git rev-parse HEAD~1` matches `audited_sha` AND `git diff --name-only <audited_sha> HEAD` contains ONLY `<pr_dir>/AUDIT-round-*.md` and/or `<pr_dir>/PROJECT.md`!
            - If no `APPROVED` audit exists or `audited_sha` does not match `current_head_sha` under (a) or (b) (e.g. a new code commit landed after the audit), print `"Error: Cannot graduate <PR-ID>: current HEAD (<current_head_sha>) lacks an APPROVED Cold-Firewall Audit verdict..."` to `sys.stderr` and return `1`!
         6. Unless `--skip-floor` is passed, run every command in `proj_doc.spec.charter.verification_floor` via `runner(["/bin/sh", "-c", cmd], cwd=real_root, timeout=300.0)`. If any command exits non-zero, print error to `sys.stderr` and return `1`.
         7. Call `grad_res = memory_grad.graduate(real_root, pr_id_canonical, completed_date=args.completed_date)`.
         8. In `.state/state.db`, find any active `pa` session for `pr_id_canonical`, unpin it via `models.LanguageServerClient().set_pinned(conv_id, False)`, and update its status to `COMPLETED` (`pinned=0`). If a `chief` session exists, notify it via `LanguageServerClient().send_message(...)`.
         9. Stage modified graduation files (`PROJECT.md`, `PROGRAM.md` if modified, and `memory/*` files if touched) and commit with `vcs_sync._git_commit_with_fallback(real_root, f"chore({pr_id_canonical.lower()}): graduate {pr_id_canonical}", runner=runner)`.
         10. Print `json.dumps(grad_res, indent=2)` to stdout and return `0`.
     - **`pa pr restack [--pr-id <pr_id>] [--onto <branch>] [--path .]` (`_cmd_pr_restack`):**
       - Call `bus = vcs_sync.get_vcs_bus(real_root, runner=runner)` and `res = bus.restack_branches(pr_id=args.pr_id, onto_branch=args.onto)`. Print `json.dumps(res, indent=2)` and return `0`.
  4. **`pa issue <subcommand>` (`create`):**
     - **`pa issue create --title "..." [--summary "..."] [--pr-id ...] [--wo-id ...] [--file-path ...] [--label ...] [--path .]` (`_cmd_issue_create`):**
       - Call `bus = vcs_sync.get_vcs_bus(real_root, runner=runner)` and `res = bus.create_deferred_issue(title=args.title, summary=args.summary or "", pr_id=args.pr_id, wo_id=args.wo_id, labels=args.label or ("pa:deferred",), file_path=args.file_path)`.
       - Print `json.dumps(res, indent=2)` to stdout and return `0`.
- [ ] **`tests/test_github_and_local_git_bus.py`:**
  - Add comprehensive CLI lifecycle tests covering:
    1. **End-to-end `local_git` CLI lifecycle (`pa enroll` -> `pa programme init` -> `pa programme charter` -> `pa pr start` -> author WO -> `pa pr approve-plan` -> `pa wo verify` -> `pa pr open-or-sync` -> `pa pr post-audit` -> `pa pr sync-audit` -> `pa pr graduate` -> `pa issue create` -> `pa sync` -> `pa pr claim` -> `pa pr restack`):** Verify exit codes `0`, JSON outputs, `PROJECT.md` / `PROGRAM.md` transitions to `GRADUATED`, `MEMORY.md` updates, and `DEFERRED_BACKLOG.md` creation with zero `gh` binary calls.
    2. **Graduation Audit Gate (Rule R6) rejection & invalidation:**
       - Attempt `pa pr graduate PR-01` before any audit is posted -> assert exit code `1` and `PROJECT.md` remains non-graduated.
       - Post an audit with `verdict: CHANGES_REQUESTED` -> assert `pa pr graduate PR-01` exits `1`.
       - Post an audit with `verdict: APPROVED` matching current `HEAD`, then make a new code commit on the branch -> assert `pa pr graduate PR-01` detects the stale `head_sha` and exits `1`!
       - Post a fresh `APPROVED` audit for the new `HEAD` -> assert `pa pr graduate PR-01` succeeds (`exit 0`).
    3. **End-to-end `github` CLI lifecycle with mocked `gh` runner:** Verify `pa pr open-or-sync`, `pa pr post-audit` (`gh pr review --comment`), `pa pr sync-audit`, `pa issue create` (`gh issue create --label pa:deferred`), and `pa pr restack` via CLI entrypoint `pa_cli.main(..., runner=...)`.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 `tree_hash` over `allowed_files` (`post_tool_receipt.compute_tree_hash`), update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (leaving Part I untouched so `spec_hash` remains valid), and commit on `pr-03-vcs-bus-models-and-memory-modes/wo5-lifecycle-cli-commands` with message:
   ```text
   WO-03.5: complete pa CLI lifecycle commands (sync, programme, pr, issue) and R6 graduation gate

   PA-WorkOrder: WO-03.5
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report rather than filing issues directly.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->
