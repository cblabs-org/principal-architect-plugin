---
schema_version: 1
programme_id: prog-principal-architect-plugin
title: "principal-architect-plugin: mechanically enforced multi-tier orchestration plugin (SPEC v1.1)"
base_branch: main
status: COMPLETED
prs:
  - id: PR-01
    slug: pr-01-core-schemas-and-enrollment
    title: "Core Pydantic v2 Split-Authority schemas, SQLite state DB, and pa enroll/unenroll/status"
    branch: feat/pr-01-core-schemas-and-enrollment
    base_branch: main
    depends_on: []
    allowed_modules:
      - pyproject.toml
      - .gitignore
      - README.md
      - scripts/dev-bootstrap.sh
      - scripts/enroll.sh
      - scripts/unenroll.sh
      - daemon/plugin.json
      - daemon/.gitignore
      - daemon/workspace-plugin/principal-architect/plugin.json
      - daemon/workspace-plugin/principal-architect/scripts/__init__.py
      - daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
      - daemon/workspace-plugin/principal-architect/scripts/schemas.py
      - daemon/workspace-plugin/principal-architect/scripts/state_db.py
      - daemon/workspace-plugin/principal-architect/scripts/common.py
      - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/
      - tests/conftest.py
      - tests/test_schemas.py
      - tests/test_state_db_and_sync.py
    required_skills: []
    status: GRADUATED
    github_pr: 1
  - id: PR-02
    slug: pr-02-agents-and-dual-mode-hooks
    title: "Custom agent definitions, hooks.json, dual-mode PreToolUse/PostToolUse/Stop gates, pa pr approve-plan, pa wo verify"
    branch: feat/pr-02-agents-and-dual-mode-hooks
    base_branch: feat/pr-01-core-schemas-and-enrollment
    depends_on: [PR-01]
    allowed_modules:
      - daemon/workspace-plugin/principal-architect/hooks.json
      - daemon/workspace-plugin/principal-architect/agents/
      - daemon/workspace-plugin/principal-architect/rules/
      - daemon/workspace-plugin/principal-architect/skills/principal-architect/SKILL.md
      - daemon/workspace-plugin/principal-architect/scripts/pre_invocation.py
      - daemon/workspace-plugin/principal-architect/scripts/pre_tool_gate.py
      - daemon/workspace-plugin/principal-architect/scripts/post_tool_receipt.py
      - daemon/workspace-plugin/principal-architect/scripts/stop_gate.py
      - daemon/workspace-plugin/principal-architect/scripts/escalation.py
      - daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
      - daemon/workspace-plugin/principal-architect/scripts/schemas.py
      - daemon/workspace-plugin/principal-architect/scripts/state_db.py
      - daemon/workspace-plugin/principal-architect/scripts/common.py
      - tests/conftest.py
      - tests/test_hooks_monitored_vs_autonomous.py
    required_skills: []
    status: GRADUATED
    github_pr: 2
  - id: PR-03
    slug: pr-03-vcs-bus-models-and-memory-modes
    title: "Local-git floor + GitHub bus (vcs_sync), model routing (models), and memory graduation modes (memory_grad)"
    branch: feat/pr-03-vcs-bus-models-and-memory-modes
    base_branch: feat/pr-02-agents-and-dual-mode-hooks
    depends_on: [PR-02]
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
    status: GRADUATED
    github_pr: 3
  - id: PR-04
    slug: pr-04-cockpit-auxpane-ui
    title: "Principal Architect Cockpit AuxPane sidecar (HTTP + SSE backend, UI) and install/uninstall scripts"
    branch: feat/pr-04-cockpit-auxpane-ui
    base_branch: feat/pr-03-vcs-bus-models-and-memory-modes
    depends_on: [PR-03]
    allowed_modules:
      - daemon/sidecars/pa_cockpit/
      - daemon/workspace-plugin/principal-architect/scripts/cockpit.py
      - scripts/install.sh
      - scripts/uninstall.sh
      - README.md
      - tests/conftest.py
      - tests/test_cockpit_api.py
    required_skills: []
    status: GRADUATED
    github_pr: 4
  - id: PR-05
    slug: pr-05-dogfood-self-enrollment-and-release
    title: "Dogfood self-enrollment, workspace migration, state reconciliation, and v0.1.0 release"
    branch: feat/pr-05-dogfood-self-enrollment-and-release
    base_branch: feat/pr-04-cockpit-auxpane-ui
    depends_on: [PR-04]
    allowed_modules:
      - CHANGELOG.md
      - README.md
      - .gitignore
      - pyproject.toml
      - daemon/plugin.json
      - daemon/workspace-plugin/principal-architect/plugin.json
      - .agents/plugins/principal-architect-workspace/
      - .agents/skills/principal-architect-workspace/
      - tests/test_state_db_and_sync.py
    required_skills: []
    status: GRADUATED
    github_pr: 5
---

# principal-architect-plugin Programme

> **Programme:** Build `principal-architect-plugin` — a self-contained Python 3.11+ / Pydantic v2 split-daemon Antigravity plugin that turns the prompt-driven `principal-architect` skill into a mechanically enforced, token-efficient, multi-tier orchestration system.
> **Specification:** [SPEC.md](../../../../SPEC.md) v1.1 (2026-10-16) + [Positioning Paper](../../../../docs/positioning-paper.md) Rev 3
> **Status:** Programme Complete (`v0.1.0`, 2026-10-16). **5/5 PRs graduated (PR-01, PR-02, PR-03, PR-04, PR-05).**
> **Base branch:** `main` (`a16d659`; `origin` = `github.com/matthewmcneill/principal-architect-plugin`, `vcs_mode: github`, `memory_mode: builtin`)
> **Execution plan:** [PROGRAM-PLAN.md](PROGRAM-PLAN.md) — dependency graph, branching, per-PR protocol, indicative Work Orders, human tasks, decisions, risks, status tracker.

## Programme Summary

Large multi-PR initiatives run inside a single agent session suffer context compaction, invariant drift, scope leakage, and frontier-token burn on mechanical edit-compile-test loops. The `principal-architect` skill proved the remedy — a four-role hierarchy (Chief Architect → Principal Architect → Cold-Firewall Auditor → Execution Worker), one sub-agent per Work Order, and PR-mediated audits — during the 21-PR build of `repo-memory-plugin`. But as a *prompt-only* skill its guardrails remain advisory, it cannot distinguish supervised from unattended execution, it wastes tokens double-writing memory, it has no local-only or multi-machine transport story, and it has zero IDE visibility.

