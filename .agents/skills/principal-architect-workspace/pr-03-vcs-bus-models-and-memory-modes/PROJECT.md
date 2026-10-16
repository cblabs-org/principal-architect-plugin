---
schema_version: 1
charter:
  pr_id: PR-03
  programme_id: prog-principal-architect-plugin
  slug: pr-03-vcs-bus-models-and-memory-modes
  title: "Local-git floor + GitHub bus (vcs_sync), model routing (models), and memory graduation modes (memory_grad)"
  branch: feat/pr-03-vcs-bus-models-and-memory-modes
  base_branch: feat/pr-02-agents-and-dual-mode-hooks
  depends_on:
    - PR-02
  allowed_modules:
    - daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py
    - daemon/workspace-plugin/principal-architect/scripts/models.py
    - daemon/workspace-plugin/principal-architect/scripts/memory_grad.py
    - daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
    - daemon/workspace-plugin/principal-architect/scripts/schemas.py
    - daemon/workspace-plugin/principal-architect/scripts/state_db.py
    - daemon/workspace-plugin/principal-architect/scripts/common.py
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/
    - tests/conftest.py
    - tests/test_github_and_local_git_bus.py
    - tests/test_memory_modes.py
  required_skills: []
  verification_floor:
    - "pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py"
  charter_locked: true
  charter_hash: "ad7e71f954cd3d2b3db2eed6c4e55ef17b855bd01bfeefa2c59246c44c5d4e21"
status: APPROVED
approved_at: "2026-10-16T21:37:00Z"
github_pr: null
work_orders:
  - id: WO-03.1
    slug: wo1-local-git-bus
    title: "Local-Git floor (VcsBus protocol, LocalGitBus stacked branches, commit trailers, AUDIT-round-K.md, DEFERRED_BACKLOG.md, sync_state, restack)"
    complexity: architect
    status: COMPLETED
    attempts: 1
    commit_sha: "114ace23784b67850f8d1455e48fa5855ec6aa43"
  - id: WO-03.2
    slug: wo2-github-bus
    title: "GitHub multi-machine bus (GitHubBus, get_vcs_bus, parse_pa_audit_comment, PR create/edit/view/diff, gh pr review --comment, pa:deferred issues)"
    complexity: standard
    status: COMPLETED
    attempts: 1
    commit_sha: "1d33f70f66fd47d16018bcd8c58ccedb7c056930"
  - id: WO-03.3
    slug: wo3-memory-graduation-modes
    title: "Mutually exclusive external vs. builtin memory graduation engine (memory_grad.py) and byte-stability tests"
    complexity: standard
    status: COMPLETED
    attempts: 1
    commit_sha: "bfe09c34a3c7bd3e2be3f0778ea54ba8dd17a335"
  - id: WO-03.4
    slug: wo4-models-routing-and-ide-client
    title: "Dynamic complexity model routing, retry step-up, LanguageServerClient with headless fallback (models.py), and pa wo debug/resolve"
    complexity: standard
    status: IN_PROGRESS
    attempts: 0
    commit_sha: null
  - id: WO-03.5
    slug: wo5-lifecycle-cli-commands
    title: "Complete pa CLI lifecycle commands (sync, programme init/charter, pr start/claim/open-or-sync/post-audit/sync-audit/graduate/restack, issue create)"
    complexity: architect
    status: PENDING
    attempts: 0
    commit_sha: null
---

# PR-03 — VCS Bus, Model Routing & Memory Graduation Modes

| | |
|---|---|
| **Programme** | [`prog-principal-architect-plugin`](../programme-principal-architect-plugin/PROGRAM.md) · [plan](../programme-principal-architect-plugin/PROGRAM-PLAN.md) |
| **Spec** | [`SPEC.md` v1.1](../../../../SPEC.md) §5.3 (model routing & JIT pinning), §8 (lifecycle CLI commands & VCS bus), §9 (`external` vs. `builtin` memory modes), §11.3 |
| **Base → head** | `feat/pr-02-agents-and-dual-mode-hooks` → `feat/pr-03-vcs-bus-models-and-memory-modes` (WO branches: `pr-03-vcs-bus-models-and-memory-modes/woM-<topic>`) |
| **Part I owner** | Tier 1 Chief Architect (locked — amendments only via escalation to the Chief) |
| **Part II / III owner** | Tier 2 Principal Architect for PR-03 |

