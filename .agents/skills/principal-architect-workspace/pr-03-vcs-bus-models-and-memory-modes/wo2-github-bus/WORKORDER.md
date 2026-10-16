---
schema_version: 1
wo_id: WO-03.2
pr_id: PR-03
title: GitHub multi-machine bus (GitHubBus, get_vcs_bus, PR create/edit/view/diff,
  gh pr review --comment, pa:deferred issues)
complexity: standard
status: COMPLETED
allowed_files:
- daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py
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
spec_hash: aafcdd3910b17edbca64723a644147da3e101d3b8f0e41a464762c15afb08107
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: rcpt_0fa061d433fd
  commit_sha: null
  files_modified:
  - daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py
  - tests/test_github_and_local_git_bus.py
  verification_summary: "102 passed (pytest) and ruff check daemon tests clean"
  out_of_scope_findings: []
  escalation_request: null
  decisions_made:
  - "Persisted GitHub review comment payloads to .state/audit_comment_<pr>_r<K>.md before invoking gh pr review --comment --body-file so both gh and callers/tests can inspect the exact payload without mutating tracked repository files."
  - "Extended GitHubBus.sync_audit to materialize missing or updated AUDIT-round-<K>.md files from remote <!-- pa:audit ... --> review comments (preserving PROJECT.md charter_hash) before delegating to LocalGitBus.sync_audit."
  dead_ends: []
---

