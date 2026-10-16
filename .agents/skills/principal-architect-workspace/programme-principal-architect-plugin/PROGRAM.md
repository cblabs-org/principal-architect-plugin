---
schema_version: 1
programme_id: prog-principal-architect-plugin
title: "principal-architect-plugin: mechanically enforced multi-tier orchestration plugin (SPEC v1.1)"
base_branch: main
status: DRAFT
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
    status: PLANNED
    github_pr: null
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
    status: PLANNED
    github_pr: null
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
    status: PLANNED
    github_pr: null
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
    status: PLANNED
    github_pr: null
---

# principal-architect-plugin — Programme Charter

| | |
|---|---|
| **Programme** | `prog-principal-architect-plugin` |
| **Canonical specification** | [`SPEC.md` v1.1](../../../../SPEC.md) — normative for schemas (§6), hook contracts (§7), CLI (§8), memory modes (§9), Cockpit (§10), and the 4-PR plan (§12) |
| **Rationale** | [`docs/positioning-paper.md` Rev 3](../../../../docs/positioning-paper.md) |
| **Execution plan** | [`PROGRAM-PLAN.md`](PROGRAM-PLAN.md) — DAG, branching, per-PR protocol, decisions, status |
| **Base branch** | `main` (programme chartered at `24cae59`) |
| **Owner** | Tier 1 Chief Architect |

## 1. Architectural Vision & System Invariants

The programme turns the prompt-driven `principal-architect` skill into a **self-contained Python 3.11+ / Pydantic v2 split-daemon plugin** whose critical workflow rules are enforced by hooks rather than prose. Four stacked PRs build it bottom-up — contracts and state first, enforcement second, transport and routing third, visibility last — so every PR is independently reviewable and the stack tells one sequential story.

The following invariants hold across **all four PRs**. A PR that violates one fails its Cold-Firewall audit regardless of test results.

