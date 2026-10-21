# Positioning Paper: From Prompt-Driven Skill to `principal-architect-plugin`

**Date:** 2026-10-16 (Revision 3)  
**Status:** Architecture & Positioning Proposal  
**Companion Specification:** [`SPEC.md`](../SPEC.md)

---

## Executive Summary

The `principal-architect` skill proved its core orchestration design during the 21-PR dogfooding of `repo-memory-plugin`: introducing a **4-role hierarchy** (Chief Architect $\to$ Principal Architect $\to$ Cold-Firewall PR Auditor $\to$ Execution Worker), enforcing **1 sub-agent per Work Order** (Core Directive 3), and gating graduation behind a **PR-mediated cold-firewall audit** (Step 6A/6B) eliminated mid-PR context compaction and caught 11 architectural defects across PRs #18–#21 before merge.

However, remaining a **pure prompt-driven skill** leaves five structural gaps:
1. **Guardrails and contract boundaries are advisory prose, not mechanical constraints:** Nothing mechanically prevents a Tier 3 Engineer from editing files outside its `WORKORDER.md` Strict Boundary Box or stopping before tests pass, nor prevents a Tier 2 Principal Architect from drifting into inline application code edits or silently altering the PR scope assigned by the Tier 1 Chief Architect.
2. **Untapped model and token efficiency:** Without a deterministic contract engine and complexity router, frontier model tokens (`Gemini 3.1 Pro`, `Claude Opus 4.6`) are burned on repetitive edit-compile-test loops, or output tokens are wasted double-writing narrative memory logs when an external memory system (`repo-memory-plugin`) is already harvesting session trajectories.
3. **No distinction between Monitored (interactive) and Autonomous (unattended) execution:** When a boundary expansion or ambiguity arises, there is no mechanical toggle between asking the human immediately (`Monitored Mode`) vs. reliably escalating up the agent hierarchy (`Tier 3 Worker` $\to$ `Tier 2 PA` $\to$ `Tier 1 Chief` $\to$ `Human Attention Queue` in `Autonomous Mode`).
4. **Lack of formalized Local-Git Floor + Multi-Machine / Multi-Harness GitHub handoffs:** Repositories without a GitHub remote need a 100% functional local Git floor (`vcs_mode: "local_git"`), while projects spanning multiple machines (e.g., planning on a desktop workstation vs. building/testing on a lab machine wired to an ESP32) or multiple agent harnesses (Antigravity, Claude Code, Gemini CLI) need seamless GitHub PR/Review/Issue synchronization (`vcs_mode: "github"`).
5. **Zero IDE visibility or one-click conversation routing:** Across a 15-PR programme, the user has no visual DAG in the Antigravity AuxPane to see which items need human attention, track Git/GitHub PR states (`Local`, `Draft`, `Staged`, `Reviewed`, `Merged`), or activate the right conversation in one click.

