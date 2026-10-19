# Principal Architect Plugin: Technical Specification

| | |
|---|---|
| **Status** | **v1.1** |
| **Date** | 2026-10-16 |
| **Scope** | Hierarchical multi-agent software architecture, dynamic model/token efficiency routing, stacked-PR programme orchestration, deterministic boundary enforcement, local-Git + optional-GitHub multi-machine/multi-harness bus, and AuxPane IDE Cockpit. **Primary Harness: Antigravity (`agy`). Portable via Git/GitHub to Claude Code (`claude`) and Gemini CLI (`gemini`).** |
| **Implementation** | Self-contained Python 3.11+ & Pydantic v2 control plane (`scripts/`) packaged inside `daemon/` |
| **Companion Docs** | [Positioning Paper (`docs/positioning-paper.md`)](docs/positioning-paper.md) |

---

## 1. Purpose

Large engineering initiatives—spanning multiple stacked pull requests, dozens of files, and strict architectural invariants—routinely fail or waste massive token budgets when executed in a single monolithic agent session. As the context window fills with file reads, build logs, and debugging detours, a monolithic session suffers context compaction, forgets architectural invariants, drifts outside its intended file scope, or burns expensive frontier-model tokens on repetitive edit-compile-test loops.

`principal-architect-plugin` transforms the Principal Architect workflow from an advisory prompt skill into a **mechanically enforced, token-efficient, multi-tier orchestration plugin**:

- **Dynamic model & token efficiency:** Invests frontier reasoning (`Gemini 4 Argon`, `Gemini 3.1 Pro`, `Claude Opus`) up front in the Architect tiers to produce tight, unambiguous contracts, then dynamically routes bounded implementation slices to the most cost- and token-efficient model tier capable of reliable execution (`mechanical` $\to$ `flash_lite`, `standard` $\to$ `flash`, `architect` $\to$ `inherit`/frontier)—avoiding burning frontier tokens on mechanical edits and test loops.
- **Fractal top-down contract ownership:** Enforces a symmetric hierarchy where each tier authors the immutable charter for the tier below it (**Tier 1 Chief Architect** authors the `PROGRAM.md` DAG and Part I `PR Charter` of `PROJECT.md` $\to$ **Tier 2 Principal Architect** authors Part II `Implementation Plan & Work Order Breakdown` of `PROJECT.md` and `WORKORDER.md` specs $\to$ **Tier 3 Execution Worker** implements a single `WORKORDER.md` and authors its `Completion Report`).
- **Evidence-based capability scoping (`inheritCustomizations: false` + repo-scoped manifests):** Strips ~10k–14k tokens of unrelated global personal skills/rules (`~/.gemini/config/`) and conflicting interactive-only workspace rules (`01-plan-before-execute.md`) via repo-generated `.state/pa-skills.json` and `.state/pa-worker-rules.json` manifests, while preserving 100% of `<repo>/.agents/skills/`, repo-configured domain/hardware skills (`pio`), and MCP tools across Architects and Engineers with a KV-cache-stable system prompt prefix.
- **Dual-mode execution (`Monitored` vs. `Autonomous`):** Supports interactive confirmation prompts (`permissionDecision: "ask"`) when a human is pair-supervising, and deterministic **Upward Hierarchical Escalation** (`Worker` $\to$ `PA` $\to$ `Chief` $\to$ `Human Attention Queue`) when running unattended.
- **Local Git floor with optional GitHub multi-machine/multi-harness bus:** Requires only a local Git repository (`git init`) to run end-to-end offline (stacked branches, cryptographic commit trailers, local Cold-Firewall branch audits), while seamlessly upgrading to synchronize across machines and harnesses via GitHub Pull Requests, Reviews, and Issues when a GitHub remote is configured.
- **Clean memory boundary (`external` vs. `builtin` fallback):** Defers all codebase memory management to `repo-memory-plugin` when installed (keeping `WORKORDER.md` and `PROJECT.md` write-backs terse and token-succinct so tokens are never burned duplicating memory), and only activates the built-in 3-file progressive-reveal memory index (`MEMORY.md`, `MODULE_INDEX.md`, `PROJECT_INDEX.md`) as a fallback when no external memory plugin is present.
- **First-class IDE visibility:** Provides an interactive **Principal Architect Cockpit** in the Antigravity Auxiliary Pane (`AuxPane`) featuring a **🔔 Human Attention Needed** inbox, live Programme $\to$ Stacked PR $\to$ Work Order DAG, Git/GitHub PR lifecycle badges, and one-click conversation switching (`window.sidecar.ui.toggleConversation`).

### 1.1 Goals

| # | Goal |
|---|---|
| **G1** | **Zero inline implementation drift by Architects.** Tier 1 Chief Architects and Tier 2 Principal Architects are mechanically prevented from editing application source code directly (`PreToolUse` gate), keeping their context windows clean and high-level across entire PR lifecycles. |
| **G2** | **Fractal top-down contract enforcement.** Tier 1 Chief Architects author and lock the Part I `PR Charter` (`Scope`, `Goals`, `Requirements`, `Allowed Modules`, `Required Tools/Skills`) of `PROJECT.md`; Tier 2 Principal Architects author the Part II `Implementation Plan & Work Order Breakdown` and individual `WORKORDER.md` specs; Tier 3 `pa-engineer` subagents execute strictly within their bound `WORKORDER.md` `allowed_files`. |
| **G3** | **Evidence-based capability scoping (stripping global bloat & conflicting rules while preserving 100% of repo-relevant skills/MCPs).** Constrain skills, rules, and tools statically at the **Role $\times$ Enrolled Repository** level (`pa enroll`)—stripping ~10k–14k tokens of unrelated global user skills/rules (`~/.gemini/config/`) and conflicting interactive-only workspace rules (`01-plan-before-execute.md`) while mounting 100% of `<repo>/.agents/skills/` and repo-configured hardware/domain skills (`pio`, `framework-expert`) with a KV-cache-stable system prompt prefix. |
| **G4** | **Cryptographic verification receipts & empirically calibrated retry budgets (`max_attempts: 5`).** A `pa-engineer` subagent cannot finish its turn (`Stop` hook returns `decision: "continue"`) until its declared `verification_command` exits `0` against the current working-tree file hashes. Normal compile/test/review rework is granted up to **5 attempts**, while structural blockers (hook/scope denials, 3 consecutive `ERROR_MESSAGE` steps) fast-fail and escalate after **2 structural failures**. |
| **G5** | **Cold-Firewall PR Audit before graduation.** A PR cannot graduate (`pa pr graduate`) until a stateless `pa-auditor` inspects the PR diff (`gh pr diff <N>` or local `git diff <base>...<branch>`) against `PROGRAM.md` and `PROJECT.md` without access to the PA's internal rationalizations and records an `APPROVED` verdict matching the current `HEAD` SHA. |
| **G6** | **Configurable `Monitored` vs. `Autonomous` execution.** Boundary exceptions prompt the user inline in `Monitored` mode and escalate up the `Worker` $\to$ `PA` $\to$ `Chief` $\to$ `Human Attention Queue` hierarchy in `Autonomous` mode. |
| **G7** | **100% self-contained plugin packaging & clean state scoping.** All operational scripts (`scripts/`), Pydantic schemas, hooks, agents, and UI assets live inside `daemon/`. Global enrollment state lives inside gitignored `daemon/state/`, committed project specs live in `<repo>/.agents/plugins/principal-architect-workspace/`, and local checkout runtime state lives in gitignored `<repo>/.agents/plugins/principal-architect-workspace/.state/state.db`. |
| **G8** | **Local Git floor + cross-machine/cross-harness GitHub interoperability.** All workflows operate against a local `.git` database when GitHub is not initialized (`vcs_mode: "local_git"`), and automatically synchronize via GitHub PRs/Reviews/Issues when a GitHub remote is present (`vcs_mode: "github"`). |
| **G9** | **Clean mutual-exclusion boundary with `repo-memory-plugin`.** (a) When `repo-memory-plugin` is installed (`memory_mode: "external"`), `principal-architect-plugin` stays completely out of memory management and restricts `WORKORDER.md` / `PROJECT.md` write-backs to succinct mechanical status fields. (b) Only when `repo-memory-plugin` is *not* installed (`memory_mode: "builtin"`) does `principal-architect-plugin` maintain its own `memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}` index. |
| **G10** | **One-click Cockpit navigation & attention management.** The AuxPane Cockpit surfaces a prioritized **🔔 Human Attention Needed** queue, live Git/GitHub PR badges (`Local`, `Draft`, `Staged`, `Changes Requested`, `Approved`, `Merged`), and 1-click conversation activation. |

### 1.2 Non-Goals

