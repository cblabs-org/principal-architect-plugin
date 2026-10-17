"""Principal Architect Plugin (c) 2026 Matt McNeill
https://github.com/matthewmcneill/principal-architect-plugin
SPDX-License-Identifier: Apache-2.0
Module: daemon/workspace-plugin/principal-architect/scripts/schemas.py

Canonical Split-Authority document schemas, lossless Markdown parser/renderer,
and normative cryptographic hash computers (`charter_hash` and `spec_hash`).

SPEC.md §6 is normative for all Split-Authority document models (`ProgramSpec`,
`PRNodeSpec`, `ProjectSpec`, `PRCharterSpec`, `WOSummaryRow`, `WorkOrderSpec`,
`CompletionReport`, `EscalationRequest`, `AuditReport`, `AuditFinding`), string
enumerations (`PRState`, `WorkOrderStatus`, `ComplexityTier`), H2 section parsing,
and `charter_hash` / `spec_hash` algorithms.

Exported API Summary:
- _SCRIPTS_DIR: Absolute directory path containing the Principal Architect control-plane scripts.
- PRState: Lifecycle state enumeration for a Pull Request (`PROJECT.md` / `PRNodeSpec`).
- WorkOrderStatus: Execution state enumeration for a Work Order (`WORKORDER.md` / `WOSummaryRow`).
- ComplexityTier: Model routing complexity tier enumeration for a Work Order.
- PRNodeSpec: Pydantic model for a PR node entry inside `PROGRAM.md` (`ProgramSpec.prs`).
- ProgramSpec: Pydantic frontmatter schema for `PROGRAM.md` (SPEC §6.1).
- PRCharterSpec: Pydantic model for Part I of `PROJECT.md` locked via `charter_hash`.
- WOSummaryRow: Pydantic model for a Work Order summary entry in `PROJECT.md`.
- ProjectSpec: Pydantic Split-Authority frontmatter schema for `PROJECT.md` (SPEC §6.2).
- EscalationRequest: Pydantic model for structured upward escalation payloads.
- CompletionReport: Pydantic model for Part II of `WORKORDER.md` authored by `pa-engineer`.
- WorkOrderSpec: Pydantic Split-Authority frontmatter schema for `WORKORDER.md` (SPEC §6.3).
- AuditFinding: Pydantic model for a single Cold-Firewall audit finding inside `AuditReport`.
- AuditReport: Pydantic frontmatter schema for `AUDIT-round-<K>.md` (SPEC §6.4).
- Section: Dataclass representing an H2 Markdown section (or pre-H2 preamble).
- T: Type variable bound to `pydantic.BaseModel` for generic `Document[T]` typing.
- Document: Generic dataclass wrapping validated frontmatter `spec`, `sections`, and `path`.
- _FRONTMATTER_RE: Compiled regular expression matching YAML frontmatter delimited by `---`.
- parse_document: Parse a YAML-frontmatter + H2-section Markdown string into dict and sections.
- dump_document: Serialize a frontmatter model/mapping and ordered sections back to Markdown.
- _require_sections: Validate that a `Document` contains all required H2 section prefixes.
- load_program: Load, parse, and validate a `PROGRAM.md` document from disk.
- load_project: Load, parse, and validate a `PROJECT.md` document from disk.
- load_workorder: Load, parse, and validate a `WORKORDER.md` document from disk.
- load_audit: Load, parse, and validate an `AUDIT-round-<K>.md` document from disk.
- canonical_json: Serialize a dictionary to deterministic canonical JSON for hashing.
- norm_section: Normalize a Markdown section string by stripping outer and trailing whitespace.
- _part1_workorder_sections: Extract Part I H2 sections preceding `## Completion Report`.
- _resolve_project_and_sections: Normalize a target into `(PRCharterSpec, Sequence[Section])`.
- compute_charter_hash: Compute the normative SHA-256 `charter_hash` over Part I of `PROJECT.md`.
- verify_charter_hash: Verify that `charter.charter_hash` matches `compute_charter_hash`.
- _resolve_workorder_and_sections: Normalize a target into `(WorkOrderSpec, Sequence[Section])`.
- compute_spec_hash: Compute the normative SHA-256 `spec_hash` over Part I of `WORKORDER.md`.
- verify_spec_hash: Verify that `wo_spec.spec_hash` matches `compute_spec_hash`.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

# Absolute directory containing the Principal Architect control-plane scripts.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common

common.activate_daemon_venv()

import yaml
from pydantic import BaseModel, ConfigDict, Field


class PRState(str, Enum):
    """Lifecycle states for a Pull Request (`PROJECT.md` / `PRNodeSpec`)."""

    # PR Charter has been drafted; Part II Work Order decomposition is not yet approved.
    PLANNED = "PLANNED"
    # Part II Work Order decomposition is approved and ready for Worker dispatch.
    APPROVED = "APPROVED"
    # One or more Work Orders are actively being executed by Tier 3 Workers.
    IN_PROGRESS = "IN_PROGRESS"
    # All Work Orders are complete and the cumulative PR diff is ready for Cold-Firewall Audit.
    STAGED_FOR_AUDIT = "STAGED_FOR_AUDIT"
    # Cold-Firewall Auditor returned blocking findings requiring remediation Work Orders.
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    # Cold-Firewall Auditor approved the current HEAD SHA for graduation.
    AUDIT_APPROVED = "AUDIT_APPROVED"
    # PR has passed the verification floor and audit gate and has been graduated/merged.
    GRADUATED = "GRADUATED"
    # PR has been superseded or closed without graduation.
    ARCHIVED = "ARCHIVED"


class WorkOrderStatus(str, Enum):
    """Execution states for a Work Order (`WORKORDER.md` / `WOSummaryRow`)."""

    # Work Order is queued and awaiting dispatch to a Tier 3 Worker.
    PENDING = "PENDING"
    # Work Order is currently assigned to an active Tier 3 Worker session.
    IN_PROGRESS = "IN_PROGRESS"
    # Worker finished implementation, stamped a valid verification receipt, and reported completion.
    COMPLETED = "COMPLETED"
    # Work Order is blocked on external dependencies or interactive debugging (`pa-debugger`).
    BLOCKED = "BLOCKED"
    # Worker encountered a boundary or structural blocker and escalated upward to the PA.
    ESCALATED_TO_PA = "ESCALATED_TO_PA"


class ComplexityTier(str, Enum):
    """Model routing complexity tiers for a Work Order."""

    # Routine, deterministic edits suitable for fast/lightweight model tiers.
    mechanical = "mechanical"
    # Standard feature or bug-fix implementation within a bounded module.
    standard = "standard"
    # Multi-file or intricate logic requiring high-reasoning architectural judgment.
    architect = "architect"
    # Hardware-in-the-loop, live debugging, or ambiguous investigation routed to `pa-debugger`.
    interactive = "interactive"


class PRNodeSpec(BaseModel):
    """PR node entry inside `PROGRAM.md` (`ProgramSpec.prs`).

    Defines the stacked branch topology, module boundaries, required skills,
    and lifecycle status for a single Pull Request in a multi-PR programme.
    """

    # Reject unknown frontmatter keys to catch schema drift or typos in YAML specs early.
    model_config = ConfigDict(extra="forbid")

    # Canonical PR identifier (e.g. "PR-1" or "PR-2a").
    id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    # Filesystem-safe slug used for the PR directory name under `prs/`.
    slug: str = Field(..., pattern=r"^pr-\d+[a-z]?-[a-z0-9-]+$")
    # Concise human-readable title summarizing the PR scope.
    title: str = Field(..., min_length=5, max_length=140)
    # Git branch name dedicated to this PR.
    branch: str = Field(..., min_length=1)
    # Parent Git branch onto which this PR is stacked or merged.
    base_branch: str = "main"
    # Upstream PR IDs that must graduate before this PR can merge.
    depends_on: list[str] = Field(default_factory=list)
    # Repository-relative module prefixes or globs authorized for this PR.
    allowed_modules: list[str] = Field(..., min_length=1)
    # Domain skill names mandated for agents working on this PR.
    required_skills: list[str] = Field(default_factory=list)
    # Current lifecycle state of this PR node.
    status: PRState = PRState.PLANNED
    # Associated GitHub Pull Request number, or None in local-only mode.
    github_pr: int | None = None


class ProgramSpec(BaseModel):
    """Frontmatter schema for `PROGRAM.md` (SPEC §6.1).

    Captures the Tier 1 Chief Architect's multi-PR programme DAG, base branch,
    and overall programme lifecycle status.
    """

    # Reject unknown frontmatter keys to catch schema drift or typos in YAML specs early.
    model_config = ConfigDict(extra="forbid")

    # Schema version constant (always 1 for SPEC v1.1).
    schema_version: Literal[1] = 1
    # Unique kebab-case programme identifier prefixed with "prog-".
    programme_id: str = Field(..., pattern=r"^prog-[a-z0-9-]+$")
    # Human-readable programme title.
    title: str = Field(..., min_length=1)
    # Default target base branch for root PRs in the programme DAG.
    base_branch: str = "main"
    # High-level lifecycle status of the programme.
    status: Literal["DRAFT", "APPROVED", "ACTIVE", "COMPLETED"] = "DRAFT"
    # Ordered list of PR nodes comprising the programme DAG.
    prs: list[PRNodeSpec] = Field(default_factory=list)


class PRCharterSpec(BaseModel):
    """Part I of `PROJECT.md`: authored by Tier 1 Chief Architect and locked via `charter_hash`.

    Establishes the immutable architectural boundary box (`allowed_modules`,
    `required_skills`, `verification_floor`) that the Tier 2 Principal Architect
    must honor when decomposing the PR into Work Orders.
    """

    # Enforce strict Part I Charter schema so unauthorized keys cannot bypass charter_hash.
    model_config = ConfigDict(extra="forbid")

    # Canonical PR identifier matching the parent programme node (e.g., "PR-01").
    pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    # Parent programme identifier linking this PR into a multi-PR stacked DAG, or None if standalone.
    programme_id: str | None = None
    # Filesystem-safe PR directory slug under the workspace root (e.g., "pr-01-foundations").
    slug: str = Field(..., min_length=1)
    # Human-readable PR title used in commit subjects and GitHub PR headers.
    title: str = Field(..., min_length=1)
    # Dedicated Git branch where all Work Orders for this PR are committed.
    branch: str = Field(..., min_length=1)
    # Upstream Git branch onto which this PR is stacked and diffed during Cold-Firewall Audit.
    base_branch: str = "main"
    # Upstream PR IDs whose branches must land before this PR can graduate.
    depends_on: list[str] = Field(default_factory=list)
    # Repository-relative directory prefixes or globs defining the PR's outer file boundary (R1b).
    allowed_modules: list[str] = Field(
        ...,
        min_length=1,
        description="Subsystem/module boundaries this PR is authorized to touch",
    )
    # Mandatory domain skills injected on Turn 1 for all Principal Architect and Worker turns.
    required_skills: list[str] = Field(
        default_factory=list,
        description="Skills/tools mandated for this PR (e.g. ['pio', 'framework-expert'])",
    )
    # Minimum test/lint commands executed at PR graduation to guarantee end-to-end health.
    verification_floor: list[str] = Field(
        default_factory=list,
        description="Minimum test/build commands that must pass before PR graduation",
    )
    # When True, `pre_tool_gate.py` blocks Tier 2 PA edits to Part I unless `charter_hash` matches.
    charter_locked: bool = True
    # Normative SHA-256 over Part I frontmatter + Sections 1-2 protecting Chief Architect authority.
    charter_hash: str | None = Field(
        default=None,
        description="SHA-256 of Charter YAML + Sections 1-2 to detect unauthorized PA edits",
    )


class WOSummaryRow(BaseModel):
    """Work Order summary entry in `PROJECT.md` (`ProjectSpec.work_orders`).

    Tracks execution progress, attempt count, and landed commit SHA for each
    sequential Work Order inside the PR's Part II decomposition table.
    """

    # Reject unknown frontmatter keys to catch schema drift or typos in YAML specs early.
    model_config = ConfigDict(extra="forbid")

    # Canonical Work Order identifier (e.g. "WO-1.1" or "WO-2a.3").
    id: str = Field(..., pattern=r"^WO-\d+[a-z]?\.\d+$")
    # Filesystem-safe Work Order slug.
    slug: str = Field(..., min_length=1)
    # Concise summary title for the Work Order.
    title: str = Field(..., min_length=1)
    # Assigned complexity tier controlling agent/model routing.
    complexity: ComplexityTier
    # Current execution status of the Work Order.
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    # Number of execution attempts consumed by Workers so far.
    attempts: int = Field(default=0, ge=0)
    # Git commit SHA produced when the Work Order completed, if landed.
    commit_sha: str | None = None


class ProjectSpec(BaseModel):
    """Split-Authority frontmatter schema for `PROJECT.md` (SPEC §6.2).

    Combines the Tier 1 Chief Architect's locked `PRCharterSpec` (Part I) with
    the Tier 2 Principal Architect's mutable PR status and Work Order ledger (Part II).
    """

    # Reject unknown frontmatter keys to catch schema drift or typos in YAML specs early.
    model_config = ConfigDict(extra="forbid")

    # Schema version constant (always 1 for SPEC v1.1).
    schema_version: Literal[1] = 1
    # Part I PR Charter authored by the Chief Architect.
    charter: PRCharterSpec
    # Overall lifecycle state of the Pull Request.
    status: PRState = PRState.PLANNED
    # UTC timestamp when the Part II Work Order plan was approved.
    approved_at: datetime | None = None
    # Associated GitHub Pull Request number, if synced to a remote.
    github_pr: int | None = None
    # Ordered list of Work Order summary rows decomposing this PR.
    work_orders: list[WOSummaryRow] = Field(default_factory=list)


class EscalationRequest(BaseModel):
    """Structured upward escalation payload recorded by a Worker or PA.

    Captures the blocker category, machine-readable reason code, target authority
    tier, and any out-of-bounds file paths needed to unblock execution.
    """

    # Reject unknown frontmatter keys to catch schema drift or typos in YAML specs early.
    model_config = ConfigDict(extra="forbid")

    # High-level blocker classification determining escalation routing.
    blocker_type: Literal["structural", "boundary", "charter", "verification", "other"]
    # Machine-readable uppercase reason code (e.g. "BOUNDARY_EXPANSION_NEEDED").
    reason_code: str = Field(..., min_length=1)
    # Authority role to which this escalation is directed.
    target_role: Literal["pa", "chief", "human"]
    # Additional repository-relative file paths or globs requested by the caller.
    requested_files: list[str] = Field(default_factory=list)
    # Concise human-readable explanation of why escalation is required.
    summary: str = Field(..., min_length=1, max_length=500)


class CompletionReport(BaseModel):
    """Part II of `WORKORDER.md`: authored by Tier 3 Worker (`pa-engineer`).

    Records the final status, cryptographic verification receipt ID, modified
    files, verification summary, and any upward escalation request.
    """

    # Reject unknown frontmatter keys to catch schema drift or typos in YAML specs early.
    model_config = ConfigDict(extra="forbid")

    # Terminal or escalated status reported by the Worker for this attempt.
    status: WorkOrderStatus
    # 1-based attempt counter (bounded between 1 and 5).
    attempt_num: int = Field(default=1, ge=1, le=5)
    # Verification receipt identifier stamped in SQLite `verification_receipts`.
    receipt_id: str | None = None
    # Git commit SHA created after verification succeeded, if committed.
    commit_sha: str | None = None
    # Repository-relative paths of files created or modified during execution.
    files_modified: list[str] = Field(default_factory=list)
    # Succinct 1-line test/build outcome.
    verification_summary: str = Field(
        ...,
        max_length=280,
        description="Succinct 1-line test/build outcome",
    )
    # Non-blocking observations or defects noticed outside `allowed_files`.
    out_of_scope_findings: list[str] = Field(default_factory=list)
    # Structured upward escalation payload when `status == ESCALATED_TO_PA`.
    escalation_request: EscalationRequest | None = None
    # Key implementation choices made by the Worker within its boundary box.
    decisions_made: list[str] = Field(default_factory=list)
    # Approaches tried and rejected during the attempt to prevent repeat loops.
    dead_ends: list[str] = Field(default_factory=list)


class WorkOrderSpec(BaseModel):
    """Split-Authority frontmatter schema for `WORKORDER.md` (SPEC §6.3).

    Combines the Tier 2 Principal Architect's Part I execution contract (locked
    via `spec_hash`) with the Tier 3 Worker's Part II `CompletionReport`.
    """

    # Enforce strict Work Order frontmatter schema so Workers cannot inject arbitrary keys.
    model_config = ConfigDict(extra="forbid")

    # Schema version constant (always 1 for SPEC v1.1).
    schema_version: Literal[1] = 1
    # Canonical Work Order identifier (e.g., "WO-01.1") binding sessions and verification receipts.
    wo_id: str = Field(..., pattern=r"^WO-\d+[a-z]?\.\d+$")
    # Parent Pull Request identifier whose `allowed_modules` must enclose `allowed_files`.
    pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    # Concise Work Order title displayed in `PROJECT.md` summary tables and Cockpit rows.
    title: str = Field(..., min_length=5, max_length=140)
    # Complexity tier governing Worker model selection (`models.route`) or debugger routing.
    complexity: ComplexityTier
    # Current execution lifecycle status; excluded from `spec_hash` so Workers can transition it.
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    # Repo-relative file paths or globs the Worker is mechanically authorized to edit (R3).
    allowed_files: list[str] = Field(
        ...,
        min_length=1,
        description="Repo-relative file paths or globs Worker may create/modify",
    )
    # Protected paths that override `allowed_files` globs and are unconditionally denied in R3.
    forbidden_files: list[str] = Field(
        default_factory=list,
        description="Explicitly protected paths",
    )
    # Domain skills injected by `pre_invocation.py` on Turn 1 of the Worker's session.
    required_skills: list[str] = Field(
        default_factory=list,
        description="Domain skills (e.g. ['pio', 'framework-expert']) highlighted on Turn 1",
    )
    # Exact verification shell command that must exit 0 on the final file tree to stamp a receipt.
    verification_command: str = Field(
        ...,
        min_length=2,
        description="Shell command that must exit 0 after the final file edit",
    )
    # Maximum productive verification attempts before `stop_gate.py` escalates to `pa-debugger`.
    max_attempts: int = Field(
        default=5,
        ge=1,
        le=5,
        description="Max productive verification attempts before escalating to pa-debugger",
    )
    # Fast-fail threshold for consecutive structural/hook blockers (`STRUCTURAL_SIGNATURES`).
    max_structural_failures: int = Field(
        default=2,
        ge=1,
        le=3,
        description="Fast-fail escalation threshold for structural/hook blockers",
    )
    # Normative SHA-256 over Part I frontmatter + H2 sections preventing Worker contract self-edits.
    spec_hash: str | None = Field(
        default=None,
        description="SHA-256 of Part I Spec to prevent Worker from editing its own contract",
    )
    # Mutable Part II completion report populated by `pa-engineer` (excluded from `spec_hash`).
    completion: CompletionReport | None = None


class AuditFinding(BaseModel):
    """Single Cold-Firewall audit finding entry inside `AuditReport`.

    Represents a blocking or non-blocking defect identified by `pa-auditor`
    along one of the five mandatory review axes.
    """

    # Reject unknown frontmatter keys to catch schema drift or typos in YAML specs early.
    model_config = ConfigDict(extra="forbid")

    # Finding identifier prefixed with severity (e.g. "BLOCKING-1" or "NON-BLOCKING-2").
    id: str = Field(..., pattern=r"^(BLOCKING|NON-BLOCKING)-\d+$")
    # Evaluation axis under which the finding was classified.
    axis: Literal["spec_alignment", "invariants", "edge_cases", "test_quality", "scope_hygiene"]
    # Repository-relative file path where the defect resides.
    file_path: str = Field(..., min_length=1)
    # Optional 1-based line range string (e.g. "L42-L58").
    line_range: str | None = None
    # Concise description of the observed defect or spec deviation.
    summary: str = Field(..., min_length=1)
    # Concrete instructions for remediating the finding in a follow-up Work Order.
    remediation: str = Field(..., min_length=1)


class AuditReport(BaseModel):
    """Frontmatter schema for `AUDIT-round-<K>.md` (SPEC §6.4).

    Published by the read-only Tier 2b Cold-Firewall Auditor (`pa-auditor`)
    evaluating the cumulative PR diff at a specific `head_sha`.
    """

    # Reject unknown frontmatter keys to catch schema drift or typos in YAML specs early.
    model_config = ConfigDict(extra="forbid")

    # Schema version constant (always 1 for SPEC v1.1).
    schema_version: Literal[1] = 1
    # Canonical identifier of the Pull Request being audited.
    pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    # GitHub PR number, or None when operating in local_git mode without a remote.
    github_pr: int | None = Field(
        default=None,
        description="None when operating in local_git mode without a GitHub remote",
    )
    # 1-based audit iteration round number (1 through 5).
    audit_round: int = Field(..., ge=1, le=5)
    # Git commit SHA of the PR branch HEAD evaluated during this audit round.
    head_sha: str = Field(..., min_length=7, max_length=40)
    # Execution harness identifier for the Auditor agent.
    auditor_harness: str = "antigravity"
    # Overall audit decision gating PR graduation (`R6`).
    verdict: Literal["APPROVED", "CHANGES_REQUESTED"]
    # Structured list of blocking and non-blocking findings discovered.
    findings: list[AuditFinding] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Document Layer: Section, Document[T], parse_document, dump_document, load_*
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """Represents a Markdown H2 section (or pre-H2 preamble when `heading == ''`)."""

    # H2 heading line starting with "## " (or empty string "" for pre-H2 preamble text).
    heading: str
    # Raw Markdown body text following the heading line up to the next H2 boundary.
    body: str

    def full_text(self) -> str:
        """Reconstruct the full section text including its H2 heading line.

        Returns:
            Combined `heading` and `body` separated by a newline, or whichever part is non-empty.
        """
        if not self.heading:
            return self.body
        if not self.body:
            return self.heading
        return f"{self.heading}\n{self.body}"


# Generic type variable bound to Pydantic BaseModel for typed Document frontmatter specs.
T = TypeVar("T", bound=BaseModel)


@dataclass
class Document(Generic[T]):
    """Validated Split-Authority Markdown document with typed frontmatter and H2 sections."""

    # Validated Pydantic frontmatter model instance (`ProgramSpec`, `ProjectSpec`, etc.).
    spec: T
    # Ordered list of preamble and H2 `Section` objects preserving original Markdown structure.
    sections: list[Section]
    # Optional filesystem path from which the document was loaded.
    path: Path | None = None

    def section(self, prefix: str) -> Section | None:
        """Return the first section whose heading starts with `prefix`, or `None`.

        Args:
            prefix: Heading prefix string to match (e.g., `"## 1."` or `"## Completion Report"`).

        Returns:
            First matching `Section` instance, or `None` if no heading starts with `prefix`.
        """
        for sec in self.sections:
            if sec.heading.startswith(prefix):
                return sec
        return None


# Multiline regex matching a leading YAML frontmatter block delimited by `---` fences.
_FRONTMATTER_RE = re.compile(
    r"^---[ \t]*\r?\n(.*?)^---[ \t]*(?:\r?\n|\Z)",
    flags=re.DOTALL | re.MULTILINE,
)


def parse_document(text: str) -> tuple[dict[str, Any], list[Section]]:
    """Parse a YAML-frontmatter + H2-section Markdown document.

    Preserves section order, pre-H2 preamble (H1 title, metadata tables, HTML comments),
    and unknown H2 sections for lossless round-tripping.

    Args:
        text: Raw UTF-8 Markdown document content beginning with a `---` YAML frontmatter block.

    Returns:
        A 2-tuple of `(frontmatter_dict, sections_list)`.

    Raises:
        ValueError: If `text` lacks a valid leading YAML frontmatter block or if the YAML root
            is not a mapping (`dict`).
    """
    # --- Step 1: Strip optional UTF-8 BOM and extract the leading YAML frontmatter block ---
    # Strip any leading UTF-8 Byte Order Mark (\ufeff) so ^--- anchors at index 0.
    text = text.removeprefix("\ufeff")

    fm_match = _FRONTMATTER_RE.match(text)
    if not fm_match:
        raise ValueError("Document must begin with a YAML frontmatter block delimited by '---'")

    fm_raw = fm_match.group(1)
    fm_data = yaml.safe_load(fm_raw)
    if not isinstance(fm_data, dict):
        raise ValueError("YAML frontmatter root must be a mapping (dict)")  # noqa: TRY004

    # --- Step 2: Split the remaining Markdown body on H2 boundaries via zero-width lookahead ---
    body = text[fm_match.end() :].lstrip("\r\n")
    # Zero-width multiline lookahead splits right before each line starting with "## "
    # while keeping the "## " heading prefix attached to the start of its chunk.
    chunks = re.split(r"(?m)^(?=## )", body)

    # --- Step 3: Classify each chunk into either an H2 Section or a pre-H2 preamble Section ---
    sections: list[Section] = []
    for chunk in chunks:
        if not chunk:
            continue
        if chunk.startswith("## "):
            if "\n" in chunk:
                heading, sec_body = chunk.split("\n", 1)
            else:
                heading, sec_body = chunk, ""
            sections.append(Section(heading=heading.rstrip("\r"), body=sec_body))
        elif chunk.strip():
            sections.append(Section(heading="", body=chunk))

    return fm_data, sections


def dump_document(
    frontmatter_model: BaseModel | Mapping[str, Any],
    sections: Sequence[Section],
) -> str:
    """Serialize a Pydantic model (or mapping) and ordered sections back to Markdown.

    Args:
        frontmatter_model: Validated Pydantic `BaseModel` or raw dictionary for YAML frontmatter.
        sections: Ordered sequence of `Section` objects to render after the frontmatter block.

    Returns:
        Formatted Markdown string containing the `---` YAML block followed by all sections.
    """
    # --- Step 1: Convert frontmatter to a JSON-compatible dictionary and dump to YAML ---
    if isinstance(frontmatter_model, BaseModel):
        fm_dict = frontmatter_model.model_dump(mode="json")
    else:
        fm_dict = dict(frontmatter_model)

    yaml_str = yaml.safe_dump(fm_dict, sort_keys=False, allow_unicode=True).rstrip("\n")

    # --- Step 2: Concatenate section texts while preserving inter-section newline boundaries ---
    parts: list[str] = []
    for idx, sec in enumerate(sections):
        chunk = sec.full_text()
        if idx < len(sections) - 1 and not chunk.endswith("\n"):
            chunk += "\n"
        parts.append(chunk)

    body_str = "".join(parts)
    if body_str and not body_str.endswith("\n"):
        body_str += "\n"

    # --- Step 3: Assemble the final YAML frontmatter fence and Markdown body ---
    if body_str:
        return f"---\n{yaml_str}\n---\n\n{body_str}"
    return f"---\n{yaml_str}\n---\n"


def _require_sections(doc: Document[Any], required_prefixes: Sequence[str], kind: str) -> None:
    """Verify that `doc` contains an H2 section matching each prefix in `required_prefixes`.

    Args:
        doc: Parsed `Document` instance to inspect.
        required_prefixes: Sequence of H2 heading prefixes that must be present.
        kind: Document type label (e.g., `"PROGRAM.md"`) used in error messages.

    Raises:
        ValueError: If any required H2 section prefix is missing from `doc`.
    """
    for prefix in required_prefixes:
        if doc.section(prefix) is None:
            raise ValueError(f"{kind} is missing required H2 section starting with '{prefix}'")


def load_program(path: str | Path) -> Document[ProgramSpec]:
    """Load and validate a `PROGRAM.md` file from disk.

    Args:
        path: Filesystem path to `PROGRAM.md`.

    Returns:
        Validated `Document[ProgramSpec]` containing parsed frontmatter and H2 sections.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If frontmatter parsing, Pydantic validation, or required H2 check fails.
    """
    p = Path(path)
    fm_data, sections = parse_document(p.read_text(encoding="utf-8"))
    spec = ProgramSpec.model_validate(fm_data)
    doc = Document(spec=spec, sections=sections, path=p)
    _require_sections(doc, ("## 1.", "## 2.", "## 3."), "PROGRAM.md")
    return doc


def load_project(path: str | Path) -> Document[ProjectSpec]:
    """Load and validate a `PROJECT.md` file from disk.

    Args:
        path: Filesystem path to `PROJECT.md`.

    Returns:
        Validated `Document[ProjectSpec]` containing parsed frontmatter and H2 sections.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If frontmatter parsing, Pydantic validation, or required H2 check fails.
    """
    p = Path(path)
    fm_data, sections = parse_document(p.read_text(encoding="utf-8"))
    spec = ProjectSpec.model_validate(fm_data)
    doc = Document(spec=spec, sections=sections, path=p)
    _require_sections(doc, ("## 1.", "## 2.", "## 3.", "## 4."), "PROJECT.md")
    return doc


def load_workorder(path: str | Path) -> Document[WorkOrderSpec]:
    """Load and validate a `WORKORDER.md` file from disk.

    Args:
        path: Filesystem path to `WORKORDER.md`.

    Returns:
        Validated `Document[WorkOrderSpec]` containing parsed frontmatter and H2 sections.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If frontmatter validation fails or Part I / `## Completion Report` is missing.
    """
    p = Path(path)
    fm_data, sections = parse_document(p.read_text(encoding="utf-8"))
    spec = WorkOrderSpec.model_validate(fm_data)
    doc = Document(spec=spec, sections=sections, path=p)
    part1 = _part1_workorder_sections(sections)
    if not part1:
        raise ValueError("WORKORDER.md requires at least one Part I H2 section")
    if doc.section("## Completion Report") is None:
        raise ValueError("WORKORDER.md is missing required H2 section '## Completion Report'")
    return doc


def load_audit(path: str | Path) -> Document[AuditReport]:
    """Load and validate an `AUDIT-round-<K>.md` file from disk.

    Args:
        path: Filesystem path to the audit report Markdown file.

    Returns:
        Validated `Document[AuditReport]` containing parsed frontmatter and H2 sections.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If frontmatter parsing or `AuditReport` Pydantic validation fails.
    """
    p = Path(path)
    fm_data, sections = parse_document(p.read_text(encoding="utf-8"))
    spec = AuditReport.model_validate(fm_data)
    return Document(spec=spec, sections=sections, path=p)


# ---------------------------------------------------------------------------
# Normative Hashing: charter_hash & spec_hash
# ---------------------------------------------------------------------------


def canonical_json(data: Mapping[str, Any]) -> str:
    """Serialize a dictionary to deterministic canonical JSON for cryptographic hashing.

    Uses sorted keys, compact `(",", ":")` separators, and unescaped UTF-8 characters.

    Args:
        data: Mapping of frontmatter fields to serialize.

    Returns:
        Deterministic canonical JSON string.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def norm_section(text: str) -> str:
    """Normalize a Markdown section string by stripping outer whitespace and trailing line spaces.

    Args:
        text: Raw section text (including its H2 heading line).

    Returns:
        Normalized LF-joined string immune to trailing whitespace or CRLF variations.
    """
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _part1_workorder_sections(sections: Sequence[Section]) -> list[Section]:
    """Return all Part I H2 sections appearing before `## Completion Report` or `## Part II`.

    Args:
        sections: Full sequence of parsed `Section` objects from a `WORKORDER.md` document.

    Returns:
        Ordered list of H2 `Section` objects belonging to Part I (the Principal Architect's spec).
    """
    part1: list[Section] = []
    for sec in sections:
        if sec.heading.startswith("## Completion Report") or sec.heading.startswith("## Part II"):
            break
        if sec.heading.startswith("## "):
            part1.append(sec)
    return part1