> [!IMPORTANT]
> **Core Recommendation:** Evolve `principal-architect` into a **self-contained, Python + Pydantic v2 Split-Daemon Antigravity Plugin (`principal-architect-plugin`)** built around seven pillars:
> 1. **Dynamic Model & Token Efficiency without Starving Relevant Capabilities:** Invest frontier reasoning in the Architect tiers to produce tight, unambiguous contracts, then dynamically route bounded implementation Work Orders to the most cost-effective model tier (`mechanical` $\to$ `flash_lite`, `standard` $\to$ `flash`, `architect` $\to$ `inherit`/frontier)—while preserving full access to relevant domain skills (`pio`, embedded tools) via `inheritCustomizations: true` and `required_skills` highlighting on Turn 1.
> 2. **Fractal Split-Authority Contracts (`PROGRAM.md` $\to$ `PROJECT.md` $\to$ `WORKORDER.md`):** Just as the Tier 2 Principal Architect authors Part I (`Specification & Boundary Box`) of `WORKORDER.md` and instantiates the Tier 3 Worker to implement it and fill in Part II (`Completion Report`), the **Tier 1 Chief Architect authors and locks Part I (`PR Charter`: Scope, Goals, Requirements, Allowed Modules, Required Skills/Tools) of `PROJECT.md`**, and the **Tier 2 Principal Architect authors Part II (`Implementation Plan & Work Order Breakdown`)** before spinning up Workers.
> 3. **Dual-Mode Anti-Drift Hooks (`Monitored` vs. `Autonomous` Mode) & Empirically Calibrated Retries (`max_attempts: 5`):** Mechanically enforce `PROJECT.md` Charter locks, `WORKORDER.md` Strict Boundary Boxes, Architect no-inline-code rules, and cryptographic test verification receipts. Grounded in empirical trajectory data across 38 autonomous PRs in `bug-fixer-loop-plugin` and `esp32-app-foundation`, grant up to **5 productive attempts** (`max_attempts: 5`) before escalating to `pa-debugger`, while fast-failing after **2 structural/hook blockers** (`max_structural_failures: 2`).
> 4. **Self-Contained `scripts/` Packaging, `pa enroll` Lifecycle, & Clean State Scoping:** All operational code (`scripts/` Pydantic models, hook gates, Git/GitHub CLI, and AuxPane server) lives **100% inside the installed plugin package** (`daemon/`). State is cleanly split between **Global Plugin State** in gitignored `daemon/state/registry.json`, **Committed Repo Plugin Workspace** in `<repo>/.agents/plugins/principal-architect-workspace/`, and **Local Repo Runtime State** in gitignored `<repo>/.agents/plugins/principal-architect-workspace/.state/state.db`.
> 5. **Local Git Floor (`local_git`) + GitHub Multi-Machine/Multi-Harness Bus (`github`):** Requires only a local `.git` repository (`git init`) for offline stacked branches, commit trailers, and local `AUDIT-round-<K>.md` Cold-Firewall reviews, while automatically upgrading to GitHub PRs, Reviews, and Issues when a GitHub remote is configured.
> 6. **Strict Mutual-Exclusion Boundary with `repo-memory-plugin` (`memory_mode: "external" | "builtin"`):** When `repo-memory-plugin` is installed (`external`), `principal-architect-plugin` **stays completely out of memory management** (omitting `memory/` and enforcing **token-succinct mechanical write-backs** in `WORKORDER.md` and `PROJECT.md` so output tokens are never wasted duplicating memory). Only when `repo-memory-plugin` is absent (`builtin`) does `principal-architect-plugin` maintain its own 3-file progressive-reveal memory index (`MEMORY.md`, `MODULE_INDEX.md`, `PROJECT_INDEX.md`).
> 7. **Interactive AuxPane UI Sidecar ("Principal Architect Cockpit"):** Features a top-of-pane **🔔 Human Attention Needed** inbox, live Programme $\to$ Stacked PR $\to$ Work Order DAG, clickable Git/GitHub PR status badges, and 1-click conversation activation (`window.sidecar.ui.toggleConversation`).

---

## Part 1: Self-Contained Plugin Packaging & Antigravity Workarounds

### 1.1 Solving the "Operational vs. Development Layout" Problem (`scripts/` Convention)

A key lesson from `bug-fixer-plugin` and `repo-memory-plugin` is that **if someone installs only the plugin package (`daemon/`), every operational script, Pydantic schema, hook, agent definition, template, and UI asset must reside *inside* that installed directory tree**—and follow the standard `scripts/` folder layout:

