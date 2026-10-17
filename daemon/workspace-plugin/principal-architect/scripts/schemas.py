"""Canonical Split-Authority document schemas, Markdown parser/renderer, and normative hashes.

SPEC.md §6 is normative for all Split-Authority document models (`ProgramSpec`,
`PRNodeSpec`, `ProjectSpec`, `PRCharterSpec`, `WOSummaryRow`, `WorkOrderSpec`,
`CompletionReport`, `EscalationRequest`, `AuditReport`, `AuditFinding`), string
enumerations (`PRState`, `WorkOrderStatus`, `ComplexityTier`), H2 section parsing,
and `charter_hash` / `spec_hash` algorithms.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field


class PRState(str, Enum):
    """Lifecycle states for a Pull Request (`PROJECT.md` / `PRNodeSpec`)."""

    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    STAGED_FOR_AUDIT = "STAGED_FOR_AUDIT"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    AUDIT_APPROVED = "AUDIT_APPROVED"
    GRADUATED = "GRADUATED"
    ARCHIVED = "ARCHIVED"


class WorkOrderStatus(str, Enum):
    """Execution states for a Work Order (`WORKORDER.md` / `WOSummaryRow`)."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    ESCALATED_TO_PA = "ESCALATED_TO_PA"


class ComplexityTier(str, Enum):
    """Model routing complexity tiers for a Work Order."""

    mechanical = "mechanical"
    standard = "standard"
    architect = "architect"
    interactive = "interactive"


class PRNodeSpec(BaseModel):
    """PR node entry inside `PROGRAM.md` (`ProgramSpec.prs`)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    slug: str = Field(..., pattern=r"^pr-\d+[a-z]?-[a-z0-9-]+$")
    title: str = Field(..., min_length=5, max_length=140)
    branch: str = Field(..., min_length=1)
    base_branch: str = "main"
    depends_on: list[str] = Field(default_factory=list)
    allowed_modules: list[str] = Field(..., min_length=1)
    required_skills: list[str] = Field(default_factory=list)
    status: PRState = PRState.PLANNED
    github_pr: int | None = None


class ProgramSpec(BaseModel):
    """Frontmatter schema for `PROGRAM.md` (SPEC §6.1)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    programme_id: str = Field(..., pattern=r"^prog-[a-z0-9-]+$")
    title: str = Field(..., min_length=1)
    base_branch: str = "main"
    status: Literal["DRAFT", "APPROVED", "ACTIVE", "COMPLETED"] = "DRAFT"
    prs: list[PRNodeSpec] = Field(default_factory=list)


class PRCharterSpec(BaseModel):
    """Part I of `PROJECT.md`: authored by Tier 1 Chief Architect and locked via `charter_hash`."""

    model_config = ConfigDict(extra="forbid")

    pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    programme_id: str | None = None
    slug: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    branch: str = Field(..., min_length=1)
    base_branch: str = "main"
    depends_on: list[str] = Field(default_factory=list)
    allowed_modules: list[str] = Field(
        ...,
        min_length=1,
        description="Subsystem/module boundaries this PR is authorized to touch",
    )
    required_skills: list[str] = Field(
        default_factory=list,
        description="Skills/tools mandated for this PR (e.g. ['pio', 'framework-expert'])",
    )
    verification_floor: list[str] = Field(
        default_factory=list,
        description="Minimum test/build commands that must pass before PR graduation",
    )
    charter_locked: bool = True
    charter_hash: str | None = Field(
        default=None,
        description="SHA-256 of Charter YAML + Sections 1-2 to detect unauthorized PA edits",
    )


class WOSummaryRow(BaseModel):
    """Work Order summary entry in `PROJECT.md` (`ProjectSpec.work_orders`)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^WO-\d+[a-z]?\.\d+$")
    slug: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    complexity: ComplexityTier
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    commit_sha: str | None = None


class ProjectSpec(BaseModel):
    """Split-Authority frontmatter schema for `PROJECT.md` (SPEC §6.2)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    charter: PRCharterSpec
    status: PRState = PRState.PLANNED
    approved_at: datetime | None = None
    github_pr: int | None = None
    work_orders: list[WOSummaryRow] = Field(default_factory=list)


