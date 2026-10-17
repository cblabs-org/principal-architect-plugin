---
name: principal-architect-admin
description: >
  Manage the Principal Architect plugin and daemon: enroll or unenroll
  repositories, migrate legacy PA memory banks, check programme/PR/WO status,
  sync GitHub PRs and git trailers, switch between monitored and autonomous
  execution modes, and resolve human attention escalations. Use when the user
  asks to enroll or unenroll a repo in Principal Architect, migrate a legacy
  PA workspace, check PA status, sync PA state, or change PA execution mode.
---

# Principal Architect Admin Skill (`principal-architect-admin`)

## PA_CLI

```text
~/.local/bin/pa
```

Fallback if `~/.local/bin` is not on `PATH`:

```bash
~/.gemini/config/plugins/pa-daemon/bin/pa
```

---

## Read-Only Commands (run directly, report output)

| Command | Example | Purpose |
|---|---|---|
| **status** | `pa status [path] [--json]` | Reconciles committed specs, git trailers, and `.state/state.db`; shows Programme -> PR -> WO DAG and **Human Attention Needed** queue. |
| **doctor** | `pa doctor [path] [--fix] [--json]` | Checks CLI vs. installed `pa-daemon` version drift, Python 3.11+ & `pydantic`/`pyyaml` dependencies (provisioning `pa-daemon/.venv` when `--fix` is passed), and enrolled repository health. |
| **mode** | `pa mode [--path PATH]` | Displays active `execution_mode` (`monitored` vs `autonomous`). |

---

## Repository Enrollment, Migration & Lifecycle Commands

| Command | Args | Notes |
|---|---|---|
| **enroll** | `[path] [--execution-mode {monitored,autonomous}] [--auto-approve-pr-plans \| --no-auto-approve-pr-plans] [--memory-mode {auto,external,builtin}] [--vcs-mode {auto,github,local_git}] [--extra-skill NAME] [--exclude-rule PATTERN] [--migrate]` | Registers repo in `pa-daemon/state/registry.json`, writes `.agents/plugins.json`, initializes `.agents/plugins/principal-architect-workspace/` and `.state/{state.db,pa-skills.json,pa-worker-rules.json}`. |
| **migrate** | `[path] [--seed-repo-memory \| --no-seed-repo-memory] [--no-cleanup-legacy-skill] [--json]` | Moves/merges `.agents/skills/principal-architect-workspace/` into `.agents/plugins/principal-architect-workspace/`, removes legacy `.agents/skills/principal-architect`, rewrites stale path references (preserving `charter_hash`/`spec_hash`), backfills `.state/state.db` via `pa sync`, and seeds `repo-memory` (`seed`, `seed-docs`, `index`) when `memory_mode=external`. |
| **unenroll** | `[path]` | Removes PA workspace plugin entry from `.agents/plugins.json` and unregisters repo from `registry.json` (preserves committed `PROGRAM.md` / `PROJECT.md` / `WORKORDER.md` artifacts). |
| **sync** | `[path]` | Reconciles GitHub PRs/reviews (`vcs_mode: github`) or local git trailers & committed `AUDIT-round-*.md` files (`vcs_mode: local_git`) into `.state/state.db`. |
| **mode** | `<monitored\|autonomous> [--path PATH]` | Switches execution mode (`monitored` prompts via interactive `ask` on boundary exceptions; `autonomous` denies out-of-bounds actions and routes structured escalations up `Worker -> PA -> Chief -> Human Attention Queue`). |
| **wo resolve** | `<WO-ID> --resolution "<note>" [--repo PATH]` | Resolves an open escalation / attention queue item for `<WO-ID>` and resets structural failure counters. |

---

## Enrollment Procedure (`pa enroll`)

Whenever the user asks to enroll a repository via `/principal-architect-admin` without explicitly specifying all flags on the command line (e.g., `/principal-architect-admin enroll this repo please`), **you MUST first inspect the repository, clearly explain each enrollment option and what was auto-detected, and ask the user to choose their setup via `ask_question` before running `pa enroll`**.

### Step 1 — Read-only repository inspection

Determine the target repository root (defaults to the current workspace root if the user says *"enroll this repo"*) and inspect its current state:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true
ls -d "$REPO_ROOT/.memory" \
  "$REPO_ROOT/.agents/memory" \
  "$REPO_ROOT/.agents/skills/principal-architect-workspace" \
  "$REPO_ROOT/.agents/plugins/principal-architect-workspace" \
  "$REPO_ROOT/.agents/skills" \
  "$REPO_ROOT/.agents/rules" 2>/dev/null || true