```text
principal-architect-plugin/                  # Git repository root (Dev / Repo level only)
├── README.md                                # Documentation & installation guide
├── SPEC.md                                  # Canonical technical specification
├── docs/
│   └── positioning-paper.md                 # Architectural positioning paper
├── pyproject.toml                           # Dev/test config (pytest, ruff, pydantic)
├── scripts/
│   ├── install.sh                           # Installs `daemon/` -> ~/.gemini/config/plugins/pa-daemon
│   ├── uninstall.sh
│   ├── enroll.sh                            # Wrapper around `pa enroll`
│   └── unenroll.sh                          # Wrapper around `pa unenroll`
├── tests/                                   # Unit & adversarial hook/schema test suite
└── daemon/                                  # 📦 THE INSTALLABLE PLUGIN PACKAGE (100% Self-Contained)
    ├── plugin.json                          # Global plugin manifest ("name": "pa-daemon")
    ├── state/                               # 🔒 Gitignored plugin-internal state (registry.json, global config)
    ├── sidecars/
    │   └── pa_cockpit/
    │       ├── sidecar.json                 # SIDECAR_UI_ENTRYPOINT_AUX_PANE -> runs `scripts/cockpit.py`
    │       └── ui/                          # AuxPane Cockpit frontend (index.html, app.js, styles.css)
    └── workspace-plugin/                    # Invisible to global scan (non-recursive 1-level scan)
        └── principal-architect/             # Referenced by <repo>/.agents/plugins.json (absolute path on `pa enroll`)
            ├── plugin.json                  # Workspace plugin manifest ("name": "principal-architect")
            ├── hooks.json                   # PreInvocation, PreToolUse, PostToolUse, Stop -> `scripts/*.py`
            ├── scripts/                     # Self-contained Python + Pydantic v2 control plane & hooks
            │   ├── __init__.py
            │   ├── pa_cli.py                # `pa` CLI entrypoint (enroll, unenroll, pr, wo, audit, graduate, sync)
            │   ├── schemas.py               # Pydantic v2 Split-Authority models (ProgramSpec, ProjectSpec, WorkOrderSpec, AuditReport)
            │   ├── state_db.py              # SQLite manager (<repo>/.agents/plugins/principal-architect-workspace/.state/state.db)
            │   ├── escalation.py            # Monitored vs. Autonomous escalation & structural blocker engine
            │   ├── vcs_sync.py              # Local Git floor + optional GitHub PR/Review/Issue transport
            │   ├── memory_grad.py           # `external` (succinct no-op) vs. `builtin` 3-file index updater
            │   ├── models.py                # Model tier & family routing (3.1 Pro / Opus / Flash)
            │   ├── cockpit.py               # AuxPane HTTP + SSE backend server
            │   ├── common.py                # Fast enrollment check (<1ms fast-exit) & transcript reader
            │   ├── pre_invocation.py        # Role/WO contract push, compaction recovery, skill highlighting
            │   ├── pre_tool_gate.py         # Boundary box, Charter lock, Architect no-code gate, git/gh gate
            │   ├── post_tool_receipt.py     # Edit invalidation & test verification receipt stamper
            │   └── stop_gate.py             # Premature-exit refusal (`decision: "continue"`) & retry counter
            ├── rules/
            │   └── 00-pa-operating-model.md
            ├── agents/                      # Custom Markdown Role Agents
            │   ├── pa-chief-architect.md
            │   ├── pa-principal-architect.md
            │   ├── pa-engineer.md
            │   ├── pa-auditor.md
            │   └── pa-debugger.md
            └── skills/
                └── principal-architect/
                    ├── SKILL.md
                    └── templates/           # Canonical YAML-frontmatter + Markdown templates
```

### 1.2 Global Plugin State vs. Enrolled Repo State (`pa enroll` Lifecycle)

| Scope | Path | Git Tracked? | Contents & Purpose |
|---|---|---|---|
| **1. Global Plugin State (Inside the Plugin)** | `~/.gemini/config/plugins/pa-daemon/state/`<br>*(gitignored in the plugin repo)* | **No (Gitignored)** | • `registry.json`: Maps enrolled repository paths (and git worktrees) $\to$ `repo_slug` / `owner/repo`. Enables $<1\text{ms}$ fast-exit in hooks and lets the global AuxPane Cockpit list all enrolled repos.<br>• `config.json`: Global user defaults (e.g., preferred Architect model family). |
| **2. Enrolled Repo Local Runtime State** | `<repo>/.agents/plugins/principal-architect-workspace/.state/state.db`<br>*(+ gitignored `<repo>/.agents/plugins.json`)* | **No (Gitignored)** | • Per-checkout SQLite DB storing machine-local `conversation_id` bindings (`chief_conv_id`, per-PR `pa_conv_id`, subagent UUIDs), local hook execution ledger, local test verification receipts, `execution_mode` (`monitored \| autonomous`), `memory_mode` (`external \| builtin`), and `vcs_mode` (`github \| local_git`). |
| **3. Enrolled Repo Portable PA Specs** | `<repo>/.agents/plugins/principal-architect-workspace/`<br>(`programme-*/`, `pr-*/`, and optional `memory/`) | **Yes (Committed)** | • Portable Pydantic-validated `PROGRAM.md`, `PROJECT.md`, `WORKORDER.md`, and `AUDIT-round-*.md` files shared across machines and harnesses.<br>• `memory/` (`MEMORY.md`, `MODULE_INDEX.md`, `PROJECT_INDEX.md`) is **optional**—created and maintained **only** when `memory_mode == "builtin"` (`repo-memory-plugin` not enrolled). |

---

## Part 2: Fractal Contract Ownership (`Chief` $\to$ `PA` $\to$ `Worker`) & Empirical Retry Calibration

### 2.1 Why the Chief Architect Should Author `PROJECT.md` Part I (`PR Charter`)

In the `Tier 2 (Principal Architect) -> Tier 3 (Execution Worker)` relationship, the PA writes Part I (`Specification & Boundary Box`) of `WORKORDER.md`, and the Worker is mechanically blocked by `PreToolUse` from rewriting its own specification; the Worker only executes the code changes and fills in Part II (`Completion Report`).

Applying this **exact same principle one tier up (`Tier 1 Chief Architect -> Tier 2 Principal Architect`)** closes a major scope-drift loophole in multi-PR programmes:
- If the Tier 2 PA authors the entire `PROJECT.md` from scratch (including its own `Scope`, `Goals`, `Allowed Modules`, and `Cross-PR Interfaces`), a PA encountering friction in `PR-03` can quietly narrow its own goals or expand its module footprint into `PR-04`'s territory without the Chief Architect's sign-off.
- Instead, we structure `PROJECT.md` as a **Split-Authority Contract**:
  1. **Part I — The PR Charter (Authored & Locked by Tier 1 Chief Architect via `pa programme charter <PR-ID>`):** Defines `pr_id`, `branch`, `base_branch`, `depends_on`, `allowed_modules`, `required_skills`, `verification_floor`, **Section 1 (`PR Charter: Scope, Goals, & Non-Goals`)**, and **Section 2 (`Architectural Requirements, Cross-PR Interfaces, & Required Skills/Tools`)**, stamped with `charter_hash`.
     - **Just-In-Time (JIT) Charter Refinement:** For a multi-PR programme, the Chief writes stub Charters for all PRs when `PROGRAM.md` is initialized, and refines/locks `PR-N`'s Part I Charter right as `PR-(N-1)` graduates (when exact upstream interfaces are finalized), immediately before spawning `PR-N`'s Tier 2 PA.
     - **Mechanical Charter Lock (`Rule R1b` in `pre_tool_gate.py`):** The Tier 2 PA is mechanically prevented from editing Part I of `PROJECT.md` or scoping Work Orders outside `charter.allowed_modules`. If the PA's codebase discovery reveals that the Charter needs adjustment, the PA runs `pa escalate --to-chief`.
  2. **Part II — Implementation Plan & Work Order Breakdown (Authored by Tier 2 Principal Architect):** Operating within the locked Charter, the Tier 2 PA performs file-level discovery, authors **Section 3 (`Implementation Plan & Work Order Breakdown`)** of `PROJECT.md` and Part I of each `wo<M>-<slug>/WORKORDER.md`, obtains Plan Approval (`pa pr approve-plan`), and dispatches the Tier 3 Workers.
  3. **Part III — Outcome & Graduation Summary (Authored by Tier 2 PA at Graduation):** Records **Section 4 (`Outcome & Session Log`)** for audit and Chief review.

### 2.2 Empirical Evaluation of `bug-fixer` Trajectories: Why `max_attempts: 5` + Structural Fast-Fail (`2`) Is Optimal

To calibrate how many attempts an Execution Worker or PR Audit loop should be granted before escalating to `pa-debugger` / human intervention, we evaluated all **38 Architect-reviewed autonomous PR trajectories** and the **24-hour trajectory health reports** across `matthewmcneill/bug-fixer-loop-plugin` ($n=24$ PRs) and `matthewmcneill/esp32-app-foundation` ($n=14$ post-architect-review PRs):

| Architect Review Rounds to Approval | `bug-fixer-loop-plugin` ($n=24$) | `esp32-app-foundation` ($n=14$) | Combined ($n=38$) | Share of Resolved PRs | Cumulative Resolution Rate |
|---|---|---|---|---|---|
| **1 Round** (0 rework iterations) | 7 | 4 | **11** | **28.9%** | 28.9% |
| **2 Rounds** (1 rework iteration) | 9 | 5 | **14** | **36.8%** | 65.8% |
| **3 Rounds** (2 rework iterations) | 4 | 4 | **8** | **21.1%** | 86.8% |
| **4 Rounds** (3 rework iterations) | 3 | 1 | **4** | **10.5%** | 97.4% |
| **5 Rounds** (4 rework iterations) | 1 | 0 | **1** | **2.6%** | **100.0%** |

**Three Empirical Findings from the Trajectory Data:**
1. **A 2-attempt ceiling would have caused a 34.2% false escalation rate (`13 / 38` PRs):**
   - Over a third of successful, merged PRs required 3 to 5 rounds (`2–4` rework turns).
   - Inspecting those 3-to-5 round PRs shows *productive, multi-layer convergence*, not aimless looping:
     - **`esp32-app-foundation` PR `#281` (4 rounds):** Round 1 rejected band-aid forwarding headers $\to$ Engineer renamed the actual module files (`WebServer.hpp`, `LVGLDisplay.hpp`, etc.) $\to$ Round 2 caught nonsensical Doxygen comments added to `#define` include guards to appease `release-audit-checks.sh` $\to$ Engineer removed the comments, causing `release-audit-checks.sh` to fail $\to$ Round 3 directed fixing `check_undocumented_constants()` in `release-audit-checks.sh` to ignore value-less `#define` guards $\to$ Round 4 Approved.
     - **`bug-fixer-loop-plugin` PR `#24` (4 rounds):** Round 1 rejected unapproved `# nosec` feature creep $\to$ Round 2 caught a missed verbose output specification $\to$ Round 3 caught missing unit tests $\to$ Round 4 Approved.
     - **`bug-fixer-loop-plugin` PR `#29` (5 rounds):** Approved in Round 2 $\to$ Merge conflict detected in Round 3 $\to$ Engineer resolved conflict using temporary `fix_architect_dispatcher.py` and `resolve.py` scratch scripts accidentally committed to git $\to$ Round 4 flagged the committed scratch scripts $\to$ Round 5 Approved.