<!-- ======================================================================
     PART I — PR CHARTER (authored by the Tier 1 Chief Architect; locked via charter_hash)
     ====================================================================== -->

## 1. PR Charter: Scope, Goals, & Non-Goals

### 1.1 Scope

PR-03 delivers the **transport, model routing, memory graduation, and full CLI lifecycle layer** of `principal-architect-plugin`: `vcs_sync.py` implementing the mandatory local-Git floor (`LocalGitBus`: stacked branches, commit trailers, `AUDIT-round-<K>.md`, `DEFERRED_BACKLOG.md`, `pa sync` rebuild, `git rebase --update-refs` restack) and the optional GitHub multi-machine bus (`GitHubBus`: branch push, PR creation/update, `gh pr review --comment` with `<!-- pa:audit -->` metadata, `gh issue create --label pa:deferred`); `models.py` implementing complexity-based model routing (`mechanical -> flash_lite`, `standard -> flash`, `architect -> inherit`), retry step-up after 2 failed attempts, architect model selection, and the Antigravity Language Server client with graceful headless fallback; `memory_grad.py` implementing the mutually exclusive `external` (succinct Part III write-back, zero `memory/` mutations) and `builtin` (`MEMORY.md` 5-PR window, roll-off to `PROJECT_INDEX.md`, `MODULE_INDEX.md` rows) graduation modes; all remaining `pa` CLI commands in `pa_cli.py`; and the two test suites `tests/test_github_and_local_git_bus.py` and `tests/test_memory_modes.py`.

### 1.2 Goals

| # | Goal | Done when |
|---|---|---|
| **G1** | **`vcs_sync.py` — `LocalGitBus` floor & `GitHubBus` upgrade.** Implements stacked branch creation/checkout, trailer read/write (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`), `write_audit_round` (validating `AuditReport`, writing `AUDIT-round-<K>.md`, committing with trailer), `parse_pa_audit_comment`, `append_deferred_backlog` (`DEFERRED_BACKLOG.md`), `sync_state` (rebuilding `state.db` from trailers, committed `WORKORDER.md`/`AUDIT-round-*.md`, and optional GitHub PR comments), and `restack_branches` (`git rebase --update-refs` + optional `gh pr edit --base`); in `github` mode, pushes branches, opens/updates GitHub PRs, posts reviews via `gh pr review <N> --comment`, and files `pa:deferred` issues. | Both `LocalGitBus` (with no `gh` required) and `GitHubBus` (against a mocked `gh` runner) pass unit and end-to-end tests in `tests/test_github_and_local_git_bus.py`. |
| **G2** | **`models.py` — Complexity routing, retry step-up, architect model preference, and Language Server client.** Implements `route(complexity, attempt=1, parent_model="inherit") -> str` (`mechanical -> flash_lite`, `standard -> flash`, `architect -> inherit`, `interactive -> inherit`, stepping up `flash_lite -> flash -> inherit` when `attempt >= 3`), `step_up(tier) -> str`, `ARCHITECT_MODEL_PREFERENCE = ("gemini-4-argon-high", "gemini-3.1-pro-high", "claude-opus-5-5-high")`, `select_architect_model`, and `LanguageServerClient` (creating conversations and JIT pinning/unpinning via `ANTIGRAVITY_LS_ADDRESS` + `ANTIGRAVITY_CSRF_TOKEN`, degrading gracefully to bridge-prompt output when no IDE is connected). | Tested for all complexity tiers, retry step-up on attempts 1..5, never downgrading `"inherit"` to `"pro"`, architect model catalog matching, and headless `LanguageServerClient` fallback. |
| **G3** | **`memory_grad.py` — Mutually exclusive `external` vs. `builtin` graduation.** Implements `graduate(repo_root, pr_id, *, memory_mode=None) -> dict[str, Any]`. In `external` mode: never creates, reads, or modifies `memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}` and writes a succinct mechanical outcome summary into `PROJECT.md` Part III. In `builtin` mode: removes the PR from `MEMORY.md` `## Active Projects`, prepends it to `## Recently Completed (last 5)`, rolls any entries beyond the 5-PR window into `PROJECT_INDEX.md`, and idempotently records module rows in `MODULE_INDEX.md`. | `tests/test_memory_modes.py` verifies zero `memory/` file creation/mutation in `external` mode, 5-PR window roll-off into `PROJECT_INDEX.md` in `builtin` mode, and byte-stability on repeated graduation runs. |
| **G4** | **Complete `pa` CLI lifecycle commands (`pa_cli.py`).** Adds `pa sync`, `pa programme init`, `pa programme charter`, `pa pr start`, `pa pr claim`, `pa pr open-or-sync`, `pa pr post-audit`, `pa pr sync-audit`, `pa pr graduate` (enforcing R6: requiring an `APPROVED` `AuditReport` matching current `HEAD` and passing `charter.verification_floor`), `pa pr restack`, `pa wo debug`, `pa wo resolve`, and `pa issue create`. | End-to-end scripted CLI lifecycle passes in both `local_git` and `github` modes; `pa pr graduate` refuses when `HEAD` is unaudited or when a new commit lands after the audit. |
| **G5** | **All verification floors green & hygiene clean.** `pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py` passes from `./.venv`; `ruff check daemon tests` clean; zero I10 hygiene violations. | Cold-Firewall audit `APPROVED`. |