```

Note the auto-detected defaults:
- **Detected `vcs_mode`**: `github` (if `origin` is a GitHub URL and `gh auth status` succeeds) else `local_git`.
- **Detected `memory_mode`**: `external` (if `.memory/` or `repo-memory` is enrolled) else `builtin`.
- **Legacy PA workspace present**: whether `.agents/skills/principal-architect-workspace` exists (and how many PR/programme folders or memory files it contains).

### Step 2 — Explain the Enrollment Options & Ask the User (`ask_question`)

Before calling `pa enroll`, present a concise overview of the **enrollment options and their trade-offs** (highlighting what was auto-detected in Step 1) and invoke `ask_question` so the user can choose their setup:

#### Options to Explain to the User

1. **Execution Mode (`--execution-mode` & `--auto-approve-pr-plans`)** — controls how the `PreToolUse` and `Stop` governance hooks handle boundary exceptions and plan gates:
   - **`monitored` (Interactive — default)**: Prompts you (`ask`) in the IDE whenever an Architect attempts an inline code edit (R1), when a PA dispatches the first Worker on a `PLANNED` PR (R2), when a Worker needs a file outside `allowed_files` (R3), or when graduating without a matching audit (R6). Best when you want interactive human sign-off at each boundary.
   - **`autonomous` (Review PR Plans — `--no-auto-approve-pr-plans`)**: Workers execute unattended inside their `allowed_files` boundary box; out-of-bounds actions or retry-ceiling hits are denied and automatically routed up `Worker -> PA -> Chief -> 🔔 Human Attention Needed` inbox. New PR Work Order plans still pause for your approval before Workers are dispatched.
   - **`autonomous` + Auto-Approve PR Plans (`--auto-approve-pr-plans`)**: Fully unattended execution — if a PA's `PROJECT.md` Part II plan and `WORKORDER.md` specs pass schema, `charter_hash`, and `charter.allowed_modules` validation, the R2 gate auto-approves the plan and dispatches `pa-engineer` Workers immediately.

2. **Memory Mode (`--memory-mode`)** — controls how repository architecture memory and Work Order write-backs are managed (mutually exclusive so tokens are never wasted duplicating work):
   - **`external` (`repo-memory-plugin`)**: Recommended when `repo-memory` (`.memory/`) is used. `repo-memory` owns codebase memory (`ATLAS.md`, subsystem dossiers, op-log), while Principal Architect switches to **Succinct Write-Back Mode** (never creating/updating PA's `memory/` folder and keeping `WORKORDER.md` completion reports strictly mechanical to save output tokens).
   - **`builtin` (PA 3-File Markdown Memory Bank)**: Scaffolds and maintains `.agents/plugins/principal-architect-workspace/memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}` with a 5-PR rolling window and **Full Distillation Mode** (`decisions_made` and `dead_ends` recorded in `WORKORDER.md` and `PROJECT.md`). Best for standalone repos not using `repo-memory`.

3. **VCS & Audit Bus (`--vcs-mode`)** — controls how stacked branches, Cold-Firewall audits, and deferred findings are synchronized:
   - **`github` (GitHub PR-Mediated Bus)**: Pushes stacked branches (`feat/pr-NN-<slug>`) to `origin`, opens/updates GitHub PRs (`pa pr open-or-sync`), posts Cold-Firewall `AuditReport` reviews on the PR via `gh pr review --comment`, and files out-of-scope findings as `pa:deferred` GitHub Issues.
   - **`local_git` (Offline Local Git Floor)**: Operates 100% locally without requiring a GitHub remote or `gh` CLI — uses local stacked branches, cryptographic git commit trailers (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`), committed `AUDIT-round-<K>.md` files, and `DEFERRED_BACKLOG.md`.

4. **Legacy Workspace Migration (`--migrate`)** *(only when `.agents/skills/principal-architect-workspace/` is detected)*:
   - Moves/merges `.agents/skills/principal-architect-workspace/` into `.agents/plugins/principal-architect-workspace/`, removes any legacy `.agents/skills/principal-architect` skill/submodule, rewrites stale path references while recomputing `charter_hash`/`spec_hash`, backfills `.state/state.db` from git trailers, and (if `memory_mode=external`) seeds `repo-memory`.

#### `ask_question` Prompts to Present

Call `ask_question` with self-contained option descriptions so every choice is clear inside the modal:

1. **Question 1 — Execution Mode**:
   - *"How should Principal Architect enforce hook gates and PR plan approvals in this repository?"*
   - Options:
     - `(Recommended) Monitored mode (interactive) — prompt me on boundary exceptions and before dispatching new PR Work Order plans`
     - `Autonomous mode (review PR plans) — run Workers unattended with upward escalations to the Cockpit inbox, but pause for my approval on new PR plans`
     - `Autonomous mode (auto-approve PR plans) — run fully unattended, auto-approving PR Work Order plans that pass Charter & schema validation`
2. **Question 2 — Memory Mode**:
   - *"How should codebase architecture memory and Work Order takeaways be managed?"*
   - Options:
     - `(Recommended) <Auto-detected mode: External (repo-memory-plugin) | Built-in 3-file PA memory> — <1-line reason based on whether .memory/ was detected>`
     - `External (repo-memory-plugin) — delegate codebase memory to repo-memory and use token-saving Succinct Write-Back Mode in PA`
     - `Built-in (.agents/plugins/principal-architect-workspace/memory/) — maintain PA's own MEMORY.md, MODULE_INDEX.md, and PROJECT_INDEX.md in Full Distillation Mode`
