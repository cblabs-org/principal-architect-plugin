---
schema_version: 1
wo_id: WO-01.5
pr_id: PR-01
title: "Seven Split-Authority and built-in memory .md.tpl templates and validation tests"
complexity: mechanical
status: COMPLETED
allowed_files:
  - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROGRAM.md.tpl
  - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROJECT.md.tpl
  - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/WORKORDER.md.tpl
  - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/AUDIT.md.tpl
  - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/MEMORY.md.tpl
  - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/MODULE_INDEX.md.tpl
  - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROJECT_INDEX.md.tpl
  - daemon/workspace-plugin/principal-architect/scripts/common.py
  - tests/test_schemas.py
forbidden_files:
  - SPEC.md
  - docs/positioning-paper.md
  - .agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/PROJECT.md
  - .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: "./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests"
max_attempts: 5
max_structural_failures: 2
spec_hash: "c50767609a217366f744e9546d52a7d4f8e4de04cfe821062a64170f8e9ac03f"
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: "rcpt-wo01.5-templates"
  commit_sha: null
  files_modified:
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROGRAM.md.tpl
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROJECT.md.tpl
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/WORKORDER.md.tpl
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/AUDIT.md.tpl
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/MEMORY.md.tpl
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/MODULE_INDEX.md.tpl
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROJECT_INDEX.md.tpl
    - daemon/workspace-plugin/principal-architect/scripts/common.py
    - tests/test_schemas.py
  verification_summary: "39 passed in 1.89s, ruff check clean"
  out_of_scope_findings: []
  escalation_request: null
  decisions_made:
    - "Created all seven Split-Authority and built-in memory .md.tpl templates with correct placeholders and section structures."
    - "Added render_template_file helper in common.py."
    - "Added comprehensive test suite for templates and dogfooded WO-01.4 and WO-01.5 work orders in test_schemas.py."
  dead_ends: []
---

# WO-01.5 — Split-Authority & Built-in Memory Templates (`.md.tpl`)

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-01` (`pr-01-core-schemas-and-enrollment`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T18:50:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Create the seven `.md.tpl` templates in `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/` (`PROGRAM.md.tpl`, `PROJECT.md.tpl`, `WORKORDER.md.tpl`, `AUDIT.md.tpl`, `MEMORY.md.tpl`, `MODULE_INDEX.md.tpl`, `PROJECT_INDEX.md.tpl`) with `{{name}}` placeholders, add a `render_template_file` helper to `common.py`, and add template validation tests in `tests/test_schemas.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROGRAM.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROJECT.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/WORKORDER.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/AUDIT.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/MEMORY.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/MODULE_INDEX.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROJECT_INDEX.md.tpl`
  - `daemon/workspace-plugin/principal-architect/scripts/common.py`
  - `tests/test_schemas.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/wo5-templates/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh`. Commit only on the currently checked-out branch `pr-01-core-schemas-and-enrollment/wo5-templates` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R13):** Templates MUST use relative Markdown links only (`PROJECT_INDEX.md`, `MODULE_INDEX.md`, `../pr-.../PROJECT.md`) and never contain absolute machine paths or internal identifiers.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROGRAM.md.tpl`:**
  - YAML frontmatter validating against `ProgramSpec`:
    - `schema_version: 1`
    - `programme_id: {{programme_id}}`
    - `title: "{{title}}"`
    - `base_branch: {{base_branch}}`
    - `status: DRAFT`
    - `prs: []`
  - Markdown body with `# {{title}}` and required H2 sections:
    - `## 1. Architectural Vision & System Invariants`
    - `## 2. Cross-PR Contracts & Interfaces`
    - `## 3. Programme Session Log`
- [ ] **`daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROJECT.md.tpl`:**
  - YAML frontmatter validating against `ProjectSpec`:
    - `schema_version: 1`
    - `charter:` with `pr_id: {{pr_id}}`, `programme_id: {{programme_id}}`, `slug: {{slug}}`, `title: "{{title}}"`, `branch: {{branch}}`, `base_branch: {{base_branch}}`, `depends_on: []`, `allowed_modules: [{{allowed_module}}]`, `required_skills: []`, `verification_floor: ["{{verification_command}}"]`, `charter_locked: true`, `charter_hash: null`
    - `status: PLANNED`
    - `approved_at: null`
    - `github_pr: null`
    - `work_orders: []`
  - Markdown body with `# {{pr_id}} — {{title}}` and required H2 sections:
    - `## 1. PR Charter: Scope, Goals, & Non-Goals`
    - `## 2. Architectural Requirements, Cross-PR Interfaces, & Required Skills/Tools`
    - `## 3. Implementation Plan & Work Order Breakdown`
    - `## 4. Outcome & Session Log`