2. **True trajectory failures were caused by structural/environmental blockers, never by productive 3–5 turn code iteration:**
   - Across `esp32-app-foundation` Issues `#269` and `#277` and `bug-fixer-loop-plugin` Issues `#3`, `#15`, and `#31`, every failed trajectory exhibited one of three non-progress signatures:
     1. **Structural Hook / Gate Denials (`BLOCKER_STRUCTURAL`, Issue `#31`):** 18 pre-tool hook denials (`Use safe_ingest.py instead of raw gh commands`), 10 leak-scan blocks on test fixture strings, or `>= 3` consecutive `ERROR_MESSAGE` steps in `transcript.jsonl`.
     2. **Hardware / MCP Exclusive Lock Contention (`Issue #269`):** Sessions `ddd7f636` and `3b62a4f0` stalled for >2 hours with `Hardware is currently tied` because an earlier session exited without releasing the `platformio-mcp` lock.
     3. **Silent Session Stalls (`Issue #277`, PRs `#272` & `#274`):** Sessions going idle (`PLANNER_RESPONSE` with no tool calls) waiting for human confirmation in an unattended session.
3. **Resulting Two-Tier Retry Policy in `principal-architect-plugin`:**
   - **Productive Iteration Ceiling (`max_attempts: 5`, `max_audit_rounds: 5`):** Matches `bug-fixer-plugin`'s `MAX_REVIEW_ROUNDS = 5`, accommodating progressive multi-layer fixes and mid-flight rebases (plus optional model tier step-up from `flash_lite` $\to$ `flash` $\to$ `inherit` after attempt 2).
   - **Structural Blocker Fast-Fail (`max_structural_failures: 2`, `error_loop_threshold: 3`):** If a Worker hits 2 structural blockers (e.g., `PreToolUse` scope denials because `allowed_files` is missing a file, or hardware lock contention) or 3 consecutive `ERROR_MESSAGE` steps, `stop_gate.py` immediately escalates to the Principal Architect / `pa-debugger` without wasting attempts 3–5.