def _resolve_project_and_sections(
    target: Document[ProjectSpec] | ProjectSpec | PRCharterSpec | str | Path,
    sections: Sequence[Section] | None = None,
) -> tuple[PRCharterSpec, Sequence[Section]]:
    """Normalize a flexible project/charter target into `(PRCharterSpec, Sequence[Section])`.

    Accepts a loaded `Document[ProjectSpec]`, raw Markdown text, a filesystem path,
    a `ProjectSpec`, or a `PRCharterSpec`.

    Args:
        target: Project document, spec model, raw Markdown string, or file path.
        sections: Optional explicit sequence of `Section` objects overriding `target`'s sections.

    Returns:
        A 2-tuple of `(PRCharterSpec, resolved_sections)`.

    Raises:
        ValueError: If `target` is a model instance (`ProjectSpec` or `PRCharterSpec`) and
            `sections` was not supplied, or if a parsed document is invalid.
        TypeError: If `target` is not one of the supported types.
    """
    # --- Step 1: Handle pre-parsed Document[ProjectSpec] instances ---
    if isinstance(target, Document):
        charter = target.spec.charter
        resolved_sections = sections if sections is not None else target.sections
        return charter, resolved_sections

    # --- Step 2: Handle raw Markdown strings (starting with '---') or filesystem paths ---
    if isinstance(target, (str, Path)):
        # Strip optional UTF-8 BOM before checking for inline YAML frontmatter fence.
        if isinstance(target, str) and target.lstrip("\ufeff").startswith("---"):
            fm_data, parsed_sections = parse_document(target)
            spec = ProjectSpec.model_validate(fm_data)
            return spec.charter, (sections if sections is not None else parsed_sections)
        doc = load_project(target)
        return doc.spec.charter, (sections if sections is not None else doc.sections)

    # --- Step 3: Handle bare ProjectSpec or PRCharterSpec models requiring explicit sections ---
    if isinstance(target, ProjectSpec):
        if sections is None:
            raise ValueError("sections must be provided when target is a ProjectSpec")
        return target.charter, sections

    if isinstance(target, PRCharterSpec):
        if sections is None:
            raise ValueError("sections must be provided when target is a PRCharterSpec")
        return target, sections

    raise TypeError(f"Unsupported target type for charter hash: {type(target)!r}")


