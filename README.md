# Principal Architect Plugin (`principal-architect-plugin`)

Mechanically enforced, token-efficient, multi-tier orchestration plugin for large software engineering programmes (`SPEC.md` v1.1).

---

## 1. Overview & 3-Tier Operating Model

Large engineering initiatives—spanning multiple stacked pull requests, dozens of files, and strict architectural invariants—routinely fail or burn excessive token budgets when run inside a single monolithic agent session. `principal-architect-plugin` turns the Principal Architect workflow into a deterministic, self-contained Python 3.11+ & Pydantic v2 control plane packaged inside `daemon/`:

### Role Hierarchy

| Role | Agent Handle | Execution Surface | Responsibility & Authority Boundary |
|---|---|---|---|
| **Tier 1: Chief Architect** | `pa-chief-architect` (`pa-chief`) | Pinned Top-Level Conversation (`🏛️ [Chief] <Programme>`) | Owns multi-PR programme discovery, `PROGRAM.md` (including the stacked PR DAG), **Part I of each PR's `PROJECT.md` (`PR Charter`: Scope, Goals, Architectural Requirements, Cross-PR Interfaces, Allowed Modules, & Required Skills/Tools)**, cross-PR escalations, and deferred GitHub Issue creation (`pa issue create`). Mechanically blocked from editing application source code or individual `WORKORDER.md` files. |
| **Tier 2: Principal Architect** | `pa-principal-architect` (`pa-architect`) | Pinned Top-Level Conversation (`📐 [PR-NN] <Title>`) | Owns a single Pull Request (`1 PR = 1 Project`) within the Chief Architect's locked `PR Charter`. Performs file-level PR discovery, authors **Part II of `PROJECT.md` (`Implementation Plan & Work Order Breakdown`)** and sequential `WORKORDER.md` Part I specs, dispatches `pa-engineer` (1 per WO) and `pa-auditor` (Step 6A), reviews diffs, authors **Part III of `PROJECT.md` (`Outcome & Session Log`)**, and runs `pa pr graduate`. Blocked from mutating Part I of `PROJECT.md` or editing source code inline. |
| **Tier 2b: Cold-Firewall PR Auditor** | `pa-auditor` | Isolated Subagent (`invoke_subagent`) or External Session | Stateless adversarial reviewer operating behind an information firewall (receives only `PROGRAM.md`, `PROJECT.md`, and the PR diff via `gh pr diff <N>` or `git diff <base>...<branch>`—never the PA's internal chat history). Evaluates 5 audit axes (`spec_alignment`, `invariants`, `edge_cases`, `test_quality`, `scope_hygiene`, up to `max_audit_rounds: 5`) and publishes `AUDIT-round-<K>.md` via `pa pr post-audit`. Strictly read-only. |
| **Adversarial Plan Critic** | `pa-critic` | Isolated Review Role | Stress-tests PR charters and Work Order decompositions prior to plan lock, ensuring non-overlapping single-writer `allowed_files` boundaries, explicit verification commands, and complete cross-PR contract coverage. |
| **Tier 3: Execution Worker** | `pa-engineer` | Isolated Subagent (`invoke_subagent`, 1 per `WORKORDER.md`) | Ephemeral builder scoped to a single `WORKORDER.md`. Modifies only `allowed_files`, runs `verification_command` (up to `max_attempts: 5`), commits with `<WO-ID>:` prefix + receipt trailers, and authors **Part II of `WORKORDER.md` (`Completion Report`)**. Blocked from mutating Part I of `WORKORDER.md`, touching files outside `allowed_files`, running `git push`/`git checkout`, or spawning subagents. |
| **Tier 3b: Interactive Debugger** | `pa-debugger` | On-Demand Top-Level Conversation (`🔬 [Debug WO-NN.M]`) | Activated when a Work Order is marked `complexity: interactive`, exhausts its 5 productive verification attempts (`max_attempts: 5`), or hits 2 structural blockers (`max_structural_failures: 2`). Pairs with the human engineer to isolate root cause, commit the fix, and resolve via `pa wo resolve`. |

### Fractal Split-Authority Markdown Contracts (`charter_hash` & `spec_hash`)

Every canonical Markdown artifact in `.agents/plugins/principal-architect-workspace/` combines a Pydantic v2-validated YAML frontmatter block (`extra="forbid"`) with structured Markdown sections whose ownership is split between the commissioning tier and the executing tier:

- **`PROGRAM.md` (`ProgramSpec`):** Authored by the Tier 1 Chief Architect; defines programme-wide invariants, cross-PR interfaces, and the stacked PR DAG.
- **`PROJECT.md` (`ProjectSpec`):**
  - **Part I (`PR Charter` — Chief-owned, locked via SHA-256 `charter_hash`):** `charter` frontmatter + `## 1. PR Charter: Scope, Goals, & Non-Goals` + `## 2. Architectural Requirements, Cross-PR Interfaces, & Required Skills/Tools`.
  - **Part II (`Implementation Plan` — PA-owned, locked once `status == APPROVED`):** `work_orders` ledger + `## 3. Implementation Plan & Work Order Breakdown`.
  - **Part III (`Outcome & Graduation Summary` — PA-owned):** `## 4. Outcome & Session Log`.
- **`WORKORDER.md` (`WorkOrderSpec` & `CompletionReport`):**
  - **Part I (`Specification & Boundary Box` — PA-owned, locked via SHA-256 `spec_hash`):** `allowed_files`, `forbidden_files`, `required_skills`, `verification_command`, `max_attempts: 5`, `max_structural_failures: 2`, and Markdown specification sections.
  - **Part II (`Completion Report` — Worker-owned):** `completion` frontmatter (`status`, `attempt_num`, `receipt_id`, `commit_sha`, `files_modified`, `verification_summary`, `out_of_scope_findings`, `escalation_request`) + `## Completion Report`.
- **`AUDIT-round-<K>.md` (`AuditReport`):** Cold-Firewall audit verdict (`APPROVED` or `CHANGES_REQUESTED`) tied cryptographically to `head_sha`.

---

## 2. Two-Tier Installation (`SPEC.md §4.1`)

`principal-architect-plugin` uses a clean **Two-Tier Installation** model so unenrolled repositories experience zero hook overhead (`<1ms` fast-exit).

### Tier 1: Global Host Daemon (`scripts/install.sh` & `scripts/uninstall.sh`)

Install the self-contained `daemon/` package into `~/.gemini/config/plugins/pa-daemon` and symlink the `pa` CLI into `~/.local/bin/pa`:

```bash
./scripts/install.sh
```

- **Environment Overrides:** Both `scripts/install.sh` and `scripts/uninstall.sh` honour:
  - `PA_DAEMON_HOME="${PA_DAEMON_HOME:-$HOME/.gemini/config/plugins/pa-daemon}"`
  - `PA_BIN_DIR="${PA_BIN_DIR:-$HOME/.local/bin}"`
- **State Preservation Across Upgrades:** Re-running `./scripts/install.sh` automatically backs up and restores `<PA_DAEMON_HOME>/state/` (including `<PA_DAEMON_HOME>/state/registry.json`), preserving all enrolled repositories across upgrades.

To uninstall the global daemon and remove the `pa` CLI symlink (idempotent):

```bash
./scripts/uninstall.sh
```

### Tier 2: Per-Repository Opt-In Enrollment (`/principal-architect-admin` or `pa enroll` / `pa unenroll`)

Because `pa-daemon` bundles the lightweight global **`principal-architect-admin`** management skill (`daemon/skills/principal-architect-admin/SKILL.md`), you can enroll any repository directly from chat:

```text
/principal-architect-admin enroll this repo please
```

Or via the `pa` CLI:

```bash
pa enroll /path/to/repo
# or via the convenience wrapper:
./scripts/enroll.sh /path/to/repo
```

Optional enrollment flags and execution mode configuration:

```bash
pa enroll /path/to/repo \
  --memory-mode auto \
  --vcs-mode auto \
  --extra-skill pio \
  --exclude-rule "custom-rule-*"

# Set or query execution mode (monitored | autonomous)
pa mode --path /path/to/repo monitored
pa mode --path /path/to/repo autonomous
```

What `pa enroll` does deterministically:
1. Resolves the target repository's Git root (running `git init` if not yet a Git repository).
2. Migrates any legacy `.agents/skills/principal-architect-workspace/` directory to `.agents/plugins/principal-architect-workspace/` while preserving relative memory links.
3. Auto-detects `memory_mode` (`external` if `cblabs-org/repo-memory-plugin` is present, else `builtin`) and `vcs_mode` (`github` if a GitHub `origin` remote and authenticated `gh` CLI exist, else `local_git`).
4. Generates role-scoped capability manifests `.state/pa-skills.json` (mounting `<repo>/.agents/skills` + `--extra-skill`) and `.state/pa-worker-rules.json` (mounting `<repo>/.agents/rules` while excluding `01-plan-before-execute.md` and `bug-fixer-*` rules that cause autonomous Workers to stall).
5. Initializes `.state/state.db` (SQLite WAL mode), writes `<repo>/.agents/plugins.json` (added to `.git/info/exclude`), and registers the repository in `<PA_DAEMON_HOME>/state/registry.json`.

To unenroll a repository while keeping all committed artifacts in `.agents/plugins/principal-architect-workspace/`:

```bash
pa unenroll /path/to/repo
# or:
./scripts/unenroll.sh /path/to/repo
```

---

## 3. Dual Execution Modes & Hook Enforcement (`SPEC.md §6–§7`)

The workspace plugin registers **4 fast-exit Python hooks** (`<1ms` stdlib-only check via `common.is_repo_enrolled` on unenrolled repositories):

1. **`PreInvocation` (`pre_invocation.py`):** Binds sessions from `PA_ROLE:` / `PR_ID:` / `WO_ID:` headers, detects `CHECKPOINT` context compaction or `/rewind` in `transcript.jsonl`, and injects the active role contract, `allowed_files` boundary box, `required_skills` paths, and memory mode rules.
2. **`PreToolUse` (`pre_tool_gate.py`):** Enforces rules **R1–R6** across file-writing tools, `run_command`, and `invoke_subagent`.
3. **`PostToolUse` (`post_tool_receipt.py`):** Invalidates verification receipts whenever a Worker edits a file, and stamps a cryptographic SHA-256 `tree_hash` verification receipt (`rcpt_<hash12>`) into `.state/state.db` when `verification_command` exits `0`.
4. **`Stop` (`stop_gate.py`):** Refuses premature Worker or Auditor termination (`{"decision": "continue"}`) until all completion invariants and verification receipts are satisfied, while enforcing the **Two-Tier Retry Policy** (`max_attempts: 5` productive attempts vs. fast-fail escalation after `max_structural_failures: 2` structural blockers or `3` consecutive `ERROR_MESSAGE` steps).

### `monitored` vs. `autonomous` Behavior Across Rules R1–R6

| Rule | Trigger Condition | `monitored` Mode | `autonomous` Mode |
|---|---|---|---|
| **R1: Architect No-Inline-Code Gate** | `chief` or `pa` attempts to edit files outside `.agents/plugins/principal-architect-workspace/`. | Returns `permissionDecision: "ask"` for human confirmation. | Returns `permissionDecision: "deny"`; instructs Architect to issue a `WORKORDER.md` and dispatch `pa-engineer`. |
| **R1b: Fractal `PROJECT.md` Charter Lock** | `pa` mutates locked Part I `PR Charter` (`charter_hash` mismatch) or touches files outside `charter.allowed_modules`. | Returns `permissionDecision: "ask"` for Charter amendment confirmation. | Returns `permissionDecision: "deny"`, records `CHARTER_AMENDMENT_NEEDED` (`PA -> Chief`), and instructs PA to run `pa escalate --to-chief`. |
| **R2: Plan Approval Gate** | `pa` calls `invoke_subagent(TypeName: "pa-engineer")` while `PROJECT.md` status is `PLANNED`. | Returns `permissionDecision: "ask"` to approve the Work Order plan. | Enqueues a `plan_approval` item in the **🔔 Human Attention Needed** inbox and denies until approved (unless `auto_approve_pr_plans: true`). |
| **R3: Worker Strict Boundary Box & Spec Lock** | `engineer` writes outside `allowed_files`, touches `forbidden_files`, or edits Part I of `WORKORDER.md` (`spec_hash`). | Returns `permissionDecision: "ask"` to approve expanding `allowed_files`. | Returns `permissionDecision: "deny"`, increments `structural_failures`, logs `BOUNDARY_EXPANSION_NEEDED` (`Worker -> PA`), and directs Worker to escalate in Part II. |
| **R4: Worker Git/GitHub Lockdown** | `engineer` runs `git push`, `git checkout`, `git switch`, `git branch`, `git rebase`, `git reset --hard`, `gh pr *`, or `gh issue *`. | Hard `permissionDecision: "deny"`. | Hard `permissionDecision: "deny"` (increments `structural_failures`). |
| **R5: Auditor Read-Only Lockdown** | `auditor` attempts any file mutation or mutating git/shell command (other than `pa pr post-audit` / test suites). | Hard `permissionDecision: "deny"`. | Hard `permissionDecision: "deny"`. |
| **R6: Graduation Audit Gate** | `pa pr graduate` or `gh pr merge` invoked without an `APPROVED` `AuditReport` matching current `HEAD` SHA. | Returns `permissionDecision: "ask"` warning that `HEAD` lacks Cold-Firewall approval. | Hard `permissionDecision: "deny"`. |

---

## 4. Local-Git Floor + GitHub Multi-Machine Bus (`SPEC.md §8`)

`principal-architect-plugin` operates offline against a local `.git` repository (`vcs_mode: "local_git"`) and automatically upgrades to synchronize across machines and agent harnesses via GitHub Pull Requests, Reviews, and Issues when a GitHub remote is configured (`vcs_mode: "github"`):

- **Stacked Branch Topology:**
  - PR integration branches follow `feat/pr-NN-<slug>` stacked on `main` (or the upstream PR's `feat/pr-MM-<slug>` branch).
  - Work Order branches follow `pr-NN-<slug>/woM-<topic>` branched from the owning PR branch.
- **Cryptographic Git Commit Trailers:**
  - Every verified Work Order commit includes `PA-WorkOrder: WO-NN.M` and `PA-Verified-Hash: <sha256_tree_hash>`.
  - Every Cold-Firewall audit commit includes `PA-Audit-Verdict: APPROVED (<head_sha>)` or `PA-Audit-Verdict: CHANGES_REQUESTED (<head_sha>)`.
- **Canonical Audit & Backlog Artifacts:**
  - Cold-Firewall audits are committed to `.agents/plugins/principal-architect-workspace/pr-<slug>/AUDIT-round-<K>.md` (and posted to GitHub PRs via `gh pr review <N> --comment` containing a machine-parseable `<!-- pa:audit ... -->` block in `github` mode, avoiding GitHub same-account self-approval restrictions).
  - Out-of-scope findings surfaced by Workers are recorded via `pa issue create` into `.agents/plugins/principal-architect-workspace/DEFERRED_BACKLOG.md` in `local_git` mode or filed as labeled GitHub Issues (`pa:deferred`) in `github` mode.
- **Reconciliation & Restacking (`pa sync` & `pa pr restack`):**
  - `pa sync` scans local commit trailers, `WORKORDER.md` completion blocks, `AUDIT-round-<K>.md` files, and (in `github` mode) remote GitHub PR comments to reconstruct `.state/state.db`.
  - `pa pr restack` rebases downstream stacked PR branches (`git rebase --update-refs`) when an upstream PR is amended or merged.

---

## 5. Mutually Exclusive Memory Modes (`SPEC.md §9`)

To prevent duplicate memory harvesting and wasted output tokens, `principal-architect-plugin` enforces a strict boundary controlled by `memory_mode`:

| Mode | Detection / Trigger | Operational Behavior |
|---|---|---|
| **`external` Mode** | Auto-selected when `cblabs-org/repo-memory-plugin` is detected (`.memory/`, `.agents/plugins.json`, or `repo-memory-daemon` registry) or via `--memory-mode external`. | **Zero mutations to `memory/`:** `principal-architect-plugin` never creates, reads, updates, or injects `.agents/plugins/principal-architect-workspace/memory/`. Enforces **Succinct Write-Back Mode** on `WORKORDER.md` (`decisions_made` and `dead_ends` omitted) and `PROJECT.md` so tokens are never wasted duplicating `repo-memory-plugin`. |
| **`builtin` Mode** | Auto-selected when no external memory plugin is present or via `--memory-mode builtin`. | **3-File Progressive-Reveal Index:** Scaffolds and maintains `.agents/plugins/principal-architect-workspace/memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}`. `MEMORY.md` keeps a **5-PR rolling window** of recently completed PRs; on `pa pr graduate`, older completed PRs automatically roll into `PROJECT_INDEX.md` and domain links are appended to `MODULE_INDEX.md`. |

---

## 6. Principal Architect Cockpit AuxPane UI (`SPEC.md §10`)

The global daemon bundles the **Principal Architect Cockpit** AuxPane sidecar (`daemon/sidecars/pa_cockpit/sidecar.json` + `cockpit.py` stdlib `ThreadingHTTPServer` + `ui/{index.html,styles.css,app.js}`), styled dynamically with Antigravity host theme CSS variables (`--background`, `--foreground`, `--card`, `--border`, `--primary`, `--muted-foreground`):

- **Zone 1 — Top Header & Controls:**
  - Workspace selector (auto-switching on `window.sidecar.onWorkspaceChange`), live environment badges (`Git: GitHub | Local`, `Memory: repo-memory | Built-in`), and `[🔄 Sync]` button (`POST /api/sync`).
  - Interactive **`[👀 Monitored]` / `[🤖 Autonomous]`** segmented execution mode toggle (`POST /api/mode`).
  - **Architect Model Selector** (`Gemini 4 Argon (High)`, `Gemini 3.1 Pro (High)`, `Claude Opus 5.5 (High)`).
- **Zone 2 — `🔔 Human Attention Needed` Inbox:**
  - Prioritized action cards for pending human decisions:
    - **Plan Approval:** `[✅ Approve Plan]` (`POST /api/pr/approve-plan`) and `[💬 Open PA]`.
    - **Boundary / Charter Escalation:** `[✅ Approve & Resume]` (expands `allowed_files`, re-stamps `spec_hash`, and resolves the escalation via `POST /api/escalation/resolve`) and `[❌ Deny]`.
    - **Debug Escalation:** `[🔬 Launch Interactive Debug]` (`POST /api/wo/debug`).
    - **Audit Approved — Ready to Graduate:** `[🚀 Graduate PR]` (`POST /api/pr/graduate`).
- **Zone 3 — Interactive Programme $\to$ Stacked PR $\to$ Work Order DAG:**
  - **PR Cards:** Display PR ID, title, `base -> head` branch, lifecycle status pill, `🔒 Charter by Chief` integrity badge, Audit round verdict badge, `[💬 Jump to PA]` button (`window.sidecar.ui.toggleConversation(pr.pa_conversation_id)`), and `[🚀 Graduate PR]`.
  - **Work Order Rows:** Display `WO-ID`, title, `complexity` model badge (`mechanical` $\to$ `flash_lite`, `standard` $\to$ `flash`, `architect` $\to$ `inherit`), `required_skills` pills, attempt counter (`Attempt K/5`), cryptographic receipt badge (`rcpt_xxxx`), `[👁️ Peek Worker]` (`window.sidecar.ui.toggleConversation(wo.subagent_id)`), and `[🔬 Debug]`.

---

## 7. Complete CLI Reference & Verification Floor

### `pa` CLI Reference

| Command | Description |
|---|---|
| `pa enroll [path] [--memory-mode auto\|external\|builtin] [--vcs-mode auto\|github\|local_git] [--extra-skill <name>] [--exclude-rule <glob>]` | Enroll a repository, migrate legacy workspace paths if present, generate `.state/` manifests, initialize `.state/state.db`, and register in `daemon/state/registry.json`. |
| `pa unenroll [path]` | Remove the workspace plugin entry from `.agents/plugins.json` and unregister from `daemon/state/registry.json`. |
| `pa status [path] [--json]` | Reconcile committed specs, local git trailers, and `.state/state.db`; output human-readable tree or `--json`. |
| `pa mode [monitored\|autonomous] [--path <repo>]` | Query or set the repository's `execution_mode` (`monitored` or `autonomous`). |
| `pa sync [path]` | Reconcile git commit trailers (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`), `AUDIT-round-<K>.md` files, and GitHub PR state into `.state/state.db`. |
| `pa programme init <slug> --title "..." [--base-branch main] [--path <repo>]` | Scaffold `programme-<slug>/PROGRAM.md` and bind the Tier 1 Chief Architect session. |
| `pa programme charter <PR-ID> --slug <slug> --title "..." --allowed-module <mod> [--verification-command <cmd>] [--depends-on <PR-ID>] [--required-skill <skill>] [--open-draft] [--path <repo>]` | Author or update Part I (`PR Charter`) of `pr-<slug>/PROJECT.md`, compute `charter_hash`, and lock Part I (`charter_locked: true`). |
| `pa pr start <PR-ID> [--slug <slug>] [--title "..."] [--allowed-module <mod>] [--path <repo>]` | Create/check out the stacked PR branch, verify/scaffold `PROJECT.md`, and start/pin the Tier 2 Principal Architect session. |
| `pa pr claim <PR-ID> [--path <repo>]` | Reconstruct PR & Work Order state across machines/harnesses and emit the Tier 2 PA continuation prompt. |
| `pa pr approve-plan <PR-ID> [--path <repo>]` | Validate `PROJECT.md` Part II and all `wo*/WORKORDER.md` specs, verify `charter_hash`, stamp `spec_hash` on each `WORKORDER.md`, and set `status: APPROVED`. |
| `pa pr open-or-sync <PR-ID> [--draft] [--path <repo>]` | Transition PR to `STAGED_FOR_AUDIT` and create/update the GitHub PR in `github` mode. |
| `pa pr post-audit <PR-ID> --file <audit.md> [--no-commit] [--path <repo>]` | Validate `AuditReport`, write `AUDIT-round-<K>.md`, commit with `PA-Audit-Verdict` trailer, and post `gh pr review --comment` in `github` mode. |
| `pa pr sync-audit <PR-ID> [--path <repo>]` | Sync latest `AuditReport` from `AUDIT-round-<K>.md` or GitHub PR review into `.state/state.db`. |
| `pa pr graduate <PR-ID> [--skip-floor] [--completed-date YYYY-MM-DD] [--path <repo>]` | Verify `APPROVED` audit for current `HEAD` + `verification_floor`, update `memory/` (in `builtin` mode), mark PR `GRADUATED`, and unpin the PA session. |
| `pa pr restack [PR-ID] [--onto <branch>] [--path <repo>]` | Rebase downstream stacked PR branches onto their updated base branches (`git rebase --update-refs`). |
| `pa wo verify <WO-ID> [--path <repo>]` | Verify scope hygiene and `spec_hash`, run `verification_command`, stamp cryptographic `receipt_id` and `tree_hash`, and commit with `PA-WorkOrder` and `PA-Verified-Hash` trailers. |
| `pa wo debug <WO-ID> [--reason "..."] [--path <repo>]` | Transition a blocked Work Order to `BLOCKED` and spawn/pin an interactive `pa-debugger` session. |
| `pa wo resolve <WO-ID> --summary "..." [--path <repo>]` | Verify the fix, record the resolution in `WORKORDER.md`, resolve open escalations, and unpin the debugger session. |
| `pa escalate [--to-pa \| --to-chief \| --to-human] [--pr-id <PR-ID>] [--wo-id <WO-ID>] [--blocker-type <type>] [--reason-code <code>] [--requested-file <path>] --summary "..."` | Record an upward hierarchical escalation in `.state/state.db` and enqueue human attention items when required. |
| `pa issue create --title "..." [--summary "..."] [--pr-id <PR-ID>] [--wo-id <WO-ID>] [--file-path <path>] [--label <label>] [--path <repo>]` | File a `pa:deferred` GitHub Issue (`github` mode) or append to `.agents/plugins/principal-architect-workspace/DEFERRED_BACKLOG.md` (`local_git` mode). |

### Developer Bootstrap & Verification Floor

Provision `./.venv` and run the complete 6-suite verification floor and linter:

```bash
./scripts/dev-bootstrap.sh

./.venv/bin/pytest \
  tests/test_schemas.py \
  tests/test_state_db_and_sync.py \
  tests/test_hooks_monitored_vs_autonomous.py \
  tests/test_github_and_local_git_bus.py \
  tests/test_memory_modes.py \
  tests/test_cockpit_api.py

./.venv/bin/ruff check daemon tests
```

---

## 8. Release & Self-Enrollment Status (v0.1.0)

- **Current Release:** `v0.1.0` (`2026-10-16`) — see [CHANGELOG.md](CHANGELOG.md) for the full release notes across `PR-01` through `PR-05`.
- **Dogfood Self-Enrollment:** `principal-architect-plugin` dogfoods its own 3-tier operating model, Fractal Split-Authority contracts (`charter_hash` and `spec_hash`), Cold-Firewall audit artifacts (`AUDIT-round-1.md`), and cryptographic commit trailers (`PA-WorkOrder`, `PA-Verified-Hash`, `PA-Audit-Verdict`) directly inside [`.agents/plugins/principal-architect-workspace/`](.agents/plugins/principal-architect-workspace/) under programme `programme-principal-architect-plugin` (`PR-01`..`PR-05`).