This programme ships the plugin that closes those five gaps, in **four stacked pull requests built bottom-up**:

1. **PR-01 — Contracts & State.** The installable `daemon/` package, Pydantic v2 Split-Authority document models (`PROGRAM.md` / `PROJECT.md` / `WORKORDER.md` / `AUDIT.md`) with `charter_hash` / `spec_hash` locks, the SQLite state database and global registry, and `pa enroll` / `unenroll` / `status` / `mode`.
2. **PR-02 — Enforcement.** The five role agents with evidence-based capability scoping (`inheritCustomizations: false` + repo-scoped manifests), the four-hook engine (`PreInvocation`, `PreToolUse`, `PostToolUse`, `Stop`) implementing rules R1–R6 in both `monitored` and `autonomous` modes, cryptographic verification receipts, and the two-tier retry policy (`max_attempts: 5` / `max_structural_failures: 2`).
3. **PR-03 — Transport, Routing & Memory.** The local-Git floor and optional GitHub bus (`vcs_sync.py`), the full PR/WO lifecycle commands, complexity-based model routing with retry step-up and IDE conversation pinning (`models.py`), and the mutually exclusive `external` / `builtin` memory graduation modes (`memory_grad.py`).
4. **PR-04 — Visibility.** The Principal Architect Cockpit AuxPane sidecar (HTTP + SSE backend, 🔔 Human Attention Needed inbox, Monitored/Autonomous toggle, Programme → PR → WO DAG, one-click conversation switching) and the install/uninstall scripts.
5. **PR-05 — Dogfood & Release.** Installs the finished plugin, runs `pa enroll .` on this repository (exercising the legacy `.agents/skills/` → `.agents/plugins/` workspace migration), reconciles `.state/state.db` via `pa sync`, and tags `v0.1.0`.

The build itself is run by the skill the plugin replaces: this Chief Architect session, one Tier 2 PA per PR, one Tier 3 Worker per Work Order, and a Cold-Firewall audit before every graduation. Every artifact produced here (`PROGRAM.md`, `PROJECT.md`, `WORKORDER.md`, `AUDIT-round-K.md`) is written in the schema the plugin will validate — so PR-01's own test suite parses this programme's committed documents.

## Repositories in Scope

| Repository | Programme work |
|---|---|
| **principal-architect-plugin** (this repo, `github.com/matthewmcneill/principal-architect-plugin`) | SPEC, the `daemon/` plugin package, dev/test wrapper, all PRs. Also the first enrolled (dogfood) repository in Phase 5. |
| **principal-architect skill** (installed at `~/.gemini/config/skills/principal-architect`, upstream `mm-skills/principal-architect`) | Read-only source of the methodology and templates the plugin internalises (`skills/principal-architect/SKILL.md`, `templates/`, `rules/00-pa-operating-model.md`). Any change to the skill itself is raised through that repository's own process, not here. |
| **repo-memory-plugin** (`cblabs-org/repo-memory-plugin`) | Read-only reference for the split-daemon packaging convention, hook I/O conventions, and the `memory_mode: external` detection contract. No changes. |

## 1. Architectural Vision & System Invariants

### 1.1 Vision

Three ideas organise the design:

- **Fractal top-down contracts.** Each tier authors the immutable charter of the tier below and never executes that tier's work: the Chief authors `PROGRAM.md` and Part I of each `PROJECT.md`; the PA authors Part II/III of `PROJECT.md` and Part I of each `WORKORDER.md`; the Worker implements one Work Order and authors its Completion Report. Locks are hashes, not promises.
- **Invariants in hooks, not prose.** Architect no-inline-code, Charter and Spec locks, Worker boundary boxes, verification receipts, and audit-before-graduation are enforced deterministically by `PreToolUse` / `PostToolUse` / `Stop` hooks with symmetric `monitored` (ask) and `autonomous` (deny + escalate) behaviour.
- **Spend frontier tokens on contracts, not keystrokes.** Architects run on frontier models to write tight specifications; bounded implementation is routed to the cheapest capable tier (`mechanical → flash_lite`, `standard → flash`, `architect → inherit`), with static, KV-cache-stable role prompts and repo-scoped capability manifests that strip ~11–14k tokens of unrelated global customisations per sub-agent.

### 1.2 System invariants (binding on every PR)

A PR that violates one fails its Cold-Firewall audit regardless of test results.