---

## Part 3: Dynamic Model Efficiency, Skills Preservation, & Calling Gemini 3.1 Pro vs. Claude Opus vs. Flash Tiers

### 3.1 The 4-Criterion Framework: When & How to Constrain Skills, Rules, Tools, & MCPs

Earlier we assumed skill descriptions were negligible (~25 tokens each) and proposed `inheritCustomizations: true` everywhere. Measuring the actual environment on disk (`~/.gemini/config/` vs. `<repo>/.agents/` in `esp32-app-foundation`) refutes that assumption and gives us **four concrete engineering criteria** for what to constrain vs. preserve:

| Criterion | Empirical Measurement | Architectural Decision in `principal-architect-plugin` |
|---|---|---|
| **1. Origin & Signal-to-Noise (`Global Personal Bloat` vs. `Repo Domain Skills`)** | • Global `~/.gemini/config/skills/` (23+ personal/office skills) averages **175 tokens/skill** (`~4,039–6,500 tokens` of `<skills>` descriptions alone), plus **~5,000–7,300 tokens** of unrelated global plugin `<user_rules>` (`~11,000–13,800 tokens` of pure prefix noise per subagent).<br>• By contrast, a repo's own `<repo>/.agents/skills/` (e.g., `framework-expert`, `framework-portal-design`, `framework-setup` in `esp32-app-foundation`) has only 3–5 skills (**~450 tokens** of descriptions) that are **100% relevant**. | **Set `inheritCustomizations: false` on subagents (`pa-engineer`, `pa-auditor`) and mount a repo-scoped `.state/pa-skills.json` manifest** generated at `pa enroll`. This strips ~13,000+ tokens of unrelated global personal/office bloat at **zero LLM token cost** while keeping 100% of `<repo>/.agents/skills/` plus any explicitly enrolled global hardware/domain skills (`extra_skills: ["pio"]`). |
| **2. Rule Conflict Prevention (Especially on `flash_lite` / `flash`)** | • In `esp32-app-foundation/.agents/rules/`, `01-plan-before-execute.md` (**1,602 tokens**) instructs the agent: *"Never execute code edits before asking the user to approve your plan"*, and global memory rules instruct agents to write memory files before stopping.<br>• Inheriting these unfiltered into autonomous Workers caused the exact Plan-Gate stalls documented in `bug-fixer-plugin/liveness.py`. | **Filter workspace rules via `.state/pa-worker-rules.json` at `pa enroll`:** Mount `<repo>/.agents/rules` (preserving domain rules like `02-tmp_workspace.md`, `03-versioning.md`, `04-mcp-tooling.md`) with `"exclude": ["01-plan-before-execute.md", "bug-fixer-*"]` so Workers never inherit conflicting interactive gates. |
| **3. KV Prompt-Cache Prefix Stability (`Static Per-Repo Role Prefix` vs. `Dynamic Per-WO Rewriting`)** | • Dynamically rewriting `agents/pa-engineer.md`'s system prompt or `tools:`/`skills:` list before every single Work Order busts the LLM's KV prompt-cache prefix across consecutive Work Orders on the same model tier (`flash`). | **Never rewrite `agents/*.md` per Work Order.** Constrain statically at the **Role $\times$ Repo** level so all `pa-engineer` runs share an identical cached system prefix, and pass per-Work-Order `required_skills` pointers in the `PreInvocation` `userMessage` (after the cached system prefix). |
| **4. Tool & MCP Blast Radius per Role** | • Each MCP server injects ~1,500–6,000 tokens of JSON Schema declarations.<br>• Builtin tools like `search_web`, `search_marketplace`, `ask_question`, and `invoke_subagent` invite drift or stalls inside `pa-engineer`. | • **`pa-engineer`:** Strip `invoke_subagent`, `ask_question`, `search_web`, `search_marketplace`; keep `inheritMcp: true` for build/hardware MCPs (`platformio`).<br>• **`pa-auditor`:** Strip all file-write tools and set **`inheritMcp: false`** (saves thousands of MCP schema tokens and enforces a strict read-only firewall). |