class EscalationRequest(BaseModel):
    """Structured upward escalation payload recorded by a Worker or PA."""

    model_config = ConfigDict(extra="forbid")

    blocker_type: Literal["structural", "boundary", "charter", "verification", "other"]
    reason_code: str = Field(..., min_length=1)
    target_role: Literal["pa", "chief", "human"]
    requested_files: list[str] = Field(default_factory=list)
    summary: str = Field(..., min_length=1, max_length=500)


class CompletionReport(BaseModel):
    """Part II of `WORKORDER.md`: authored by Tier 3 Worker (`pa-engineer`)."""

    model_config = ConfigDict(extra="forbid")

    status: WorkOrderStatus
    attempt_num: int = Field(default=1, ge=1, le=5)
    receipt_id: str | None = None
    commit_sha: str | None = None
    files_modified: list[str] = Field(default_factory=list)
    verification_summary: str = Field(
        ...,
        max_length=280,
        description="Succinct 1-line test/build outcome",
    )
    out_of_scope_findings: list[str] = Field(default_factory=list)
    escalation_request: EscalationRequest | None = None
    decisions_made: list[str] = Field(default_factory=list)
    dead_ends: list[str] = Field(default_factory=list)


class WorkOrderSpec(BaseModel):
    """Split-Authority frontmatter schema for `WORKORDER.md` (SPEC §6.3)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    wo_id: str = Field(..., pattern=r"^WO-\d+[a-z]?\.\d+$")
    pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    title: str = Field(..., min_length=5, max_length=140)
    complexity: ComplexityTier
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    allowed_files: list[str] = Field(
        ...,
        min_length=1,
        description="Repo-relative file paths or globs Worker may create/modify",
    )
    forbidden_files: list[str] = Field(
        default_factory=list,
        description="Explicitly protected paths",
    )
    required_skills: list[str] = Field(
        default_factory=list,
        description="Domain skills (e.g. ['pio', 'framework-expert']) highlighted on Turn 1",
    )
    verification_command: str = Field(
        ...,
        min_length=2,
        description="Shell command that must exit 0 after the final file edit",
    )
    max_attempts: int = Field(
        default=5,
        ge=1,
        le=5,
        description="Max productive verification attempts before escalating to pa-debugger",
    )
    max_structural_failures: int = Field(
        default=2,
        ge=1,
        le=3,
        description="Fast-fail escalation threshold for structural/hook blockers",
    )
    spec_hash: str | None = Field(
        default=None,
        description="SHA-256 of Part I Spec to prevent Worker from editing its own contract",
    )
    completion: CompletionReport | None = None


class AuditFinding(BaseModel):
    """Single Cold-Firewall audit finding entry inside `AuditReport`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^(BLOCKING|NON-BLOCKING)-\d+$")
    axis: Literal["spec_alignment", "invariants", "edge_cases", "test_quality", "scope_hygiene"]
    file_path: str = Field(..., min_length=1)
    line_range: str | None = None
    summary: str = Field(..., min_length=1)
    remediation: str = Field(..., min_length=1)


