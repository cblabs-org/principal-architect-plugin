---
schema_version: 1
wo_id: WO-01.3
pr_id: PR-01
title: "Pydantic v2 Split-Authority models, Markdown frontmatter/section parser, and normative hashes"
complexity: architect
status: COMPLETED
allowed_files:
  - daemon/workspace-plugin/principal-architect/scripts/schemas.py
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
spec_hash: "7c29f211923befd92174483b711dbf39ad1867617e8a8e3d447d176e64c08e8d"
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: "4b3b6d967b22b3c3013d2d34cac5e7ddc768cb2324ac07c5e69396d135e2c0bc"
  commit_sha: "HEAD"
  files_modified:
    - daemon/workspace-plugin/principal-architect/scripts/schemas.py
    - tests/test_schemas.py
  verification_summary: "29 passed in pytest (tests/test_schemas.py + tests/test_state_db_and_sync.py); ruff check passed with 0 errors."
  out_of_scope_findings: []
  escalation_request: null
  decisions_made:
    - "Preserved pre-H2 preamble (H1 titles, metadata tables, HTML comments) as Section(heading='', body=...) so parse_document/dump_document round-trips losslessly."
    - "Supported Document[T], Spec models, file paths, and raw Markdown strings in compute_charter_hash/verify_charter_hash and compute_spec_hash/verify_spec_hash."
  dead_ends: []
---