# WO-03.2 — GitHub Multi-Machine Bus (`vcs_sync.py`: `GitHubBus` & `get_vcs_bus`)

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-03` (`pr-03-vcs-bus-models-and-memory-modes`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T21:37:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Extend `daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py` with `GitHubBus(LocalGitBus)` and wire `get_vcs_bus(repo_root, *, vcs_mode=None, runner=common.run)` to return `GitHubBus` when `vcs_mode == "github"`. Implement GitHub branch push, stacked PR creation/editing (`gh pr create --base <base> --head <head>` / `gh pr edit`), PR inspection (`view_pr`, `diff_pr`), same-account-compatible review posting via `gh pr review <N> --comment --body-file <path>` with `<!-- pa:audit ... -->` metadata (never `--approve` or `--request-changes`), remote review ingestion in `sync_audit` and `sync_state`, `pa:deferred` issue creation via `gh issue create --label pa:deferred` with local `DEFERRED_BACKLOG.md` fallback, and remote base retargeting in `restack_branches`. Add comprehensive mocked-`gh` tests in `tests/test_github_and_local_git_bus.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py`
  - `tests/test_github_and_local_git_bus.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-03-vcs-bus-models-and-memory-modes/wo2-github-bus/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or live `gh` commands against the workspace repository. Commit only on the currently checked-out branch `pr-03-vcs-bus-models-and-memory-modes/wo2-github-bus` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R7):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py` (`GitHubBus` & `get_vcs_bus`):**
  1. **`_gh_bin()` helper:**
     - Return `os.environ.get("PA_GH_BIN", "").strip() or "gh"` so tests and CLI callers can override the `gh` executable path or inject a mock `runner`.
  2. **`GitHubBus(LocalGitBus)` (`mode = "github"`):**
     - Inherit from `LocalGitBus` so all local-git floor operations (`create_or_checkout_branch`, `read_commit_trailers`, `format_commit_with_trailers`, `write_audit_round`, `append_deferred_backlog`) work identically and provide offline local persistence.
     - `open_or_sync_pr(self, pr_id: str, *, draft: bool = False) -> dict[str, Any]`:
       - Call `local_info = super().open_or_sync_pr(pr_id, draft=draft)` to stage `PROJECT.md` (`status: STAGED_FOR_AUDIT`) and verify `base_branch`.
       - Push `<branch>` to `origin` via `self.runner(["git", "push", "-u", "origin", branch], cwd=self.repo_root)`.
       - Build deterministic PR title (`f"{canonical_pr_id}: {proj_doc.spec.charter.title}"`) and PR body containing charter summary, `base_branch -> branch`, and Work Order table.
       - Determine if a GitHub PR already exists for `<branch>` (check `proj_doc.spec.github_pr` or run `[gh, "pr", "view", branch, "--json", "number,url,state,baseRefName,headRefName"]`).
       - If no PR exists yet, run `[gh, "pr", "create", "--base", base_branch, "--head", branch, "--title", title, "--body", body]` (plus `"--draft"` when `draft=True`). Extract the PR number from stdout URL (e.g. `.../pull/123`) or via `gh pr view <branch> --json number,url`. Update `proj_doc.spec.github_pr = pr_number` in `PROJECT.md` (verifying `schemas.verify_charter_hash` if `charter_locked`), commit, and push if updated.
       - If the PR already exists, run `[gh, "pr", "edit", str(pr_number_or_branch), "--base", base_branch, "--title", title, "--body", body]` and ensure `proj_doc.spec.github_pr` is set.
       - Return `{"mode": "github", "pr_id": canonical_pr_id, "branch": branch, "base_branch": base_branch, "status": "STAGED_FOR_AUDIT", "github_pr": pr_number, "pr_url": pr_url, "head_sha": head_sha}`.
     - `view_pr(self, pr_id_or_number: str | int) -> dict[str, Any]` and `diff_pr(self, pr_id_or_number: str | int) -> str`:
       - Resolve target (`str(pr_number)` or `branch`) from `pr_id_or_number` (checking `PROJECT.md` if `pr_id_or_number` is a PR ID like `"PR-01"`).
       - `view_pr` invokes `[gh, "pr", "view", target, "--json", "number,url,state,title,body,baseRefName,headRefName,headRefOid,reviews,comments"]` and returns the parsed JSON dict.
       - `diff_pr` invokes `[gh, "pr", "diff", target]` and returns `res.stdout` (falling back to local `git diff <base>...<branch>` if `gh` returns non-zero).
     - `post_audit(self, pr_id: str, audit_source: ..., *, commit: bool = True) -> dict[str, Any]`:
       - Call `local_res = super().post_audit(pr_id, audit_source, commit=commit)` to write and commit `<pr_dir>/AUDIT-round-<K>.md` locally and update `PROJECT.md` status.
       - Load the written `AUDIT-round-<K>.md` (`audit_doc = schemas.load_audit(local_res["audit_path"])`) and format the GitHub comment payload via `format_pa_audit_comment(audit_doc.spec)` (which starts with `<!-- pa:audit pr_id=... round=... head_sha=... verdict=... blocking=... major=... minor=... -->` and `**Audit Verdict:** <VERDICT> ...`).
       - Write the comment payload to a temporary file (e.g. inside `<ws_dir>/.state/audit_comment_<pr_id>_r<K>.md` or `tempfile.NamedTemporaryFile`) and invoke:
         `[gh, "pr", "review", target, "--comment", "--body-file", str(body_file)]`
         **CRITICAL (Charter R2 & SPEC §11.3):** Always use `--comment` — NEVER `--approve` or `--request-changes`.
       - Return `{**local_res, "mode": "github", "review_posted": review_res.returncode == 0, "review_command": cmd}`.
     - `sync_audit(self, pr_id: str) -> dict[str, Any] | None`:
       - Resolve target PR (`proj_doc.spec.github_pr` or `proj_doc.spec.charter.branch` or `pr_id`).
       - Query `[gh, "pr", "view", str(target), "--json", "number,url,headRefOid,reviews,comments"]`. If `returncode == 0` and JSON parses, scan all items in `reviews` and `comments` (`item.get("body", "")`) using `parse_pa_audit_comment(body)`.
       - For any parsed `pa:audit` comment matching `pr_id`, check if `<pr_dir>/AUDIT-round-<K>.md` exists locally. If it does not exist (or has an older verdict/sha), construct a valid `schemas.AuditReport` from the parsed metadata and call `write_audit_round(self.repo_root, pr_id, report, commit=False, runner=self.runner)` so `<pr_dir>/AUDIT-round-<K>.md` and `PROJECT.md` status are materialized on disk.
       - Call and return `super().sync_audit(pr_id)` (updating `"mode": "github"`).
     - `create_deferred_issue(self, *, title: str, summary: str = "", pr_id: str | None = None, wo_id: str | None = None, labels: Sequence[str] = ("pa:deferred",), file_path: str | None = None) -> dict[str, Any]`:
       - Ensure `"pa:deferred"` is included in the label set.
       - Build issue body with `pr_id`, `wo_id`, `file_path`, and `summary`.
       - Run `[gh, "issue", "create", "--title", title, "--body", body, *(label flags)]`.
       - Also record in local `DEFERRED_BACKLOG.md` via `self.append_deferred_backlog(...)` (so local backlog is always up to date and serves as fallback if `gh` fails).
       - Return `{"mode": "github", "issue_url": issue_url, "backlog_path": str(backlog_path)}`.
     - `sync_state(self) -> dict[str, Any]`:
       - Run `self.runner(["git", "fetch", "origin"], cwd=self.repo_root)` (ignoring non-zero in offline/test repos without remote).
       - For every `pr-*/PROJECT.md` under `common.workspace_dir(self.repo_root)`, attempt `self.sync_audit(proj_doc.spec.charter.pr_id)` to pull any remote `<!-- pa:audit ... -->` review comments before rebuilding `state.db`.
       - Call `res = super().sync_state()`, set `res["vcs_mode"] = "github"`, and return `res`.
     - `restack_branches(self, *, pr_id: str | None = None, onto_branch: str | None = None) -> dict[str, Any]`:
       - Call `res = super().restack_branches(pr_id=pr_id, onto_branch=onto_branch)`.
       - For each entry in `res["restacked"]`, run `git push --force-with-lease origin <branch>` and `[gh, "pr", "edit", target, "--base", entry["onto_branch"]]`, appending both commands to `res["commands"]`.
       - Return `res`.
  3. **`get_vcs_bus(repo_root, *, vcs_mode=None, runner=common.run) -> VcsBus`:**
     - Return `GitHubBus(real_root, runner=runner)` when `str(resolved_mode).strip().lower() == "github"`, otherwise `LocalGitBus(real_root, runner=runner)`.
- [ ] **`tests/test_github_and_local_git_bus.py`:**
  - Add thorough unit and integration tests for `GitHubBus` and `get_vcs_bus` using a fake/recording `runner` (no network calls):
    1. `get_vcs_bus` returns `LocalGitBus` when `vcs_mode="local_git"` (or configured in `state.db`) and `GitHubBus` when `vcs_mode="github"`.
    2. `GitHubBus.open_or_sync_pr`: pushes branch to `origin`, calls `gh pr create --base ... --head ...`, parses PR number/URL, records `github_pr` in `PROJECT.md` while preserving `charter_hash`, and on subsequent calls invokes `gh pr edit`.
    3. `GitHubBus.post_audit`: writes `AUDIT-round-1.md`, commits with `PA-Audit-Verdict` trailer, and invokes `gh pr review <N> --comment --body-file <path>` (asserting `"--comment"` is in the command and `"--approve"` / `"--request-changes"` are NEVER in the command, and verifying the `--body-file` contents parse via `parse_pa_audit_comment`).
    4. `GitHubBus.sync_audit` and `GitHubBus.sync_state`: ingests a remote GitHub PR review containing `<!-- pa:audit pr_id=PR-01 round=2 head_sha=... verdict=APPROVED blocking=0 major=1 minor=0 -->`, materializes `AUDIT-round-2.md` locally, updates `PROJECT.md` to `AUDIT_APPROVED`, and records `latest_audit:PR-01` in `state.db`.
    5. `GitHubBus.create_deferred_issue`: invokes `gh issue create` with `--label pa:deferred`, captures the returned issue URL, and falls back gracefully to `DEFERRED_BACKLOG.md` when `gh` fails.
    6. `GitHubBus.restack_branches`: rebases via `git rebase --update-refs`, force-pushes with `--force-with-lease`, and retargets the PR base via `gh pr edit <N> --base <onto_branch>`.
    7. `GitHubBus.view_pr` and `GitHubBus.diff_pr`: verify command construction and output parsing.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 `tree_hash` over `allowed_files` (`post_tool_receipt.compute_tree_hash`), update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (leaving Part I untouched so `spec_hash` remains valid), and commit on `pr-03-vcs-bus-models-and-memory-modes/wo2-github-bus` with message:
   ```text
   WO-03.2: GitHub multi-machine bus (GitHubBus, get_vcs_bus, PR sync, --comment audits, deferred issues)

   PA-WorkOrder: WO-03.2
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report rather than filing issues directly.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

