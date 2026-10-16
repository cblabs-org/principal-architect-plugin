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
status: PLANNED
approved_at: null
github_pr: null
work_orders: []
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

_To be authored by the Tier 2 Principal Architect for PR-03 after file-level discovery. Ledger rows must link to each `woM-<topic>/WORKORDER.md`._

<!-- ======================================================================
     PART III — OUTCOME & GRADUATION SUMMARY (authored by the Tier 2 Principal Architect)
     ====================================================================== -->

## 4. Outcome & Session Log

_To be authored by the Tier 2 Principal Architect. memory_mode is `builtin`: record full architectural distillation (decisions, dead ends, surfaced findings, audit rounds, final head_sha)._