### 3.2 Calling Gemini 3.1 Pro vs. Claude Opus 4.6 vs. Flash Tiers

| Target Model Family | CLI Slugs (`agy models`) & UI Names | 1. How to Call for Top-Level Conversations (Chief, PR PA, Debugger) | 2. How to Call for Subagents (`invoke_subagent` / `agents/*.md`) |
|---|---|---|---|
| **Gemini 3.1 Pro** *(Frontier Architecture, Auditing, & Complex Coding)* | • CLI: `gemini-3.1-pro --effort high\|low`<br>• UI: `Gemini 3.1 Pro (High / Low)` | • **Interactive IDE:** Select `Gemini 3.1 Pro (High)` in the session model picker.<br>• **Headless CLI:** `agy -p --model gemini-3.1-pro --effort high` | • **Pass `Model: "inherit"`** when the parent Architect session is running on Gemini 3.1 Pro (High) or Claude Opus! (Passing `Model: "pro"` downgrades off the parent's explicit model/thinking tier to the platform's generic `pro` default.) |
| **Claude Opus 4.6 (Thinking)** | • CLI: `claude-opus-4-6-thinking`<br>• UI: `Claude Opus 4.6 (Thinking)` | • **Interactive IDE:** Select `Claude Opus 4.6 (Thinking)` in the session model picker.<br>• **Headless CLI:** `agy -p --model claude-opus-4-6-thinking` | • **Pass `Model: "inherit"`** when the parent session is on Claude Opus 4.6 (Thinking). |
| **Gemini 2.5 Flash (`standard` WOs)** | • CLI: `gemini-2.5-flash`<br>• Tier alias: `flash` | • `agentapi new-conversation --model flash` | • Pass **`Model: "flash"`** on `invoke_subagent`. |
| **Gemini 2.5 Flash Lite (`mechanical` WOs)** | • CLI: `gemini-2.5-flash-lite`<br>• Tier alias: `flash_lite` | • `agentapi new-conversation --model flash_lite` | • Pass **`Model: "flash_lite"`** on `invoke_subagent`. |