### 1.3 Non-Goals (explicitly out of scope for PR-03)

- `cockpit.py`, `daemon/sidecars/pa_cockpit/`, `scripts/install.sh`, `scripts/uninstall.sh`, `tests/test_cockpit_api.py` — **PR-04**.
- Self-enrollment of this repository and `v0.1.0` release tagging — **PR-05**.

## 2. Architectural Requirements, Cross-PR Interfaces, & Required Skills/Tools

### 2.1 Architectural requirements

| # | Requirement |
|---|---|
| **R1** | **Local-Git floor independence (I5).** Every lifecycle command (`programme init/charter`, `pr start/claim/open-or-sync/post-audit/sync-audit/graduate/restack`, `wo debug/resolve`, `issue create`, `sync`) must succeed in `vcs_mode: local_git` with no `gh` binary on `PATH` and no network access. `GitHubBus` must use the injectable `runner: common.Runner = common.run` and respect `PA_GH_BIN`. |
| **R2** | **Same-account GitHub review compatibility (SPEC §11.3 & Risk R9).** `GitHubBus` and `pa pr post-audit` must always invoke `gh pr review <N> --comment --body-file <path>` (never `--approve` or `--request-changes`). The review body and `AUDIT-round-<K>.md` must carry a machine-parseable `<!-- pa:audit pr_id=<PR-ID> round=<K> head_sha=<SHA> verdict=<VERDICT> blocking=<B> major=<M> minor=<N> -->` HTML comment header (or YAML block) plus `**Audit Verdict:** <VERDICT> ...` so `parse_pa_audit_comment` and `pa pr sync-audit` can reconstruct `AuditReport` state deterministically. |
| **R3** | **Graduation Audit Gate (R6) in `pa pr graduate`.** Before graduating `<PR-ID>`, `pa pr graduate` must: (1) resolve current `HEAD` SHA (`git rev-parse HEAD`), (2) verify that an `AuditReport` for `<PR-ID>` exists (in `AUDIT-round-*.md` or synced via `sync-audit`) with `verdict == "APPROVED"` and `head_sha` matching current `HEAD` (or matching the parent of the audit commit itself when `HEAD` is the `audit(pr-NN):` commit that added `AUDIT-round-<K>.md` and only `AUDIT-round-<K>.md` changed between `audited_head_sha` and `HEAD`), (3) run every command in `charter.verification_floor` (unless `--skip-floor` is explicitly passed in unit tests or verified via receipt), and (4) invoke `memory_grad.graduate`, update `PROGRAM.md` PR status to `GRADUATED`, unpin the PA session, and commit the graduation artifacts. |
| **R4** | **Model routing & tier-downgrade prevention (SPEC §5.3).** `models.route(complexity, attempt=1, parent_model="inherit")` maps `mechanical -> "flash_lite"`, `standard -> "flash"`, `architect -> "inherit"`, `interactive -> "inherit"` on attempts 1–2, and steps up one tier on attempts 3–5 (`flash_lite -> flash -> inherit`). It must never return `"pro"` when the architect tier is `"inherit"`. |
| **R5** | **Strict memory boundary (I6 & SPEC §9).** When `memory_mode == "external"`, `memory_grad.graduate` must not create `<workspace_dir>/memory/` or touch `MEMORY.md`, `MODULE_INDEX.md`, or `PROJECT_INDEX.md` even if they exist; it updates only `PROJECT.md` Part III with a compact mechanical graduation summary. When `memory_mode == "builtin"`, `memory_grad.graduate` updates `MEMORY.md` (keeping at most 5 entries in `## Recently Completed (last 5)`), moves older entries to `PROJECT_INDEX.md`, and updates `MODULE_INDEX.md` idempotently so running `graduate` twice produces byte-identical files. |
| **R6** | **Preserve `pa_cli.py` lazy imports & PR-01/PR-02 contracts (I4 & R8).** `pa_cli.py` must remain stdlib-only at module import time (`vcs_sync`, `models`, `memory_grad`, and `schemas` imported lazily inside subcommand handlers). All PR-01 and PR-02 tests (`85 passed`) must continue to pass without modification. |
| **R7** | **Hygiene (I10).** Zero internal identifiers, machine-specific absolute paths, or personal emails in any committed file, test fixture, or commit message. |