- Duplicating memory management when `repo-memory-plugin` is installed. `principal-architect-plugin` only manages its own `memory/` index when `repo-memory-plugin` is absent (`memory_mode: "builtin"`).
- Requiring a remote GitHub repository or external cloud database for local development. A local Git repository (`git init`) and local SQLite are the only mandatory dependencies.
- Dynamically rewriting `agents/*.md` system prompts before every individual Work Order (which invalidates the LLM's KV prompt-cache prefix across consecutive Work Orders) or stripping repository-local domain skills (`<repo>/.agents/skills/`, `pio`) that Engineers and Architects need to build and verify code.

---

## 2. Core Design Principles

| # | Principle | Operational Consequence |
|---|---|---|
| **P1** | **Enforce invariants in hooks, not prose.** | Every critical workflow rule (no inline Architect code edits, Chief Charter lock on `PROJECT.md` Part I, Worker `allowed_files` boundary boxes, mandatory post-edit test execution, audit-before-graduation) is enforced deterministically by `PreToolUse`, `PostToolUse`, and `Stop` hooks. |
| **P2** | **Constrain customizations statically by Role $\times$ Repo (`inheritCustomizations: false` + curated manifests); specialize per-WO in `PreInvocation`.** | Empirically, unfiltered `inheritCustomizations: true` injects **~11,000–14,000 tokens** of unrelated global skills (`~175 tokens/skill` across 20–40 personal skills) and global/workspace rules (including conflicting rules like `01-plan-before-execute.md` that cause autonomous Workers to stall). Instead, `pa enroll` generates static, KV-cache-stable `skills.json` and `rules.json` manifests per role that strip global personal bloat and conflicting rules while retaining 100% of `<repo>/.agents/skills/` and enrolled hardware/domain skills (`pio`). |
| **P3** | **Hybrid tiered execution topology.** | Stateful, human-interactive roles (**Tier 1 Chief Architect**, **Tier 2 per-PR Principal Architect**, **Tier 3b Interactive Debugger**) run as persistent top-level conversations (auto-pinned and 1-click navigable in the IDE). Stateless, bounded roles (**Tier 3 `pa-engineer`**, **Tier 2b `pa-auditor`**) run as isolated `invoke_subagent` calls. |
| **P4** | **Preserve frontier model fidelity (`Model: "inherit"`).** | Custom agent definitions use `model: inherit`. When an Architect session running on **Gemini 4 Argon (High)**, **Gemini 3.1 Pro (High)**, or **Claude Opus 5.5** spawns `pa-auditor` or an `architect`-tier `pa-engineer`, it passes `Model: "inherit"` so the subagent inherits the exact parent frontier model rather than downgrading to a generic tier default. |
| **P5** | **Fractal Split-Authority Contracts (Pydantic v2 + Markdown).** | Every canonical artifact (`PROGRAM.md`, `PROJECT.md`, `WORKORDER.md`, `AUDIT.md`) pairs a machine-validated YAML frontmatter block (`scripts/schemas.py`) with structured Markdown sections whose ownership is split between the commissioning parent tier (locked Charter/Spec) and the executing child tier (Plan/Completion Report). |
| **P6** | **Local Git is the mandatory floor; GitHub is the portable multi-machine bus; `.state/state.db` is the local cache.** | Stacked branches, `PROJECT.md`/`WORKORDER.md` specs, `PA-Verified-Hash` / `PA-Audit-Verdict` commit trailers, and local `AUDIT-round-<K>.md` files work 100% against a local `.git` repo (`vcs_mode: "local_git"`). When a GitHub remote is initialized (`vcs_mode: "github"`), `pa sync` projects and reconciles state across GitHub PRs, Reviews, and Issues for multi-machine and multi-harness handoffs. |
| **P7** | **Strict memory boundary & token-succinct write-backs.** | When an external memory plugin (`repo-memory`) is active (`memory_mode: "external"`), `principal-architect-plugin` disables its own `memory/` subsystem and enforces **succinct mechanical write-backs** in `WORKORDER.md` and `PROJECT.md` (status, SHA, receipt, 1-line summary/escalations) to avoid burning tokens duplicating `repo-memory`'s turn-note harvesting. Only when no external memory plugin is installed (`memory_mode: "builtin"`) does `principal-architect-plugin` enable full warm-cache distillation and maintain `memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}`. |
| **P8** | **Zero overhead in unenrolled repositories.** | The split-daemon packaging ensures workspace hooks (`workspace-plugin/principal-architect/hooks.json`) only load in repositories enrolled via `<repo>/.agents/plugins.json`, and fast-exit in $<1\text{ms}$ if `.agents/plugins/principal-architect-workspace/` is absent. |

---

## 3. Terminology, Fractal Role Hierarchy, & Empirical Retry Calibration

### 3.1 Role Hierarchy & Split-Authority Ownership

| Term / Role | Tier | Execution Surface | Responsibility & Authority Boundary |
|---|---|---|---|
| **Chief Architect (`pa-chief-architect`)** | **Tier 1** | Pinned Top-Level Conversation (`🏛️ [Chief] <Programme>`) | Owns multi-PR programme discovery, `PROGRAM.md` (including the stacked PR DAG), **Part I of each PR's `PROJECT.md` (`PR Charter`: Scope, Goals, Architectural Requirements, Cross-PR Interfaces, Allowed Modules, & Required Skills/Tools)**, cross-PR escalations, and deferred GitHub Issue creation (`pa issue create`). **Forbidden** from editing application source code or individual `WORKORDER.md` files. |
| **Principal Architect (`pa-principal-architect`)** | **Tier 2** | Pinned Top-Level Conversation (`📐 [PR-NN] <Title>`) | Owns exactly **one PR** (`1 PR = 1 Project`) within the Chief Architect's locked `PR Charter`. Performs file-level PR discovery, authors **Part II of `PROJECT.md` (`Implementation Plan & Work Order Breakdown`)** and sequential `WORKORDER.md` Part I specs, dispatches `pa-engineer` (1 per WO) and `pa-auditor` (Step 6A), reviews diffs, authors **Part III of `PROJECT.md` (`Outcome & Graduation Summary`)**, and runs `pa pr graduate`. **Forbidden** from mutating Part I of `PROJECT.md` (must escalate to Chief via `pa escalate --to-chief`) or editing application source code inline. |
| **Cold-Firewall PR Auditor (`pa-auditor`)** | **Tier 2b** | Isolated Subagent (`invoke_subagent`) or External Harness Session | Stateless adversarial reviewer operating behind an information firewall (receives only `PROGRAM.md`, `PROJECT.md`, and the PR diff via `gh pr diff <N>` or `git diff <base>...<branch>`—never the PA's conversation history). Evaluates 5 audit axes (up to `max_audit_rounds: 5`) and publishes `AUDIT.md` via `pa pr post-audit`. **Read-only** (`write_file` and `edit_file` removed). |
| **Execution Worker (`pa-engineer`)** | **Tier 3** | Isolated Subagent (`invoke_subagent`, 1 per `WORKORDER.md`) | Ephemeral builder scoped to a single `WORKORDER.md`. Modifies only `allowed_files`, runs `verification_command` (up to `max_attempts: 5`), commits with `WO-NN.M:` prefix + receipt trailer, and authors **Part II of `WORKORDER.md` (`Completion Report`)**. **Forbidden** from mutating Part I of `WORKORDER.md`, touching files outside `allowed_files`, running `git push`/`git checkout`, or spawning subagents (`invoke_subagent` removed). |
| **Interactive Debugger (`pa-debugger`)** | **Tier 3b** | On-Demand Top-Level Conversation (`🔬 [Debug WO-NN.M]`) | Activated when a Work Order is marked `complexity: interactive`, exhausts its **5 verification attempts** (`max_attempts: 5`), or hits **2 structural blockers** (`max_structural_failures: 2`). Pairs with the human engineer to isolate root cause, commit the fix, and return a structured resolution to the PR Principal Architect. |
| **Programme** | — | `.agents/plugins/principal-architect-workspace/programme-<slug>/` | A multi-PR initiative decomposed into a DAG of stacked pull requests in `PROGRAM.md`. |
| **Project (PR Slice)** | — | `.agents/plugins/principal-architect-workspace/pr-<slug>/` | A single reviewable Pull Request (`PROJECT.md`), split between Part I (`PR Charter`, Chief-owned) and Part II/III (`Implementation Plan & Outcome`, PA-owned). |
| **Work Order (WO)** | — | `.agents/plugins/principal-architect-workspace/pr-<slug>/wo<M>-<slug>/WORKORDER.md` | An atomic implementation slice within a Project, split between Part I (`Specification & Boundary Box`, PA-owned) and Part II (`Completion Report`, Worker-owned). |
| **Verification Receipt** | — | `.state/state.db` + Git Commit Trailer (`PA-Verified-Hash`) | Cryptographic record stamped by `PostToolUse` / `pa wo verify` proving that `verification_command` exited `0` when the working-tree files in `allowed_files` matched `tree_hash`. |

### 3.2 Empirical Calibration of `max_attempts: 5` vs. `max_structural_failures: 2`

Analysis of 38 autonomous Engineer $\leftrightarrow$ Architect PR trajectories and 24-hour trajectory health reports across `matthewmcneill/bug-fixer-loop-plugin` (24 PRs) and `matthewmcneill/esp32-app-foundation` (14 post-architect-review PRs) established the following empirical distribution of iterations required to reach an approved, merged PR:

| Rounds to Approval | `bug-fixer-loop-plugin` ($n=24$) | `esp32-app-foundation` ($n=14$) | Combined ($n=38$) | Share of Resolved PRs |
|---|---|---|---|---|
| **1 Round** (0 rework turns) | 7 | 4 | **11** | **28.9%** |
| **2 Rounds** (1 rework turn) | 9 | 5 | **14** | **36.8%** |
| **3 Rounds** (2 rework turns) | 4 | 4 | **8** | **21.1%** |
| **4 Rounds** (3 rework turns) | 3 | 1 | **4** | **10.5%** |
| **5 Rounds** (4 rework turns) | 1 | 0 | **1** | **2.6%** |

Key operational conclusions incorporated into this specification:
1. **Why `max_attempts: 5` (and `max_audit_rounds: 5`) is mandatory:** Capping attempts at `2` would have prematurely aborted **34.2% (`13 / 38`)** of successful autonomous fixes that legitimately required 3 to 5 rounds due to progressive multi-layer discovery (e.g., `esp32-app-foundation` PR `#281`, where renaming headers exposed `#define` include-guard false positives in the audit script across 4 rounds), multi-item test/spec verification (`bug-fixer-loop-plugin` PR `#24`, 4 rounds), or mid-flight rebase cleanup (`bug-fixer-loop-plugin` PR `#29`, 5 rounds).
2. **What actually caused trajectory failures in production:** None of the true trajectory failures in `bug-fixer` health reports (`esp32-app-foundation` Issues `#269`, `#277`; `bug-fixer-loop-plugin` Issues `#3`, `#15`, `#31`) were caused by productive multi-turn code/test iteration. Instead, every trajectory failure fell into one of three **structural/environmental categories**:
   - **Structural Hook / Gate Denials (`BLOCKER_STRUCTURAL`, Issue `#31`):** Repeated `PreToolUse` denials or `>= 3` consecutive `ERROR_MESSAGE` steps in `transcript.jsonl` where retrying the identical blocked command is futile.
   - **Exclusive Hardware / MCP Lock Starvation (`Issue #269`):** Sessions stalling for >2 hours on `Hardware is currently tied` when a prior session exited without releasing `platformio-mcp`.
   - **Silent Session Stalls (`Issue #277`, PRs `#272` & `#274`):** Sessions emitting a `PLANNER_RESPONSE` with no tool calls and waiting idly for human approval in an unattended loop.
3. **Resulting Two-Tier Retry Policy:** `principal-architect-plugin` grants **up to 5 productive attempts (`max_attempts: 5`)** when the Worker/Auditor is making state progress (editing allowed files, running tests, addressing review findings), but fast-fails and escalates after **2 structural blockers (`max_structural_failures: 2`)** or **3 consecutive `ERROR_MESSAGE` steps (`error_loop_threshold: 3`)**.

---

## 4. Packaging & Directory Architecture

### 4.1 Self-Contained Split-Daemon Repository Layout

To ensure that installing `daemon/` provides a 100% self-contained runtime with zero external repository dependencies (matching the `scripts/` layout convention of `bug-fixer-plugin` and `repo-memory-plugin`), all operational Python modules, Pydantic schemas, hook entrypoints, custom agents, skills, templates, and AuxPane UI assets reside inside `daemon/`:

```text
principal-architect-plugin/                  # Git repository root (Development & Test wrapper)
├── README.md
├── SPEC.md                                  # This specification
├── docs/
│   └── positioning-paper.md
├── pyproject.toml                           # Dev/test configuration (pytest, ruff, pydantic>=2.0)
├── scripts/
│   ├── install.sh                           # Installs `daemon/` -> ~/.gemini/config/plugins/pa-daemon
│   ├── uninstall.sh                         # Removes ~/.gemini/config/plugins/pa-daemon
│   ├── enroll.sh                            # Convenience wrapper -> `pa enroll`
│   └── unenroll.sh                          # Convenience wrapper -> `pa unenroll`
├── tests/                                   # Unit, schema, & adversarial hook test suite
│   ├── test_schemas.py
│   ├── test_hooks_monitored_vs_autonomous.py
│   ├── test_state_db_and_sync.py
│   ├── test_github_and_local_git_bus.py
│   └── test_memory_modes.py
└── daemon/                                  # 📦 THE INSTALLABLE PLUGIN PACKAGE (100% Self-Contained)
    ├── plugin.json                          # Global plugin manifest ("name": "pa-daemon")
    ├── state/                               # 🔒 Gitignored plugin-internal state
    │   ├── registry.json                    # Enrolled repositories map (workspace_path -> repo metadata)
    │   └── config.json                      # Global user defaults (default_architect_model, etc.)
    ├── sidecars/
    │   └── pa_cockpit/
    │       ├── sidecar.json                 # SIDECAR_UI_ENTRYPOINT_AUX_PANE -> runs `scripts/cockpit.py`
    │       └── ui/
    │           ├── index.html
    │           ├── styles.css
    │           └── app.js
    └── workspace-plugin/                    # Invisible to global plugin scan (depth-1 non-recursive scan)
        └── principal-architect/             # Referenced by <repo>/.agents/plugins.json (absolute path)
            ├── plugin.json                  # Workspace plugin manifest ("name": "principal-architect")
            ├── hooks.json                   # PreInvocation, PreToolUse, PostToolUse, Stop
            ├── scripts/                     # Self-contained Python + Pydantic v2 control plane & hooks
            │   ├── __init__.py
            │   ├── pa_cli.py                # `pa` CLI entrypoint (symlinked to ~/.local/bin/pa)
            │   ├── schemas.py               # Pydantic v2 models & Split-Authority Markdown parser/renderer
            │   ├── state_db.py              # SQLite manager for repo-local `.state/state.db` & `daemon/state/`
            │   ├── escalation.py            # Monitored vs. Autonomous escalation & structural blocker engine
            │   ├── vcs_sync.py              # Local Git floor + optional `gh` PR/Review/Issue sync
            │   ├── memory_grad.py           # `external` (no-op / succinct) vs. `builtin` 3-file index updater
            │   ├── models.py                # Model tier & family router + Language Server RPC client
            │   ├── cockpit.py               # AuxPane HTTP + SSE server
            │   ├── common.py                # Fast enrollment check (<1ms fast-exit) & transcript reader
            │   ├── pre_invocation.py        # Role/WO contract push, compaction recovery, skill highlighting
            │   ├── pre_tool_gate.py         # Boundary box, Charter lock, Architect no-code gate, git/gh gate
            │   ├── post_tool_receipt.py     # Edit invalidation & test verification receipt stamper
            │   └── stop_gate.py             # Premature-exit refusal (`decision: "continue"`) & retry counter
            ├── rules/
            │   └── 00-pa-operating-model.md
            ├── agents/
            │   ├── pa-chief-architect.md
            │   ├── pa-principal-architect.md
            │   ├── pa-engineer.md
            │   ├── pa-auditor.md
            │   └── pa-debugger.md
            └── skills/
                └── principal-architect/
                    ├── SKILL.md
                    └── templates/
                        ├── PROGRAM.md.tpl
                        ├── PROJECT.md.tpl
                        ├── WORKORDER.md.tpl
                        ├── AUDIT.md.tpl
                        ├── MEMORY.md.tpl
                        ├── MODULE_INDEX.md.tpl
                        └── PROJECT_INDEX.md.tpl
```

### 4.2 Enrolled Consumer Repository Layout

When a target repository is enrolled via `pa enroll <repo-path>`, its layout under `<repo>/.agents/` is:

```text
<enrolled-repo>/
├── .agents/
│   ├── plugins.json                                   # 🔒 Gitignored: {"entries": [{"path": "/abs/path/to/pa-daemon/workspace-plugin"}]}
│   └── plugins/
│       └── principal-architect-workspace/             # ✅ Committed to Git: Portable PA Workspace
│           ├── .gitignore                             # Ignores `.state/`
│           ├── .state/                                # 🔒 Gitignored: Local checkout runtime state & manifests
│           │   ├── state.db                           # SQLite: local conv UUIDs, receipts, execution_mode, memory_mode, vcs_mode
│           │   ├── pa-skills.json                     # Role-scoped skill manifest (<repo>/.agents/skills + extra_skills)
│           │   └── pa-worker-rules.json               # Worker/Auditor rule manifest (<repo>/.agents/rules minus conflicting rules)
│           ├── memory/                                # ⚙️ OPTIONAL (Created & maintained ONLY when memory_mode == "builtin";
│           │   │                                      #    omitted when repo-memory-plugin is enrolled)
│           │   ├── MEMORY.md                          # Boot registry (Active + last 5 completed PRs)
│           │   ├── MODULE_INDEX.md                    # Domain/module cross-reference -> PROJECT.md links
│           │   └── PROJECT_INDEX.md                   # Chronological archive of graduated PRs
│           ├── programme-<slug>/                      # ✅ Committed: Tier 1 Chief Architect artifacts
│           │   └── PROGRAM.md                         # Programme invariants, stacked PR DAG, & session log
│           └── pr-<slug>/                             # ✅ Committed: Split-Authority PR artifacts
│               ├── PROJECT.md                         # Part I: PR Charter (Chief) | Part II: WO Plan (PA) | Part III: Outcome (PA)
│               ├── AUDIT-round-1.md                   # Committed AuditReport (canonical in local_git mode; mirror in github mode)
│               └── wo<M>-<slug>/
│                   └── WORKORDER.md                   # Part I: Spec & Boundary Box (PA) | Part II: Completion Report (Worker)
```

### 4.3 Enrollment, Capability Detection, & Legacy Migration (`pa enroll` / `pa unenroll`)

1. **`pa enroll [repo_path] [--memory-mode auto|external|builtin] [--vcs-mode auto|github|local_git] [--extra-skill <name>...] [--exclude-rule <pattern>...]`:**
   - Resolves `repo_path` to its canonical absolute git root (`git rev-parse --show-toplevel`). If `repo_path` is not yet a git repository, runs `git init` to establish the mandatory local Git floor.
   - **Legacy Migration Check:** If `<repo>/.agents/skills/principal-architect-workspace/` exists and `<repo>/.agents/plugins/principal-architect-workspace/` does not, executes `git mv .agents/skills/principal-architect-workspace .agents/plugins/principal-architect-workspace` (or `mv` if untracked). Because all links inside `memory/MODULE_INDEX.md` and `memory/PROJECT_INDEX.md` are relative (`../pr-XX/PROJECT.md`), every historical link remains intact.
   - **External Memory Auto-Detection (`memory_mode`):**
     - Inspects `<repo>/.memory/`, `<repo>/.agents/plugins.json`, and `~/.gemini/config/plugins/repo-memory-daemon/state/registry.json`.
     - If `repo-memory-plugin` is enrolled on `<repo>`, sets `memory_mode = "external"` in `.state/state.db` and **does not scaffold `memory/`** (avoiding any overlap with `repo-memory`).
     - Otherwise, sets `memory_mode = "builtin"` and scaffolds `.agents/plugins/principal-architect-workspace/memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}` from templates if missing.
   - **VCS / GitHub Remote Auto-Detection (`vcs_mode`):**
     - Checks `git remote get-url origin` and `gh auth status`. If a GitHub remote is reachable, sets `vcs_mode = "github"`; otherwise sets `vcs_mode = "local_git"` (all stacked branch, receipt trailer, and Cold-Firewall Audit operations run locally against `.git`).
   - **Role-Scoped Customization Manifests (`pa-skills.json` & `pa-worker-rules.json` in `.state/`):**
     - Generates `<repo>/.agents/plugins/principal-architect-workspace/.state/pa-skills.json` and `.state/pa-worker-rules.json`:
       ```json
       // .agents/plugins/principal-architect-workspace/.state/pa-skills.json
       {
         "entries": [
           { "path": "<abs-repo-root>/.agents/skills" },
           { "path": "<abs-user-config>/skills", "include_only": ["pio"] }
         ]
       }
       ```
       ```json
       // .agents/plugins/principal-architect-workspace/.state/pa-worker-rules.json
       {
         "entries": [
           {
             "path": "<abs-repo-root>/.agents/rules",
             "exclude": ["01-plan-before-execute.md", "bug-fixer-*"]
           }
         ]
       }
       ```
       - `pa-skills.json` mounts `<repo>/.agents/skills` plus any global domain skills explicitly declared via `--extra-skill` or `repo_config.extra_skills` (e.g., `["pio"]`), excluding unrelated global personal skills (`~/.gemini/config/skills/`).
       - `pa-worker-rules.json` mounts `<repo>/.agents/rules` with `"exclude": ["01-plan-before-execute.md", "bug-fixer-*"]` (plus any `--exclude-rule` patterns), preventing autonomous `pa-engineer` and `pa-auditor` subagents from inheriting interactive plan-gate rules or sibling-plugin rules that conflict with Work Order execution.
   - Creates `.agents/plugins/principal-architect-workspace/.gitignore` containing `.state/`, initializes `.state/state.db`, writes the resolved **absolute path** of `daemon/workspace-plugin` into `<repo>/.agents/plugins.json` (listed in `.git/info/exclude`), and registers `repo_path` in `daemon/state/registry.json`.
2. **`pa unenroll [repo_path]`:**
   - Removes the `pa-daemon/workspace-plugin` entry from `<repo>/.agents/plugins.json` and removes the repository from `daemon/state/registry.json` while preserving committed files in `.agents/plugins/principal-architect-workspace/`.

---

## 5. Execution Topology, Context Partitioning, & Model Routing

### 5.1 Hybrid Tiered Execution Topology

| Tier / Role | Execution Mechanism | Sidebar & UI Behavior | Rationale |
|---|---|---|---|
| **Tier 1: `pa-chief-architect`** | Persistent Top-Level Conversation | Auto-pinned (`🏛️ [Chief] <Programme>`); 1-click jump via `window.sidecar.ui.toggleConversation(chief_conv_id)`. | Multi-turn strategic interaction with the user across the life of the programme; authors `PROGRAM.md` and each PR's Part I `PR Charter` in `PROJECT.md`. |
| **Tier 2: `pa-principal-architect`** | Persistent Top-Level Conversation (1 per PR) | Auto-pinned while PR is active (`📐 [PR-NN] <Title>`); automatically unpinned on `pa pr graduate`. | Gives each PR a clean 0-token starting context window while allowing direct human plan review and steering within the Chief's locked `PR Charter`. |
| **Tier 2b: `pa-auditor`** | Isolated Subagent (`invoke_subagent`) or External Session | Inspectable under parent PR conversation and in Cockpit Audit Scorecard. | Guarantees a cold information firewall (zero PA chat history) and automatic parent wakeup on completion. |
| **Tier 3: `pa-engineer`** | Isolated Subagent (`invoke_subagent`, strictly 1 per WO) | Live progress & receipt badge shown in Cockpit DAG; does not clutter top-level sidebar. | Eliminates PA context bloat (0 PA compactions across 6–8 WOs), routes work to `flash_lite`/`flash`/`inherit`, and enforces single-writer working-tree safety. |
| **Tier 3b: `pa-debugger`** | On-Demand Top-Level Conversation | Spawned & auto-pinned (`🔬 [Debug WO-NN.M]`) when `complexity: interactive`, after 5 failed Worker attempts, or after 2 structural blockers; unpinned on `pa wo resolve`. | Interactive pair-debugging with the human requires a first-class chat window without polluting the PA's context. |

### 5.2 Custom Agent Specifications (`agents/*.md`) & The 4-Criterion Capability Scoping Framework

Whether to constrain or inherit tools, skills, rules, and MCPs for each role is decided by **four quantitative engineering criteria**:

| Customization Source | Measured Prompt Cost (`inheritCustomizations: true`) | Relevance / Conflict Risk in `pa-engineer` (`flash_lite` / `flash`) | Policy under `inheritCustomizations: false` + `.state/` Manifests |
|---|---|---|---|
| **Global `~/.gemini/config/skills/`** (23–40 personal/office skills) | **~4,039–6,500 tokens** (`~175` tokens/skill description in `<skills>`) | **<5% relevant** to a target repo; distracts smaller models | **Stripped by default**; repo-relevant global skills (e.g. `pio`) explicitly included via `pa-skills.json` `include_only` |
| **Global `~/.gemini/config/` & plugin `<user_rules>`** | **~5,000–7,300 tokens** (injected in full on every turn) | **0% relevant** to coding Work Orders; causes out-of-scope file/memory edits | **Stripped** from `pa-engineer` and `pa-auditor` |
| **Repo-local `<repo>/.agents/skills/`** (e.g. `framework-expert`, `framework-portal-design`, `framework-setup`) | **~450 tokens** (`3–5` repo skills) | **100% relevant** to both Architects and Engineers | **Retained 100%** via `.state/pa-skills.json` |
| **Repo-local `<repo>/.agents/rules/` — Domain Rules** (`02-tmp_workspace.md`, `03-versioning.md`, `04-mcp-tooling.md`) | **~2,240 tokens** | **100% relevant** (prevents `/tmp` writes, enforces MCP lock protocol) | **Retained 100%** via `.state/pa-worker-rules.json` |
| **Repo-local `<repo>/.agents/rules/` — Conflicting Interactive / Sibling Rules** (`01-plan-before-execute.md`, `bug-fixer-*`) | **~3,405 tokens** (`1,602` tokens for `01-plan-before-execute.md`) | **Actively harmful** to autonomous Workers (*"Never edit code before asking user to approve plan"* causes Plan-Gate stalls) | **Excluded** from `pa-engineer` and `pa-auditor` via `"exclude": ["01-plan-before-execute.md", "bug-fixer-*"]` |

1. **Criterion 1 — Signal-to-Noise & Token Footprint (`~11,000–13,800` tokens of Global Personal Bloat vs. `~450` tokens of Repo Domain Skills):**
   - Empirically, a developer's global `~/.gemini/config/` typically accumulates 20–40 personal/office skills averaging **~175 tokens per YAML description** (`~4,000–6,500` tokens in `<skills>`) plus **~5,000–7,300 tokens** of unrelated global plugin rules (`<user_rules>`).
   - By contrast, a target repository's own `.agents/skills/` (e.g., `framework-expert`, `framework-portal-design`, `framework-setup` in `esp32-app-foundation`) has only 3–5 domain skills (**~450 tokens** of catalog descriptions) that are **100% relevant** to the codebase.
   - **Decision:** Set `inheritCustomizations: false` on subagent roles (`pa-engineer`, `pa-auditor`) and point their `skills:` and `rules:` frontmatter at the repo-scoped `.state/pa-skills.json` and `.state/pa-worker-rules.json` manifests generated by `pa enroll`. This strips ~11,000–13,800 tokens of global personal noise at **zero LLM token cost** while keeping 100% of `<repo>/.agents/skills/` and repo-configured hardware skills (e.g. `pio`).
2. **Criterion 2 — Rule Conflict Prevention on Smaller Models (`flash_lite` / `flash`):**
   - Unfiltered workspace rules often include interactive-only rules like `01-plan-before-execute.md` (~1,602 tokens: *"Never execute code edits before asking the user to approve your plan"*) or global memory rules (*"Update memory files before ending your turn"*). On smaller models (`flash_lite`, `flash`), conflicting high-priority `<RULE>` blocks cause Plan-Gate stalls or out-of-scope file edits.
   - **Decision:** `.state/pa-worker-rules.json` mounts `<repo>/.agents/rules` (retaining domain rules like `02-tmp_workspace.md`, `03-versioning.md`, `04-mcp-tooling.md`) while deterministically excluding `01-plan-before-execute.md` and other plugins' operating rules.
3. **Criterion 3 — KV Prompt-Cache Prefix Stability (Static Per-Role Prefix vs. Dynamic Per-WO Rewriting):**
   - Dynamically rewriting `pa-engineer.md`'s system prompt or `tools:`/`skills:` list before every single Work Order would bust the LLM's KV prompt-cache prefix across consecutive Work Orders running on the same model tier (`flash`).
   - **Decision:** Keep the `agents/*.md` system prompt and repo-scoped skill/rule manifests **100% static across all Work Orders in the repository** (maximizing KV cache read hits across turns and across sequential WOs), and perform per-Work-Order `required_skills` activation inside the `PreInvocation` `userMessage` (which sits *after* the cached system prefix).
4. **Criterion 4 — Tool & MCP Blast Radius per Role:**
   - Strip non-engineering distractors (`search_web`, `search_marketplace`, `ask_question`, `invoke_subagent`) from `pa-engineer.md`, and set `inheritMcp: false` (plus zero write tools) on `pa-auditor.md` so the Auditor has a minimal, strictly read-only prompt prefix.

```yaml
# Subagent frontmatter pattern (pa-engineer.md / pa-auditor.md):
model: inherit
inheritCustomizations: false    # Strips ~11k-13.8k tokens of unrelated global ~/.gemini/config/ skills & rules
skills:
  - .agents/plugins/principal-architect-workspace/.state/pa-skills.json       # Mounts <repo>/.agents/skills + extra_skills (e.g. pio)
rules:
  - .agents/plugins/principal-architect-workspace/.state/pa-worker-rules.json # Mounts <repo>/.agents/rules minus 01-plan-before-execute.md
inheritMcp: true                # true for pa-engineer/architects/debugger (hardware/test MCPs); false for pa-auditor
excludeDefaultComponents: false
```

**Per-Agent Tool Allowlists, Customization Scopes, & Hook Constraints:**

| Agent File | `mainAgent` / `subagent` | `tools:` Frontmatter Allowlist & Customization Scope | Mechanical Hook Constraints (`pre_tool_gate.py` & `stop_gate.py`) |
|---|---|---|---|
| `pa-chief-architect.md` | `mainAgent: true`<br>`subagent: true` | • **Tools:** `view_file`, `read_file`, `write_to_file`, `write_file`, `replace_file_content`, `edit_file`, `list_dir`, `grep_search`, `find_by_name`, `run_command`, `invoke_subagent`, `ask_question`, `send_message`<br>• **Customizations:** Repo `.state/pa-skills.json` + `<repo>/.agents/rules`, `inheritMcp: true` | • **Write scope:** `.agents/plugins/principal-architect-workspace/programme-*/**`, **Part I (`PR Charter`) of `pr-*/PROJECT.md`**, and `memory/**` (when `memory_mode == "builtin"`).<br>• **Blocked:** Editing application source files, Part II of `PROJECT.md`, or `WORKORDER.md` files. |
| `pa-principal-architect.md` | `mainAgent: true`<br>`subagent: true` | Same as `pa-chief-architect` | • **Write scope:** **Part II (`Implementation Plan & Work Order Breakdown`) and Part III (`Outcome & Graduation Summary`) of `pr-*/PROJECT.md`**, **Part I (`Specification`) of `pr-*/wo*/WORKORDER.md`**, and `memory/**` (when `memory_mode == "builtin"`).<br>• **Blocked:** Mutating **Part I (`PR Charter`) of `PROJECT.md`** when `programme_id` is set or after plan approval (must run `pa escalate --to-chief`).<br>• **Blocked:** Editing application source/test files inline (must dispatch `pa-engineer`).<br>• **Blocked:** Calling `invoke_subagent(TypeName: "pa-engineer")` before `PROJECT.md` status is `APPROVED`, or running `pa pr graduate` before `AuditReport.verdict == "APPROVED"` for `HEAD`. |
| `pa-engineer.md` | `mainAgent: false`<br>`subagent: true` | • **Tools:** `view_file`, `read_file`, `write_to_file`, `write_file`, `replace_file_content`, `edit_file`, `list_dir`, `grep_search`, `find_by_name`, `run_command`, `send_message` *(Omits `invoke_subagent`, `ask_question`, `search_web`, `search_marketplace`!)*<br>• **Customizations:** `inheritCustomizations: false` + `.state/pa-skills.json` + `.state/pa-worker-rules.json` (excludes `01-plan-before-execute.md`), `inheritMcp: true` | • **Write scope:** Strictly restricted to `allowed_files` of the bound `WORKORDER.md` plus **Part II (`Completion Report`) of that `WORKORDER.md`**.<br>• **Blocked:** Mutating Part I (`Specification & Boundary Box`) of `WORKORDER.md`.<br>• **Shell scope:** Blocked from `git push`, `git checkout`, `git switch`, `git branch`, `git rebase`, `git merge`, `gh pr *`, `gh issue *`.<br>• **Stop gate:** Cannot stop with `COMPLETED` unless a valid verification receipt exists for the current working-tree hash and `Completion Report` is valid. |
| `pa-auditor.md` | `mainAgent: true`<br>`subagent: true` | • **Tools:** `view_file`, `read_file`, `list_dir`, `grep_search`, `find_by_name`, `run_command`, `send_message` *(Omits all file-write tools and `invoke_subagent`!)*<br>• **Customizations:** `inheritCustomizations: false` + `.state/pa-skills.json` + `.state/pa-worker-rules.json`, **`inheritMcp: false`** | • **Write scope:** Zero direct file writes.<br>• **Shell scope:** Read-only inspection (`git diff`, `git log`, `gh pr diff`, `gh pr view`), test execution, and `pa pr post-audit`.<br>• **Stop gate:** Cannot stop until `pa pr post-audit` has recorded a valid `AuditReport`. |
| `pa-debugger.md` | `mainAgent: true`<br>`subagent: true` | • **Tools:** `view_file`, `read_file`, `write_to_file`, `write_file`, `replace_file_content`, `edit_file`, `list_dir`, `grep_search`, `find_by_name`, `run_command`, `ask_question`, `send_message`<br>• **Customizations:** Repo `.state/pa-skills.json` + `.state/pa-worker-rules.json`, `inheritMcp: true` | • **Write scope:** Active PR files + `WORKORDER.md` debug resolution section.<br>• On `pa wo resolve <WO-ID>`, stamps verification receipt and sends root-cause summary back to the PR PA conversation. |

### 5.3 Dynamic Model & Token Efficiency Routing (`scripts/models.py`)

1. **Subagent Dispatch (`invoke_subagent`) — Right-Sizing Execution Models:**
   - `complexity: mechanical` (boilerplate, renames, mechanical refactors, simple wiring with explicit line targets) $\to$ `invoke_subagent(TypeName: "pa-engineer", Model: "flash_lite", ...)`
   - `complexity: standard` (bounded module logic, unit/integration test implementation, standard bug fixes) $\to$ `invoke_subagent(TypeName: "pa-engineer", Model: "flash", ...)`
   - `complexity: architect` (intricate concurrency, subtle memory/pointer ownership, cross-layer state machines) $\to$ `invoke_subagent(TypeName: "pa-engineer", Model: "inherit", ...)` *(Never `"pro"` when parent is on Argon/Opus, preventing tier downgrade!)*
   - Cold-Firewall Audit $\to$ `invoke_subagent(TypeName: "pa-auditor", Model: "inherit", ...)`
   - **Auto-Upgrade on Retry:** If a `flash_lite` or `flash` Worker fails verification twice on a Work Order (`attempt_count >= 2` of `max_attempts: 5`), the Principal Architect can automatically upgrade attempts 3–5 to the next model tier (`flash_lite` $\to$ `flash` $\to$ `inherit`) before escalating to `pa-debugger`.
2. **Top-Level Conversation Creation (`pa pr start`, `pa programme start`, `pa wo debug`):**
   - Queries the local Antigravity Language Server (`ANTIGRAVITY_LS_ADDRESS` with `ANTIGRAVITY_CSRF_TOKEN`) or CLI model catalog (`agy models`) and starts the conversation using the configured `architect_model` (defaulting to **Gemini 4 Argon (High)** `gemini-4-argon-high` when available in the user's catalog, with fallback/selection for **Gemini 3.1 Pro (High)** `gemini-3.1-pro-high` or **Claude Opus 5.5 (High)** `claude-opus-5-5-high`).

---

## 6. Canonical Split-Authority Document Schemas & Pydantic v2 Contracts (`scripts/schemas.py`)

Every Markdown file in `.agents/plugins/principal-architect-workspace/` begins with a YAML frontmatter block delimited by `---` and validated by Pydantic v2 (`extra="forbid"`).

### 6.1 `PROGRAM.md` Schema (`ProgramSpec`)

Located at `.agents/plugins/principal-architect-workspace/programme-<slug>/PROGRAM.md` (Authored by Tier 1 Chief Architect):

```python
class PRNodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    slug: str = Field(..., pattern=r"^pr-\d+[a-z]?-[a-z0-9-]+$")
    title: str = Field(..., min_length=5, max_length=140)
    branch: str
    base_branch: str = "main"
    depends_on: list[str] = Field(default_factory=list)
    allowed_modules: list[str] = Field(..., min_length=1)
    required_skills: list[str] = Field(default_factory=list)
    status: PRState = PRState.PLANNED
    github_pr: int | None = None

class ProgramSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    programme_id: str = Field(..., pattern=r"^prog-[a-z0-9-]+$")
    title: str
    base_branch: str = "main"
    status: Literal["DRAFT", "APPROVED", "ACTIVE", "COMPLETED"] = "DRAFT"
    prs: list[PRNodeSpec] = Field(default_factory=list)
```

**Required Markdown Sections in `PROGRAM.md`:**
- `# <Title>`
- `## 1. Architectural Vision & System Invariants`
- `## 2. Cross-PR Contracts & Interfaces`
- `## 3. Programme Session Log` *(Succinct 1-line PR graduation entries when `memory_mode == "external"`; rich progressive synthesis when `memory_mode == "builtin"`)*

### 6.2 `PROJECT.md` Split-Authority Schema (`ProjectSpec`)

Located at `.agents/plugins/principal-architect-workspace/pr-<slug>/PROJECT.md`. To enforce fractal top-down governance, `PROJECT.md` is divided into **Part I (`PR Charter` — authored by Chief Architect, immutable to PA)**, **Part II (`Implementation Plan & Work Order Breakdown` — authored by PA)**, and **Part III (`Outcome & Graduation Summary` — authored by PA at graduation)**:

```python
class PRCharterSpec(BaseModel):
    """Part I of PROJECT.md: Authored by Tier 1 Chief Architect (or locked at Step 2 in standalone PRs).
    PreToolUse blocks Tier 2 PA from mutating this block or Markdown Sections 1-2 once locked."""
    model_config = ConfigDict(extra="forbid")
    pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    programme_id: str | None = None
    slug: str
    title: str
    branch: str
    base_branch: str = "main"
    depends_on: list[str] = Field(default_factory=list)
    allowed_modules: list[str] = Field(..., min_length=1, description="Subsystem/module boundaries this PR is authorized to touch")
    required_skills: list[str] = Field(default_factory=list, description="Skills/tools mandated for this PR (e.g. ['pio', 'framework-expert'])")
    verification_floor: list[str] = Field(default_factory=list, description="Minimum test/build commands that must pass before PR graduation")
    charter_locked: bool = True
    charter_hash: str | None = Field(default=None, description="SHA-256 of Charter YAML + Sections 1-2 to detect unauthorized PA edits")

class WOSummaryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^WO-\d+[a-z]?\.\d+$")
    slug: str
    title: str
    complexity: ComplexityTier
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    attempts: int = 0
    commit_sha: str | None = None

class ProjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    charter: PRCharterSpec
    status: PRState = PRState.PLANNED
    approved_at: datetime | None = None
    github_pr: int | None = None
    work_orders: list[WOSummaryRow] = Field(default_factory=list)
```

**Split-Authority Markdown Sections in `PROJECT.md`:**
- **Part I — PR Charter *(Authored by Tier 1 Chief Architect; Locked to Tier 2 PA via `charter_hash`)*:**
  - `## 1. PR Charter: Scope, Goals, & Non-Goals`
  - `## 2. Architectural Requirements, Cross-PR Interfaces, & Required Skills/Tools`
- **Part II — Implementation Plan *(Authored by Tier 2 Principal Architect; Locked once `status == APPROVED`)*:**
  - `## 3. Implementation Plan & Work Order Breakdown`
- **Part III — Outcome & Graduation Summary *(Authored by Tier 2 Principal Architect)*:**
  - `## 4. Outcome & Session Log` *(Succinct mechanical status/escalation record when `memory_mode == "external"`; full architectural distillation when `memory_mode == "builtin"`)*

### 6.3 `WORKORDER.md` Split-Authority Schema (`WorkOrderSpec` & `CompletionReport`)

Located at `.agents/plugins/principal-architect-workspace/pr-<slug>/wo<M>-<slug>/WORKORDER.md`. Divided into **Part I (`Specification & Boundary Box` — authored by Tier 2 PA, immutable to Worker)** and **Part II (`Completion Report` — authored by Tier 3 Worker)**:

```python
class CompletionReport(BaseModel):
    """Part II of WORKORDER.md: Authored by Tier 3 Worker (`pa-engineer`).
    When memory_mode == 'external', narrative fields (decisions_made, dead_ends) are optional
    and kept empty/1-line so tokens are not wasted duplicating repo-memory."""
    model_config = ConfigDict(extra="forbid")
    status: WorkOrderStatus
    attempt_num: int = Field(default=1, ge=1, le=5)
    receipt_id: str | None = None
    commit_sha: str | None = None
    files_modified: list[str] = Field(default_factory=list)
    verification_summary: str = Field(..., max_length=280, description="Succinct 1-line test/build outcome")
    out_of_scope_findings: list[str] = Field(default_factory=list)
    escalation_request: EscalationRequest | None = None
    # Populated ONLY when memory_mode == "builtin" (or when escalating a blocker):
    decisions_made: list[str] = Field(default_factory=list)
    dead_ends: list[str] = Field(default_factory=list)

class WorkOrderSpec(BaseModel):
    """Part I of WORKORDER.md: Authored by Tier 2 PA; locked to Tier 3 Worker via spec_hash."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    wo_id: str = Field(..., pattern=r"^WO-\d+[a-z]?\.\d+$")
    pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    title: str = Field(..., min_length=5, max_length=140)
    complexity: ComplexityTier
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    allowed_files: list[str] = Field(..., min_length=1, description="Repo-relative file paths or globs Worker may create/modify")
    forbidden_files: list[str] = Field(default_factory=list, description="Explicitly protected paths")
    required_skills: list[str] = Field(default_factory=list, description="Domain skills (e.g. ['pio', 'framework-expert']) highlighted on Turn 1")
    verification_command: str = Field(..., min_length=2, description="Shell command that must exit 0 after the final file edit")
    max_attempts: int = Field(default=5, ge=1, le=5, description="Max productive verification attempts before escalating to pa-debugger")
    max_structural_failures: int = Field(default=2, ge=1, le=3, description="Fast-fail escalation threshold for structural/hook blockers")
    spec_hash: str | None = Field(default=None, description="SHA-256 of Part I Spec to prevent Worker from editing its own contract")
    completion: CompletionReport | None = None
```

### 6.4 `AUDIT.md` Schema (`AuditReport`)

Recorded locally in `.agents/plugins/principal-architect-workspace/pr-<slug>/AUDIT-round-<K>.md` (and `.state/state.db`), and posted to the GitHub PR via `gh pr review <N> --comment` when `vcs_mode == "github"`:

```python
class AuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^(BLOCKING|NON-BLOCKING)-\d+$")
    axis: Literal["spec_alignment", "invariants", "edge_cases", "test_quality", "scope_hygiene"]
    file_path: str
    line_range: str | None = None
    summary: str
    remediation: str

class AuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    pr_id: str
    github_pr: int | None = Field(default=None, description="None when operating in local_git mode without a GitHub remote")
    audit_round: int = Field(..., ge=1, le=5)
    head_sha: str = Field(..., min_length=7, max_length=40)
    auditor_harness: str = "antigravity"
    verdict: Literal["APPROVED", "CHANGES_REQUESTED"]
    findings: list[AuditFinding] = Field(default_factory=list)
```

### 6.5 Local SQLite Database Schema (`<repo>/.agents/plugins/principal-architect-workspace/.state/state.db`)

`state.db` uses WAL mode (`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`) and contains 5 tables:
1. **`repo_config`**: `key TEXT PRIMARY KEY, value TEXT` (`execution_mode` = `"monitored" | "autonomous"`, `memory_mode` = `"external" | "builtin"`, `vcs_mode` = `"github" | "local_git"`, `extra_skills_json`, `exclude_rules_json`, `architect_model`, `last_vcs_sync_at`).
2. **`sessions`**: `conversation_id TEXT PRIMARY KEY, role TEXT, programme_id TEXT, pr_id TEXT, wo_id TEXT, attempt_num INTEGER, structural_failures INTEGER, pinned INTEGER, last_checkpoint_step INTEGER, created_at TEXT, updated_at TEXT`.
3. **`verification_receipts`**: `receipt_id TEXT PRIMARY KEY, wo_id TEXT, pr_id TEXT, cmd TEXT, exit_code INTEGER, tree_hash TEXT, git_head_sha TEXT, valid INTEGER, created_at TEXT`.
4. **`escalations`**: `escalation_id TEXT PRIMARY KEY, level TEXT, source_role TEXT, target_role TEXT, pr_id TEXT, wo_id TEXT, blocker_type TEXT, reason_code TEXT, requested_files_json TEXT, summary TEXT, status TEXT, github_issue_or_comment_url TEXT, created_at TEXT, resolved_at TEXT`.
5. **`attention_queue`**: `item_id TEXT PRIMARY KEY, priority INTEGER, kind TEXT, pr_id TEXT, wo_id TEXT, title TEXT, action_payload_json TEXT, status TEXT, created_at TEXT`.

---

## 7. Deterministic Hook Engine & Dual-Mode Escalation

The workspace plugin's `hooks.json` registers four fast Python hook entrypoints (`timeout: 10`) in `daemon/workspace-plugin/principal-architect/scripts/`. Every hook first runs `common.is_repo_enrolled(workspace_paths)` against `daemon/state/registry.json` and exits `0` in $<1\text{ms}$ if the workspace is not enrolled.

### 7.1 `PreInvocation` (`scripts/pre_invocation.py`)

Fires before each LLM invocation:
1. **Session & Subagent Role Binding:**
   - Checks `sessions` in `.state/state.db` for `conversationId`.
   - If unbound (e.g., on `invocationNum == 1` of a newly spawned `pa-engineer` or `pa-auditor` subagent after `message_delivery` has delivered the parent prompt), parses the deterministic `PA_ROLE:` / `WO_ID:` / `PR_ID:` header from the initial prompt in `transcriptPath` and binds `(conversationId, role, pr_id, wo_id)` in `sessions`.
2. **Compaction & Rewind Detection:**
   - Scans `transcript.jsonl` for the latest `"type": "CHECKPOINT"` step index and total step count. If a new `CHECKPOINT` occurred since `last_checkpoint_step` (or if step count rewound), re-arms state injection.
3. **Role-Specific Persistent `userMessage` Injection:**
   - **For `pa-chief-architect` & `pa-principal-architect`:**
     - Injects the active `PROGRAM.md` / `PROJECT.md` Part I Charter status and any open escalations for that tier.
     - **Memory Boundary Check:** If `memory_mode == "builtin"`, also injects `memory/MEMORY.md` **plus the matching domain sections of `memory/MODULE_INDEX.md`** for `allowed_modules`. If `memory_mode == "external"`, omits `memory/` injection completely (deferring to `repo-memory-plugin`'s own hook) and instructs the Architect to use **Succinct Write-Back Mode**.
   - **For `pa-engineer`:** Injects the bound `WORKORDER.md` Part I contract (`allowed_files`, `forbidden_files`, `verification_command`, `attempt_num` of `5`), **explicit links/paths to the `SKILL.md` files listed in `required_skills`**, and whether `Completion Report` write-backs should use **Succinct Mode** (`memory_mode == "external"`) or **Full Distillation Mode** (`memory_mode == "builtin"`).

### 7.2 `PreToolUse` (`scripts/pre_tool_gate.py`)

Intercepts mutating file tools (`write_to_file`, `write_file`, `replace_file_content`, `edit_file`, `multi_replace_file_content`) and `run_command`:

| Rule | Condition Checked | Response in `Monitored Mode` | Response in `Autonomous Mode` |
|---|---|---|---|
| **R1: Architect No-Inline-Code Gate** | `role in ("chief", "pa")` and target file path is outside `.agents/plugins/principal-architect-workspace/` (or shell command mutates source files). | Returns `permissionDecision: "ask"` (*"Architect is attempting to edit `<path>` directly instead of dispatching `pa-engineer`. Allow one-off edit?"*). | Returns `permissionDecision: "deny"` (*"Autonomous Mode: Architects cannot edit source files inline. Issue/amend a `WORKORDER.md` and invoke `pa-engineer`."*). |
| **R1b: Fractal `PROJECT.md` Charter Lock** | `role == "pa"` edits `PROJECT.md` and alters `charter` frontmatter or Markdown Sections 1–2 (`PR Charter`) when `charter.charter_locked == true` (or edits files outside `charter.allowed_modules`). | Returns `permissionDecision: "ask"` (*"Principal Architect is modifying the Chief Architect's locked PR Charter (`<PR-ID>`). Allow Charter amendment?"*). | Returns `permissionDecision: "deny"`, logs a `CHARTER_AMENDMENT_NEEDED` escalation (`PA` $\to$ `Chief`), and instructs the PA: *"Part I (`PR Charter`) of `PROJECT.md` is owned by the Chief Architect. Run `pa escalate --to-chief` to request a scope or interface change."* |
| **R2: Plan Approval Gate** | `role == "pa"` calls `invoke_subagent(TypeName: "pa-engineer")` when `PROJECT.md` `status == "PLANNED"` (not yet `APPROVED`). | Returns `permissionDecision: "ask"` (*"Approve `PROJECT.md` Part II Work Order decomposition for `<PR-ID>` and start Worker execution?"*). If approved, marks `PROJECT.md` `APPROVED`. | If `auto_approve_pr_plans: false` (default), adds to **🔔 Human Attention Needed** queue and denies; if `auto_approve_pr_plans: true`, allows if `PROJECT.md` Part II and all `WORKORDER.md` files pass Pydantic validation and stay within `charter.allowed_modules`. |
| **R3: Worker Strict Boundary Box & Spec Lock Gate** | `role == "engineer"` attempts to write/edit a file not matching `WORKORDER.md` `allowed_files` (or matching `forbidden_files`), or attempts to mutate Part I (`Specification`) of its bound `WORKORDER.md`. | Returns `permissionDecision: "ask"` (*"Worker `<WO-ID>` wants to edit `<path>` outside `allowed_files`. Approve and add `<path>` to `allowed_files`?"*). | Returns `permissionDecision: "deny"`, increments `structural_failures` in `sessions`, logs a `BOUNDARY_EXPANSION_NEEDED` record in `escalations`, and instructs the Worker: *"File `<path>` is outside your `allowed_files`. Record an `escalation_request` in Part II (`Completion Report`) of `WORKORDER.md` with `status: ESCALATED_TO_PA` and finish your turn."* |
| **R4: Worker Git/GitHub Lockdown** | `role == "engineer"` runs `git push`, `git checkout`, `git switch`, `git branch`, `git rebase`, `git reset --hard`, `gh pr *`, or `gh issue *`. | Hard `permissionDecision: "deny"`. | Hard `permissionDecision: "deny"` (increments `structural_failures`). |
| **R5: Auditor Read-Only Lockdown** | `role == "auditor"` attempts any file mutation or mutating git/shell command (other than `pa pr post-audit` / test suites). | Hard `permissionDecision: "deny"`. | Hard `permissionDecision: "deny"`. |
| **R6: Graduation Audit Gate** | `pa pr graduate <PR-ID>` or `gh pr merge` invoked when no `AuditReport` with `verdict == "APPROVED"` and `head_sha == current_head_sha` exists in `.state/state.db` / `AUDIT-round-*.md` / GitHub PR reviews. | Returns `permissionDecision: "ask"` (warns user that Cold-Firewall Audit has not approved current `HEAD`). | Hard `permissionDecision: "deny"` (*"Cannot graduate `<PR-ID>`: current `HEAD` (`<sha>`) lacks an `APPROVED` Cold-Firewall Audit verdict."*). |

### 7.3 `PostToolUse` (`scripts/post_tool_receipt.py`)

1. **Receipt Invalidation on Edit:** Whenever `pa-engineer` executes a file-writing tool or mutating shell command, marks any existing `verification_receipts` for `wo_id` as `valid = 0`.
2. **Verification Receipt Stamping & Attempt Tracking:** When `pa-engineer` runs `run_command` containing the `verification_command` declared in `WORKORDER.md`:
   - If `error == ""` (exit code `0`): computes `tree_hash` (SHA-256 over the contents of all `allowed_files` in the working tree) and inserts a valid receipt (`receipt_id = "rcpt_<short_sha>"`, `valid = 1`, `tree_hash`) into `verification_receipts` in `.state/state.db`.
   - If non-zero exit code: increments `attempt_num` in `sessions` (up to `max_attempts: 5`). If the output matches a known structural blocker signature (e.g., `Hardware is currently tied` MCP lock contention or missing host toolchain), increments `structural_failures` (`max_structural_failures: 2`).

### 7.4 `Stop` (`scripts/stop_gate.py`)

Fires when `terminationReason == "NO_TOOL_CALL"`:
1. **Two-Tier Retry & Fast-Fail Blocker Check (for `pa-engineer`):**
   - Inspects `transcript.jsonl` and `sessions`:
     - **Fast-Fail Structural Escalation (`structural_failures >= 2` or `>= 3` consecutive `ERROR_MESSAGE` steps):** Allows the Worker to stop immediately and marks the Work Order `ESCALATED_TO_PA` (`blocker_type: "structural"`) so the Principal Architect or `pa-debugger` can intervene without burning the remaining verification attempts.
     - **Productive Attempt Ceiling (`attempt_num >= max_attempts` [5]):** Allows the Worker to stop with `status: BLOCKED` and automatically enqueues a `pa-debugger` escalation (`🔬 [Debug <WO-ID>]`).
2. **Normal Completion Check (when `attempt_num < 5` and `structural_failures < 2`):**
   - **Case A (`status == "ESCALATED_TO_PA"` or `"BLOCKED"`):** Verifies that `completion.escalation_request` or `completion.verification_summary` explains the blocker, updates `escalations` in `.state/state.db`, and allows termination (`{}`) so control returns cleanly to `pa-principal-architect`.
   - **Case B (`status == "COMPLETED"` or still `"IN_PROGRESS"`):** Checks three mandatory completion invariants:
     1. A valid receipt (`valid == 1`) exists in `verification_receipts` for `wo_id` whose `tree_hash` matches the current working-tree files in `allowed_files`.
     2. All modified files in `allowed_files` and `WORKORDER.md` are committed to the branch (`git status --porcelain -- <allowed_files>` is clean) with a commit message starting with `<WO-ID>:`.
     3. `WORKORDER.md` has a valid Part II `completion` block (`status: COMPLETED`, `receipt_id`, `commit_sha`, `files_modified`, `verification_summary`) and its Part I `spec_hash` is unchanged.
   - If any check fails, returns:
     ```json
     {
       "decision": "continue",
       "reason": "Work Order WO-14.2 (attempt 2/5) cannot complete yet: [missing verification receipt / uncommitted files / incomplete Completion Report]. Run `pa wo verify WO-14.2` to verify, stamp the receipt, and commit."
     }
     ```
3. **For `pa-auditor`:**
   - Verifies that `pa pr post-audit` has recorded an `AuditReport` for the current `head_sha` (in `.state/state.db` and `AUDIT-round-<K>.md`, plus GitHub PR review when `vcs_mode == "github"`). If not, returns `{"decision": "continue", "reason": "Publish your audit findings via `pa pr post-audit <PR-ID> --file <path>` before finishing."}`.

---

## 8. `pa` CLI Reference & Local-Git / GitHub Multi-Machine Bus

The `pa` CLI (`daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`, symlinked to `~/.local/bin/pa` on install) operates seamlessly in both **`vcs_mode: "local_git"`** (local Git repository only, zero GitHub dependency) and **`vcs_mode: "github"`** (synchronized with `origin` and `gh` CLI):

| Command | Description & Deterministic Behavior (`local_git` Floor + `github` Upgrade) |
|---|---|
| `pa enroll [path]` | Enrolls repository (initializing `git init` if needed), migrates legacy `.agents/skills/principal-architect-workspace` to `.agents/plugins/principal-architect-workspace` if present, auto-detects `memory_mode` (`external` if `repo-memory` is enrolled, else `builtin`) and `vcs_mode` (`github` if `origin` + `gh` exist, else `local_git`), generates `.state/pa-skills.json` and `.state/pa-worker-rules.json` (respecting `--extra-skill` and `--exclude-rule`), configures `.agents/plugins.json`, and registers repo in `daemon/state/registry.json`. |
| `pa unenroll [path]` | Removes workspace plugin entry and unregisters repo from `daemon/state/registry.json`. |
| `pa status [--json]` | Reconciles committed specs, local git trailers (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`), optional GitHub PR status, and `.state/state.db`; prints the Programme $\to$ PR $\to$ WO DAG and any items in the **🔔 Human Attention Needed** queue. |
| `pa sync` | In `local_git` mode, scans local branch commit trailers and `AUDIT-round-*.md` files to rebuild `.state/state.db`. In `github` mode, also fetches remote branches, GitHub PR states, and `<!-- pa:audit -->` / `<!-- pa:escalation -->` PR comments to synchronize across machines and harnesses. |
| `pa mode [monitored\|autonomous]` | Gets or sets `execution_mode` for the repository. |
| `pa programme init <slug> --title "..."` | Scaffolds `.agents/plugins/principal-architect-workspace/programme-<slug>/PROGRAM.md` and binds the Tier 1 Chief Architect conversation. |
| `pa programme charter <PR-ID>` | **Chief Architect Action:** Authors or updates **Part I (`PR Charter`)** of `pr-<slug>/PROJECT.md`, computes `charter_hash`, and locks Part I (`charter_locked: true`) before the Tier 2 PA is spawned. In `github` mode, optionally pushes the branch and opens a Draft PR. |
| `pa pr start <PR-ID>` | Creates/checks out stacked branch `<branch>` from `<base_branch>`, verifies `PROJECT.md` Part I Charter is present (or scaffolds it for standalone single-PR tasks), spawns/activates the dedicated Tier 2 PA conversation (`📐 [<PR-ID>] <Title>`), and JIT auto-pins it in the IDE sidebar. |
| `pa pr claim <PR-ID>` | **Multi-Machine / Multi-Harness Pickup:** Fetches the PR branch (if remote exists), reconstructs WO completion state from committed `WORKORDER.md` files and `PA-Verified-Hash` git trailers into local `.state/state.db`, and outputs/injects the Tier 2 PA continuation prompt. |
| `pa pr approve-plan <PR-ID>` | Validates `PROJECT.md` Part II (`Implementation Plan & Work Order Breakdown`) and all `wo*/WORKORDER.md` Part I specs against `ProjectSpec` and `WorkOrderSpec` Pydantic schemas (verifying `charter_hash` integrity and that all WO `allowed_files` fall within `charter.allowed_modules`); sets `PROJECT.md` `status: APPROVED` and stamps `spec_hash` on each `WORKORDER.md`. |
| `pa wo verify <WO-ID>` | 1. Checks `git status --porcelain` to verify zero modified/untracked files outside `allowed_files` and verifies `WORKORDER.md` Part I `spec_hash` is unmodified.<br>2. Executes `verification_command` from `WORKORDER.md`.<br>3. Stamps cryptographic `receipt_id` and `tree_hash` into `.state/state.db` and `WORKORDER.md` Part II.<br>4. Commits `allowed_files` and `WORKORDER.md` with message `<WO-ID>: <title>` and trailers `PA-WorkOrder: <WO-ID>` and `PA-Verified-Hash: <tree_hash>`. |
| `pa wo debug <WO-ID>` | Escalates a blocked Work Order (after 5 verification failures, 2 structural blockers, or `complexity: interactive`) to a top-level `pa-debugger` conversation (`🔬 [Debug <WO-ID>]`), pre-seeded with the failure log and diff, and auto-pins it in the sidebar. |
| `pa wo resolve <WO-ID> --summary "..."` | Verifies the fix, records the resolution in `WORKORDER.md`, unpins the debug conversation, and wakes the owning PR PA conversation. |
| `pa pr open-or-sync <PR-ID>` | **Step 6A Entry:** Transitions status to `STAGED_FOR_AUDIT`. In `local_git` mode, verifies the local branch `<branch>` is clean against `<base_branch>`. In `github` mode, pushes `<branch>` to `origin`, creates or updates the GitHub PR (`gh pr create --base <base_branch> --head <branch>`), and renders the WO status table into the PR body. |
| `pa pr post-audit <PR-ID> --file <audit.md>` | **Step 6A Auditor Action:** Validates `<audit.md>` against `AuditReport` Pydantic schema (up to `max_audit_rounds: 5`), writes `.agents/plugins/principal-architect-workspace/pr-<slug>/AUDIT-round-<K>.md`, commits it with trailer `PA-Audit-Verdict: <verdict> (<head_sha>)`, and records it in `.state/state.db`. When `vcs_mode == "github"`, also posts to the GitHub PR via **`gh pr review <N> --comment --body-file ...`**. |
| `pa pr sync-audit <PR-ID>` | Syncs the latest audit report from `AUDIT-round-<K>.md` or GitHub PR `<N>` (`<!-- pa:audit ... -->`), validates it via Pydantic, and updates `.state/state.db`. |
| `pa pr graduate <PR-ID>` | **Step 6B Gate:** Verifies an `APPROVED` `AuditReport` exists for current code `HEAD` and all `charter.verification_floor` commands pass. Then:<br>1. **If `memory_mode == "external"`:** Leaves memory management entirely to `repo-memory-plugin` and writes only a succinct mechanical graduation summary to `PROJECT.md` Part III.<br>2. **If `memory_mode == "builtin"`:** Deterministically updates `memory/MEMORY.md`, rolls $>5$ completed PRs to `memory/PROJECT_INDEX.md`, and appends rows under `allowed_modules` in `memory/MODULE_INDEX.md`.<br>3. Commits graduation updates, marks `PR-ID` `GRADUATED`, unpins the PR PA conversation, and notifies the Chief Architect conversation (triggering JIT Charter verification for the next dependent PR in `PROGRAM.md`). |
| `pa pr restack` | Rebases downstream stacked PR branches (`git rebase --update-refs`) when an upstream PR is amended or merged, and (in `github` mode) updates GitHub PR base branches (`gh pr edit <N> --base main`) after parent PR merge. |
| `pa escalate` / `pa issue create` | Records an upward hierarchical escalation (`Worker` $\to$ `PA` $\to$ `Chief` $\to$ `Human Attention Queue`). For deferred out-of-scope findings, files a labeled GitHub Issue (`gh issue create --label pa:deferred`) in `github` mode, or appends to `.agents/plugins/principal-architect-workspace/DEFERRED_BACKLOG.md` in `local_git` mode. |

---

## 9. Memory Architecture: Strict Boundary Between `external` (`repo-memory`) and `builtin` Fallback

To avoid duplicating work or burning output tokens when an external memory plugin is installed, `principal-architect-plugin` enforces a strict two-mode boundary controlled by `memory_mode` in `.state/state.db`:

### 9.1 Mode A: External Memory Plugin Active (`memory_mode: "external"`)

Automatically selected during `pa enroll` (or `pa sync`) whenever `repo-memory-plugin` is enrolled on the repository:
1. **Zero Memory Overlap:** `principal-architect-plugin` **does not create, update, read, or inject** `.agents/plugins/principal-architect-workspace/memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}`. All codebase memory indexing, turn-note harvesting, and file/symbol dossier injection are handled exclusively by `repo-memory-plugin`.
2. **Token-Succinct Write-Backs (`Succinct Mode`):**
   - Because `repo-memory-plugin`'s `Stop` hook automatically harvests engineering notes at the end of agent turns, `principal-architect-plugin` instructs Workers and Architects via `pre_invocation.py` to keep `WORKORDER.md` Part II (`Completion Report`) and `PROJECT.md` Part III (`Outcome & Session Log`) **strictly mechanical and succinct**:
     - `WORKORDER.md` `Completion Report` records only: `status`, `attempt_num`, `receipt_id`, `commit_sha`, `files_modified`, a 1-line `verification_summary` ($\le 280$ chars), and (only if needed) `out_of_scope_findings` or `escalation_request`. Narrative `decisions_made` and `dead_ends` lists are omitted unless the Worker is escalating a blocker.
     - `PROJECT.md` `Outcome & Session Log` records only the compact Work Order table (`WO-ID`, `status`, `attempts`, `commit_sha`), Audit round verdicts, and cross-PR interface notes needed by the Chief Architect.

### 9.2 Mode B: Built-in Fallback Memory (`memory_mode: "builtin"`)

Selected when `repo-memory-plugin` is **not** installed or enrolled on the repository:
1. **Warm-Cache Distillation:** Workers populate `decisions_made` and `dead_ends` in `WORKORDER.md` while their prompt cache is warm (~90% cache read discount), and the PA synthesizes architectural decisions into `PROJECT.md` `## 4. Outcome & Session Log`.
2. **The 3-File Progressive-Reveal Index (`memory/`):**
   - **`MEMORY.md` (Recency Boot Registry — $<50$ lines):** Tracks `## Active Programs`, `## Active Projects`, and `## Recently Completed (last 5)`.
   - **`MODULE_INDEX.md` (Subsystem Cross-Reference — $O(1)$ Progressive Reveal):** Organized under codebase domain headings (`## [Domain Category]`), linking each module directly to `[PROJECT.md](../pr-XX/PROJECT.md)`. On Turn 1, `pre_invocation.py` pushes `MEMORY.md` plus the matching `MODULE_INDEX.md` sections for `charter.allowed_modules`.
   - **`PROJECT_INDEX.md` (Chronological Archive):** Receives completed PR entries as they roll off the 5-PR window in `MEMORY.md` during `pa pr graduate`.

---

## 10. AuxPane UI Sidecar Specification ("Principal Architect Cockpit")

### 10.1 Sidecar Registration (`daemon/sidecars/pa_cockpit/sidecar.json`)

```json
{
  "command": "python3",
  "args": [
    "${PLUGIN_ROOT}/workspace-plugin/principal-architect/scripts/cockpit.py"
  ],
  "restart_policy": "always",
  "display_name": "Principal Architect Cockpit",
  "description": "Programme, Stacked PRs, Work Orders & Escalation Queue",
  "has_web_ui": true,
  "ui_config": {
    "display_name": "Principal Architect",
    "views": [
      {
        "path": "/",
        "entrypoint": "SIDECAR_UI_ENTRYPOINT_SIDEBAR",
        "title": "Principal Architect"
      },
      {
        "path": "/",
        "entrypoint": "SIDECAR_UI_ENTRYPOINT_AUX_PANE",
        "title": "Principal Architect Cockpit"
      }
    ]
  },
  "env": {
    "PYTHONPATH": "${PLUGIN_ROOT}/workspace-plugin/principal-architect/scripts"
  }
}
```

### 10.2 Cockpit Backend HTTP & SSE API (`scripts/cockpit.py`)

`scripts/cockpit.py` binds an ephemeral local port (`PORT` injected by `SidecarManager` or `127.0.0.1:0` handshake), serves `sidecars/pa_cockpit/ui/`, and exposes:

- `GET /api/workspaces` — Lists all enrolled repositories from `daemon/state/registry.json` and matches against `window.sidecar.getWorkspaceUris()`.
- `GET /api/state?workspace=<uri>` — Returns the complete reconciled Programme, Stacked PR DAG (`PR Charter` + `Work Orders`), Verification Receipts, Audit Scorecard, environment badges (`vcs_mode`, `memory_mode`), and **🔔 Human Attention Needed** queue for the active workspace.
- `GET /api/events?workspace=<uri>` — Server-Sent Events (SSE) stream pushing real-time updates whenever `.state/state.db` or `.agents/plugins/principal-architect-workspace/` changes.
- `POST /api/mode` — Toggles `execution_mode` between `"monitored"` and `"autonomous"`.
- `POST /api/pr/approve-plan` — Executes `pa pr approve-plan <PR-ID>` and wakes the PR PA conversation via `window.sidecar.agent.sendMessage`.
- `POST /api/escalation/resolve` — Approves or denies a pending boundary expansion (`Worker` $\to$ `PA`) or Charter amendment (`PA` $\to$ `Chief`) from the **🔔 Human Attention Needed** queue.
- `POST /api/pr/start` / `POST /api/wo/debug` / `POST /api/pr/graduate` — Triggers the corresponding `pa` CLI lifecycle transition and returns the target `conversationId` for immediate UI focus via `window.sidecar.ui.toggleConversation(conversationId)`.

### 10.3 Cockpit Frontend Views & Interaction Contract (`sidecars/pa_cockpit/ui/`)

1. **Adaptive Host Theme Styling:** Uses Antigravity host CSS variables (`--background`, `--foreground`, `--card`, `--border`, `--primary`, `--muted-foreground`) and loads `<script src="/preload.js"></script>`.
2. **Automatic Workspace Switching:** Registers `window.sidecar.onWorkspaceChange((uris) => ...)` so switching repository windows in the IDE immediately switches the Cockpit to that repository's Programme DAG.
3. **Zone 1 — Top Header & Controls:**
   - Enrolled repository indicator, active mode pills (`Git: GitHub | Local`, `Memory: repo-memory | Built-in`), and `[🔄 Sync]` button (`pa sync`).
   - Interactive **`[👀 Monitored]` / `[🤖 Autonomous]`** segmented mode toggle.
   - Architect Model selector (`Gemini 4 Argon (High)`, `Gemini 3.1 Pro (High)`, `Claude Opus 5.5 (High)`).
4. **Zone 2 — 🔔 Human Attention Needed Inbox:**
   - Pinned at the top of the panel whenever `attention_queue` is non-empty, sorted by priority:
     - `🟠 [Plan Approval]` PR Part II Work Order decomposition ready (`[✅ Approve Plan]`, `[💬 Open PA]`).
     - `🔴 [Boundary / Charter Escalation]` Worker requested `allowed_files` expansion or PA requested Part I `PR Charter` amendment (`[✅ Approve & Resume]`, `[❌ Deny]`, `[💬 Open Architect]`).
     - `🟣 [Debug Escalation]` Work Order exhausted **5 verification attempts** (`max_attempts: 5`) or hit **2 structural blockers** (`[🔬 Launch Interactive Debug]`).
     - `🟢 [Audit Approved — Ready to Graduate]` PR passed Cold-Firewall Audit on current `HEAD` (`[🚀 Graduate PR]`, `[🔗 View PR / Diff]`).
5. **Zone 3 — Interactive Programme $\to$ Stacked PR $\to$ Work Order DAG:**
   - **PR Cards:** Show PR ID, title, base $\to$ head branch, **status badge** (`📝 Local Branch`, `🚧 Draft PR #N ↗`, `📤 Staged for Audit`, `🔍 Changes Requested (Round K/5)`, `✅ Audit Approved`, `🟣 Graduated`), Charter lock indicator (`🔒 Charter by Chief`), and **`[💬 Jump to PA]`** button (`window.sidecar.ui.toggleConversation(pr.pa_conversation_id)`).
   - **Work Order Rows:** Expand under the active PR card, displaying `WO-ID`, title, `complexity` routing badge (`flash_lite`, `flash`, `inherit`), `required_skills` pills, attempt counter (`Attempt K/5`), live status (`⏳ PENDING`, `⚡ RUNNING`, `✅ COMPLETED [rcpt_xxxx]`, `🔴 ESCALATED`), and action buttons (`[👁️ Peek Worker]` calling `toggleConversation(wo.subagent_id)`, `[🔍 View Diff]`, `[🔬 Debug]`).

---

## 11. Security, Trust Boundaries, & Failure Recovery

1. **Fractal Contract Integrity (`charter_hash` & `spec_hash`):**
   - Subagents and lower-tier Architects never accept unverified chat claims (`"the user/Chief approved this"`). `pre_tool_gate.py` verifies `charter_hash` on `PROJECT.md` Part I (locking the Tier 2 PA to the Chief Architect's Charter) and `spec_hash` on `WORKORDER.md` Part I (locking the Tier 3 Worker to the PA's Work Order specification).
2. **Canonical Path Resolution & Traversal Defense:**
   - `pre_tool_gate.py` resolves all target file paths with `os.path.realpath` relative to the repository root before matching against `allowed_files`, `forbidden_files`, and `charter.allowed_modules`, blocking symlink escapes or `../` traversal outside the boundary box.
3. **Local-Git Floor & GitHub Same-Account Self-Review Handling:**
   - In `local_git` mode, `pa pr post-audit` stores the signed `AuditReport` in committed `pr-<slug>/AUDIT-round-<K>.md` with commit trailer `PA-Audit-Verdict: APPROVED (<head_sha>)`.
   - In `github` mode, because GitHub rejects `gh pr review --approve` and `--request-changes` when the Auditor shares the author's GitHub account, `pa pr post-audit` also posts via `gh pr review <N> --comment` containing the machine-parseable `<!-- pa:audit ... -->` YAML block.
4. **Compaction & Rewind Recovery:**
   - If a long Chief Architect or PR PA session undergoes `CHECKPOINT` context compaction or user `/rewind`, `pre_invocation.py` detects the step delta in `transcript.jsonl` and re-injects the active role contract, `PROJECT.md` Charter, current PR/WO status table, and (only when `memory_mode == "builtin"`) `MEMORY.md` + `MODULE_INDEX.md` slices on the very next turn.

---

## 12. Phased Implementation Plan

The implementation of `principal-architect-plugin` is structured as a 4-PR stacked programme:

| PR | Branch | Scope & Key Deliverables | Verification Command |
|---|---|---|---|
| **PR-01** | `feat/pr-01-core-schemas-and-enrollment` | Self-contained `daemon/` package skeleton, `scripts/schemas.py` (Pydantic v2 Split-Authority models `ProgramSpec`, `ProjectSpec` with `PRCharterSpec`, `WorkOrderSpec`, `AuditReport`), `scripts/state_db.py`, `pa enroll` / `pa unenroll` (auto-detecting `memory_mode` and `vcs_mode`, generating `.state/pa-skills.json` and `.state/pa-worker-rules.json`, plus legacy `.agents/skills/` $\to$ `.agents/plugins/` migration), `pa status`, and templates. | `pytest tests/test_schemas.py tests/test_state_db_and_sync.py` |
| **PR-02** | `feat/pr-02-agents-and-dual-mode-hooks` | Custom agent definitions (`agents/pa-*.md` with `inheritCustomizations: false` + `.state/pa-skills.json` & `.state/pa-worker-rules.json`), `hooks.json`, `scripts/pre_invocation.py`, `scripts/pre_tool_gate.py` (`Monitored` `ask` vs. `Autonomous` escalation, `R1b` Charter lock, `R3` Worker boundary lock), `scripts/post_tool_receipt.py`, `scripts/stop_gate.py` (two-tier retry: `max_attempts: 5` vs. `max_structural_failures: 2`), and `pa wo verify`. | `pytest tests/test_hooks_monitored_vs_autonomous.py` |
| **PR-03** | `feat/pr-03-vcs-bus-models-and-memory-modes` | `scripts/vcs_sync.py` (`local_git` floor + optional `github` sync for `pa programme charter`, `pa pr start/claim/open-or-sync/post-audit/sync-audit/restack`, `pa issue create`), `scripts/models.py` (Argon / 3.1 Pro / Flash complexity routing + auto-upgrade on retry + JIT sidebar auto-pinning), and `scripts/memory_grad.py` (`external` succinct no-op vs. `builtin` 3-file index graduation). | `pytest tests/test_github_and_local_git_bus.py tests/test_memory_modes.py` |
| **PR-04** | `feat/pr-04-cockpit-auxpane-ui` | `sidecars/pa_cockpit/sidecar.json`, `scripts/cockpit.py` (HTTP + SSE server), and `sidecars/pa_cockpit/ui/` (**🔔 Human Attention Needed** inbox, Mode/Model controls, live Git/GitHub PR badges, Charter lock indicators, and `/preload.js` `toggleConversation` integration). | `pytest tests/test_cockpit_api.py` + live AuxPane UI verification |