---

## Part 4: Clean Boundary Between `repo-memory-plugin` (`external`) and Built-in Progressive-Reveal Memory (`builtin`)

To keep the boundary clean and avoid duplicating memory writes or burning output tokens twice, `principal-architect-plugin` operates in one of two mutually exclusive modes (`memory_mode` in `.state/state.db`):

| Aspect | Mode A: `memory_mode = "external"` (`repo-memory-plugin` Installed & Enrolled) | Mode B: `memory_mode = "builtin"` (`repo-memory-plugin` NOT Installed — Fallback) |
|---|---|---|
| **Who manages codebase memory?** | **100% `repo-memory-plugin`** (`.memory/`). `principal-architect-plugin` **does not** create, update, or inject `.agents/plugins/principal-architect-workspace/memory/`. | **`principal-architect-plugin`** maintains `.agents/plugins/principal-architect-workspace/memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}`. |
| **`WORKORDER.md` & `PROJECT.md` Write-Back Verbosity** | **Succinct Mechanical Mode:** Workers record only `status`, `attempt_num`, `receipt_id`, `commit_sha`, `files_modified`, a 1-line `verification_summary` ($\le 280$ chars), and any `escalation_request` / `out_of_scope_findings`. Narrative `decisions_made` and `dead_ends` prose is omitted because `repo-memory`'s `Stop` hook already harvests turn notes. | **Full Warm-Cache Distillation Mode:** Workers and Architects record `decisions_made`, `dead_ends`, and rich `PROJECT.md` `Session Log` syntheses while the KV prompt cache is warm (~90% cache read discount). |
| **`pa pr graduate` Behavior** | Verifies Audit + `verification_floor`, writes compact mechanical graduation status to `PROJECT.md` Part III, and marks the PR `GRADUATED`. | Also deterministically updates `MEMORY.md` (5-PR window), rolls older PRs to `PROJECT_INDEX.md`, and appends rows under `allowed_modules` in `MODULE_INDEX.md`. |
| **`PreInvocation` Boot Injection** | Injects only PA role/contract state (`PROJECT.md` Charter / `WORKORDER.md` Spec); defers all memory dossier injection to `repo-memory-plugin`. | Also pushes `MEMORY.md` + matching domain sections of `MODULE_INDEX.md` (`[PROJECT.md](../pr-XX/PROJECT.md)` links) for $O(1)$ module-indexed progressive reveal. |