def compute_charter_hash(
    target: Document[ProjectSpec] | ProjectSpec | PRCharterSpec | str | Path,
    sections: Sequence[Section] | None = None,
) -> str:
    """Compute the normative SHA-256 `charter_hash` over Part I of `PROJECT.md`.

    Assembles the canonical preimage from `charter` (excluding `charter_hash` itself)
    plus normalized H2 sections `## 1.` and `## 2.`, preventing unauthorized Part I
    modifications by Tier 2 or Tier 3 agents.

    Args:
        target: `Document[ProjectSpec]`, `ProjectSpec`, `PRCharterSpec`, Markdown string, or path.
        sections: Optional explicit sequence of `Section` objects when `target` is a model.

    Returns:
        64-character lowercase hexadecimal SHA-256 digest string.

    Raises:
        ValueError: If required Part I sections `## 1.` or `## 2.` are missing.
        TypeError: If `target` is an unsupported type.
    """
    # --- Step 1: Resolve PRCharterSpec and validate presence of Part I H2 sections 1 and 2 ---
    charter, resolved_sections = _resolve_project_and_sections(target, sections)
    sec1 = next((s for s in resolved_sections if s.heading.startswith("## 1.")), None)
    sec2 = next((s for s in resolved_sections if s.heading.startswith("## 2.")), None)
    if sec1 is None or sec2 is None:
        raise ValueError("PROJECT.md charter_hash requires sections '## 1.' and '## 2.'")

    # --- Step 2: Assemble deterministic SHA-256 preimage excluding charter_hash itself ---
    # Normative preimage: canonical_json(charter \ {charter_hash}) + "\n" + norm(§1) + "\n" + norm(§2)
    charter_dict = charter.model_dump(mode="json", exclude={"charter_hash"})
    payload = (
        canonical_json(charter_dict)
        + "\n"
        + norm_section(sec1.full_text())
        + "\n"
        + norm_section(sec2.full_text())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_charter_hash(
    target: Document[ProjectSpec] | ProjectSpec | PRCharterSpec | str | Path,
    sections: Sequence[Section] | None = None,
) -> bool:
    """Verify that `charter.charter_hash` is present and matches `compute_charter_hash`.

    Args:
        target: `Document[ProjectSpec]`, `ProjectSpec`, `PRCharterSpec`, Markdown string, or path.
        sections: Optional explicit sequence of `Section` objects when `target` is a model.

    Returns:
        `True` if `charter_hash` is non-empty and matches the computed SHA-256 digest; `False`
        otherwise.
    """
    charter, resolved_sections = _resolve_project_and_sections(target, sections)
    if not charter.charter_hash:
        return False
    return compute_charter_hash(charter, resolved_sections) == charter.charter_hash


def _resolve_workorder_and_sections(
    target: Document[WorkOrderSpec] | WorkOrderSpec | str | Path,
    sections: Sequence[Section] | None = None,
) -> tuple[WorkOrderSpec, Sequence[Section]]:
    """Normalize a flexible Work Order target into `(WorkOrderSpec, Sequence[Section])`.

    Accepts a loaded `Document[WorkOrderSpec]`, raw Markdown text, a filesystem path,
    or a `WorkOrderSpec` model instance.

    Args:
        target: Work Order document, `WorkOrderSpec` model, raw Markdown string, or file path.
        sections: Optional explicit sequence of `Section` objects overriding `target`'s sections.

    Returns:
        A 2-tuple of `(WorkOrderSpec, resolved_sections)`.

    Raises:
        ValueError: If `target` is a `WorkOrderSpec` and `sections` was not provided, or if
            document validation fails.
        TypeError: If `target` is not one of the supported types.
    """
    # --- Step 1: Handle pre-parsed Document[WorkOrderSpec] instances ---
    if isinstance(target, Document):
        return target.spec, (sections if sections is not None else target.sections)

    # --- Step 2: Handle raw Markdown strings (starting with '---') or filesystem paths ---
    if isinstance(target, (str, Path)):
        # Strip optional UTF-8 BOM before checking for inline YAML frontmatter fence.
        if isinstance(target, str) and target.lstrip("\ufeff").startswith("---"):
            fm_data, parsed_sections = parse_document(target)
            spec = WorkOrderSpec.model_validate(fm_data)
            return spec, (sections if sections is not None else parsed_sections)
        doc = load_workorder(target)
        return doc.spec, (sections if sections is not None else doc.sections)

    # --- Step 3: Handle bare WorkOrderSpec models requiring explicit sections ---
    if isinstance(target, WorkOrderSpec):
        if sections is None:
            raise ValueError("sections must be provided when target is a WorkOrderSpec")
        return target, sections

    raise TypeError(f"Unsupported target type for spec hash: {type(target)!r}")


def compute_spec_hash(
    target: Document[WorkOrderSpec] | WorkOrderSpec | str | Path,
    sections: Sequence[Section] | None = None,
) -> str:
    """Compute the normative SHA-256 `spec_hash` over Part I of `WORKORDER.md`.

    Assembles the canonical preimage from `WorkOrderSpec` (excluding mutable Part II
    fields `spec_hash`, `status`, and `completion`) plus all normalized Part I H2
    sections preceding `## Completion Report`.

    Args:
        target: `Document[WorkOrderSpec]`, `WorkOrderSpec`, raw Markdown string, or file path.
        sections: Optional explicit sequence of `Section` objects when `target` is a model.

    Returns:
        64-character lowercase hexadecimal SHA-256 digest string.

    Raises:
        ValueError: If no Part I H2 sections exist before `## Completion Report`.
        TypeError: If `target` is an unsupported type.
    """
    # --- Step 1: Resolve WorkOrderSpec and extract Part I H2 sections ---
    wo_spec, resolved_sections = _resolve_workorder_and_sections(target, sections)
    part1_sections = _part1_workorder_sections(resolved_sections)
    if not part1_sections:
        raise ValueError(
            "WORKORDER.md spec_hash requires at least one Part I H2 section "
            "before '## Completion Report'"
        )

    # --- Step 2: Assemble deterministic SHA-256 preimage excluding mutable Part II fields ---
    # Exclude spec_hash, status, and completion so Worker Part II updates do not invalidate Part I.
    wo_dict = wo_spec.model_dump(mode="json", exclude={"spec_hash", "status", "completion"})
    payload = (
        canonical_json(wo_dict)
        + "\n"
        + "\n".join(norm_section(s.full_text()) for s in part1_sections)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_spec_hash(
    target: Document[WorkOrderSpec] | WorkOrderSpec | str | Path,
    sections: Sequence[Section] | None = None,
) -> bool:
    """Verify that `wo_spec.spec_hash` is present and matches `compute_spec_hash`.

    Args:
        target: `Document[WorkOrderSpec]`, `WorkOrderSpec`, raw Markdown string, or file path.
        sections: Optional explicit sequence of `Section` objects when `target` is a model.

    Returns:
        `True` if `spec_hash` is non-empty and matches the computed SHA-256 digest; `False`
        otherwise.
    """
    wo_spec, resolved_sections = _resolve_workorder_and_sections(target, sections)
    if not wo_spec.spec_hash:
        return False
    return compute_spec_hash(wo_spec, resolved_sections) == wo_spec.spec_hash