### 2.2 Cross-PR interfaces exported by PR-03 (stability contract)

| Module | Symbol | Contract |
|---|---|---|
| `vcs_sync.py` | `VcsBus`, `LocalGitBus`, `GitHubBus`, `get_vcs_bus`, `read_commit_trailers`, `write_audit_round`, `parse_pa_audit_comment`, `append_deferred_backlog`, `sync_state`, `restack_branches` | Local-Git floor + GitHub projection bus consumed by `pa_cli.py` and PR-04 `cockpit.py`. |
| `models.py` | `ARCHITECT_MODEL_PREFERENCE`, `route`, `step_up`, `select_architect_model`, `LanguageServerClient` | Model routing and IDE conversation/pinning client consumed by `pa_cli.py` and PR-04 `cockpit.py`. |
| `memory_grad.py` | `graduate(repo_root, pr_id, *, memory_mode=None) -> dict[str, Any]` | Memory graduation engine for `external` and `builtin` modes consumed by `pa pr graduate` and PR-04 `POST /api/pr/graduate`. |
| `pa_cli.py` | `pa sync`, `pa programme init/charter`, `pa pr start/claim/open-or-sync/post-audit/sync-audit/graduate/restack`, `pa wo debug/resolve`, `pa issue create` | Complete CLI control plane consumed by PR-04 Cockpit actions and PR-05 dogfooding. |

### 2.3 Required skills & tools

| Kind | Item | Notes |
|---|---|---|
| Runtime | `./.venv/bin/python` (Python 3.11+, `pydantic>=2,<3`, `pyyaml>=6`) | Provisioned in `./.venv`. |
| Test / lint | `./.venv/bin/pytest`, `./.venv/bin/ruff` | Verification floor runs PR-01, PR-02, and PR-03 test suites. |
| CLI | `git` (real temp repos in tests), `gh` (mocked via `fake_runner` / `PA_GH_BIN` in tests) | Tests must never hit the network. |