---

## Part 5: Dual-Mode Hooks (`Monitored` vs. `Autonomous`) & Local-Git / GitHub Multi-Machine Bus

### 5.1 Local Git Floor (`local_git`) vs. GitHub Multi-Machine Synchronization (`github`)

- **Mandatory Floor — Local Git Database (`vcs_mode: "local_git"`):** If a repository has no GitHub remote (`origin`) or `gh` is not initialized, every `pa` workflow still works end-to-end against the local `.git` repository (`git init`). Stacked branches (`git checkout -b`), commit trailers (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`), and Step 6A Cold-Firewall Audits (`git diff <base_branch>...<branch>` $\to$ committed `pr-<slug>/AUDIT-round-<K>.md`) operate 100% locally.
- **Remote Upgrade — GitHub Bus (`vcs_mode: "github"`):** When a GitHub remote is present, `pa programme charter`, `pa pr open-or-sync`, `pa pr post-audit` (`gh pr review <N> --comment`), `pa pr sync-audit`, and `pa pr claim` project and synchronize state through GitHub PRs, Reviews, and Issues so Chief Architects, PR Principal Architects, Hardware-Attached Workers, and Cold-Firewall Auditors can collaborate across multiple machines and harnesses.

### 5.2 Interactive AuxPane UI Sidecar ("Principal Architect Cockpit")

The AuxPane Cockpit (`sidecars/pa_cockpit/`) runs inside the Antigravity right-hand side panel (`SIDECAR_UI_ENTRYPOINT_AUX_PANE`) and integrates with `/preload.js` (`window.sidecar.ui.toggleConversation`, `window.sidecar.onWorkspaceChange`, `window.sidecar.agent.sendMessage`):

1. **Header Bar:** Enrolled workspace selector, mode badges (`Git: GitHub | Local`, `Memory: repo-memory | Built-in`), **Mode Toggle (`[👀 Monitored]` $\leftrightarrow$ `[🤖 Autonomous]`)**, Architect Model Family selector, and `[🔄 Sync]`.
2. **🔔 Human Attention Needed Queue (Top Priority Inbox):** Surfaces every item across the programme awaiting plan approval, boundary/Charter expansion, or debug escalation (`5` failed attempts or `2` structural blockers), with 1-click action buttons.
3. **Stacked PR & Work Order DAG with Live Git/GitHub Status Badges:** Displays every PR in the stack with its Charter lock badge (`🔒 Charter by Chief`), state icon (`📝 Local Branch`, `🚧 Draft #21`, `📤 Staged #21`, `🔍 Changes Requested (Round K/5)`, `✅ Approved #21`, `🟣 Graduated`), attempt counters (`Attempt K/5`), clickable external links to GitHub (when `vcs_mode == "github"`), and 1-click `[💬 Jump to Conversation]` buttons calling `window.sidecar.ui.toggleConversation(convId)`.