class AuditReport(BaseModel):
    """Frontmatter schema for `AUDIT-round-<K>.md` (SPEC §6.4)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    pr_id: str = Field(..., pattern=r"^PR-\d+[a-z]?$")
    github_pr: int | None = Field(
        default=None,
        description="None when operating in local_git mode without a GitHub remote",
    )
    audit_round: int = Field(..., ge=1, le=5)
    head_sha: str = Field(..., min_length=7, max_length=40)
    auditor_harness: str = "antigravity"
    verdict: Literal["APPROVED", "CHANGES_REQUESTED"]
    findings: list[AuditFinding] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Document Layer: Section, Document[T], parse_document, dump_document, load_*
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """Represents a Markdown H2 section (or pre-H2 preamble when `heading == ''`)."""

    heading: str
    body: str

    def full_text(self) -> str:
        """Reconstruct the full section text including its H2 heading line."""
        if not self.heading:
            return self.body
        if not self.body:
            return self.heading
        return f"{self.heading}\n{self.body}"


T = TypeVar("T", bound=BaseModel)


@dataclass
class Document(Generic[T]):
    """Validated Split-Authority Markdown document with typed frontmatter and H2 sections."""

    spec: T
    sections: list[Section]
    path: Path | None = None

    def section(self, prefix: str) -> Section | None:
        """Return the first section whose heading starts with `prefix`, or None."""
        for sec in self.sections:
            if sec.heading.startswith(prefix):
                return sec
        return None


_FRONTMATTER_RE = re.compile(
    r"^---[ \t]*\r?\n(.*?)^---[ \t]*(?:\r?\n|\Z)",
    flags=re.DOTALL | re.MULTILINE,
)


def parse_document(text: str) -> tuple[dict[str, Any], list[Section]]:
    """Parse a YAML-frontmatter + H2-section Markdown document.

    Preserves section order, pre-H2 preamble (H1 title, metadata tables, HTML comments),
    and unknown H2 sections for lossless round-tripping.
    """
    text = text.removeprefix("\ufeff")

    fm_match = _FRONTMATTER_RE.match(text)
    if not fm_match:
        raise ValueError("Document must begin with a YAML frontmatter block delimited by '---'")

    fm_raw = fm_match.group(1)
    fm_data = yaml.safe_load(fm_raw)
    if not isinstance(fm_data, dict):
        raise ValueError("YAML frontmatter root must be a mapping (dict)")  # noqa: TRY004

    body = text[fm_match.end() :].lstrip("\r\n")
    chunks = re.split(r"(?m)^(?=## )", body)
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
    """Serialize a Pydantic model (or mapping) and ordered sections back to Markdown."""
    if isinstance(frontmatter_model, BaseModel):
        fm_dict = frontmatter_model.model_dump(mode="json")
    else:
        fm_dict = dict(frontmatter_model)

    yaml_str = yaml.safe_dump(fm_dict, sort_keys=False, allow_unicode=True).rstrip("\n")
    parts: list[str] = []
    for idx, sec in enumerate(sections):
        chunk = sec.full_text()
        if idx < len(sections) - 1 and not chunk.endswith("\n"):
            chunk += "\n"
        parts.append(chunk)

    body_str = "".join(parts)
    if body_str and not body_str.endswith("\n"):
        body_str += "\n"

    if body_str:
        return f"---\n{yaml_str}\n---\n\n{body_str}"
    return f"---\n{yaml_str}\n---\n"


def _require_sections(doc: Document[Any], required_prefixes: Sequence[str], kind: str) -> None:
    for prefix in required_prefixes:
        if doc.section(prefix) is None:
            raise ValueError(f"{kind} is missing required H2 section starting with '{prefix}'")


def load_program(path: str | Path) -> Document[ProgramSpec]:
    """Load and validate a `PROGRAM.md` file."""
    p = Path(path)
    fm_data, sections = parse_document(p.read_text(encoding="utf-8"))
    spec = ProgramSpec.model_validate(fm_data)
    doc = Document(spec=spec, sections=sections, path=p)
    _require_sections(doc, ("## 1.", "## 2.", "## 3."), "PROGRAM.md")
    return doc


def load_project(path: str | Path) -> Document[ProjectSpec]:
    """Load and validate a `PROJECT.md` file."""
    p = Path(path)
    fm_data, sections = parse_document(p.read_text(encoding="utf-8"))
    spec = ProjectSpec.model_validate(fm_data)
    doc = Document(spec=spec, sections=sections, path=p)
    _require_sections(doc, ("## 1.", "## 2.", "## 3.", "## 4."), "PROJECT.md")
    return doc


def load_workorder(path: str | Path) -> Document[WorkOrderSpec]:
    """Load and validate a `WORKORDER.md` file."""
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
    """Load and validate an `AUDIT-round-<K>.md` file."""
    p = Path(path)
    fm_data, sections = parse_document(p.read_text(encoding="utf-8"))
    spec = AuditReport.model_validate(fm_data)
    return Document(spec=spec, sections=sections, path=p)


# ---------------------------------------------------------------------------
# Normative Hashing: charter_hash & spec_hash
# ---------------------------------------------------------------------------


def canonical_json(data: Mapping[str, Any]) -> str:
    """Serialize a dictionary to deterministic canonical JSON."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def norm_section(text: str) -> str:
    """Normalize a Markdown section string (strip outer whitespace and rstrip each line)."""
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _part1_workorder_sections(sections: Sequence[Section]) -> list[Section]:
    """Return all Part I H2 sections before `## Completion Report` or `## Part II`."""
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
    if isinstance(target, Document):
        charter = target.spec.charter
        resolved_sections = sections if sections is not None else target.sections
        return charter, resolved_sections

    if isinstance(target, (str, Path)):
        if isinstance(target, str) and target.lstrip("\ufeff").startswith("---"):
            fm_data, parsed_sections = parse_document(target)
            spec = ProjectSpec.model_validate(fm_data)
            return spec.charter, (sections if sections is not None else parsed_sections)
        doc = load_project(target)
        return doc.spec.charter, (sections if sections is not None else doc.sections)

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
    """Compute the normative SHA-256 `charter_hash` over Part I of `PROJECT.md`."""
    charter, resolved_sections = _resolve_project_and_sections(target, sections)
    sec1 = next((s for s in resolved_sections if s.heading.startswith("## 1.")), None)
    sec2 = next((s for s in resolved_sections if s.heading.startswith("## 2.")), None)
    if sec1 is None or sec2 is None:
        raise ValueError("PROJECT.md charter_hash requires sections '## 1.' and '## 2.'")

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
    """Verify that `charter.charter_hash` is present and matches `compute_charter_hash`."""
    charter, resolved_sections = _resolve_project_and_sections(target, sections)
    if not charter.charter_hash:
        return False
    return compute_charter_hash(charter, resolved_sections) == charter.charter_hash