| # | Invariant | Source |
|---|---|---|
| **I1** | **Everything operational lives inside `daemon/`.** Python modules, hook entrypoints, agent definitions, rules, templates, and UI assets ship under `daemon/`; the repository root holds only dev/test wrappers (`pyproject.toml`, `tests/`, `scripts/*.sh`, docs). Installing `daemon/` alone yields a complete runtime. | SPEC G7, §4.1, P8 |
| **I2** | **State is scoped in three tiers and never mixed:** global plugin state in gitignored `daemon/state/` (`registry.json`, `config.json`); committed portable specs in `<repo>/.agents/plugins/principal-architect-workspace/` (`programme-*/`, `pr-*/`, optional `memory/`); local checkout runtime state in gitignored `<repo>/.agents/plugins/principal-architect-workspace/.state/` (`state.db`, `pa-skills.json`, `pa-worker-rules.json`). | SPEC G7, §4.2 |
| **I3** | **Split-Authority documents are machine-validated.** Every `PROGRAM.md`, `PROJECT.md`, `WORKORDER.md`, and `AUDIT-round-K.md` is YAML frontmatter + H2 sections, validated by Pydantic v2 models with `extra="forbid"`, with field names, regex patterns, and section headings exactly as SPEC §6. Part ownership (Chief → Part I of `PROJECT.md`; PA → Part II/III of `PROJECT.md` and Part I of `WORKORDER.md`; Worker → Part II of `WORKORDER.md`) is locked by `charter_hash` / `spec_hash`. | SPEC P5, §6, §11.1 |
| **I4** | **Hooks fast-exit in unenrolled repositories.** Every hook entrypoint calls an enrollment check that imports only the standard library and returns in < 1 ms when the workspace is not in `daemon/state/registry.json`. Pydantic is imported lazily, after the enrollment check passes. | SPEC P8, §7 |
| **I5** | **Local Git is the mandatory floor; GitHub is an optional bus.** All workflows must function with only a local `.git` (`vcs_mode: local_git`): stacked branches, commit trailers (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`), committed `AUDIT-round-K.md`. GitHub PRs/Reviews/Issues are an additive projection when `vcs_mode: github`. No code path may hard-require `gh` or network. | SPEC G8, P6, §8 |
| **I6** | **Memory modes are mutually exclusive.** `memory_mode: external` ⇒ the plugin never creates, reads, writes, or injects `memory/` and enforces succinct write-backs. `memory_mode: builtin` ⇒ the plugin owns the 3-file index (`MEMORY.md`, `MODULE_INDEX.md`, `PROJECT_INDEX.md`). Detection happens at `pa enroll` / `pa sync`, never ad hoc. | SPEC G9, P7, §9 |
| **I7** | **Two-tier retry policy is a schema constant, not a prompt suggestion.** `max_attempts: 5` (productive attempts), `max_structural_failures: 2`, `error_loop_threshold: 3`, `max_audit_rounds: 5`. These numbers are the empirically calibrated defaults and appear in `WorkOrderSpec` / `AuditReport` field constraints. | SPEC G4, §3.2 |
| **I8** | **Dual-mode escalation is symmetric.** Every boundary rule (R1–R6) has a defined `monitored` response (`permissionDecision: ask`) and `autonomous` response (`deny` + escalation record + upward routing `Worker → PA → Chief → Human Attention Queue`). Hard denials (R4, R5) are mode-independent. | SPEC G6, §7.2 |
| **I9** | **KV-cache-stable role prompts.** `agents/*.md` and the `.state/*.json` manifests are static per role × repository; per-Work-Order specialisation happens only in `PreInvocation` `userMessage` injections. `inheritCustomizations: false` on `pa-engineer` and `pa-auditor`; `inheritMcp: false` on `pa-auditor`. | SPEC G3, P2, §5.2 |
| **I10** | **Repository hygiene.** No absolute machine-specific paths, no personal or employer-internal references, tool names, ticket prefixes, or shortlink schemes in any committed file, test fixture, or commit message. Paths in committed Markdown are relative. Generated absolute paths appear only in gitignored files (`.agents/plugins.json`, `.state/*.json`). | Programme constraint |
| **I11** | **Verification is cryptographic, not asserted.** A Work Order is complete only when its `verification_command` exited 0 against the current `allowed_files` tree hash and that receipt is recorded (`.state/state.db` + `PA-Verified-Hash` trailer). A PR graduates only when an `AuditReport` with `verdict: APPROVED` matches the current `HEAD`. | SPEC G4, G5 |

## 2. Cross-PR Contracts & Interfaces

### 2.1 Dependency DAG and what each PR exports

The stack is **strictly linear** (`PR-01 → PR-02 → PR-03 → PR-04`): each PR extends `pa_cli.py` and consumes the previous PR's modules, so PRs execute serially. Downstream PRs may make **additive-only** changes to upstream modules (new functions, new tables/columns via migrations, new CLI subcommands); they may not change the signature or semantics of an exported interface listed below without a Charter amendment from the Chief Architect.

| PR | Exports (consumed downstream) | Consumes |
|---|---|---|
| **PR-01** | `schemas.py` (all SPEC §6 models + enums `PRState`, `WorkOrderStatus`, `ComplexityTier`; `EscalationRequest`; document parser/renderer with idempotent round-trip; `compute_charter_hash`, `compute_spec_hash`, `verify_*_hash`); `state_db.py` (`StateDB` with the 5 tables of §6.5, `repo_config` accessors, registry helpers for `daemon/state/registry.json`); `common.py` (repo-root and workspace-dir resolution incl. legacy path fallback, `is_repo_enrolled()` stdlib-only fast path, `daemon_home()` honouring `PA_DAEMON_HOME`, `transcript` reader incl. latest `CHECKPOINT` step); `pa_cli.py` (argparse root with a `COMMAND_MODULES` extension list; `enroll`, `unenroll`, `status [--json]`, `mode`); 7 `.tpl` templates; `tests/conftest.py` fixtures (isolated temp git repo, isolated `PA_DAEMON_HOME`, fake `gh`). | `SPEC.md` §4, §6, §8 |
| **PR-02** | `hooks.json`; hook entrypoints (`pre_invocation.py`, `pre_tool_gate.py`, `post_tool_receipt.py`, `stop_gate.py`) with pure, unit-testable decision functions; `escalation.py` (`decide(rule, mode, ctx) -> HookResponse`, structural-blocker signatures, attention-queue enqueue); `agents/pa-*.md`; `rules/00-pa-operating-model.md`; in-plugin `SKILL.md`; `pa pr approve-plan`, `pa wo verify`, `pa escalate`. | PR-01 schemas, state DB, common, CLI extension point |
| **PR-03** | `vcs_sync.py` (`VcsBus` protocol with `LocalGitBus` and `GitHubBus`; trailer read/write; `pa programme init/charter`, `pa pr start/claim/open-or-sync/post-audit/sync-audit/graduate/restack`, `pa issue create`, `pa sync`); `models.py` (complexity → model tier routing, retry step-up `flash_lite → flash → inherit`, Language-Server conversation creation + JIT pinning with graceful no-op when the IDE is absent); `memory_grad.py` (`external` succinct writer vs `builtin` 3-file graduation). | PR-01/02 schemas, state DB, hooks' escalation records |
| **PR-04** | `daemon/sidecars/pa_cockpit/sidecar.json`; `cockpit.py` (HTTP + SSE API of SPEC §10.2, stdlib `http.server` only); `ui/` (`index.html`, `styles.css`, `app.js`); `scripts/install.sh` / `uninstall.sh`. | PR-01 state DB + `pa status --json` shape; PR-02 attention queue; PR-03 lifecycle commands |

### 2.2 Normative shared conventions (binding on every PR)

1. **Runtime dependencies:** Python standard library + `pydantic>=2,<3` + `pyyaml>=6`. Nothing else at runtime. Dev-only: `pytest`, `ruff`. Target `python>=3.11`; the reference host runs 3.13.
2. **Dev toolchain bootstrap:** `scripts/dev-bootstrap.sh` (PR-01) provisions `./.venv` idempotently (prefers `uv` if present; otherwise `python3 -m venv`; otherwise a `--without-pip` venv bootstrapped with `get-pip.py`) and installs `-e .[dev]`. All verification floors are executed from that venv. `.venv/` is gitignored.
3. **Test discipline:** `pytest` only; no network; no writes outside `tmp_path`; `PA_DAEMON_HOME` and `HOME` isolated per test; `gh`/`git remote` interactions mocked via injectable command runner or `PA_GH_BIN`. Every PR's verification floor is the pytest command named in its Charter; the floor must stay green at the tip of every Work Order (an earlier WO may legitimately collect 0 tests).
4. **CLI I/O contract:** machine-readable output on stdout (`--json` where defined), diagnostics on stderr; exit `0` success, `1` validation/usage error, `2` environment/precondition error. Emoji only in human-facing `pa status` text, never in `--json`.
5. **Hash algorithms (normative, fixed by this Charter so PR-01 can be stamped before the code exists):**
   - `charter_hash = sha256( canonical_json(PRCharterSpec minus charter_hash) + "\n" + norm(§1) + "\n" + norm(§2) )`
   - `spec_hash = sha256( canonical_json(WorkOrderSpec minus {spec_hash, status, completion}) + "\n" + norm(Part I sections) )`
   - `canonical_json(x) = json.dumps(model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)`; `norm(section)` = the section's full Markdown from its `## ` heading line up to (not including) the next `## ` heading, `.strip()`-ed, with trailing whitespace removed from every line and lines joined by `\n`. Hex digest, lowercase.
6. **Branching:** see `PROGRAM-PLAN.md` §2. Work Order branches `pr-NN-<slug>/woM-<topic>` stack linearly; each PR's declared `branch` (`feat/pr-NN-<slug>`) is the integration tip, fast-forwarded to the final WO branch at Step 6A and used as the PR head and as the next PR's `base_branch`.
7. **Commit message convention:** `WO-NN.M: <title>` for Work Order commits with trailers `PA-WorkOrder: WO-NN.M` and `PA-Verified-Hash: <tree_hash>`; `chore(pr-NN): …` for PA ledger commits; `audit(pr-NN): round K — <verdict>` with trailer `PA-Audit-Verdict: <verdict> (<head_sha>)`.
8. **Hygiene (I10):** enforced by the Cold-Firewall auditor on every round with a repository-wide search.

## 3. Programme Session Log

<!-- memory_mode: builtin — rich progressive synthesis. One entry per programme-level event. -->

### 2026-10-16 — Programme chartered (Tier 1 Chief Architect)
- Grounded on `SPEC.md` v1.1 and `docs/positioning-paper.md` Rev 3 at `main` `24cae59`.
- Provisioned `.agents/rules/00-operating-model.md` (byte-identical to the skill asset) so Tier 3 Workers hold standing authorization for approved Work Orders.
- Bootstrapped the PA workspace at the **legacy path** `.agents/skills/principal-architect-workspace/` (decision D1 in `PROGRAM-PLAN.md`): the currently installed skill reads that path, and PR-01's `pa enroll` migration to `.agents/plugins/principal-architect-workspace/` will be dogfooded on this very repository.
- Environment baseline recorded: no `origin` remote (→ `vcs_mode: local_git` until a GitHub remote is added); no external memory plugin enrolled (→ `memory_mode: builtin`); host Python 3.13 without `pip`/`ensurepip`, PyPI reachable (→ `scripts/dev-bootstrap.sh` is a PR-01 deliverable).
- Authored and locked Part I (`PR Charter`) of [`pr-01-core-schemas-and-enrollment/PROJECT.md`](../pr-01-core-schemas-and-enrollment/PROJECT.md); PR-02..PR-04 Charters remain stubs in this file's frontmatter and will be refined just-in-time as each upstream PR graduates.

### 2026-10-16 — GitHub remote added; programme switched to `vcs_mode: github`
- User created the public repository `matthewmcneill/principal-architect-plugin`; `origin` configured and `main` pushed (`5ce84f1`). Decision D3 superseded in `PROGRAM-PLAN.md`: each PR's Step 6A now pushes `feat/pr-NN-<slug>` and opens a GitHub PR; Cold-Firewall audits are committed as `AUDIT-round-K.md` (canonical) and mirrored as `gh pr review --comment`. The PR-01 Charter is mode-agnostic and remains locked unchanged.