# WO-01.3 — Split-Authority Schemas, Document Parser/Renderer & Normative Hashing

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-01` (`pr-01-core-schemas-and-enrollment`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T18:50:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/workspace-plugin/principal-architect/scripts/schemas.py` containing all SPEC §6.1–6.4 Pydantic v2 models (`extra="forbid"`), string enums (`PRState`, `WorkOrderStatus`, `ComplexityTier`), `EscalationRequest`, the YAML-frontmatter + H2-section Markdown parser/renderer (`Section`, `Document`, `parse_document`, `dump_document`, `load_program`, `load_project`, `load_workorder`, `load_audit`), and the normative hash functions (`compute_charter_hash`, `compute_spec_hash`, `verify_charter_hash`, `verify_spec_hash`), verified by comprehensive unit and dogfood tests in `tests/test_schemas.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/schemas.py`
  - `tests/test_schemas.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/wo3-schemas-models-and-document-layer/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh`. Commit only on the currently checked-out branch `pr-01-core-schemas-and-enrollment/wo3-schemas-models-and-document-layer` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/schemas.py`:**
  1. **Module Docstring (Charter R2):** State explicitly that `SPEC.md` §6 is normative for all Split-Authority document models and hash algorithms.
  2. **String Enums (Charter R2, §2.2):**
     - `class PRState(str, Enum)`: `PLANNED = "PLANNED"`, `APPROVED = "APPROVED"`, `IN_PROGRESS = "IN_PROGRESS"`, `STAGED_FOR_AUDIT = "STAGED_FOR_AUDIT"`, `CHANGES_REQUESTED = "CHANGES_REQUESTED"`, `AUDIT_APPROVED = "AUDIT_APPROVED"`, `GRADUATED = "GRADUATED"`, `ARCHIVED = "ARCHIVED"`.
     - `class WorkOrderStatus(str, Enum)`: `PENDING = "PENDING"`, `IN_PROGRESS = "IN_PROGRESS"`, `COMPLETED = "COMPLETED"`, `BLOCKED = "BLOCKED"`, `ESCALATED_TO_PA = "ESCALATED_TO_PA"`.
     - `class ComplexityTier(str, Enum)`: `mechanical = "mechanical"`, `standard = "standard"`, `architect = "architect"`, `interactive = "interactive"`.
  3. **Pydantic v2 Models (`model_config = ConfigDict(extra="forbid")`, SPEC §6.1–6.4 & Charter R2):**
     - `PRNodeSpec`:
       - `id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")`
       - `slug: str = Field(..., pattern=r"^pr-\d+[a-z]?-[a-z0-9-]+$")`
       - `title: str = Field(..., min_length=5, max_length=140)`
       - `branch: str = Field(..., min_length=1)`
       - `base_branch: str = "main"`
       - `depends_on: list[str] = Field(default_factory=list)`
       - `allowed_modules: list[str] = Field(..., min_length=1)`
       - `required_skills: list[str] = Field(default_factory=list)`
       - `status: PRState = PRState.PLANNED`
       - `github_pr: int | None = None`
     - `ProgramSpec`:
       - `schema_version: Literal[1] = 1`
       - `programme_id: str = Field(..., pattern=r"^prog-[a-z0-9-]+$")`
       - `title: str = Field(..., min_length=1)`
       - `base_branch: str = "main"`
       - `status: Literal["DRAFT", "APPROVED", "ACTIVE", "COMPLETED"] = "DRAFT"`
       - `prs: list[PRNodeSpec] = Field(default_factory=list)`
     - `PRCharterSpec`:
       - `pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")`
       - `programme_id: str | None = None`
       - `slug: str = Field(..., min_length=1)`
       - `title: str = Field(..., min_length=1)`
       - `branch: str = Field(..., min_length=1)`
       - `base_branch: str = "main"`
       - `depends_on: list[str] = Field(default_factory=list)`
       - `allowed_modules: list[str] = Field(..., min_length=1)`
       - `required_skills: list[str] = Field(default_factory=list)`
       - `verification_floor: list[str] = Field(default_factory=list)`
       - `charter_locked: bool = True`
       - `charter_hash: str | None = None`
     - `WOSummaryRow`:
       - `id: str = Field(..., pattern=r"^WO-\d+[a-z]?\.\d+$")`
       - `slug: str = Field(..., min_length=1)`
       - `title: str = Field(..., min_length=1)`
       - `complexity: ComplexityTier`
       - `status: WorkOrderStatus = WorkOrderStatus.PENDING`
       - `attempts: int = Field(default=0, ge=0)`
       - `commit_sha: str | None = None`
     - `ProjectSpec`:
       - `schema_version: Literal[1] = 1`
       - `charter: PRCharterSpec`
       - `status: PRState = PRState.PLANNED`
       - `approved_at: datetime | None = None`
       - `github_pr: int | None = None`
       - `work_orders: list[WOSummaryRow] = Field(default_factory=list)`
     - `EscalationRequest` (Charter R2):
       - `blocker_type: Literal["structural", "boundary", "charter", "verification", "other"]`
       - `reason_code: str = Field(..., min_length=1)`
       - `target_role: Literal["pa", "chief", "human"]`
       - `requested_files: list[str] = Field(default_factory=list)`
       - `summary: str = Field(..., min_length=1, max_length=500)`
     - `CompletionReport`:
       - `status: WorkOrderStatus`
       - `attempt_num: int = Field(default=1, ge=1, le=5)`
       - `receipt_id: str | None = None`
       - `commit_sha: str | None = None`
       - `files_modified: list[str] = Field(default_factory=list)`
       - `verification_summary: str = Field(..., max_length=280)`
       - `out_of_scope_findings: list[str] = Field(default_factory=list)`
       - `escalation_request: EscalationRequest | None = None`
       - `decisions_made: list[str] = Field(default_factory=list)`
       - `dead_ends: list[str] = Field(default_factory=list)`
     - `WorkOrderSpec`:
       - `schema_version: Literal[1] = 1`
       - `wo_id: str = Field(..., pattern=r"^WO-\d+[a-z]?\.\d+$")`
       - `pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")`
       - `title: str = Field(..., min_length=5, max_length=140)`
       - `complexity: ComplexityTier`
       - `status: WorkOrderStatus = WorkOrderStatus.PENDING`
       - `allowed_files: list[str] = Field(..., min_length=1)`
       - `forbidden_files: list[str] = Field(default_factory=list)`
       - `required_skills: list[str] = Field(default_factory=list)`
       - `verification_command: str = Field(..., min_length=2)`
       - `max_attempts: int = Field(default=5, ge=1, le=5)`
       - `max_structural_failures: int = Field(default=2, ge=1, le=3)`
       - `spec_hash: str | None = None`
       - `completion: CompletionReport | None = None`
     - `AuditFinding`:
       - `id: str = Field(..., pattern=r"^(BLOCKING|NON-BLOCKING)-\d+$")`
       - `axis: Literal["spec_alignment", "invariants", "edge_cases", "test_quality", "scope_hygiene"]`
       - `file_path: str = Field(..., min_length=1)`
       - `line_range: str | None = None`
       - `summary: str = Field(..., min_length=1)`
       - `remediation: str = Field(..., min_length=1)`
     - `AuditReport`:
       - `schema_version: Literal[1] = 1`
       - `pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")`
       - `github_pr: int | None = None`
       - `audit_round: int = Field(..., ge=1, le=5)`
       - `head_sha: str = Field(..., min_length=7, max_length=40)`
       - `auditor_harness: str = "antigravity"`
       - `verdict: Literal["APPROVED", "CHANGES_REQUESTED"]`
       - `findings: list[AuditFinding] = Field(default_factory=list)`
  4. **Document Layer (`Section`, `Document[T]`, `parse_document`, `dump_document`, `load_*`) (Charter G4, R3, §2.2):**
     - `Section` (dataclass or BaseModel): `heading: str`, `body: str`, with helper `full_text() -> str` returning `f"{self.heading}\n{self.body}"` when `self.heading` is non-empty (or `self.heading` if `self.body == ""`), and `self.body` when `self.heading == ""` (used for any preamble before the first `^## ` heading so H1 titles, metadata tables, and HTML comments before `## 1.` round-trip losslessly!).
     - `Document(Generic[T])`: attributes `.spec: T`, `.sections: list[Section]`, `.path: Path | None = None`, and method `.section(prefix: str) -> Section | None` that returns the first `Section` whose `heading.startswith(prefix)` (or `None` if not found).
     - `parse_document(text: str) -> tuple[dict[str, Any], list[Section]]`:
       - Strip optional UTF-8 BOM (`\ufeff`).
       - Verify text starts with a `---` line and contains a closing `---` line; parse the YAML mapping with `yaml.safe_load` (raising `ValueError` if frontmatter delimiter is missing or YAML root is not a `dict`).
       - Split the Markdown remainder on H2 headings using `re.split(r"(?m)^(?=## )", body)`:
         - If the first chunk does not start with `"## "` and is non-empty, store `Section(heading="", body=chunk)`.
         - For each chunk starting with `"## "`, split on the first `"\n"` into `heading` (the `"## ..."` line without newline) and `body` (everything after that newline up to the next `"## "` heading).
     - `dump_document(frontmatter_model: BaseModel | Mapping[str, Any], sections: Sequence[Section]) -> str`:
       - Convert `frontmatter_model` via `.model_dump(mode="json")` if it is a `BaseModel`, else `dict(frontmatter_model)`.
       - Dump YAML via `yaml.safe_dump(fm_dict, sort_keys=False, allow_unicode=True)`.
       - Concatenate `sections` in order using `s.full_text()` (ensuring a clean separator newline after the closing `---` when the first section is an H2 heading, and preserving exact preamble spacing when the first section has `heading == ""`).
     - Typed loaders:
       - `load_program(path: str | Path) -> Document[ProgramSpec]`
       - `load_project(path: str | Path) -> Document[ProjectSpec]`
       - `load_workorder(path: str | Path) -> Document[WorkOrderSpec]`
       - `load_audit(path: str | Path) -> Document[AuditReport]`
       - Also check required H2 section prefixes on load (`PROGRAM.md`: `"## 1."`, `"## 2."`, `"## 3."`; `PROJECT.md`: `"## 1."`, `"## 2."`, `"## 3."`, `"## 4."`; `WORKORDER.md`: at least one Part I H2 section and `"## Completion Report"`), raising `ValueError` if missing.
  5. **Normative Hash Functions (Charter R4, `PROGRAM.md` §2.2(5)):**
     - `canonical_json(data: Mapping[str, Any]) -> str`: `json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
     - `norm_section(text: str) -> str`: `"\n".join(line.rstrip() for line in text.strip().splitlines())`.
     - `compute_charter_hash(target: Document[ProjectSpec] | ProjectSpec | PRCharterSpec | str | Path, sections: Sequence[Section] | None = None) -> str`:
       - Accept a file path (`str | Path`), a `Document[ProjectSpec]`, or `(charter_or_project_spec, sections)`.
       - Extract `charter_dict = charter.model_dump(mode="json", exclude={"charter_hash"})`.
       - Find section `"## 1."` and section `"## 2."` from `sections` (raising `ValueError` if either is missing).
       - Compute `payload = canonical_json(charter_dict) + "\n" + norm_section(sec1.full_text()) + "\n" + norm_section(sec2.full_text())`.
       - Return `hashlib.sha256(payload.encode("utf-8")).hexdigest()`.
     - `verify_charter_hash(target: Document[ProjectSpec] | str | Path) -> bool`:
       - Load `Document[ProjectSpec]` if given a path. If `not doc.spec.charter.charter_hash`, return `False`.
       - Return `compute_charter_hash(doc) == doc.spec.charter.charter_hash`.
     - `compute_spec_hash(target: Document[WorkOrderSpec] | WorkOrderSpec | str | Path, sections: Sequence[Section] | None = None) -> str`:
       - Accept a file path (`str | Path`), a `Document[WorkOrderSpec]`, or `(wo_spec, sections)`.
       - Extract `wo_dict = wo_spec.model_dump(mode="json", exclude={"spec_hash", "status", "completion"})`.
       - Collect all Part I H2 sections (`s.heading.startswith("## ")`) from `sections` before the first section whose `s.heading` starts with `"## Completion Report"` or `"## Part II"` (raising `ValueError` if no Part I H2 sections exist).
       - Compute `payload = canonical_json(wo_dict) + "\n" + "\n".join(norm_section(s.full_text()) for s in part1_sections)`.
       - Return `hashlib.sha256(payload.encode("utf-8")).hexdigest()`.
     - `verify_spec_hash(target: Document[WorkOrderSpec] | str | Path) -> bool`:
       - Load `Document[WorkOrderSpec]` if given a path. If `not doc.spec.spec_hash`, return `False`.
       - Return `compute_spec_hash(doc) == doc.spec.spec_hash`.
- [ ] **`tests/test_schemas.py`:**
  - Comprehensive unit tests covering:
    - Accept and reject (`ValidationError`) cases for every model (`PRNodeSpec`, `ProgramSpec`, `PRCharterSpec`, `WOSummaryRow`, `ProjectSpec`, `EscalationRequest`, `CompletionReport`, `WorkOrderSpec`, `AuditFinding`, `AuditReport`) and every regex/length/range constraint and `extra="forbid"`.
    - `parse_document` and `dump_document` idempotent round-trip (`parse_document(dump_document(model, sections)) == parse_document(original)`), preserving section order, pre-H2 preamble, HTML comments, and unknown H2 sections.
    - `compute_charter_hash` / `verify_charter_hash` and `compute_spec_hash` / `verify_spec_hash` determinism, tamper detection when a frontmatter field or Part I section changes, and invariance when Part II (`## 3.`/`## 4.` in `PROJECT.md`; `status`/`completion`/`## Completion Report` in `WORKORDER.md`) changes.
    - **Dogfood assertions (Charter G4, R12):**
      - Locate the repository's workspace via `common.workspace_dir(common.find_repo_root(__file__))`.
      - Assert `load_program` succeeds on `programme-principal-architect-plugin/PROGRAM.md`.
      - Assert `load_project` succeeds on `pr-01-core-schemas-and-enrollment/PROJECT.md` and `verify_charter_hash` returns `True` (matching `"9005d5135f25ae53fd2ed1b6ee63ece115b521cbaccd4469fd690fb6ca061d1a"`).
      - Assert `load_workorder` and `verify_spec_hash` return `True` on `wo1-dev-bootstrap-and-package-skeleton/WORKORDER.md`, `wo2-common-stdlib-foundations/WORKORDER.md`, and `wo3-schemas-models-and-document-layer/WORKORDER.md`.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute `tree_hash`, update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block — using strictly valid `CompletionReport` keys: `status`, `attempt_num`, `receipt_id`, `commit_sha`, `files_modified`, `verification_summary`, `out_of_scope_findings`, `escalation_request`, `decisions_made`, `dead_ends`) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-01-core-schemas-and-enrollment/wo3-schemas-models-and-document-layer` with message:
   ```text
   WO-01.3: Pydantic v2 Split-Authority models, document parser, and normative hashes

   PA-WorkOrder: WO-01.3
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