def _resolve_workorder_and_sections(
    target: Document[WorkOrderSpec] | WorkOrderSpec | str | Path,
    sections: Sequence[Section] | None = None,
) -> tuple[WorkOrderSpec, Sequence[Section]]:
    if isinstance(target, Document):
        return target.spec, (sections if sections is not None else target.sections)

    if isinstance(target, (str, Path)):
        if isinstance(target, str) and target.lstrip("\ufeff").startswith("---"):
            fm_data, parsed_sections = parse_document(target)
            spec = WorkOrderSpec.model_validate(fm_data)
            return spec, (sections if sections is not None else parsed_sections)
        doc = load_workorder(target)
        return doc.spec, (sections if sections is not None else doc.sections)

    if isinstance(target, WorkOrderSpec):
        if sections is None:
            raise ValueError("sections must be provided when target is a WorkOrderSpec")
        return target, sections

    raise TypeError(f"Unsupported target type for spec hash: {type(target)!r}")


def compute_spec_hash(
    target: Document[WorkOrderSpec] | WorkOrderSpec | str | Path,
    sections: Sequence[Section] | None = None,
) -> str:
    """Compute the normative SHA-256 `spec_hash` over Part I of `WORKORDER.md`."""
    wo_spec, resolved_sections = _resolve_workorder_and_sections(target, sections)
    part1_sections = _part1_workorder_sections(resolved_sections)
    if not part1_sections:
        raise ValueError(
            "WORKORDER.md spec_hash requires at least one Part I H2 section before '## Completion Report'"
        )

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
    """Verify that `wo_spec.spec_hash` is present and matches `compute_spec_hash`."""
    wo_spec, resolved_sections = _resolve_workorder_and_sections(target, sections)
    if not wo_spec.spec_hash:
        return False
    return compute_spec_hash(wo_spec, resolved_sections) == wo_spec.spec_hash