3. **Question 3 — VCS & Audit Bus Mode**:
   - *"How should stacked PR branches, Cold-Firewall audits, and deferred findings be synchronized?"*
   - Options:
     - `(Recommended) <Auto-detected mode: GitHub PR bus (github) | Local Git only (local_git)> — <1-line reason based on origin remote & gh auth>`
     - `GitHub PR-mediated (github) — sync stacked branches with origin, post Cold-Firewall audits to GitHub PRs, and file pa:deferred GitHub Issues`
     - `Local Git only (local_git) — keep everything offline using local stacked branches, git commit trailers, and committed AUDIT-round-*.md files`
4. **Question 4 — Legacy PA Workspace Migration** *(include only if `.agents/skills/principal-architect-workspace/` was detected in Step 1)*:
   - *"A legacy `.agents/skills/principal-architect-workspace/` directory was detected. How should it be handled?"*
   - Options:
     - `(Recommended) Migrate & merge into .agents/plugins/principal-architect-workspace/ (--migrate) — move artifacts, clean up legacy skill, rewrite paths, and backfill/seed memory`
     - `Skip migration — leave the legacy directory untouched`

*(Note: Do **not** ask the user to curate `--extra-skill` or `--exclude-rule` lists at enrollment time. `pa-chief-architect` and `pa-principal-architect` inherit full skill visibility (`inheritCustomizations: true`), and it is the Principal Architect's responsibility when scoping each `WORKORDER.md` to populate `required_skills: [...]`, which `pre_invocation.py` automatically resolves and injects into the isolated `pa-engineer` Worker on Turn 1.)*

### Step 3 — Execute enrollment & initial sync

Run `pa enroll` with the user's confirmed flags, followed by `pa sync` and `pa status`:

```bash
~/.local/bin/pa enroll "$REPO_ROOT" \
  --execution-mode <monitored|autonomous> \
  [--auto-approve-pr-plans | --no-auto-approve-pr-plans] \
  --memory-mode <auto|external|builtin> \
  --vcs-mode <auto|github|local_git> \
  [--migrate]
~/.local/bin/pa sync "$REPO_ROOT"
~/.local/bin/pa status "$REPO_ROOT"
```

### Step 4 — Post-enrollment summary

Report back to the user:
- Enrolled `workspace_dir`, `vcs_mode`, `memory_mode`, `execution_mode`, and any migrated paths or `repo-memory` seeding results.
- Remind the user to start a new conversation (or reload) in the newly enrolled repository if they want the workspace-scoped hooks (`PreInvocation`, `PreToolUse`, `PostToolUse`, `Stop`) and custom agents (`pa-chief-architect`, `pa-principal-architect`, `pa-engineer`, `pa-auditor`, `pa-debugger`) active in their chat session.

---

## Standalone Migration Procedure (`pa migrate`)

When migrating an existing repository that used the legacy `principal-architect` skill (`.agents/skills/principal-architect-workspace/`):

```bash
~/.local/bin/pa migrate <repo-root> [--seed-repo-memory]
```

What `pa migrate` executes:
1. **Moves or merges** `.agents/skills/principal-architect-workspace/` (`memory/`, `programme-*/`, `pr-*/`) into `.agents/plugins/principal-architect-workspace/` (even if `.agents/plugins/principal-architect-workspace/` was already partially created) and removes `.agents/skills/principal-architect`.
2. **Rewrites stale paths** (`.agents/skills/principal-architect-workspace` -> `.agents/plugins/principal-architect-workspace`) across `.md` artifacts while recomputing `charter_hash` and `spec_hash` so locked specs stay valid, then runs `pa sync` to backfill `.state/state.db`.
3. **Bridges into `repo-memory`** (when `memory_mode=external` or `--seed-repo-memory` is passed): adds `.agents/plugins/principal-architect-workspace/memory` to `.agents/memory/config.json` `doc_seeds` and runs `repo-memory seed`, `repo-memory seed-docs`, and `repo-memory index`.

---

## Troubleshooting

1. **Hooks or CLI failing with `No module named 'pydantic'`**:
   Run `pa doctor --fix` to automatically provision `~/.gemini/config/plugins/pa-daemon/.venv` with `pydantic` and `pyyaml` (especially on PEP 668 externally-managed Python environments such as Homebrew on macOS), or verify manually:
   ```bash
   ~/.gemini/config/plugins/pa-daemon/bin/pa doctor --fix
   ```
2. **Stale PR/WO status after switching branches or pulling**:
   Run `pa sync <repo-root>` followed by `pa status <repo-root>`.
3. **Worker blocked in `autonomous` mode**:
   Run `pa status <repo-root>` to inspect the `Human Attention Needed` queue, then either approve/expand scope in `WORKORDER.md` (`pa pr approve-plan <PR-ID>`) or run `pa wo resolve <WO-ID> --resolution "<note>"`.
