---
schema_version: 1
charter:
  pr_id: PR-01
  programme_id: prog-principal-architect-plugin
  slug: pr-01-core-schemas-and-enrollment
  title: "Core Pydantic v2 Split-Authority schemas, SQLite state DB, and pa enroll/unenroll/status"
  branch: feat/pr-01-core-schemas-and-enrollment
  base_branch: main
  depends_on: []
  allowed_modules:
    - pyproject.toml
    - .gitignore
    - README.md
    - scripts/dev-bootstrap.sh
    - scripts/enroll.sh
    - scripts/unenroll.sh
    - daemon/plugin.json
    - daemon/.gitignore
    - daemon/workspace-plugin/principal-architect/plugin.json
    - daemon/workspace-plugin/principal-architect/scripts/__init__.py
    - daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
    - daemon/workspace-plugin/principal-architect/scripts/schemas.py
    - daemon/workspace-plugin/principal-architect/scripts/state_db.py
    - daemon/workspace-plugin/principal-architect/scripts/common.py
    - daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/
    - tests/conftest.py
    - tests/test_schemas.py
    - tests/test_state_db_and_sync.py
  required_skills: []
  verification_floor:
    - "pytest tests/test_schemas.py tests/test_state_db_and_sync.py"
  charter_locked: true
  charter_hash: "9005d5135f25ae53fd2ed1b6ee63ece115b521cbaccd4469fd690fb6ca061d1a"
status: APPROVED
approved_at: "2026-10-16T18:50:00Z"
github_pr: null
work_orders:
  - id: WO-01.1
    slug: wo1-dev-bootstrap-and-package-skeleton
    title: "Developer toolchain bootstrap, pyproject.toml, plugin manifests, and test floor skeleton"
    complexity: standard
    status: COMPLETED
    attempts: 1
    commit_sha: "84c04d8e7c54cde5b3852f3750504e652aed5d44"
  - id: WO-01.2
    slug: wo2-common-stdlib-foundations
    title: "Stdlib-only common.py foundations, fast enrollment check, and shared pytest fixtures"
    complexity: standard
    status: COMPLETED
    attempts: 1
    commit_sha: "0d581381fd4efb2cde52c856df93b4ed00b6b1a7"
  - id: WO-01.3
    slug: wo3-schemas-models-and-document-layer
    title: "Pydantic v2 Split-Authority models, Markdown frontmatter/section parser, and normative hashes"
    complexity: architect
    status: COMPLETED
    attempts: 1
    commit_sha: "555a907322142d339da3acf69b4b1075772b7f35"
  - id: WO-01.4
    slug: wo4-state-db-and-registry
    title: "Repo-local SQLite StateDB (WAL, 5 SPEC §6.5 tables) and global atomic Registry"
    complexity: standard
    status: COMPLETED
    attempts: 1
    commit_sha: "b0a92c14aa7cbf8b68c850548148c2a672f2eccf"
  - id: WO-01.5
    slug: wo5-templates
    title: "Seven Split-Authority and built-in memory .md.tpl templates and validation tests"
    complexity: mechanical
    status: IN_PROGRESS
    attempts: 0
    commit_sha: null
  - id: WO-01.6
    slug: wo6-pa-cli-enroll-unenroll-status-mode
    title: "pa CLI entrypoint (enroll, unenroll, status --json, mode), wrapper scripts, and README"
    complexity: architect
    status: PENDING
    attempts: 0
    commit_sha: null
---

# PR-01 — Core Schemas, State DB & Enrollment

| | |
|---|---|
| **Programme** | [`prog-principal-architect-plugin`](../programme-principal-architect-plugin/PROGRAM.md) · [plan](../programme-principal-architect-plugin/PROGRAM-PLAN.md) |
| **Spec** | [`SPEC.md` v1.1](../../../../SPEC.md) §4 (packaging & enrollment), §6 (schemas & state DB), §8 (`enroll`, `unenroll`, `status`, `mode`) |
| **Base → head** | `main` → `feat/pr-01-core-schemas-and-enrollment` (WO branches: `pr-01-core-schemas-and-enrollment/woM-<topic>`) |
| **Part I owner** | Tier 1 Chief Architect (locked — amendments only via escalation to the Chief) |
| **Part II / III owner** | Tier 2 Principal Architect for PR-01 |

