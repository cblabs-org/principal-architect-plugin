---
name: principal-architect
description: "Three-tier Split-Authority software delivery workflow (Chief Architect -> Principal Architect -> Engineer / Auditor / Debugger) with mechanical PreToolUse/PostToolUse/Stop hook enforcement, stacked Git branches, cryptographic verification receipts, and Cold-Firewall audits."
---

# Principal Architect Skill (`principal-architect`)

This skill defines the workflow and CLI control plane for **Principal Architect Plugin (`principal-architect-plugin`)** — a three-tier Split-Authority architecture that decomposes multi-PR programmes and complex Pull Requests into mechanically bounded Work Orders with cryptographic verification receipts and Cold-Firewall audits.

---

## 1. Three-Tier Split-Authority Architecture

| Tier & Agent | Owned Artifacts & Write Scope | Key Responsibilities |
|---|---|---|
| **Tier 1: `pa-chief-architect`** | `programme-<slug>/PROGRAM.md` + **Part I (`PR Charter`)** of `pr-<slug>/PROJECT.md` (`charter_hash`) | Defines programme vision, invariants, stacked PR DAG, and each PR's `allowed_modules`, `required_skills`, & `verification_floor` (`inheritCustomizations: true` for full skill discovery). |
| **Tier 2: `pa-principal-architect`** | **Part II (`WO Plan`)** & **Part III (`Outcome`)** of `PROJECT.md` + **Part I (`Spec`)** of `wo<M>-<slug>/WORKORDER.md` (`spec_hash`) | Decomposes the locked Charter into single-writer Work Orders, selects `required_skills` per `WORKORDER.md`, dispatches 1 `pa-engineer` per WO, and orchestrates Step 6A/6B audit & graduation (`inheritCustomizations: true`). |
| **Tier 3: `pa-engineer`** | Assigned `allowed_files` + **Part II (`Completion Report`)** of bound `WORKORDER.md` | Isolated (`inheritCustomizations: false`); receives only the exact `required_skills` `SKILL.md` paths injected by `pre_invocation.py`, implements the Work Order checklist, runs `pa wo verify <WO-ID>`, stamps `tree_hash` receipt, and commits `<WO-ID>: <title>`. |
| **Tier 2b: `pa-auditor`** | Read-only + `AUDIT-round-<K>.md` via `pa pr post-audit` | Evaluates the cumulative PR diff cold across `spec_alignment`, `invariants`, `edge_cases`, `test_quality`, and `scope_hygiene`. |
| **Tier 3b: `pa-debugger`** | Active PR scope + `WORKORDER.md` Part II resolution | Interactive root-cause diagnosis after `max_attempts: 5` verification failures, `max_structural_failures: 2` blockers, or `complexity: interactive`. |

---

## 2. Stacked Git Branch Topology

Every Programme and Pull Request follows a deterministic stacked branch hierarchy that works identically in `vcs_mode: "local_git"` (local Git only) and `vcs_mode: "github"` (synchronized with `origin` and `gh` CLI):

```text
main
 └── feat/pr-01-<slug>
      ├── pr-01-<slug>/wo1-<topic>   (committed via `pa wo verify WO-01.1`)
      ├── pr-01-<slug>/wo2-<topic>   (stacked on wo1, committed via `pa wo verify WO-01.2`)
      └── (fast-forward `feat/pr-01-<slug>` to final WO tip -> Step 6A Cold-Firewall Audit)
           └── feat/pr-02-<slug>     (stacked on `feat/pr-01-<slug>`)
```

---

## 3. `pa` CLI Control Plane Reference