- [ ] **`daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/WORKORDER.md.tpl`:**
  - YAML frontmatter validating against `WorkOrderSpec`:
    - `schema_version: 1`
    - `wo_id: {{wo_id}}`
    - `pr_id: {{pr_id}}`
    - `title: "{{title}}"`
    - `complexity: {{complexity}}`
    - `status: PENDING`
    - `allowed_files: [{{allowed_file}}]`
    - `forbidden_files: []`
    - `required_skills: []`
    - `verification_command: "{{verification_command}}"`
    - `max_attempts: 5`
    - `max_structural_failures: 2`
    - `spec_hash: null`
    - `completion: null`
  - Markdown body with `# {{wo_id}} — {{title}}`, Part I H2 sections (`## 1. Role & Objective`, `## 2. Strict Boundary Box & Constraints`, `## 3. Line-Item Instructions`, `## 4. Verification, Cryptographic Receipt & Issue Surfacing`), and Part II H2 section (`## Completion Report`).
- [ ] **`daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/AUDIT.md.tpl`:**
  - YAML frontmatter validating against `AuditReport`:
    - `schema_version: 1`
    - `pr_id: {{pr_id}}`
    - `github_pr: {{github_pr}}`
    - `audit_round: {{audit_round}}`
    - `head_sha: "{{head_sha}}"`
    - `auditor_harness: "{{auditor_harness}}"`
    - `verdict: {{verdict}}`
    - `findings: []`
  - Markdown body with `# Cold-Firewall Audit — {{pr_id}} (Round {{audit_round}})`, `**Audit Verdict:** {{verdict}} (0 blocking, 0 major)`, `## 1. Audit Scorecard`, and `## 2. Findings`.
- [ ] **`daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/MEMORY.md.tpl`:**
  - Matches `.agents/skills/principal-architect-workspace/memory/MEMORY.md` structure (with optional `{{updated_at}}` placeholder or clean default):
    - `# Principal Architect Memory`
    - `<!-- Last updated: {{updated_at}} -->`
    - `<!-- memory_mode: builtin -->`
    - `## Active Programs` table (`| Program | Plan | Status |`)
    - `## Active Projects` table (`| Project | Status | Modules | Context |`)
    - `## Recently Completed (last 5)` table (`| Project | Completed | Modules | Key Outcome |`)
    - `## Older Projects` with relative links `[PROJECT_INDEX.md](PROJECT_INDEX.md)` and `[MODULE_INDEX.md](MODULE_INDEX.md)`.
- [ ] **`daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/MODULE_INDEX.md.tpl`:**
  - `# Module Index` with comment block explaining cross-cutting domain reference (`| Project | Scope | Context |`).
- [ ] **`daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROJECT_INDEX.md.tpl`:**
  - `# Project Index` with comment block and chronological archive table (`| Project | Completed | Scope | Session | Context |`).
- [ ] **`daemon/workspace-plugin/principal-architect/scripts/common.py`:**
  - Add `render_template_file(template_name: str, values: Mapping[str, Any] | None = None) -> str` which reads `templates_dir() / template_name` (appending `.md.tpl` if not already ending with `.tpl`) and calls `render_template(text, values or {})`.
- [ ] **`tests/test_schemas.py`:**
  - Add template validation tests (Charter G8):
    - Verify all 7 `.md.tpl` files exist under `common.templates_dir()`.
    - Render `PROGRAM.md.tpl`, `PROJECT.md.tpl`, `WORKORDER.md.tpl`, and `AUDIT.md.tpl` to `tmp_path` with sample placeholder values and assert `load_program`, `load_project`, `load_workorder`, and `load_audit` succeed, and that `compute_charter_hash` and `compute_spec_hash` work on the rendered `PROJECT.md` and `WORKORDER.md`.
    - Render `MEMORY.md.tpl`, `MODULE_INDEX.md.tpl`, and `PROJECT_INDEX.md.tpl` and assert they contain only relative links (`PROJECT_INDEX.md`, `MODULE_INDEX.md`) and no unreplaced `{{...}}` placeholders.
    - Also add `wo4-state-db-and-registry/WORKORDER.md` and `wo5-templates/WORKORDER.md` to the dogfood `load_workorder` / `verify_spec_hash` test!

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute `tree_hash`, update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block — using strictly valid `CompletionReport` keys: `status`, `attempt_num`, `receipt_id`, `commit_sha`, `files_modified`, `verification_summary`, `out_of_scope_findings`, `escalation_request`, `decisions_made`, `dead_ends`) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-01-core-schemas-and-enrollment/wo5-templates` with message:
   ```text
   WO-01.5: Seven Split-Authority and built-in memory .md.tpl templates

   PA-WorkOrder: WO-01.5
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

- **Status:** `COMPLETED`
- **Attempt Number:** 1
- **Receipt ID:** `rcpt-wo01.5-templates`
- **Verification Summary:** `39 passed in 1.89s, ruff check clean`
- **Files Modified:**
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROGRAM.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROJECT.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/WORKORDER.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/AUDIT.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/MEMORY.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/MODULE_INDEX.md.tpl`
  - `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/PROJECT_INDEX.md.tpl`
  - `daemon/workspace-plugin/principal-architect/scripts/common.py`
  - `tests/test_schemas.py`
- **Decisions Made:** Created all 7 Split-Authority and built-in memory `.md.tpl` templates, added `render_template_file` to `common.py`, added comprehensive test coverage in `tests/test_schemas.py`, and dogfooded WO-01.4 and WO-01.5 in tests.
