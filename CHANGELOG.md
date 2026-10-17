# Changelog

All notable changes to `principal-architect-plugin` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-16

### Added

- **Core Schemas, Two-Tier Enrollment & CLI Foundation (`PR-01`):**
  - Self-contained global daemon (`daemon/plugin.json`) and workspace orchestration plugin (`daemon/workspace-plugin/principal-architect/plugin.json`).
  - Zero-dependency `<1ms` stdlib fast-exit enrollment probe (`common.py`) so unenrolled repositories experience zero hook overhead.
  - Fractal Split-Authority Pydantic v2 schemas (`schemas.py`, `extra="forbid"`) for `PROGRAM.md` (`ProgramSpec`), `PROJECT.md` (`ProjectSpec`), `WORKORDER.md` (`WorkOrderSpec` & `CompletionReport`), and `AUDIT-round-<K>.md` (`AuditReport`) with cryptographic SHA-256 `charter_hash` and `spec_hash` integrity locks.
  - Per-repository SQLite WAL state engine (`state_db.py`) managing `programme_state`, `pr_state`, `work_order_state`, `session_bindings`, `verification_receipts`, `audit_history`, and `escalations`.
  - Canonical Markdown templates (`PROGRAM.md.tmpl`, `PROJECT.md.tmpl`, `WORKORDER.md.tmpl`, `AUDIT.md.tmpl`, `MEMORY.md.tmpl`, `MODULE_INDEX.md.tmpl`, `PROJECT_INDEX.md.tmpl`).
  - Core CLI commands (`pa_cli.py`): `pa enroll`, `pa unenroll`, `pa status [--json]`, and `pa mode [monitored|autonomous]`.

- **Role Agents, Escalation Engine & Dual-Mode Hooks R1–R6 (`PR-02`):**
  - Five dedicated role agent definitions (`pa-chief-architect.md`, `pa-principal-architect.md`, `pa-auditor.md`, `pa-critic.md`, `pa-engineer.md`) and `.agents/rules/00-operating-model.md`.
  - Dual-mode upward hierarchical escalation engine (`escalation.py`) supporting `monitored` mode (`permissionDecision: "ask"`) and `autonomous` mode (`permissionDecision: "deny"` + structured `Worker -> PA -> Chief -> Human` escalation records).
  - Four fast-exit lifecycle hooks enforcing Rules R1–R6:
    - `PreInvocation` (`pre_invocation.py`): Session role binding from `PA_ROLE:` / `PR_ID:` / `WO_ID:` headers, `CHECKPOINT` compaction and `/rewind` detection in `transcript.jsonl`, and role-scoped context/skill/memory injection.
    - `PreToolUse` (`pre_tool_gate.py`): Mechanical enforcement of R1 (Architect No-Inline-Code Gate), R1b (Fractal `PROJECT.md` Charter Lock), R2 (Plan Approval Gate), R3 (Worker Strict Boundary Box & `spec_hash` Lock), R4 (Worker Git/GitHub Lockdown), R5 (Auditor Read-Only Lockdown), and R6 (Graduation Audit Gate).
    - `PostToolUse` (`post_tool_receipt.py`): Automatic receipt invalidation on file mutation and cryptographic SHA-256 `tree_hash` verification receipt generation (`rcpt_<hash12>`) when `verification_command` exits `0`.
    - `Stop` (`stop_gate.py`): Completion invariant verification and Two-Tier Retry Policy enforcement (`max_attempts: 5` productive verification attempts vs. fast-fail escalation after `max_structural_failures: 2` structural blockers or `3` consecutive `ERROR_MESSAGE` steps).
  - CLI commands: `pa pr approve-plan`, `pa wo verify`, and `pa escalate`.

- **Local-Git & GitHub Dual VCS Bus, Model Routing & Memory Modes (`PR-03`):**
  - Dual-bus VCS abstraction (`vcs_sync.py`) with offline `LocalGitBus` floor and multi-machine `GitHubBus` upgrade (`gh pr create/view/diff/review`, `gh issue create`).
  - Cryptographic Git commit trailers (`PA-WorkOrder: WO-NN.M`, `PA-Verified-Hash: <tree_hash>`, `PA-Audit-Verdict: <VERDICT> (<head_sha>)`) and machine-parseable `<!-- pa:audit ... -->` GitHub PR review comment envelopes (`gh pr review --comment`, avoiding self-approval blocks).
  - Mutually exclusive memory modes (`memory_grad.py`): zero-touch `external` mode when `cblabs-org/repo-memory-plugin` is active (with Succinct Write-Back validation) vs. `builtin` mode with a 3-file progressive-reveal index (`MEMORY.md` 5-PR rolling window, `PROJECT_INDEX.md`, `MODULE_INDEX.md`).
  - Complexity-based model routing and interactive debugger step-up ladder (`models.py`).
  - CLI commands: `pa sync`, `pa programme init|charter`, `pa pr start|claim|open-or-sync|post-audit|sync-audit|graduate|restack`, `pa wo debug|resolve`, and `pa issue create`.

- **Principal Architect Cockpit AuxPane UI & Host Installer (`PR-04`):**
  - Sidecar AuxPane manifest (`daemon/sidecars/pa_cockpit/sidecar.json` with `SIDECAR_UI_ENTRYPOINT_AUX_PANE` and zero `agent_permissions`).
  - Stdlib `CockpitHTTPServer` (`cockpit.py`) serving 10 REST and Server-Sent Events (`/api/events`) endpoints for live multi-repo status, mode switching, architect model selection, plan approval, escalation resolution, interactive debug launch, and PR graduation.
  - Adaptive host-themed AuxPane frontend (`ui/index.html`, `ui/styles.css`, `ui/app.js`) featuring Top Controls (Zone 1), `🔔 Human Attention Needed` Inbox (Zone 2), and Interactive Programme $\to$ Stacked PR $\to$ Work Order DAG (Zone 3).
  - State-preserving host installer (`scripts/install.sh`), idempotent uninstaller (`scripts/uninstall.sh`), per-repo enrollment wrappers (`scripts/enroll.sh`, `scripts/unenroll.sh`), and comprehensive `README.md`.

- **Dogfood Self-Enrollment, Reconciliation & Verification Suite (`PR-05`):**
  - End-to-end self-enrollment and `pa sync` / `pa status --json` state reconciliation across all 5 stacked PRs (`PR-01`..`PR-05`), 22 Work Orders, and Cold-Firewall audits in `.agents/plugins/principal-architect-workspace/`.
  - Permanent dogfood test suite (`test_dogfood_self_enroll_sync_and_status_on_repo_workspace` in `tests/test_state_db_and_sync.py`, expanding the 6-suite verification floor to 122 passing tests).

### Changed

- **Canonical Workspace Path Migration (`PR-05`):**
  - Migrated the repository's own dogfood workspace from `.agents/skills/principal-architect-workspace/` to `.agents/plugins/principal-architect-workspace/` via `pa enroll`, preserving all cryptographic `charter_hash` and `spec_hash` locks across `PR-01`..`PR-05`.