### 2.4 Delivery constraints for the Tier 2 PA

- Decompose into **sequential, single-writer Work Orders** (expected 5, following `PROGRAM-PLAN.md` §4 PR-03 guidance), each with a tight `allowed_files` subset of `allowed_modules` and the verification floor `pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py`.
- Spawn **exactly one Tier 3 Execution Worker per `WORKORDER.md`**; never execute Work Orders inline.
- Record the user's standing programme approval of Part II in this file (`status: APPROVED`, `approved_at`, and a dated line in §4) before spawning the first Worker.
- At Step 6A: fast-forward `feat/pr-03-vcs-bus-models-and-memory-modes` to the final WO tip, push to `origin`, open the GitHub PR with `--base feat/pr-02-agents-and-dual-mode-hooks --head feat/pr-03-vcs-bus-models-and-memory-modes`, record `github_pr` in `PROJECT.md`, and pause for the Cold-Firewall audit.

<!-- ======================================================================
     PART II — IMPLEMENTATION PLAN & WORK ORDER BREAKDOWN (authored by the Tier 2 Principal Architect)
     ====================================================================== -->

## 3. Implementation Plan & Work Order Breakdown

### 3.1 File-Level Discovery & Sequencing Strategy

Inspection of `feat/pr-02-agents-and-dual-mode-hooks` (`bfda2d4`) confirms that `common.py` (stdlib-only `<1ms` helpers, `find_repo_root`, `workspace_dir`, `render_template_file`, `run`), `schemas.py` (`ProgramSpec`, `PRNodeSpec`, `ProjectSpec`, `PRCharterSpec`, `WOSummaryRow`, `WorkOrderSpec`, `CompletionReport`, `AuditReport`, `AuditFinding`, `compute_charter_hash`, `verify_charter_hash`, `compute_spec_hash`, `verify_spec_hash`, `parse_document`, `dump_document`), `state_db.py` (`StateDB` with `repo_config`, `sessions`, `verification_receipts`, `escalations`, `attention_queue`, and `Registry`), `escalation.py`, the four hooks (`pre_invocation.py`, `pre_tool_gate.py`, `post_tool_receipt.py`, `stop_gate.py`), and `pa_cli.py` (`enroll`, `unenroll`, `status`, `mode`, `pr approve-plan`, `wo verify`, `escalate`) are in place with 85 passing tests.

To build PR-03 cleanly with zero circular dependencies and keep the full verification floor (`pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py`) green at the tip of every Work Order:

1. **Local-Git Floor first (`WO-03.1`, `wo1-local-git-bus`):** Implement `scripts/vcs_sync.py` with the `VcsBus` protocol/base class and `LocalGitBus` (stacked branch creation/checkout `create_or_checkout_branch`, commit trailer helpers `read_commit_trailers` and `format_commit_with_trailers`, `write_audit_round` validating `AuditReport` up to `max_audit_rounds: 5` and committing `AUDIT-round-<K>.md` with the machine-parseable `<!-- pa:audit ... -->` header and trailer `PA-Audit-Verdict: <verdict> (<head_sha>)`, `append_deferred_backlog` writing/appending `<workspace_dir>/DEFERRED_BACKLOG.md`, `sync_state` rebuilding `state.db` from local trailers + committed `WORKORDER.md`/`AUDIT-round-*.md`, and `restack_branches` via `git rebase --update-refs`), plus initial unit tests in `tests/test_github_and_local_git_bus.py` and placeholder tests in `tests/test_memory_modes.py`.
2. **GitHub Multi-Machine Bus second (`WO-03.2`, `wo2-github-bus`):** Extend `scripts/vcs_sync.py` with `GitHubBus`, `get_vcs_bus(repo_root, *, vcs_mode=None, runner=common.run)`, and `parse_pa_audit_comment(text)` (branch push to `origin`, `gh pr create --base <base> --head <head>` / `gh pr edit`, `gh pr review <N> --comment --body-file ...` containing `<!-- pa:audit ... -->` [never `--approve` or `--request-changes`], `gh pr view` / `gh pr diff`, `gh issue create --label pa:deferred` with `DEFERRED_BACKLOG.md` fallback, remote sync in `sync_state`, and base retargeting in `restack_branches`), plus fake-`gh` tests in `tests/test_github_and_local_git_bus.py`.
3. **Memory Graduation Modes third (`WO-03.3`, `wo3-memory-graduation-modes`):** Implement `scripts/memory_grad.py` with `graduate(repo_root, pr_id, *, memory_mode=None) -> dict[str, Any]` enforcing the strict mutual-exclusion boundary between `external` mode (never creates, reads, or mutates `memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}`; writes only a succinct mechanical graduation summary to `PROJECT.md` Part III and sets `status: GRADUATED`) and `builtin` mode (removes PR from `MEMORY.md` `## Active Projects`, prepends to `## Recently Completed (last 5)`, rolls entries `> 5` into `PROJECT_INDEX.md`, idempotently updates `MODULE_INDEX.md` rows under `charter.allowed_modules`, and sets `PROJECT.md` `status: GRADUATED`), plus comprehensive tests in `tests/test_memory_modes.py`.
4. **Model Routing & IDE Client fourth (`WO-03.4`, `wo4-models-routing-and-ide-client`):** Implement `scripts/models.py` (`ARCHITECT_MODEL_PREFERENCE = ("gemini-4-argon-high", "gemini-3.1-pro-high", "claude-opus-5-5-high")`, `route(complexity, attempt=1, parent_model="inherit") -> str`, `step_up(tier) -> str`, `select_architect_model`, and `LanguageServerClient` with `start_conversation`, `set_pinned`, and graceful headless bridge-prompt fallback when `ANTIGRAVITY_LS_ADDRESS` is unset/unreachable), and add `pa wo debug <WO-ID>` and `pa wo resolve <WO-ID> --summary "..."` to `scripts/pa_cli.py`, plus unit tests in `tests/test_github_and_local_git_bus.py`.
5. **Lifecycle CLI Commands fifth (`WO-03.5`, `wo5-lifecycle-cli-commands`):** Extend `scripts/pa_cli.py` (preserving top-level stdlib-only lazy imports!) with `pa sync`, `pa programme init`, `pa programme charter`, `pa pr start`, `pa pr claim`, `pa pr open-or-sync`, `pa pr post-audit`, `pa pr sync-audit`, `pa pr graduate` (enforcing Rule R6: refusing graduation with exit `1` unless a valid `AuditReport` with `verdict == "APPROVED"` matches current `HEAD` [or its parent when `HEAD` is the `audit(pr-NN):` commit], running `charter.verification_floor`, calling `memory_grad.graduate`, updating `PROGRAM.md` PR status to `GRADUATED`, and unpinning the PA session), `pa pr restack`, and `pa issue create`, plus end-to-end scripted CLI lifecycle tests in `tests/test_github_and_local_git_bus.py`.

### 3.2 Work Order Ledger

