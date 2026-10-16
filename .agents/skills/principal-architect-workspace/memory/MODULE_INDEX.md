# Module Index
<!-- Cross-cutting reference. Read when you need to find what
     work has touched a specific domain or module.
     Domains are architect-defined based on the codebase architecture (SPEC.md §4.1). -->

## daemon-package (`daemon/plugin.json`, `daemon/workspace-plugin/principal-architect/plugin.json`, `scripts/dev-bootstrap.sh`, `pyproject.toml`, packaging)
| Project | Scope | Context |
|---|---|---|
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | Delivered `daemon/plugin.json` (`pa-daemon` v0.1.0), `daemon/workspace-plugin/principal-architect/plugin.json` (`principal-architect` v0.1.0), `pyproject.toml`, root and `daemon/` `.gitignore`, `README.md`, and 3-strategy `scripts/dev-bootstrap.sh`. | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) |

## common (`scripts/common.py` — stdlib-only `<1ms` fast-path helpers, template rendering, subprocess runner)
| Project | Scope | Context |
|---|---|---|
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | Delivered stdlib-only `find_repo_root`, `workspace_dir` (new -> legacy fallback), `daemon_home`, `is_repo_enrolled`, `read_transcript`, `latest_checkpoint_step`, `templates_dir`, `render_template`, `render_template_file`, and `run`. | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) |

## schemas (`scripts/schemas.py` — Pydantic v2 Split-Authority models, parser/renderer, hashing)
| Project | Scope | Context |
|---|---|---|
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | Delivered all SPEC §6.1–6.4 Pydantic v2 models (`extra="forbid"`), enums (`PRState`, `WorkOrderStatus`, `ComplexityTier`), `EscalationRequest`, lossless H2 `Section`/`Document[T]`/`parse_document`/`dump_document`, typed loaders (`load_program`/`load_project`/`load_workorder`/`load_audit`), and normative `compute_charter_hash`/`verify_charter_hash`/`compute_spec_hash`/`verify_spec_hash`. | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) |

## state-db (`scripts/state_db.py` — `.state/state.db`, `daemon/state/registry.json`)
| Project | Scope | Context |
|---|---|---|
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | Delivered `TABLES`, `SCHEMA_VERSION = 1`, `StateDB` (`WAL` mode, `busy_timeout=5000`, `user_version=1`, typed accessors for `repo_config`, `sessions`, `verification_receipts`, `escalations`, and `attention_queue`), and atomic `Registry` (`daemon/state/registry.json`). | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) |

## pa-cli (`scripts/pa_cli.py`, `scripts/enroll.sh`, `scripts/unenroll.sh` — `pa` command surface)
| Project | Scope | Context |
|---|---|---|
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | Delivered `COMMAND_MODULES`, `build_parser`, `main`, `detect_vcs_mode`, `detect_memory_mode`, normative 9-step `pa enroll` (including legacy workspace migration), `pa unenroll`, `pa status [--json]`, `pa mode`, and `scripts/enroll.sh` / `scripts/unenroll.sh`. | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) |

## hooks (`hooks.json`, `pre_invocation.py`, `pre_tool_gate.py`, `post_tool_receipt.py`, `stop_gate.py`, `escalation.py`)
| Project | Scope | Context |
|---|---|---|

## agents-and-rules (`agents/pa-*.md`, `rules/`, in-plugin `skills/principal-architect/SKILL.md`)
| Project | Scope | Context |
|---|---|---|

## vcs-bus (`scripts/vcs_sync.py` — local_git floor, GitHub PR/Review/Issue sync)
| Project | Scope | Context |
|---|---|---|

## model-routing (`scripts/models.py`)
| Project | Scope | Context |
|---|---|---|

## memory-modes (`scripts/memory_grad.py`, `memory/` templates)
| Project | Scope | Context |
|---|---|---|

## cockpit (`daemon/sidecars/pa_cockpit/`, `scripts/cockpit.py`)
| Project | Scope | Context |
|---|---|---|

## templates (`skills/principal-architect/templates/*.tpl`)
| Project | Scope | Context |
|---|---|---|
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | Delivered the seven `.md.tpl` templates (`PROGRAM`, `PROJECT`, `WORKORDER`, `AUDIT`, `MEMORY`, `MODULE_INDEX`, `PROJECT_INDEX`) validated against `schemas.py` models and required H2 sections. | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) |

## tests (`tests/`)
| Project | Scope | Context |
|---|---|---|
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | Delivered `tests/conftest.py` (`tmp_repo`, `daemon_home`, `fake_runner`), `tests/test_schemas.py` (17 tests), and `tests/test_state_db_and_sync.py` (34 tests). | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) |