- **Status:** `COMPLETED` (Attempt 1/5)
- **Receipt:** `rcpt_0fa061d433fd` (`tree_hash`: `0fa061d433fdd41495758377486d9242b84d9791e3dfb99ca651be26addbca90`)
- **Files Modified:**
  - `daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py`
  - `tests/test_github_and_local_git_bus.py`
- **Verification Summary:** `102 passed` across `test_schemas.py`, `test_state_db_and_sync.py`, `test_hooks_monitored_vs_autonomous.py`, `test_github_and_local_git_bus.py` (16 tests including 7 mocked-`gh` `GitHubBus` suites), and `test_memory_modes.py`; `ruff check daemon tests` clean.
- **Key Decisions:**
  - `_gh_bin()` honors `PA_GH_BIN` environment variable overrides while defaulting to `"gh"`, and all `GitHubBus` operations execute through the injectable `self.runner`.
  - `GitHubBus.post_audit` writes the machine-parseable `<!-- pa:audit ... -->` review body to `<ws_dir>/.state/audit_comment_<pr_id>_r<K>.md` and invokes `gh pr review <target> --comment --body-file <path>`, strictly avoiding `--approve` and `--request-changes` per Charter R2 and SPEC §11.3.
  - `GitHubBus.sync_audit` and `GitHubBus.sync_state` ingest remote `<!-- pa:audit ... -->` review/comment blocks, materialize `<pr_dir>/AUDIT-round-<K>.md` on disk while preserving `PROJECT.md` `charter_hash`, and synchronize `latest_audit:<PR-ID>` in `.state/state.db`.
  - `GitHubBus.create_deferred_issue` guarantees `--label pa:deferred` is passed to `gh issue create` and always records the entry in local `DEFERRED_BACKLOG.md` as an offline-safe fallback.