| # | Invariant | Source |
|---|---|---|
| **I1** | **Everything operational lives inside `daemon/`.** Python modules, hook entrypoints, agent definitions, rules, templates, and UI assets ship under `daemon/`; the repository root holds only dev/test wrappers (`pyproject.toml`, `tests/`, `scripts/*.sh`, docs). Installing `daemon/` alone yields a complete runtime. | SPEC G7, §4.1, P8 |
| **I2** | **State is scoped in three tiers and never mixed:** global plugin state in gitignored `daemon/state/` (`registry.json`, `config.json`); committed portable specs in `<repo>/.agents/plugins/principal-architect-workspace/` (`programme-*/`, `pr-*/`, optional `memory/`); local checkout runtime state in gitignored `<repo>/.agents/plugins/principal-architect-workspace/.state/` (`state.db`, `pa-skills.json`, `pa-worker-rules.json`). | SPEC G7, §4.2 |
| **I3** | **Split-Authority documents are machine-validated.** Every `PROGRAM.md`, `PROJECT.md`, `WORKORDER.md`, and `AUDIT-round-K.md` is YAML frontmatter + H2 sections, validated by Pydantic v2 models with `extra="forbid"`, with field names, regex patterns, and section headings exactly as SPEC §6. Part ownership is locked by `charter_hash` / `spec_hash`. | SPEC P5, §6, §11.1 |
| **I4** | **Hooks fast-exit in unenrolled repositories.** Every hook entrypoint calls an enrollment check that imports only the standard library and returns in < 1 ms when the workspace is not in `daemon/state/registry.json`. Pydantic is imported lazily, after the enrollment check passes. | SPEC P8, §7 |
| **I5** | **Local Git is the mandatory floor; GitHub is an optional bus.** All workflows must function with only a local `.git` (`vcs_mode: local_git`): stacked branches, commit trailers (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`), committed `AUDIT-round-K.md`. GitHub PRs/Reviews/Issues are an additive projection when `vcs_mode: github`. No code path may hard-require `gh` or network. | SPEC G8, P6, §8 |
| **I6** | **Memory modes are mutually exclusive.** `memory_mode: external` ⇒ the plugin never creates, reads, writes, or injects `memory/` and enforces succinct write-backs. `memory_mode: builtin` ⇒ the plugin owns the 3-file index (`MEMORY.md`, `MODULE_INDEX.md`, `PROJECT_INDEX.md`). Detection happens at `pa enroll` / `pa sync`, never ad hoc. | SPEC G9, P7, §9 |
| **I7** | **Two-tier retry policy is a schema constant, not a prompt suggestion.** `max_attempts: 5` (productive attempts), `max_structural_failures: 2`, `error_loop_threshold: 3`, `max_audit_rounds: 5`. These appear in `WorkOrderSpec` / `AuditReport` field constraints. | SPEC G4, §3.2 |
| **I8** | **Dual-mode escalation is symmetric.** Every boundary rule (R1–R6) has a defined `monitored` response (`permissionDecision: ask`) and `autonomous` response (`deny` + escalation record + upward routing `Worker → PA → Chief → Human Attention Queue`). Hard denials (R4, R5) are mode-independent. | SPEC G6, §7.2 |
| **I9** | **KV-cache-stable role prompts.** `agents/*.md` and the `.state/*.json` manifests are static per role × repository; per-Work-Order specialisation happens only in `PreInvocation` `userMessage` injections. `inheritCustomizations: false` on `pa-engineer` and `pa-auditor`; `inheritMcp: false` on `pa-auditor`. | SPEC G3, P2, §5.2 |
| **I10** | **Repository hygiene.** No absolute machine-specific paths, no personal or employer-internal references, tool names, ticket prefixes, or shortlink schemes in any committed file, test fixture, or commit message. Paths in committed Markdown are relative. Generated absolute paths appear only in gitignored files. | Programme constraint |
| **I11** | **Verification is cryptographic, not asserted.** A Work Order is complete only when its `verification_command` exited 0 against the current `allowed_files` tree hash and that receipt is recorded (`.state/state.db` + `PA-Verified-Hash` trailer). A PR graduates only when an `AuditReport` with `verdict: APPROVED` matches the current `HEAD`. | SPEC G4, G5 |

### 1.3 Architecture domains → delivering PR

| Domain | SPEC sections | Key components | PR |
|---|---|---|---|
| **Packaging & Enrollment** | §4.1–4.3, P8 | `daemon/plugin.json`, `workspace-plugin/principal-architect/plugin.json`, `daemon/state/registry.json`, `pa enroll` / `unenroll`, `.state/pa-skills.json` + `.state/pa-worker-rules.json` manifests, legacy `.agents/skills/` → `.agents/plugins/` migration, `scripts/dev-bootstrap.sh` | PR-01 |
| **Split-Authority Contracts** | §6.1–6.4, §11.1, P5 | `schemas.py` models + enums, frontmatter/section parser & renderer, `charter_hash` / `spec_hash`, seven `.tpl` templates | PR-01 |
| **Local State & Registry** | §6.5 | `state_db.py` (`repo_config`, `sessions`, `verification_receipts`, `escalations`, `attention_queue`; WAL) | PR-01 |
| **CLI Surface** | §8 | `pa_cli.py` root + extension list; `enroll`, `unenroll`, `status`, `mode` (PR-01); `pr approve-plan`, `wo verify`, `escalate` (PR-02); `programme *`, `pr start/claim/open-or-sync/post-audit/sync-audit/graduate/restack`, `wo debug/resolve`, `issue create`, `sync` (PR-03) | PR-01 → PR-03 |
| **Roles & Capability Scoping** | §3.1, §5.1–5.2, P2, P4 | `agents/pa-chief-architect.md`, `pa-principal-architect.md`, `pa-engineer.md`, `pa-auditor.md`, `pa-debugger.md`; `rules/00-pa-operating-model.md`; in-plugin `skills/principal-architect/SKILL.md` | PR-02 |
| **Hook Engine & Dual-Mode Escalation** | §7.1–7.4, §11.2, §11.4, P1 | `hooks.json`, `pre_invocation.py` (role binding, compaction/rewind detection, contract injection), `pre_tool_gate.py` (R1–R6, realpath traversal defence), `post_tool_receipt.py` (receipt stamping, attempt/structural tracking), `stop_gate.py` (two-tier retry, completion invariants), `escalation.py` | PR-02 |
| **VCS Bus** | §8, §11.3, P6 | `vcs_sync.py` (`LocalGitBus`, `GitHubBus`, trailers, `AUDIT-round-K.md`, `<!-- pa:audit -->` PR comments, `DEFERRED_BACKLOG.md`, `pa sync`, restack) | PR-03 |
| **Model & Token Routing** | §5.3, P4 | `models.py` (complexity → tier, retry step-up `flash_lite → flash → inherit`, architect-model selection, Language Server conversation creation + JIT pinning with graceful degradation) | PR-03 |
| **Memory Modes** | §9, P7 | `memory_grad.py` (`external` succinct writer; `builtin` 3-file graduation: 5-PR window, `PROJECT_INDEX.md` roll-off, `MODULE_INDEX.md` rows) | PR-03 (scaffolding at enroll time in PR-01) |
| **Cockpit (AuxPane UI)** | §10 | `daemon/sidecars/pa_cockpit/sidecar.json`, `cockpit.py` (HTTP + SSE), `ui/index.html`, `styles.css`, `app.js` | PR-04 |
| **Install / Uninstall** | §4.1 | `scripts/install.sh` (copies `daemon/` → `~/.gemini/config/plugins/pa-daemon`, symlinks `~/.local/bin/pa`), `scripts/uninstall.sh` | PR-04 |
| **Test Suite** | §4.1 | `tests/conftest.py`, `test_schemas.py`, `test_state_db_and_sync.py`, `test_hooks_monitored_vs_autonomous.py`, `test_github_and_local_git_bus.py`, `test_memory_modes.py`, `test_cockpit_api.py` | each PR adds its own |

## PR Sequence & Phasing

The DAG is **strictly linear** and execution is **serial**: each PR extends `pa_cli.py` and consumes the previous PR's exported interfaces, and each PR's Charter is refined just-in-time against the upstream PR's *final* exports. Per-PR indicative Work Order shapes, human tasks, and the audit protocol are in [PROGRAM-PLAN.md](PROGRAM-PLAN.md).

### Phase 0 — Programme Charter (complete, 2026-10-16)

Specification frozen at v1.1; governance rule provisioned; PA workspace and `builtin` memory index bootstrapped; `PROGRAM.md` / `PROGRAM-PLAN.md` authored; PR-01 Part I Charter locked (`charter_hash` stamped); GitHub remote established.

### Phase 1 — Contracts & State: PR-01 `pr-01-core-schemas-and-enrollment`

| | |
|---|---|
| **Objective** | Make every later PR buildable, testable, and schema-checked: the installable package skeleton, the document contracts, the state database, enrollment, and the dev toolchain. |
| **Deliverables** | `pyproject.toml`, root `.gitignore`, minimal `README.md`; `scripts/dev-bootstrap.sh` (uv → venv → `get-pip.py` chain), `scripts/enroll.sh`, `scripts/unenroll.sh`; `daemon/plugin.json`, `daemon/.gitignore`, `workspace-plugin/principal-architect/plugin.json`; `scripts/__init__.py`, `common.py` (stdlib-only: repo root, workspace dir with legacy fallback, `daemon_home()` honouring `PA_DAEMON_HOME`, `is_repo_enrolled()`, transcript reader), `schemas.py` (SPEC §6 models + enums + `EscalationRequest`, parser/renderer with idempotent round-trip, normative hash functions), `state_db.py` (`StateDB` + `Registry`), `pa_cli.py` (`enroll`, `unenroll`, `status [--json]`, `mode`); seven `.tpl` templates; `tests/conftest.py` (`tmp_repo`, `daemon_home`, `fake_runner`), `tests/test_schemas.py`, `tests/test_state_db_and_sync.py`. |
| **Verification floor** | `pytest tests/test_schemas.py tests/test_state_db_and_sync.py` (from `./.venv`) |
| **Exit criteria** | Floor green; `ruff check` clean on PR-01 modules; `verify_charter_hash()` passes on this programme's committed PR-01 `PROJECT.md`; `import common` pulls in neither `pydantic` nor `yaml`; enrollment matrix (`external\|builtin` × `github\|local_git`) and legacy migration (tracked / untracked / both-exist abort) tested offline; `pa enroll` idempotent; no network in tests; Cold-Firewall `APPROVED`. |
| **Charter** | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) — Part I **locked** (`9005d513…`). |
| **Exports consumed downstream** | See §2.1 (PR-01 row). |

### Phase 2 — Enforcement: PR-02 `pr-02-agents-and-dual-mode-hooks`

| | |
|---|---|
| **Objective** | Turn the methodology into mechanics: role agents with scoped capabilities, the four hooks implementing R1–R6 in both execution modes, verification receipts, and the two-tier retry/stop policy. |
| **Deliverables** | `hooks.json` (`PreInvocation`, `PreToolUse` matched on the mutating file tools + `run_command` + `invoke_subagent`, `PostToolUse`, `Stop`; `timeout: 10`; commands resolved via the plugin root); `escalation.py` (pure decision engine: `(rule, mode, ctx) → HookResponse`, structural-blocker signatures, escalation + attention-queue recording); `pre_tool_gate.py` (R1 Architect no-inline-code, R1b Charter lock, R2 plan-approval gate, R3 Worker boundary/spec lock, R4 Worker git/gh lockdown, R5 Auditor read-only, R6 graduation audit gate; `os.path.realpath` traversal defence); `post_tool_receipt.py` (receipt invalidation on edit, `tree_hash` receipt stamping on `verification_command` exit 0, `attempt_num` / `structural_failures` tracking); `stop_gate.py` (fast-fail structural escalation, productive ceiling → `pa-debugger` enqueue, Case A/B completion invariants, auditor `post-audit` check); `pre_invocation.py` (role binding from the `PA_ROLE:` / `WO_ID:` / `PR_ID:` prompt header, `CHECKPOINT`/rewind detection, role-specific persistent `userMessage` injection, memory-boundary-aware `MEMORY.md` + `MODULE_INDEX.md` slices, Succinct vs Full write-back instruction); five `agents/pa-*.md` with the exact §5.2 tool allowlists and `model: inherit`, `inheritCustomizations: false`, `skills:` / `rules:` → `.state/*.json`, `inheritMcp` per role; `rules/00-pa-operating-model.md`; in-plugin `skills/principal-architect/SKILL.md`; `pa pr approve-plan` (schema validation, `allowed_files ⊆ allowed_modules`, `charter_hash` check, `spec_hash` stamping, `status: APPROVED`), `pa wo verify`, `pa escalate`; `tests/test_hooks_monitored_vs_autonomous.py` (rule × mode matrix driven through the real stdin/stdout hook entrypoints). |
| **Verification floor** | `pytest tests/test_hooks_monitored_vs_autonomous.py` |
| **Exit criteria** | Floor green and PR-01 floor still green; every rule R1–R6 has both `monitored` and `autonomous` outcome tests plus the traversal-escape test; unenrolled fast-exit path measured and recorded in Part III (in-process check < 1 ms); agent files pass the harness frontmatter rules (non-empty `name`/`description`, `model` is a tier alias); Stop hook never loops beyond the harness continuation cap; Cold-Firewall `APPROVED`. |
| **Charter** | [PROJECT.md](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) — Part I **locked** (`c4101d40…`). |

### Phase 3 — Transport, Routing & Memory: PR-03 `pr-03-vcs-bus-models-and-memory-modes`

| | |
|---|---|
| **Objective** | Make the lifecycle operable end-to-end on a local repository and across machines/harnesses via GitHub, route Work Orders to the right model tier, and graduate memory correctly in both modes. |
| **Deliverables** | `vcs_sync.py` (`VcsBus` protocol; `LocalGitBus`: stacked branch create/checkout, trailer read/write, `AUDIT-round-K.md` commit, `DEFERRED_BACKLOG.md`; `GitHubBus`: push, `gh pr create/edit/view/diff`, `gh pr review --comment` with the machine-parseable `<!-- pa:audit -->` block, `gh pr comment`, `gh issue create --label pa:deferred`; `pa sync` state rebuild from trailers/audits/PR comments; `pa pr restack` via `git rebase --update-refs` + base retarget); `models.py` (`route(complexity, attempt, parent) → tier`, step-up after attempt 2, architect-model preference list, Language Server client for `pa pr start` / `pa programme init` / `pa wo debug` conversation creation + JIT pin/unpin, printing a bridge prompt when no IDE is present); `memory_grad.py` (`external`: succinct Part III writer only; `builtin`: `MEMORY.md` 5-PR window, roll-off to `PROJECT_INDEX.md`, `MODULE_INDEX.md` rows under `allowed_modules`); CLI: `pa programme init`, `pa programme charter`, `pa pr start`, `pa pr claim`, `pa pr open-or-sync`, `pa pr post-audit`, `pa pr sync-audit`, `pa pr graduate`, `pa pr restack`, `pa wo debug`, `pa wo resolve`, `pa issue create`, `pa sync`; `tests/test_github_and_local_git_bus.py` (real temp git repos + fake `gh`), `tests/test_memory_modes.py`. |
| **Verification floor** | `pytest tests/test_github_and_local_git_bus.py tests/test_memory_modes.py` |
| **Exit criteria** | Floors of PR-01..03 green; a scripted end-to-end run in `local_git` mode (programme init → charter → pr start → approve-plan → wo verify → open-or-sync → post-audit → graduate) passes with no `gh` on `PATH`; the same run in `github` mode against the fake `gh` records identical local state plus the projected PR/review calls; graduation is refused without an `APPROVED` audit on `HEAD` (R6); `builtin` graduation produces byte-stable memory files; `external` graduation touches no `memory/` file; Cold-Firewall `APPROVED`. |
| **Charter** | [PROJECT.md](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) — Part I **locked** (`ad7e71f9…`). |

### Phase 4 — Visibility: PR-04 `pr-04-cockpit-auxpane-ui`

| | |
|---|---|
| **Objective** | Give the human a live, one-click control surface inside the IDE and make the plugin installable in one command. |
| **Deliverables** | `daemon/sidecars/pa_cockpit/sidecar.json` (`SIDECAR_UI_ENTRYPOINT_AUX_PANE`, `main: python3 ${PLUGIN_ROOT}/workspace-plugin/principal-architect/scripts/cockpit.py`, `restart_policy: on_failure`, **no** `agent_permissions` so the plugin is not auto-disabled pending setup); `cockpit.py` (stdlib `http.server` + SSE; `GET /api/workspaces`, `GET /api/state`, `GET /api/events`, `POST /api/mode`, `POST /api/pr/approve-plan`, `POST /api/escalation/resolve`, `POST /api/pr/start`, `POST /api/wo/debug`, `POST /api/pr/graduate`; change detection by polling `state.db` and workspace mtimes); `ui/index.html`, `ui/styles.css` (host CSS variables), `ui/app.js` (`/preload.js`; `onWorkspaceChange`; Zone 1 header + mode toggle + model selector; Zone 2 🔔 Human Attention Needed inbox; Zone 3 PR cards + WO rows with `toggleConversation`); `scripts/install.sh`, `scripts/uninstall.sh`; `README.md` (full install/usage docs); `tests/test_cockpit_api.py` (server on an ephemeral port, every endpoint, first SSE event). |
| **Verification floor** | `pytest tests/test_cockpit_api.py` + live AuxPane verification (an `interactive` Work Order handed to the user via bridge prompt). |
| **Exit criteria** | All five floors green; `install.sh` on a clean `~/.gemini/config/plugins/` yields a working `pa` and an enabled sidecar; the Cockpit renders this repository's Programme DAG, flips execution mode, and jumps to a conversation in a live IDE session (human-verified, recorded in Part III); Cold-Firewall `APPROVED`. |
| **Charter** | [PROJECT.md](../pr-04-cockpit-auxpane-ui/PROJECT.md) — Part I **locked** (`2ac0917b…`). |

### Phase 5 — Dogfood & Release: PR-05 `pr-05-dogfood-self-enrollment-and-release`

| | |
|---|---|
| **PR** | `pr-05-dogfood-self-enrollment-and-release` (base `feat/pr-04-cockpit-auxpane-ui`) |
| **Objective** | Prove the plugin on itself and ship a first tagged release. |
| **Indicative scope** | Run `scripts/install.sh`; `pa enroll .` on this repository (exercising the legacy `.agents/skills/` → `.agents/plugins/` workspace migration from PR-01 and relinking this programme's documents); `pa sync` to rebuild `.state/state.db` from the committed PR-01..04 trailers and audits; `pa status` matches `PROGRAM-PLAN.md`'s tracker; `CHANGELOG.md`; version `0.1.0` in `pyproject.toml` + `plugin.json`; GitHub release `v0.1.0`; close out `DEFERRED_BACKLOG.md` / `pa:deferred` issues. |
| **Why it is separate** | Keeps SPEC §12's four implementation PRs pure, and verifies end-to-end self-enrollment and workspace migration after all four implementation PRs have graduated. |

## 2. Cross-PR Contracts & Interfaces

### 2.1 What each PR exports and consumes

Downstream PRs may make **additive-only** changes to upstream modules (new functions, new tables/columns via `user_version` migrations, new CLI subcommands); they may not rename, remove, or change the semantics of an exported interface without a Charter amendment from the Chief Architect.

| PR | Exports (consumed downstream) | Consumes |
|---|---|---|
| **PR-01** | `schemas.py`: all SPEC §6 models; enums `PRState`, `WorkOrderStatus`, `ComplexityTier`; `EscalationRequest`; `Section`, `parse_document`, `dump_document`, `load_program` / `load_project` / `load_workorder` / `load_audit`; `compute_charter_hash`, `compute_spec_hash`, `verify_charter_hash`, `verify_spec_hash`. `state_db.py`: `StateDB` (five tables, `repo_config` accessors, sessions, receipts, escalations, attention queue), `Registry`, `TABLES`. `common.py`: `find_repo_root`, `workspace_dir` (new path, legacy fallback), `daemon_home`, `is_repo_enrolled`, `read_transcript`, `latest_checkpoint_step`, `run`. `pa_cli.py`: `build_parser()`, `main(argv)`, `COMMAND_MODULES` (each later module exposes `register(subparsers)`). Seven `.tpl` templates + rendering helper. `tests/conftest.py`: `tmp_repo`, `daemon_home`, `fake_runner`. | `SPEC.md` §4, §6, §8 |
| **PR-02** | `hooks.json`; hook entrypoints with pure, unit-testable decision functions; `escalation.py` (`decide(rule, mode, ctx) → HookResponse`, `STRUCTURAL_SIGNATURES`, `record_escalation`, `enqueue_attention`); `agents/pa-*.md`; `rules/00-pa-operating-model.md`; in-plugin `SKILL.md`; `pa pr approve-plan`, `pa wo verify`, `pa escalate`; the `PA_ROLE:` / `WO_ID:` / `PR_ID:` spawn-prompt header convention. | PR-01 schemas, state DB, `common`, CLI extension point, templates |
| **PR-03** | `vcs_sync.py` (`VcsBus`, `LocalGitBus`, `GitHubBus`, `read_trailers`, `write_audit_round`, `parse_pa_audit_comment`); `models.py` (`route`, `step_up`, `ARCHITECT_MODEL_PREFERENCE`, `LanguageServerClient` with no-op fallback); `memory_grad.py` (`graduate(project, mode)`); all lifecycle CLI commands. | PR-01/02 schemas, state DB, escalation records, `pa wo verify` receipts |
| **PR-04** | `sidecar.json`; `cockpit.py` HTTP/SSE API of SPEC §10.2 (shape of `GET /api/state` = `pa status --json` + attention queue + audit scorecard); `ui/`; `install.sh` / `uninstall.sh`. | PR-01 `pa status --json`; PR-02 `attention_queue`; PR-03 lifecycle commands and conversation IDs |

### 2.2 Normative shared conventions (binding on every PR)

1. **Runtime dependencies:** Python standard library + `pydantic>=2,<3` + `pyyaml>=6`. Nothing else at runtime. Dev-only: `pytest`, `ruff`. Target `python>=3.11`; the reference host runs 3.13.
2. **Dev toolchain bootstrap:** `scripts/dev-bootstrap.sh` (PR-01) provisions `./.venv` idempotently (prefers `uv`; else `python3 -m venv`; else a `--without-pip` venv bootstrapped with `get-pip.py`) and installs `-e .[dev]`. All verification floors run from that venv. `.venv/` is gitignored.
3. **Test discipline:** `pytest` only; no network; no writes outside `tmp_path`; `PA_DAEMON_HOME` and `HOME` isolated per test; `gh` / `git remote` interactions mocked via the injectable runner or `PA_GH_BIN`. Every PR's floor must stay green at the tip of every Work Order (an early WO may legitimately collect fewer tests), and **all upstream floors must remain green**.
4. **CLI I/O contract:** machine-readable output on stdout (`--json` where defined), diagnostics on stderr; exit `0` success, `1` validation/usage error, `2` environment/precondition error. Emoji only in human-facing `pa status` text, never in `--json`.
5. **Hash algorithms (normative; PR-01's Charter is already stamped with them):**
   - `charter_hash = sha256( canonical_json(PRCharterSpec minus charter_hash) + "\n" + norm(§1) + "\n" + norm(§2) )`
   - `spec_hash = sha256( canonical_json(WorkOrderSpec minus {spec_hash, status, completion}) + "\n" + norm(Part I sections) )`
   - `canonical_json(x) = json.dumps(model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)`; `norm(section)` = the section's full Markdown from its `## ` heading line up to (not including) the next `## ` heading, `.strip()`-ed, trailing whitespace removed from every line, lines joined by `\n`. Lowercase hex digest.
6. **Hook I/O contract (PR-02 onward):** hooks read one JSON object on stdin and write one JSON object on stdout; `PreToolUse` responses use `permissionDecision: "allow" | "ask" | "deny"` with a human-readable `reason`; `PreInvocation` injects via `injectSteps` with plain-string `userMessage` (persistent) or `ephemeralMessage` (single invocation) — never a bare-string `systemMessage`; `Stop` responds `{}` to allow termination or `{"decision": "continue", "reason": …}` to refuse it; any non-zero exit from a `PreToolUse` hook denies the tool call, so hooks must exit 0 and encode decisions in the body.
7. **Branching:** see `PROGRAM-PLAN.md` §2. Work Order branches `pr-NN-<slug>/woM-<topic>` stack linearly; each PR's declared `branch` (`feat/pr-NN-<slug>`) is the integration tip, fast-forwarded to the final WO branch at Step 6A, pushed, and used as the GitHub PR head and as the next PR's `base_branch`.
8. **Commit message convention:** `WO-NN.M: <title>` for Work Order commits with trailers `PA-WorkOrder: WO-NN.M` and `PA-Verified-Hash: <tree_hash>`; `chore(pr-NN): …` for PA ledger commits; `audit(pr-NN): round K — <verdict>` with trailer `PA-Audit-Verdict: <verdict> (<head_sha>)`.
9. **Hygiene (I10):** enforced by the Cold-Firewall auditor on every round with a repository-wide search.

## Gates

| Gate | When | Condition | Consequence of failure |
|---|---|---|---|
| **Charter gate** | Before a PR's Tier 2 PA is spawned | Part I of `PROJECT.md` authored by the Chief, `charter_locked: true`, `charter_hash` stamped, committed on the base branch | PA is not spawned |
| **Plan-approval gate** | Before a PR's first Tier 3 Worker is spawned | User has approved the PA's Part II Work Order decomposition in the Chief session; `PROJECT.md` carries `status: APPROVED`, `approved_at`, and a dated approval line | Workers are not spawned (the operating-model rule makes a correct Worker refuse) |
| **Floor gate** | At every Work Order tip | The PR's verification floor **and all upstream floors** exit 0 from `./.venv`; receipt recorded | Work Order is not complete; next WO is not branched |
| **Cold-Firewall audit gate** | Before `pa pr graduate` / Step 6B | `AUDIT-round-K.md` with `verdict: APPROVED (0 blocking, 0 major)` for the current `HEAD`, committed on the tip and mirrored as a GitHub review comment; ≤ 5 rounds | PR does not graduate; after 5 rounds the Chief escalates to the user |
| **Self-hosting decision point** | After PR-02 graduates | User decides whether PR-03 and PR-04 execute under the plugin's own hooks (`pa enroll .` in `monitored` mode) or continue under the prompt-only skill | Recorded as a programme decision either way |
| **Ship gate** (Phase 5, if approved) | End of PR-05 | `install.sh` from a clean state, self-enrollment with workspace migration, `pa status` consistent with the tracker, `v0.1.0` tagged | No release |

## Human Approval

- [x] `SPEC.md` v1.1 and `docs/positioning-paper.md` Rev 3 committed as the canonical specification (2026-10-16, `24cae59`)
- [x] Programme Charter, `PROGRAM-PLAN.md`, and PR-01 Part I Charter committed on `main` (2026-10-16, `5ce84f1`)
- [x] GitHub remote `matthewmcneill/principal-architect-plugin` created by the user; programme switched to `vcs_mode: github` (2026-10-16, `fa6a46b`)
- [x] Spawn mechanics for Tier 2 PAs confirmed: `invoke_subagent` (`TypeName: self`, `Model: inherit`, `Workspace: inherit`); no PR-01 Charter amendments (2026-10-16)
- [x] **Full Programme Plan (this document) reviewed and approved** — `status: DRAFT → APPROVED` and autonomous sub-agent execution authorized across the programme (2026-10-16)
- [x] Phase 5 `pr-05-dogfood-self-enrollment-and-release` accepted into the programme DAG (2026-10-16)
- [x] Self-hosting decision: proceed with current `principal-architect` skill implementation (optional check-in after PR-02 graduates; default to current skill for simplicity) (2026-10-16)

## 3. Programme Session Log

<!-- memory_mode: builtin — rich progressive synthesis. One entry per programme-level event.
     Format per PR completion: Summary / Cross-PR decisions / Architecture evolution / Unresolved items escalated from PA. -->

### 2026-10-16 — Programme chartered (session 1, Tier 1 Chief Architect)
- Grounded on `SPEC.md` v1.1 and `docs/positioning-paper.md` Rev 3 at `main` `24cae59`.
- Provisioned `.agents/rules/00-operating-model.md` (byte-identical to the skill asset) so Tier 3 Workers hold standing authorization for approved Work Orders.
- Bootstrapped the PA workspace at the **legacy path** `.agents/skills/principal-architect-workspace/` (decision D1 in `PROGRAM-PLAN.md`): the currently installed skill reads that path, and PR-01's `pa enroll` migration to `.agents/plugins/principal-architect-workspace/` will be dogfooded on this very repository.
- Environment baseline recorded: no external memory plugin enrolled (→ `memory_mode: builtin`); host Python 3.13 without `pip`/`ensurepip`, PyPI reachable (→ `scripts/dev-bootstrap.sh` is a PR-01 deliverable).
- Authored and locked Part I (`PR Charter`) of [`pr-01-core-schemas-and-enrollment/PROJECT.md`](../pr-01-core-schemas-and-enrollment/PROJECT.md); PR-02..PR-04 Charters remain stubs in this file's frontmatter and will be refined just-in-time as each upstream PR graduates.

### 2026-10-16 — GitHub remote added; programme switched to `vcs_mode: github` (session 1)
- User created the public repository `matthewmcneill/principal-architect-plugin`; `origin` configured and `main` pushed (`5ce84f1`). Decision D3 superseded in `PROGRAM-PLAN.md`: each PR's Step 6A now pushes `feat/pr-NN-<slug>` and opens a GitHub PR; Cold-Firewall audits are committed as `AUDIT-round-K.md` (canonical) and mirrored as `gh pr review --comment`. The PR-01 Charter is mode-agnostic and remains locked unchanged.

### 2026-10-16 — Full Programme Plan authored for review (session 1)
- At the user's request, expanded this document to the full Chief Architect profile: programme summary, repositories in scope, architecture-domain → PR map, phased PR sequence with objectives, deliverables, floors and exit criteria for PR-01..PR-04, a **proposed Phase 5** (`pr-05-dogfood-self-enrollment-and-release`), gates, and the human-approval checklist. `PROGRAM-PLAN.md` gained per-PR indicative Work Order shapes, human tasks, and an expanded risk register. The `ProgramSpec` frontmatter and the three SPEC §6.1 required H2 sections are preserved so PR-01's loader validates this file.
- Spawn mechanics confirmed by the user (`invoke_subagent`); no amendments to the PR-01 Charter. Spawn of the PR-01 PA is held pending approval of this plan.

### 2026-10-16 — Programme approved; PR-05 accepted; PR-01 PA spawned (session 1)
- User approved the full Programme Plan (`status: APPROVED`), accepted Phase 5 (`PR-05` `pr-05-dogfood-self-enrollment-and-release`) into the frontmatter DAG, directed the programme to proceed with the current `principal-architect` skill implementation (defaulting to current skill for simplicity, with an optional check-in after PR-02), and authorized autonomous execution and sub-agent spawning across the programme.
- Spawned Tier 2 Principal Architect for `PR-01` (`pr-01-core-schemas-and-enrollment`).

### 2026-10-16 — PR-01 graduated; PR-02 Chartered & PA spawned (session 1)
- **Summary (`PR-01`, GitHub PR `#1`, `b3a9e773`):** Tier 2 PA (`18498c8a`) decomposed `PR-01` into 6 sequential Work Orders (`WO-01.1`..`WO-01.6`), spawned 6 dedicated Tier 3 Execution Workers (`ce18a7ea`, `2c7d0f68`, `6ccd1320`, `0dfb941c`, `71973f79`, `a7af1930`), and delivered `scripts/dev-bootstrap.sh`, stdlib-only `common.py` (`<1ms` `is_repo_enrolled`), `schemas.py` (all SPEC §6.1–6.4 Pydantic v2 models, lossless H2 parser/renderer, `charter_hash`/`spec_hash`), `state_db.py` (`StateDB` WAL + 5 tables, atomic `Registry`), 7 `.md.tpl` templates, `pa_cli.py` (`enroll`, `unenroll`, `status [--json]`, `mode`), and 51 passing tests (`ruff` clean). Cold-Firewall Auditor (`06c008f6`) audited `be21bcc8` on Round 1 and returned `APPROVED (0 blocking, 0 major, 0 minor)` (`ce4950c2`).
- **Cross-PR decisions & interface notes:** `schemas.parse_document` preserves pre-H2 preambles and HTML banners inside the preceding `Section.body` (so `PROJECT.md` `## 2.` includes the Part II HTML separator banner; Part II/III edits must occur from `## 3.` onward to keep `charter_hash` intact). `pa status` is strictly read-only on unenrolled repositories.
- **Next:** Authored and locked Part I Charter of [`pr-02-agents-and-dual-mode-hooks/PROJECT.md`](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) (`charter_hash: c4101d401d3bfce795e277df30e49ffc534e9e1d2c835788a433f342d95ddbde`) using `schemas.compute_charter_hash` and spawned the Tier 2 Principal Architect for `PR-02`.

### 2026-10-16 — PR-02 graduated; PR-03 Chartered & PA spawned (session 1)
- **Summary (`PR-02`, GitHub PR `#2`, `3c8584a8`):** Tier 2 PA (`3f93d1e5`) decomposed `PR-02` into 6 sequential Work Orders (`WO-02.1`..`WO-02.6`), spawned 6 dedicated Tier 3 Execution Workers (`a926d401`, `5830074c`, `5954d924`, `8f82b5c3`, `a0f09939`, `776fb15d`), and delivered `escalation.py` (pure R1–R6 dual-mode engine, structural signatures, hook I/O helpers), `hooks.json`, `pre_tool_gate.py` (`<1ms` fast-exit, `os.path.realpath` traversal defense, R1/R1b/R2/R3/R4/R5/R6), `post_tool_receipt.py` (shared `compute_tree_hash`, receipt stamping/invalidation, attempt/structural tracking), `stop_gate.py` (two-tier retry ceiling `max_attempts: 5` vs. `max_structural_failures: 2`, Case A/B checks, bounded continuation cap), `pre_invocation.py` (`parse_spawn_header`, Turn 1 binding, `CHECKPOINT`/rewind re-injection, `builtin` vs. `external` memory injection), 5 custom role agents (`agents/pa-*.md`), `rules/00-pa-operating-model.md`, `skills/principal-architect/SKILL.md`, `pa pr approve-plan`, `pa wo verify`, `pa escalate`, and 34 new tests (`85 passed` total, `ruff` clean). Cold-Firewall Auditor (`716160dd`) audited `53697f5b` on Round 1 and returned `APPROVED (0 blocking, 0 major, 0 minor)` (`0d35a8e6`).
- **Self-hosting decision (`D10`):** Following the user's explicit guidance (`"proceed with current principal-architect skill ... my instincts are to simplify and go with current skill implementation"`), `PR-03` and `PR-04` continue under the current skill implementation while `PR-05` executes end-to-end self-enrollment and dogfood verification.
- **Next:** Authored and locked Part I Charter of [`pr-03-vcs-bus-models-and-memory-modes/PROJECT.md`](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) (`charter_hash: ad7e71f954cd3d2b3db2eed6c4e55ef17b855bd01bfeefa2c59246c44c5d4e21`) and spawned the Tier 2 Principal Architect for `PR-03`.

### 2026-10-16 — PR-03 graduated; PR-04 Chartered & PA spawned (session 1)
- **Summary (`PR-03`, GitHub PR `#3`, `6be3982e`):** Tier 2 PA (`ff54a7db`) decomposed `PR-03` into 5 sequential Work Orders (`WO-03.1`..`WO-03.5`), spawned 5 dedicated Tier 3 Execution Workers, and delivered `vcs_sync.py` (`VcsBus`, `LocalGitBus`, `GitHubBus`, `write_audit_round`, `parse_pa_audit_comment`, `append_deferred_backlog`, `sync_state`, `restack_branches`), `memory_grad.py` (`graduate` enforcing `external` vs. `builtin` memory modes with 5-PR window roll-off to `PROJECT_INDEX.md` and byte-stable `MODULE_INDEX.md` rows), `models.py` (`ARCHITECT_MODEL_PREFERENCE`, `route`, `step_up`, `select_architect_model`, `LanguageServerClient`), full lifecycle CLI subcommands in `pa_cli.py`, and 30 new tests across `test_github_and_local_git_bus.py` (23) and `test_memory_modes.py` (7) (`115 passed` total, `ruff` clean). Cold-Firewall Auditor (`c568f439`) audited `cb90e3e7` on Round 1 and returned `APPROVED (0 blocking, 0 major, 0 minor)` (`b10571aa`).
- **Next:** Authored and locked Part I Charter of [`pr-04-cockpit-auxpane-ui/PROJECT.md`](../pr-04-cockpit-auxpane-ui/PROJECT.md) (`charter_hash: 2ac0917b9e8a4a0d1a85bded6036c555aebb2de04441ffd74c5d84038fc80559`) and spawned the Tier 2 Principal Architect for `PR-04`.

### 2026-10-16 — PR-04 graduated; PR-05 Chartered & PA spawned (session 1)
- **Summary (`PR-04`, GitHub PR `#4`, `fd35e69e`):** Tier 2 PA (`41c3f16b`) decomposed `PR-04` into 3 sequential Work Orders (`WO-04.1`..`WO-04.3`), spawned 3 dedicated Tier 3 Execution Workers (`7c9f5ef4`, `17b7c68f`, `7f613224`), and delivered `daemon/sidecars/pa_cockpit/sidecar.json` (`SIDECAR_UI_ENTRYPOINT_AUX_PANE`, zero `agent_permissions`), stdlib-only `cockpit.py` (HTTP + SSE server with all 10 SPEC §10.2 routes), 3-zone Cockpit UI (`ui/index.html`, `ui/styles.css` using host CSS variables, `ui/app.js` with `/preload.js`, `onWorkspaceChange`, `toggleConversation`), environment-isolatable `scripts/install.sh` & `scripts/uninstall.sh`, full `README.md`, and `tests/test_cockpit_api.py` (`121 passed` total across all 6 suites, `ruff` clean). Cold-Firewall Auditor (`631bc95c`) audited `88125eb3` on Round 1 and returned `APPROVED (0 blocking, 0 major, 0 minor)` (`cb762c41`).
- **Next:** Authored and locked Part I Charter of [`pr-05-dogfood-self-enrollment-and-release/PROJECT.md`](../pr-05-dogfood-self-enrollment-and-release/PROJECT.md) and spawned the Tier 2 Principal Architect for `PR-05`.

### 2026-10-16 — PR-05 graduated; Programme Completed (`v0.1.0`, session 1)
- **Summary (`PR-05`, GitHub PR `#5`, `e415a2a4`):** Tier 2 PA (`950c6d79`) decomposed `PR-05` into 3 sequential Work Orders (`WO-05.1`..`WO-05.3`), spawned 3 dedicated Tier 3 Execution Workers, and delivered: (1) self-enrollment and tracked `git mv` migration of this programme's workspace from `.agents/skills/principal-architect-workspace/` to `.agents/plugins/principal-architect-workspace/` (`WO-05.1` `51e0d55`), (2) live `pa sync` and `pa status --json` state reconciliation plus permanent automated dogfood tests `test_workspace_dir_dogfood` and `test_dogfood_self_enroll_sync_and_status_on_repo_workspace` in `tests/test_state_db_and_sync.py` (`WO-05.2` `8a31519`), and (3) `CHANGELOG.md` and `0.1.0` version alignment across `pyproject.toml`, `daemon/plugin.json`, and `daemon/workspace-plugin/principal-architect/plugin.json` (`WO-05.3` `02cb8de`). Cold-Firewall Auditor (`4520f6fd`) audited `1456b512` on Round 1 and returned `APPROVED (0 blocking, 0 major, 0 minor)` (`ce98e060`).
- **Programme Outcome:** All 5 stacked PRs (`PR-01`..`PR-05`, 23 Work Orders, 5 Round-1 `APPROVED` Cold-Firewall Audits) have graduated with `122/122` tests passing across all 6 test suites, `ruff check daemon tests` clean, all 5 `PROJECT.md` `charter_hash` locks and all 23 `WORKORDER.md` `spec_hash` locks verified, and `0` Invariant I10 hygiene findings.