<!-- ======================================================================
     PART I — PR CHARTER (authored by the Tier 1 Chief Architect; locked via charter_hash)
     ====================================================================== -->

## 1. PR Charter: Scope, Goals, & Non-Goals

### 1.1 Scope

PR-01 lays the **contract and state foundation** of `principal-architect-plugin`: the self-contained `daemon/` package skeleton, the Pydantic v2 Split-Authority document models and their Markdown parser/renderer, the SQLite state database and global registry, the stdlib-only `common.py` used by every future hook, the `pa` CLI root with `enroll` / `unenroll` / `status` / `mode`, the seven document templates, the developer toolchain bootstrap, and the two test modules that form this PR's verification floor. Nothing in PR-01 executes as a hook, defines an agent, talks to GitHub beyond remote detection, routes models, graduates memory, or serves UI.

### 1.2 Goals

| # | Goal | Done when |
|---|---|---|
| **G1** | **Package skeleton & dev wrapper.** `daemon/plugin.json` (`"name": "pa-daemon"`), `daemon/workspace-plugin/principal-architect/plugin.json` (`"name": "principal-architect"`), `daemon/.gitignore` (ignores `state/`), root `.gitignore` (`.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `*.db`, `.agents/plugins.json`), `pyproject.toml` (project metadata, `pydantic>=2,<3`, `pyyaml>=6`; `[project.optional-dependencies] dev = ["pytest", "ruff"]`; pytest `testpaths=["tests"]` and `pythonpath=["daemon/workspace-plugin/principal-architect/scripts"]`), and a minimal `README.md` (what it is, bootstrap, run tests, enroll a repo). | Fresh clone + `scripts/dev-bootstrap.sh` + `pytest` collects and passes. |
| **G2** | **Developer toolchain bootstrap.** `scripts/dev-bootstrap.sh` provisions `./.venv` idempotently and installs `-e .[dev]`, choosing in order: `uv` if on `PATH`; else `python3 -m venv` when `ensurepip` is importable; else `python3 -m venv --without-pip` followed by downloading `get-pip.py` into the venv. Prints the activation hint and exits non-zero with a clear diagnostic if no strategy works. | Works on the reference host (Python 3.13, no `pip`, PyPI reachable) and is a no-op on re-run. |
| **G3** | **`schemas.py` — Split-Authority models.** All models of SPEC §6.1–6.4 with the exact field names, defaults, constraints, and regex patterns: `PRNodeSpec`, `ProgramSpec`, `PRCharterSpec`, `WOSummaryRow`, `ProjectSpec`, `CompletionReport`, `WorkOrderSpec`, `AuditFinding`, `AuditReport`; enums `PRState`, `WorkOrderStatus`, `ComplexityTier`; and `EscalationRequest` (see §2.1). All `model_config = ConfigDict(extra="forbid")`. | `tests/test_schemas.py` exercises accept/reject for every model and every pattern-constrained field. |
| **G4** | **`schemas.py` — document parser/renderer & hashing.** A YAML-frontmatter + H2-section document layer: `parse_document(text) -> (frontmatter: dict, sections: list[Section])` preserving section order and unknown sections; typed loaders `load_program / load_project / load_workorder / load_audit(path)`; `dump_document(frontmatter_model, sections) -> str`; and `compute_charter_hash`, `compute_spec_hash`, `verify_charter_hash`, `verify_spec_hash` implementing the normative algorithm in §2.2. | Round-trip `parse(dump(parse(x)))` is stable; `verify_charter_hash()` passes on **this committed file**. |
| **G5** | **`state_db.py` — repo-local SQLite + global registry.** `StateDB(path)` opening `.state/state.db` with `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`, idempotent `init()` creating exactly the five tables of SPEC §6.5 with the listed columns, `PRAGMA user_version` for schema versioning, typed accessors for `repo_config` (`get_config/set_config`), `sessions` (`bind_session/get_session/update_session`), `verification_receipts` (`insert_receipt/invalidate_receipts/latest_valid_receipt`), `escalations` (`insert_escalation/resolve_escalation/open_escalations`), `attention_queue` (`enqueue/dequeue/list_open`); plus `Registry` helpers for `daemon/state/registry.json` (`register/unregister/lookup/list`, atomic write). | `tests/test_state_db_and_sync.py` covers schema creation, idempotency, WAL mode, every accessor, and registry round-trip. |
| **G6** | **`common.py` — stdlib-only foundations.** `find_repo_root(path)`, `workspace_dir(repo_root)` (returns `.agents/plugins/principal-architect-workspace` if present, else legacy `.agents/skills/principal-architect-workspace` if present, else the new path), `daemon_home()` (honours `PA_DAEMON_HOME`, default `~/.gemini/config/plugins/pa-daemon`), `is_repo_enrolled(workspace_paths: list[str]) -> bool` (reads `registry.json` only; **must not import pydantic or yaml**; < 1 ms), `read_transcript(path) -> list[dict]` and `latest_checkpoint_step(steps) -> int | None` for `transcript.jsonl`. | Import-time check in tests: `sys.modules` contains neither `pydantic` nor `yaml` after `import common`. |
| **G7** | **`pa_cli.py` — CLI root and four commands.** `python3 -m` / direct-execution entrypoint with an argparse root, a `COMMAND_MODULES` extension list that later PRs append to, and: `pa enroll [path] [--memory-mode auto\|external\|builtin] [--vcs-mode auto\|github\|local_git] [--extra-skill NAME]... [--exclude-rule PATTERN]...`, `pa unenroll [path]`, `pa status [--json]`, `pa mode [monitored\|autonomous]`. Behaviour exactly per SPEC §4.3 and §8 rows for these commands (see §2.3 for the normative sequence). | Enrollment matrix, migration, idempotency, unenroll, `status --json`, and `mode` are all covered by `tests/test_state_db_and_sync.py`. |
| **G8** | **Templates.** `daemon/workspace-plugin/principal-architect/skills/principal-architect/templates/{PROGRAM,PROJECT,WORKORDER,AUDIT,MEMORY,MODULE_INDEX,PROJECT_INDEX}.md.tpl` whose rendered output (with placeholder substitution) validates against the corresponding `schemas.py` model and carries the required H2 sections of SPEC §6. | A test renders every template with sample values and validates it. |
| **G9** | **Verification floor green, hygiene clean.** `pytest tests/test_schemas.py tests/test_state_db_and_sync.py` passes from `./.venv`; `ruff check` reports no errors on PR-01 modules; no committed file contains an absolute machine path or any identifier that violates programme invariant I10. | Cold-Firewall audit `APPROVED`. |

### 1.3 Non-Goals (explicitly out of scope for PR-01)

- `hooks.json` and any hook entrypoint (`pre_invocation.py`, `pre_tool_gate.py`, `post_tool_receipt.py`, `stop_gate.py`), `escalation.py` — **PR-02**.
- `agents/pa-*.md`, `rules/00-pa-operating-model.md`, the in-plugin `skills/principal-architect/SKILL.md` — **PR-02**.
- `pa pr approve-plan`, `pa wo verify`, `pa escalate`, `pa wo debug/resolve` — **PR-02**.
- `vcs_sync.py` (anything beyond detecting whether a GitHub remote + authenticated `gh` exist), `models.py`, `memory_grad.py` (graduation logic; **scaffolding** the three `memory/` files at enroll time *is* in scope), `pa sync`, `pa programme *`, `pa pr *`, `pa issue *` — **PR-03**.
- `cockpit.py`, `daemon/sidecars/`, `scripts/install.sh`, `scripts/uninstall.sh` — **PR-04**.
- Any change to `SPEC.md` or `docs/` (surface spec defects to the Chief in the Completion Report / Part III; do not edit).
- Any third-party runtime dependency other than `pydantic` and `pyyaml`.

## 2. Architectural Requirements, Cross-PR Interfaces, & Required Skills/Tools

### 2.1 Architectural requirements

| # | Requirement |
|---|---|
| **R1** | **Language & dependencies.** Python `>=3.11` syntax/stdlib only (host reference 3.13); runtime deps strictly `pydantic>=2,<3` and `pyyaml>=6`. `common.py` is stdlib-only (I4). Lazy-import `pydantic`/`yaml` inside `pa_cli.py` command handlers so `pa --help` and future hooks' fast-exit paths stay sub-millisecond. |
| **R2** | **Schema fidelity.** Field names, types, defaults, `Field(...)` constraints, regex patterns, and `Literal` values are exactly those printed in SPEC §6.1–6.4. Enumerations are string enums with at least these members: `PRState` = `PLANNED, APPROVED, IN_PROGRESS, STAGED_FOR_AUDIT, CHANGES_REQUESTED, AUDIT_APPROVED, GRADUATED, ARCHIVED`; `WorkOrderStatus` = `PENDING, IN_PROGRESS, COMPLETED, BLOCKED, ESCALATED_TO_PA`; `ComplexityTier` = `mechanical, standard, architect, interactive`. `EscalationRequest` (not printed in SPEC) must carry at minimum: `blocker_type: Literal["structural","boundary","charter","verification","other"]`, `reason_code: str`, `target_role: Literal["pa","chief","human"]`, `requested_files: list[str] = []`, `summary: str` (`max_length=500`); `extra="forbid"`. The `schemas.py` module docstring must state that SPEC §6 is normative. |
| **R3** | **Document format.** A document is: optional UTF-8 BOM-free text starting with a line `---`, a YAML mapping, a line `---`, then Markdown. Sections are split on H2 headings (`^## `). `dump_document` emits frontmatter via `yaml.safe_dump(sort_keys=False, allow_unicode=True)` followed by sections in order. Unknown sections and HTML comments are preserved verbatim. Section lookup is by heading prefix (`"## 1."`, `"## 2."`, …) so titles may contain punctuation. |
| **R4** | **Normative hash algorithm** (fixed by the Programme Charter §2.2(5); this file is stamped with it): `charter_hash = sha256(canonical_json(charter.model_dump(mode="json", exclude={"charter_hash"})) + "\n" + norm(section "## 1.") + "\n" + norm(section "## 2.")).hexdigest()`, where `canonical_json(d) = json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` and `norm(s)` = the section text from its `## ` heading line up to (not including) the next `## ` heading, `.strip()`-ed, each line `.rstrip()`-ed, joined with `\n`. `spec_hash` is identical in form over `WorkOrderSpec.model_dump(mode="json", exclude={"spec_hash","status","completion"})` and the concatenation of all Part I sections of `WORKORDER.md` (every section before the first heading that starts with `## Completion Report` or the Part II marker). |
| **R5** | **State DB.** WAL + `busy_timeout=5000`; `user_version = 1`; five tables with exactly the columns of SPEC §6.5 (`repo_config`, `sessions`, `verification_receipts`, `escalations`, `attention_queue`); `created_at`/`updated_at` as ISO-8601 UTC strings; all writes in transactions; connection usable as a context manager; no ORM. `Registry` writes `registry.json` atomically (temp file + `os.replace`) with shape `{"schema_version": 1, "repos": {"<abs-repo-root>": {"slug": str, "enrolled_at": str, "workspace_dir": str}}}`. |
| **R6** | **Enrollment detection is injectable and offline-testable.** `vcs_mode` auto-detection = `origin` URL contains `github.com` **and** `gh auth status` exits 0 → `github`, else `local_git`. `memory_mode` auto-detection = `external` if any of: `<repo>/.memory/` exists, `<repo>/.agents/plugins.json` has an entry whose path contains `repo-memory`, or `$HOME/.gemini/config/plugins/repo-memory-daemon/state/registry.json` lists the repo; else `builtin`. Both detectors accept an injectable command runner (and honour `PA_GH_BIN`) so tests never execute the real `gh` or touch the network. Explicit `--memory-mode` / `--vcs-mode` override auto-detection. |
| **R7** | **Generated manifests.** `.state/pa-skills.json` = `{"entries": [{"path": "<abs-repo>/.agents/skills"}] + ([{"path": "<abs-user-config>/skills", "include_only": [extra_skills…]}] if extra_skills)}`; `.state/pa-worker-rules.json` = `{"entries": [{"path": "<abs-repo>/.agents/rules", "exclude": ["01-plan-before-execute.md", "bug-fixer-*"] + exclude_rules}]}`. Extra skills and exclude rules are persisted in `repo_config` (`extra_skills_json`, `exclude_rules_json`) so `pa enroll` re-runs reproduce identical manifests. |
| **R8** | **Legacy migration.** If `<repo>/.agents/skills/principal-architect-workspace/` exists and `<repo>/.agents/plugins/principal-architect-workspace/` does not: `git mv` when tracked, `mv` otherwise; if **both** exist, abort with exit `2` and an explanatory message (never merge silently). Migration is a no-op on re-run. |
| **R9** | **Idempotency & safety.** `pa enroll` twice is a no-op with exit `0`; `pa unenroll` removes only the `.agents/plugins.json` entry and the registry record, never committed files; `.agents/plugins.json` is added to `.git/info/exclude`; the workspace `.gitignore` contains `.state/`; `git init` is run only when `repo_path` is not inside a repository. |
| **R10** | **`pa status`.** Reconciles committed `programme-*/PROGRAM.md`, `pr-*/PROJECT.md`, `pr-*/wo*/WORKORDER.md`, and `pr-*/AUDIT-round-*.md` with `repo_config` and, when available, local git trailers (`git log --format=%(trailers:key=PA-WorkOrder)` etc.). Human output: an indented Programme → PR → WO tree with status glyphs. `--json` output shape (stable, consumed by PR-04): `{"env": {"vcs_mode", "memory_mode", "execution_mode", "workspace_dir"}, "programmes": [...], "prs": [{"pr_id", "slug", "title", "status", "branch", "base_branch", "github_pr", "charter_locked", "work_orders": [...]}], "attention_queue": [...]}`. No GitHub API calls. |
| **R11** | **CLI contract.** stdout = machine output, stderr = diagnostics; exit `0`/`1`/`2` per programme convention; `--help` on every subcommand; `pa` runs both as `python3 -m pa_cli` (with `scripts/` on `PYTHONPATH`) and as a script (it must insert its own directory into `sys.path`). |
| **R12** | **Tests.** `tests/conftest.py` provides fixtures: `tmp_repo` (initialised git repo with an initial commit and configured identity), `daemon_home` (temp `PA_DAEMON_HOME` and isolated `HOME`), and `fake_runner` (records commands, returns scripted results for `git remote get-url origin` and `gh auth status`). Required coverage: every model accept/reject; parser round-trip incl. unknown sections; hash determinism and tamper detection; `verify_charter_hash` on the committed PR-01 `PROJECT.md` located via `common.workspace_dir()`; DB schema/idempotency/WAL/accessors; registry atomic write; enrollment matrix (`external|builtin` × `github|local_git`); manifests content; legacy migration (tracked, untracked, both-exist abort); idempotent re-enroll; unenroll; `status --json` shape; `mode` get/set and rejection of invalid values. |
| **R13** | **Hygiene (I10).** No absolute machine paths in committed files or test fixtures (use `tmp_path`); no personal/employer-internal identifiers, tool names, ticket prefixes, or shortlink schemes anywhere, including commit messages. Templates use relative links only. |

### 2.2 Cross-PR interfaces exported by PR-01 (stability contract)

Downstream PRs may add to these; they may not rename, remove, or change the semantics of anything listed without a Charter amendment.

| Module | Symbol | Contract |
|---|---|---|
| `schemas.py` | `PRState`, `WorkOrderStatus`, `ComplexityTier` | String enums; members as in R2 (additive growth allowed). |
| `schemas.py` | `ProgramSpec`, `PRNodeSpec`, `ProjectSpec`, `PRCharterSpec`, `WOSummaryRow`, `WorkOrderSpec`, `CompletionReport`, `EscalationRequest`, `AuditReport`, `AuditFinding` | SPEC §6 shapes; `extra="forbid"`. |
| `schemas.py` | `Section` (`heading: str`, `body: str`), `parse_document`, `dump_document`, `load_program`, `load_project`, `load_workorder`, `load_audit` | Loaders return a `Document[T]`-style object exposing `.spec` (validated model), `.sections`, `.path`, and `.section(prefix)`. |
| `schemas.py` | `compute_charter_hash`, `compute_spec_hash`, `verify_charter_hash`, `verify_spec_hash` | R4 algorithm; `verify_*` return `bool`. |
| `state_db.py` | `StateDB`, `Registry`, `TABLES` (ordered names) | R5. |
| `common.py` | `find_repo_root`, `workspace_dir`, `daemon_home`, `is_repo_enrolled`, `read_transcript`, `latest_checkpoint_step`, `run` (default subprocess runner with the injectable signature used by R6) | Stdlib-only module. |
| `pa_cli.py` | `build_parser()`, `main(argv) -> int`, `COMMAND_MODULES: list[str]` | Each later module exposes `register(subparsers) -> None`; `build_parser()` imports and calls each entry in `COMMAND_MODULES`. |
| `templates/` | the seven `.tpl` files | Placeholders use `{{name}}` tokens; the rendering helper lives in `pa_cli.py` (or a small `templating` function in `common.py`) and is exported for PR-03's `pa programme init`. |
| `tests/conftest.py` | `tmp_repo`, `daemon_home`, `fake_runner` | Reused by every later test module. |

### 2.3 Normative `pa enroll` sequence (from SPEC §4.3, binding)

1. Resolve `repo_path` (default `.`) → absolute git root; `git init` if not a repository.
2. Legacy migration check (R8).
3. Resolve `memory_mode` (flag or detector, R6); if `builtin`, scaffold `memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}` from templates **only if missing**.
4. Resolve `vcs_mode` (flag or detector, R6).
5. Write `.state/pa-skills.json` and `.state/pa-worker-rules.json` (R7); ensure workspace `.gitignore` contains `.state/`.
6. Initialise `.state/state.db` (R5) and persist `execution_mode` (default `monitored`), `memory_mode`, `vcs_mode`, `extra_skills_json`, `exclude_rules_json`.
7. Write/merge `<repo>/.agents/plugins.json` with the absolute path of `<daemon_home>/workspace-plugin` (deduplicated), add `.agents/plugins.json` to `.git/info/exclude`.
8. Register the repo in `<daemon_home>/state/registry.json`.
9. Print a one-screen summary (modes, paths, next steps) to stderr and exit `0`.

### 2.4 Required skills & tools

| Kind | Item | Notes |
|---|---|---|
| Runtime | `python3` ≥ 3.11 (host: 3.13) | — |
| Dev toolchain | `./.venv` via `scripts/dev-bootstrap.sh` (`uv` → `venv` → `get-pip.py` fallback chain) | Host has no `pip`/`ensurepip`; PyPI reachable. **First Work Order must land this.** |
| Libraries | `pydantic>=2,<3`, `pyyaml>=6`; dev: `pytest`, `ruff` | — |
| CLI | `git` (required), `gh` (optional; mocked in tests) | — |
| Repo skills | none (`required_skills: []`) | This repository ships no `.agents/skills/` domain skills yet. |
| MCP tools | none required | — |

### 2.5 Delivery constraints for the Tier 2 PA

- Decompose into **sequential, single-writer Work Orders** (expected 5–7), each with a tight `allowed_files` subset of `allowed_modules` and a `verification_command` that is the PR floor (earlier WOs may legitimately collect fewer tests, but the command must exit 0 at every WO tip).
- Spawn **exactly one Tier 3 Execution Worker per `WORKORDER.md`**; never execute Work Orders inline.
- Record the user's approval of the Part II decomposition in this file (frontmatter `status: APPROVED`, `approved_at`, and a dated line in §4) **before** the first Worker is spawned.
- At Step 6A: fast-forward `feat/pr-01-core-schemas-and-enrollment` to the final WO tip, report `{tip_branch, head_sha}` to the Chief Architect, and pause for the Cold-Firewall audit. Do not graduate `MEMORY.md` until the audit verdict is `APPROVED`.
- Surface, do not fix, any defect found in `SPEC.md`, `PROGRAM.md`, or this Charter — escalate to the Chief.

<!-- ======================================================================
     PART II — IMPLEMENTATION PLAN & WORK ORDER BREAKDOWN (authored by the Tier 2 Principal Architect)
     ====================================================================== -->

## 3. Implementation Plan & Work Order Breakdown

### 3.1 File-Level Discovery & Sequencing Strategy

Repository inspection at `main` confirms that `SPEC.md` (v1.1), `docs/positioning-paper.md`, `.agents/rules/00-operating-model.md`, and the legacy PA workspace `.agents/skills/principal-architect-workspace/` are committed, while the host Python 3.13 environment lacks system `pip`/`ensurepip`/`pydantic`/`pytest`. Consequently:

1. **Bootstrap first (`WO-01.1`):** Nothing in the verification floor can execute until `scripts/dev-bootstrap.sh` provisions `./.venv` (via `uv` -> `python3 -m venv` -> `python3 -m venv --without-pip` + `get-pip.py` fallback) and installs `-e .[dev]`, paired with the `daemon/` package manifests and initial smoke tests so `pytest tests/test_schemas.py tests/test_state_db_and_sync.py` exits `0` from `WO-01.1` onward.
2. **Stdlib foundations second (`WO-01.2`):** `common.py` provides zero-third-party-import helpers (`find_repo_root`, `workspace_dir` with `.agents/plugins/...` -> `.agents/skills/...` fallback, `daemon_home`, `<1ms` `is_repo_enrolled`, `read_transcript`, `latest_checkpoint_step`, injectable `run`, and `render_template`) plus `tests/conftest.py` fixtures (`tmp_repo`, `daemon_home`, `fake_runner`).
3. **Contracts & hashing third (`WO-01.3`):** `schemas.py` implements all SPEC §6.1–6.4 Pydantic v2 models (`extra="forbid"`), string enums (`PRState`, `WorkOrderStatus`, `ComplexityTier`), `EscalationRequest`, the lossless H2 `Section` document parser/renderer, and the normative `compute_charter_hash` / `compute_spec_hash` / `verify_charter_hash` / `verify_spec_hash` functions, dogfood-verified directly against this committed `PROJECT.md` and `PROGRAM.md`.
4. **Persistence fourth (`WO-01.4`):** `state_db.py` implements `StateDB` (`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; PRAGMA user_version=1;` and all 5 SPEC §6.5 tables with typed transactional accessors) and `Registry` (atomic temp-file + `os.replace` writes to `daemon/state/registry.json`).
5. **Templates fifth (`WO-01.5`):** The seven `.md.tpl` files (`PROGRAM`, `PROJECT`, `WORKORDER`, `AUDIT`, `MEMORY`, `MODULE_INDEX`, `PROJECT_INDEX`) and template rendering helpers, validated against `schemas.py` loaders.
6. **CLI integration sixth (`WO-01.6`):** `pa_cli.py` (`build_parser`, `main`, `COMMAND_MODULES`, lazy heavy imports, and `enroll` / `unenroll` / `status [--json]` / `mode`), `scripts/enroll.sh`, `scripts/unenroll.sh`, `README.md`, and the complete offline enrollment/migration/idempotency/status test matrix.

### 3.2 Work Order Ledger

- **[x] [wo1-dev-bootstrap-and-package-skeleton](wo1-dev-bootstrap-and-package-skeleton/WORKORDER.md)** (`WO-01.1`, `complexity: standard`, base: `main`, commit `84c04d8`): Provision `./.venv` via `scripts/dev-bootstrap.sh`, configure `pyproject.toml`, root and `daemon/` `.gitignore` files, `daemon/plugin.json`, `daemon/workspace-plugin/principal-architect/plugin.json`, `scripts/__init__.py`, and initial test suite skeleton (`tests/conftest.py`, `tests/test_schemas.py`, `tests/test_state_db_and_sync.py`).
- **[x] [wo2-common-stdlib-foundations](wo2-common-stdlib-foundations/WORKORDER.md)** (`WO-01.2`, `complexity: standard`, base: `pr-01-core-schemas-and-enrollment/wo1-dev-bootstrap-and-package-skeleton`, commit `0d58138`): Implement stdlib-only `scripts/common.py` (`find_repo_root`, `workspace_dir`, `daemon_home`, `is_repo_enrolled`, `read_transcript`, `latest_checkpoint_step`, `run`, `render_template`), shared fixtures in `tests/conftest.py` (`tmp_repo`, `daemon_home`, `fake_runner`), and unit/import-purity tests in `tests/test_state_db_and_sync.py`.
- **[x] [wo3-schemas-models-and-document-layer](wo3-schemas-models-and-document-layer/WORKORDER.md)** (`WO-01.3`, `complexity: architect`, base: `pr-01-core-schemas-and-enrollment/wo2-common-stdlib-foundations`, commit `555a907`): Implement `scripts/schemas.py` (all SPEC §6.1–6.4 Pydantic v2 models, enums, `EscalationRequest`, `Section`, `parse_document`, `dump_document`, `load_program`/`load_project`/`load_workorder`/`load_audit`, `compute_charter_hash`, `compute_spec_hash`, `verify_charter_hash`, `verify_spec_hash`) and comprehensive tests in `tests/test_schemas.py` including dogfood verification of this committed `PROJECT.md` and `PROGRAM.md`.
- **[x] [wo4-state-db-and-registry](wo4-state-db-and-registry/WORKORDER.md)** (`WO-01.4`, `complexity: standard`, base: `pr-01-core-schemas-and-enrollment/wo3-schemas-models-and-document-layer`, commit `b0a92c1`): Implement `scripts/state_db.py` (`TABLES`, `StateDB` with WAL + `busy_timeout=5000` + `user_version=1` + typed accessors for all 5 tables, and atomic `Registry`) plus unit tests in `tests/test_state_db_and_sync.py`.
- **[-] [wo5-templates](wo5-templates/WORKORDER.md)** (`WO-01.5`, `complexity: mechanical`, base: `pr-01-core-schemas-and-enrollment/wo4-state-db-and-registry`): Author the seven `.md.tpl` templates (`PROGRAM`, `PROJECT`, `WORKORDER`, `AUDIT`, `MEMORY`, `MODULE_INDEX`, `PROJECT_INDEX`), template helpers in `scripts/common.py`, and template render-and-validate tests in `tests/test_schemas.py`.
- **[ ] [wo6-pa-cli-enroll-unenroll-status-mode](wo6-pa-cli-enroll-unenroll-status-mode/WORKORDER.md)** (`WO-01.6`, `complexity: architect`, base: `pr-01-core-schemas-and-enrollment/wo5-templates`): Implement `scripts/pa_cli.py` (`build_parser`, `main`, `COMMAND_MODULES`, `enroll`, `unenroll`, `status [--json]`, `mode`), `scripts/enroll.sh`, `scripts/unenroll.sh`, `README.md`, and the full offline enrollment/migration/status/mode test suite in `tests/test_state_db_and_sync.py`.

<!-- ======================================================================
     PART III — OUTCOME & GRADUATION SUMMARY (authored by the Tier 2 Principal Architect)
     ====================================================================== -->

## 4. Outcome & Session Log

- **2026-10-16 (`status: APPROVED`):** User approved the full Programme Plan (`PROGRAM.md` `status: APPROVED`) and explicitly authorized autonomous execution and sub-agent spawning across the programme (Decision D11, 2026-10-16). Part II Work Order decomposition (`WO-01.1` through `WO-01.6`) authored and approved under standing user programme authorization (`approved_at: 2026-10-16T18:50:00Z`).
- **2026-10-16 (`WO-01.1 COMPLETED`, `84c04d8`):** Delivered `scripts/dev-bootstrap.sh` (3-strategy fallback: `uv` -> `ensurepip` -> `--without-pip` + `get-pip.py`, verified on reference Python 3.13 host and idempotent on re-run), `pyproject.toml`, root and `daemon/` `.gitignore` files, `daemon/plugin.json`, `daemon/workspace-plugin/principal-architect/plugin.json`, `scripts/__init__.py`, and initial smoke test floor (3 passed, `ruff check` clean).
- **2026-10-16 (`WO-01.2 COMPLETED`, `0d58138`):** Delivered stdlib-only `scripts/common.py` (`find_repo_root`, `workspace_dir` with new -> legacy fallback, `daemon_home`, sub-millisecond `is_repo_enrolled`, `read_transcript`, `latest_checkpoint_step`, `templates_dir`, `render_template`, `run`), shared fixtures in `tests/conftest.py` (`tmp_repo`, `daemon_home`, `fake_runner`), and 12 unit/import-purity tests in `tests/test_state_db_and_sync.py` (15 passed, `ruff check` clean).
- **2026-10-16 (`WO-01.3 COMPLETED`, `555a907`):** Delivered `scripts/schemas.py` (all SPEC §6.1–6.4 Pydantic v2 models with `extra="forbid"`, `PRState`/`WorkOrderStatus`/`ComplexityTier` enums, `EscalationRequest`, `Section`/`Document[T]`/`parse_document`/`dump_document` preserving pre-H2 preambles and unknown sections, `load_program`/`load_project`/`load_workorder`/`load_audit`, and normative `compute_charter_hash`/`verify_charter_hash`/`compute_spec_hash`/`verify_spec_hash`) and 16 test functions in `tests/test_schemas.py` including dogfood verification on this committed `PROJECT.md`, `PROGRAM.md`, and `WO-01.1`–`WO-01.3` (29 passed, `ruff check` clean).
- **2026-10-16 (`WO-01.4 COMPLETED`, `b0a92c1`):** Delivered `scripts/state_db.py` (`TABLES`, `SCHEMA_VERSION = 1`, `StateDB` with WAL mode, `busy_timeout=5000`, `user_version=1`, idempotent `init()`, context manager, and typed accessors for `repo_config`, `sessions`, `verification_receipts`, `escalations`, and `attention_queue`, plus atomic `Registry`) and 9 comprehensive tests in `tests/test_state_db_and_sync.py` (38 passed, `ruff check` clean).