| Command | Purpose |
|---|---|
| `pa enroll [path] [--execution-mode {monitored,autonomous}] [--auto-approve-pr-plans \| --no-auto-approve-pr-plans] [--memory-mode {auto,external,builtin}] [--vcs-mode {auto,github,local_git}] [--migrate]` | Enrolls repository, migrates legacy workspace if present, configures `execution_mode`, `memory_mode` (`external` vs `builtin`), and `vcs_mode` (`github` vs `local_git`), writes `.state/pa-skills.json` and `.state/pa-worker-rules.json`, and registers repo in `daemon/state/registry.json`. **When enrolling via an LLM prompt without explicit CLI flags, always follow the `principal-architect-admin` procedure: inspect the repo first, explain each option (`execution_mode`, `memory_mode`, `vcs_mode`, and `--migrate`) and its trade-offs to the user, and call `ask_question` so the user chooses their setup before running `pa enroll`.** |
| `pa migrate [path] [--seed-repo-memory \| --no-seed-repo-memory] [--json]` | Moves or merges legacy `.agents/skills/principal-architect-workspace/` into `.agents/plugins/principal-architect-workspace/`, cleans up `.agents/skills/principal-architect`, rewrites stale path references while preserving `charter_hash`/`spec_hash`, backfills `.state/state.db` via `pa sync`, and seeds `repo-memory` when `memory_mode=external`. |
| `pa unenroll [path]` | Removes workspace plugin entry and unregisters the repository. |
| `pa status [--json]` | Reconciles committed specs, git trailers (`PA-WorkOrder`, `PA-Verified-Hash`), and `.state/state.db`; displays the Programme -> PR -> WO DAG and **Human Attention Needed** queue. |
| `pa mode [monitored\|autonomous]` | Queries or sets `execution_mode` (`monitored` prompts via `ask`; `autonomous` denies out-of-bounds actions and records structured escalations). |
| `pa programme init <slug> --title "<Title>" [--base-branch <branch>]` | **(Tier 1 / Human only)** Scaffolds `.agents/plugins/principal-architect-workspace/programme-<slug>/PROGRAM.md` and binds the Tier 1 Chief Architect conversation. |
| `pa programme charter <PR-ID> [--slug <slug>] [--title "<Title>"] [--allowed-module <path>] [--verification-command "<cmd>"]` | **(Tier 1 / Human only)** Scaffolds or updates Part I (`PR Charter`) of `.agents/plugins/principal-architect-workspace/pr-<XX>-<slug>/PROJECT.md` (inheriting defaults from `PROGRAM.md`), stamps `charter_hash`, and locks Part I. |
| `pa pr start <PR-ID> [--no-spawn]` | **(Tier 1 / Human only — forbidden to Tier 2 `pa`)** Creates/checks out the stacked PR branch, verifies `charter_hash`, and starts (or reuses an existing pinned) Tier 2 Principal Architect conversation. |
| `pa pr claim <PR-ID>` | **(Tier 2 `pa`)** Syncs VCS state, checks out the PR branch, and outputs the Tier 2 PA continuation prompt without spawning a duplicate conversation. |
| `pa pr approve-plan <PR-ID>` | Validates `PROJECT.md` (`charter_hash` integrity) and all `wo*/WORKORDER.md` specs (`allowed_files` within `charter.allowed_modules`), stamps `spec_hash` on each `WORKORDER.md`, sets `PROJECT.md` `status: APPROVED`, and resolves open `plan_approval` items. |
| `pa wo verify <WO-ID>` | Checks working-tree scope hygiene and `spec_hash`, runs `verification_command`, stamps a valid `verification_receipts` row (`rcpt_<tree_hash[:12]>`) in `state.db`, updates `WORKORDER.md` Part II `Completion Report`, and commits with trailers `PA-WorkOrder: <WO-ID>` and `PA-Verified-Hash: <tree_hash>`. |
| `pa escalate` | Records an upward escalation (`--to-pa`, `--to-chief`, or `--to-human`) in `.state/state.db` (`escalations` and `attention_queue`). |

---

## 4. Subagent Spawn Header & Model Routing Protocol

Whenever a Tier 1 Chief Architect or Tier 2 Principal Architect dispatches a subagent via `invoke_subagent`, the prompt **must** begin with the machine-parsed spawn header so `pre_invocation.py` binds the session in `.state/state.db` on Turn 1:

```text
PA_ROLE: engineer
WO_ID: WO-02.1
PR_ID: PR-02
PROGRAMME_ID: prog-example
```

**Complexity-Based Model Routing (`invoke_subagent`):**
- `complexity: mechanical` -> `Model: "flash_lite"`
- `complexity: standard` -> `Model: "flash"`
- `complexity: architect` -> `Model: "inherit"`
- Cold-Firewall Audit (`pa-auditor`) -> `Model: "inherit"`

---

## 5. Step 6A Cold-Firewall Audit & Step 6B Graduation Gates

1. **Step 6A (Cold-Firewall Audit):**
   - After all Work Orders in `PR-ID` are `COMPLETED` and the PR branch is fast-forwarded to the final Work Order tip, spawn `pa-auditor` cold (`PA_ROLE: auditor`, `PR_ID: <PR-ID>`).
   - The Auditor inspects `git diff <base_branch>..HEAD`, runs the `verification_floor`, and publishes `AUDIT-round-<K>.md` (`verdict: "APPROVED"` or `"CHANGES_REQUESTED"`).
   - If `CHANGES_REQUESTED`, author a bounded remediation Work Order (`wo<M+1>-audit-fixes`), dispatch `pa-engineer`, and re-run the Cold-Firewall Audit.
2. **Step 6B (Graduation — Enforced by Rule R6):**
   - `pre_tool_gate.py` blocks `pa pr graduate <PR-ID>` and `gh pr merge` unless an `APPROVED` `AuditReport` exists whose `head_sha` matches the current `HEAD` commit SHA.
   - Upon graduation, update `PROJECT.md` Part III `Outcome & Session Log` (honoring `memory_mode`: succinct mechanical table in `external` mode; full distillation + 3-file `memory/` update in `builtin` mode).
