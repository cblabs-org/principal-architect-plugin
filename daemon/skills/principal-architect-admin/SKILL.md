---
name: principal-architect-admin
description: >
  Manage the Principal Architect plugin and daemon: enroll or unenroll
  repositories, check programme/PR/WO status, sync GitHub PRs and git trailers,
  switch between monitored and autonomous execution modes, and resolve human
  attention escalations. Use when the user asks to enroll or unenroll a repo in
  Principal Architect, check PA status, sync PA state, or change PA execution mode.
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

## Repository Enrollment & Lifecycle Commands

| Command | Args | Notes |
|---|---|---|
| **enroll** | `[path] [--memory-mode {auto,external,builtin}] [--vcs-mode {auto,github,local_git}] [--extra-skill NAME] [--exclude-rule PATTERN]` | Registers repo in `pa-daemon/state/registry.json`, writes `.agents/plugins.json`, initializes `.agents/plugins/principal-architect-workspace/` and `.state/{state.db,pa-skills.json,pa-worker-rules.json}`. |
| **unenroll** | `[path]` | Removes PA workspace plugin entry from `.agents/plugins.json` and unregisters repo from `registry.json` (preserves committed `PROGRAM.md` / `PROJECT.md` / `WORKORDER.md` artifacts). |
| **sync** | `[path]` | Reconciles GitHub PRs/reviews (`vcs_mode: github`) or local git trailers & committed `AUDIT-round-*.md` files (`vcs_mode: local_git`) into `.state/state.db`. |
| **mode** | `<monitored\|autonomous> [--path PATH]` | Switches execution mode (`monitored` prompts via interactive `ask` on boundary exceptions; `autonomous` denies out-of-bounds actions and routes structured escalations up `Worker -> PA -> Chief -> Human Attention Queue`). |
| **wo resolve** | `<WO-ID> --resolution "<note>" [--repo PATH]` | Resolves an open escalation / attention queue item for `<WO-ID>` and resets structural failure counters. |

---

## Enrollment Procedure (`pa enroll`)

### Step 1 — Inspect target repository (read-only)

Determine the target repository root (defaults to the current workspace root if the user says *"enroll this repo"*):

```bash
git rev-parse --show-toplevel
git remote get-url origin 2>/dev/null || true
```

Check whether the user requested any global domain skills (`--extra-skill <name>`, e.g., `pio`) to be mounted alongside `<repo>/.agents/skills/` for isolated subagents.

### Step 2 — Execute enrollment & initial sync

Run `pa enroll` and `pa sync`:

```bash
~/.local/bin/pa enroll <repo-root>
~/.local/bin/pa sync <repo-root>
~/.local/bin/pa status <repo-root>
```

What `pa enroll` configures automatically:
1. **Workspace Plugin Mount**: Adds `~/.gemini/config/plugins/pa-daemon/workspace-plugin` to `<repo-root>/.agents/plugins.json`.
2. **Legacy Migration**: If `<repo-root>/.agents/skills/principal-architect-workspace` exists, migrates it (preserving git history via `git mv`) to `<repo-root>/.agents/plugins/principal-architect-workspace`.
3. **VCS Mode (`vcs_mode`)**: Auto-detects `github` (when `origin` is a GitHub URL and `gh auth status` succeeds) or `local_git` (offline git branch + trailer floor).
4. **Memory Mode (`memory_mode`)**: Auto-detects `external` when `repo-memory` (`.memory/`) is present (skipping PA's built-in `memory/` directory to avoid duplicate token work), or `builtin` (scaffolding `memory/{MEMORY.md,MODULE_INDEX.md,PROJECT_INDEX.md}`).
5. **Subagent Capability Scoping**: Writes `.state/pa-skills.json` and `.state/pa-worker-rules.json` (excluding `01-plan-before-execute.md` and `bug-fixer-*` so autonomous Tier 3 Workers never stall on interactive plan gates).

### Step 3 — Post-enrollment summary

Report back to the user:
- Enrolled `workspace_dir`, `vcs_mode` (`github` vs `local_git`), `memory_mode` (`external` vs `builtin`), and `execution_mode` (`monitored` vs `autonomous`).
- Remind the user to start a new conversation (or reload) in the newly enrolled repository if they want the workspace-scoped hooks (`PreInvocation`, `PreToolUse`, `PostToolUse`, `Stop`) and custom agents (`pa-chief-architect`, `pa-principal-architect`, `pa-engineer`, `pa-auditor`, `pa-debugger`) active in their chat session.

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