- **[x] [wo1-local-git-bus](wo1-local-git-bus/WORKORDER.md)** (`WO-03.1`, `complexity: architect`, base: `feat/pr-02-agents-and-dual-mode-hooks`): Implement `scripts/vcs_sync.py` (`VcsBus` protocol + `LocalGitBus` stacked branches, commit trailers, `write_audit_round`, `append_deferred_backlog`, `sync_state`, `restack_branches`), initial `tests/test_github_and_local_git_bus.py`, and placeholder `tests/test_memory_modes.py`.
- **[x] [wo2-github-bus](wo2-github-bus/WORKORDER.md)** (`WO-03.2`, `complexity: standard`, base: `pr-03-vcs-bus-models-and-memory-modes/wo1-local-git-bus`): Extend `scripts/vcs_sync.py` with `GitHubBus`, `get_vcs_bus`, and `parse_pa_audit_comment`, plus mocked-`gh` tests in `tests/test_github_and_local_git_bus.py`.
- **[x] [wo3-memory-graduation-modes](wo3-memory-graduation-modes/WORKORDER.md)** (`WO-03.3`, `complexity: standard`, base: `pr-03-vcs-bus-models-and-memory-modes/wo2-github-bus`): Implement `scripts/memory_grad.py` (`graduate` for `external` vs. `builtin` modes) and comprehensive tests in `tests/test_memory_modes.py`.
- **[ ] [wo4-models-routing-and-ide-client](wo4-models-routing-and-ide-client/WORKORDER.md)** (`WO-03.4`, `complexity: standard`, base: `pr-03-vcs-bus-models-and-memory-modes/wo3-memory-graduation-modes`): Implement `scripts/models.py` (`ARCHITECT_MODEL_PREFERENCE`, `route`, `step_up`, `select_architect_model`, `LanguageServerClient`) and `pa wo debug`/`pa wo resolve` in `scripts/pa_cli.py`, plus tests in `tests/test_github_and_local_git_bus.py`.
- **[ ] [wo5-lifecycle-cli-commands](wo5-lifecycle-cli-commands/WORKORDER.md)** (`WO-03.5`, `complexity: architect`, base: `pr-03-vcs-bus-models-and-memory-modes/wo4-models-routing-and-ide-client`): Implement `pa sync`, `pa programme init/charter`, `pa pr start/claim/open-or-sync/post-audit/sync-audit/graduate/restack`, and `pa issue create` in `scripts/pa_cli.py`, plus end-to-end scripted CLI lifecycle tests in `tests/test_github_and_local_git_bus.py`.

<!-- ======================================================================
     PART III — OUTCOME & GRADUATION SUMMARY (authored by the Tier 2 Principal Architect)
     ====================================================================== -->

## 4. Outcome & Session Log

- **2026-10-16 (`status: APPROVED`):** User approved the full Programme Plan (`PROGRAM.md` `status: APPROVED`) and explicitly authorized autonomous execution and sub-agent spawning across the programme (Decision D11, 2026-10-16). Part II Work Order decomposition (`WO-03.1` through `WO-03.5`) authored and approved under standing user programme authorization (`approved_at: 2026-10-16T21:37:00Z`).
- **2026-10-16 (`WO-03.1 COMPLETED`, `114ace2`):** Delivered `daemon/workspace-plugin/principal-architect/scripts/vcs_sync.py` (`VcsBus` protocol, `LocalGitBus`, `format_commit_with_trailers`, `read_commit_trailers` / `read_trailers`, `format_pa_audit_comment`, `parse_pa_audit_comment`, `write_audit_round`, `append_deferred_backlog`, `sync_state`, `create_or_checkout_branch`, `restack_branches`), 9 `LocalGitBus` tests in `tests/test_github_and_local_git_bus.py`, and smoke test in `tests/test_memory_modes.py` (`95 passed`, `ruff check` clean).
- **2026-10-16 (`WO-03.2 COMPLETED`, `1d33f70`):** Extended `scripts/vcs_sync.py` with `GitHubBus(LocalGitBus)` (`open_or_sync_pr`, `view_pr`, `diff_pr`, `post_audit` via `gh pr review --comment`, `sync_audit` ingesting `<!-- pa:audit ... -->` review blocks, `create_deferred_issue` with `--label pa:deferred`, `sync_state`, `restack_branches` with `--force-with-lease` + `gh pr edit --base`) and wired `get_vcs_bus` (`102 passed`, `ruff check` clean).
- **2026-10-16 (`WO-03.3 COMPLETED`, `bfe09c3`):** Delivered `daemon/workspace-plugin/principal-architect/scripts/memory_grad.py` (`graduate` enforcing zero-touch on `memory/` in `external` mode and 5-PR window roll-off to `PROJECT_INDEX.md` + idempotent `MODULE_INDEX.md` updates in `builtin` mode) and 7 tests in `tests/test_memory_modes.py` (`108 passed`, `ruff check` clean).
