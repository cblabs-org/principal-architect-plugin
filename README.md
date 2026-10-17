# Principal Architect Plugin (`principal-architect-plugin`)

Mechanically enforced, token-efficient, multi-tier orchestration plugin for large software engineering programmes (`SPEC.md` v1.1).

## Overview

`principal-architect-plugin` turns the Principal Architect workflow into a deterministic, self-contained Python 3.11+ & Pydantic v2 control plane packaged inside `daemon/`:

- **Fractal Split-Authority Contracts:** Machine-validated Markdown + YAML frontmatter artifacts (`PROGRAM.md`, `PROJECT.md`, `WORKORDER.md`, `AUDIT-round-K.md`) where each tier locks the contract (`charter_hash`, `spec_hash`) for the tier below it (**Tier 1 Chief Architect** $\to$ **Tier 2 Principal Architect** $\to$ **Tier 3 Execution Worker**, audited by **Tier 2b Cold-Firewall Auditor**).
- **Evidence-Based Capability Scoping:** Generates repository-scoped `.state/pa-skills.json` and `.state/pa-worker-rules.json` manifests at enrollment time, stripping unrelated global personal skills/rules and conflicting interactive plan-gate rules (`01-plan-before-execute.md`) from autonomous workers while preserving 100% of `<repo>/.agents/skills/` and explicitly enrolled domain skills.
- **Dual-Mode Execution (`monitored` vs. `autonomous`):** Supports interactive confirmation prompts (`permissionDecision: "ask"`) when supervised, and upward hierarchical escalation (`Worker` $\to$ `PA` $\to$ `Chief` $\to$ `Human Attention Queue`) when running unattended.
- **Local-Git Floor + Optional GitHub Bus:** Operates offline against a local `.git` repository (`vcs_mode: "local_git"`) using stacked branches and commit trailers (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`), and upgrades to synchronize via GitHub Pull Requests, Reviews, and Issues when a GitHub remote and authenticated `gh` CLI are present (`vcs_mode: "github"`).
- **Clean Memory Boundary (`external` vs. `builtin`):** Defers codebase memory management to `repo-memory-plugin` when detected (`memory_mode: "external"`), and scaffolds the 3-file progressive-reveal memory index (`MEMORY.md`, `MODULE_INDEX.md`, `PROJECT_INDEX.md`) only as a fallback (`memory_mode: "builtin"`).

## Developer Bootstrap

Provision the local `./.venv` virtual environment and install editable runtime + dev dependencies (`pydantic>=2,<3`, `pyyaml>=6`, `pytest`, `ruff`):

```bash
./scripts/dev-bootstrap.sh
```

## Running Tests & Linter

Execute the test suite and linter from the bootstrapped virtual environment:

```bash
./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py
./.venv/bin/ruff check daemon tests
```

## Repository Enrollment & CLI Usage

### Enroll a Repository

Enroll a target repository (initializes `git init` if needed, migrates legacy `.agents/skills/principal-architect-workspace/` to `.agents/plugins/principal-architect-workspace/`, auto-detects `memory_mode` and `vcs_mode`, generates `.state/` capability manifests, initializes `.state/state.db`, updates `.agents/plugins.json`, and registers the repository in `daemon/state/registry.json`):

```bash
./scripts/enroll.sh /path/to/repo
```

Optional enrollment flags:

```bash
./scripts/enroll.sh /path/to/repo \
  --memory-mode auto \
  --vcs-mode auto \
  --extra-skill pio \
  --exclude-rule "custom-rule-*"
```

### Inspect Programme, PR, & Work Order Status

Render the human-readable Programme $\to$ PR $\to$ Work Order tree or machine-readable JSON:

```bash
./.venv/bin/python3 daemon/workspace-plugin/principal-architect/scripts/pa_cli.py status
./.venv/bin/python3 daemon/workspace-plugin/principal-architect/scripts/pa_cli.py status --json
```

### Query or Switch Execution Mode

Get or set the repository execution mode (`monitored` or `autonomous`):

```bash
./.venv/bin/python3 daemon/workspace-plugin/principal-architect/scripts/pa_cli.py mode
./.venv/bin/python3 daemon/workspace-plugin/principal-architect/scripts/pa_cli.py mode autonomous
./.venv/bin/python3 daemon/workspace-plugin/principal-architect/scripts/pa_cli.py mode monitored
```

### Unenroll a Repository

Remove the workspace plugin entry and unregister the repository while preserving all committed files in `.agents/plugins/principal-architect-workspace/`:

```bash
./scripts/unenroll.sh /path/to/repo
```
