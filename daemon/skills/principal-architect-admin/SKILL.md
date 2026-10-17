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
python3 ~/.gemini/config/plugins/pa-daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
```

---

## Read-Only Commands (run directly, report output)

| Command | Example | Purpose |
|---|---|---|
| **status** | `pa status [path] [--json]` | Reconciles committed specs, git trailers, and `.state/state.db`; shows Programme -> PR -> WO DAG and **Human Attention Needed** queue. |
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

Whenever the user asks to enroll a repository via `/principal-architect-admin` without explicitly specifying all flags on the command line, **always inspect the repository first and ask the user to confirm their enrollment options before running `pa enroll`**.

### Step 1 — Read-only repository inspection

Determine the target repository root (defaults to the current workspace root if the user says *"enroll this repo"*) and inspect its current state:

```bash
git rev-parse --show-toplevel
git remote get-url origin 2>/dev/null || true
ls -d .memory .agents/memory .agents/skills/principal-architect-workspace .agents/plugins/principal-architect-workspace .agents/skills .agents/rules 2>/dev/null || true
```

Note the auto-detected defaults:
- **Detected `vcs_mode`**: `github` (if `origin` is a GitHub URL and `gh auth status` succeeds) else `local_git`.
- **Detected `memory_mode`**: `external` (if `.memory/` or `repo-memory` is enrolled) else `builtin`.
- **Legacy PA workspace present**: whether `.agents/skills/principal-architect-workspace` exists.

### Step 2 — Interactive Option Confirmation (`ask_question`)

Use `ask_question` to confirm the user's preferred configuration before executing `pa enroll`:

1. **Execution Mode (`--execution-mode` & `--auto-approve-pr-plans`)**:
   - `(Recommended) Monitored mode — interactive prompts on boundary exceptions and PR plan dispatches`
   - `Autonomous mode (review PR plans) — unattended Worker execution with upward escalations; require human approval before new PR plans`
   - `Autonomous mode (auto-approve PR plans) — fully unattended execution when PR Work Order plans pass schema validation`
2. **Memory Mode (`--memory-mode`)**:
   - `(Recommended) Auto-detected (<external | builtin>)`
   - `External (repo-memory-plugin) — delegate codebase memory to repo-memory (Succinct Write-Back Mode)`
   - `Built-in (.agents/plugins/principal-architect-workspace/memory/) — maintain PA's 3-file markdown memory bank (Full Distillation Mode)`
3. **VCS Mode (`--vcs-mode`)**:
   - `(Recommended) Auto-detected (<github | local_git>)`
   - `GitHub PR-mediated (github) — use gh pr for Cold-Firewall audits and PR graduation`
   - `Local Git only (local_git) — use local stacked branches, git trailers, and committed AUDIT-round-*.md files`
4. **Legacy Migration & Extra Global Skills (`--migrate`, `--extra-skill`)** *(include when a legacy workspace or global skills are relevant)*:
   - If `.agents/skills/principal-architect-workspace/` exists: confirm running with `--migrate` (to move/merge legacy PA memory, clean up `.agents/skills/principal-architect`, rewrite stale paths, and seed `repo-memory` if `external`).
   - Ask if any global skills from `~/.gemini/config/skills/` (`--extra-skill <name>`) or custom worker rule exclusions (`--exclude-rule <pattern>`) should be mounted into isolated Worker subagents.

### Step 3 — Execute enrollment & initial sync

Run `pa enroll` with the selected flags, followed by `pa sync` and `pa status`:

```bash
~/.local/bin/pa enroll <repo-root> \
  --execution-mode <monitored|autonomous> \
  [--auto-approve-pr-plans | --no-auto-approve-pr-plans] \
  --memory-mode <auto|external|builtin> \
  --vcs-mode <auto|github|local_git> \
  [--migrate] \
  [--extra-skill <skill-name>] \
  [--exclude-rule <pattern>]
~/.local/bin/pa sync <repo-root>
~/.local/bin/pa status <repo-root>
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

1. **Hooks failing with `No module named 'pydantic'`**:
   Ensure `pydantic` and `pyyaml` are installed in user site-packages for system `python3`:
   ```bash
   python3 -c "import pydantic, yaml"
   ```
2. **Stale PR/WO status after switching branches or pulling**:
   Run `pa sync <repo-root>` followed by `pa status <repo-root>`.
3. **Worker blocked in `autonomous` mode**:
   Run `pa status <repo-root>` to inspect the `Human Attention Needed` queue, then either approve/expand scope in `WORKORDER.md` (`pa pr approve-plan <PR-ID>`) or run `pa wo resolve <WO-ID> --resolution "<note>"`.