### 1. Summary of Changes
- Implemented `daemon/workspace-plugin/principal-architect/scripts/schemas.py` with all SPEC §6.1–6.4 Pydantic v2 models (`PRNodeSpec`, `ProgramSpec`, `PRCharterSpec`, `WOSummaryRow`, `ProjectSpec`, `EscalationRequest`, `CompletionReport`, `WorkOrderSpec`, `AuditFinding`, `AuditReport` with `extra="forbid"`), string enums (`PRState`, `WorkOrderStatus`, `ComplexityTier`), the H2 section parser/renderer (`Section`, `Document[T]`, `parse_document`, `dump_document`, `load_program`, `load_project`, `load_workorder`, `load_audit`), and the normative hash functions (`canonical_json`, `norm_section`, `compute_charter_hash`, `verify_charter_hash`, `compute_spec_hash`, `verify_spec_hash`).
- Implemented `tests/test_schemas.py` covering accept/reject validation for every model and constraint, lossless `parse_document`/`dump_document` round-trips, hash tamper detection and Part II invariance, and dogfood verification on this repository's committed `PROGRAM.md`, `PROJECT.md`, and `WO-01.1`–`WO-01.3` `WORKORDER.md` files.

### 2. Verification Floor Results
- Executed `./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests`: 29 passed, `ruff check` passed with 0 errors.
- Tree Hash (`PA-Verified-Hash`): `4b3b6d967b22b3c3013d2d34cac5e7ddc768cb2324ac07c5e69396d135e2c0bc`

