# Module Index
<!-- Cross-cutting reference. Read when you need to find what
     work has touched a specific domain or module.
     Domains are architect-defined based on the codebase architecture (SPEC.md §4.1). -->

## daemon-package (`daemon/plugin.json`, `daemon/workspace-plugin/principal-architect/plugin.json`, `scripts/dev-bootstrap.sh`, `scripts/install.sh`, `scripts/uninstall.sh`, `pyproject.toml`, `README.md`, `CHANGELOG.md`, `.gitignore`, `.agents/plugins/principal-architect-workspace/`, packaging)
| Project | Scope | Context |
|---|---|---|
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | Delivered `daemon/plugin.json` (`pa-daemon` v0.1.0), `daemon/workspace-plugin/principal-architect/plugin.json` (`principal-architect` v0.1.0), `pyproject.toml`, root and `daemon/` `.gitignore`, `README.md`, and 3-strategy `scripts/dev-bootstrap.sh`. | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) |
| [pr-04-cockpit-auxpane-ui](../pr-04-cockpit-auxpane-ui/PROJECT.md) | Delivered `scripts/install.sh` and `scripts/uninstall.sh` (`chmod +x`, honouring `PA_DAEMON_HOME` and `PA_BIN_DIR`, preserving `<PA_DAEMON_HOME>/state/registry.json` across upgrades, and managing the `pa` CLI symlink) and the full user-facing `README.md`. | [PROJECT.md](../pr-04-cockpit-auxpane-ui/PROJECT.md) |
| [pr-05-dogfood-self-enrollment-and-release](../pr-05-dogfood-self-enrollment-and-release/PROJECT.md) | Migrated `.agents/skills/principal-architect-workspace/` to `.agents/plugins/principal-architect-workspace/` via `pa enroll`, added `.agents/plugins/principal-architect-workspace/.gitignore` and root `.gitignore` `.state/` rules, authored `CHANGELOG.md` for `v0.1.0`, appended Section 8 to `README.md`, and verified `v0.1.0` metadata across `pyproject.toml` and both `plugin.json` manifests. | [PROJECT.md](../pr-05-dogfood-self-enrollment-and-release/PROJECT.md) |

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
| [pr-02-agents-and-dual-mode-hooks](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) | Added `pa pr approve-plan <PR-ID>` (validates `PROJECT.md` Part II & `WORKORDER.md` specs, checks `allowed_files ⊆ charter.allowed_modules`, stamps `spec_hash`, marks `APPROVED`), `pa wo verify <WO-ID>` (checks scope hygiene & `spec_hash`, runs `verification_command`, stamps cryptographic receipt, commits with `PA-WorkOrder`/`PA-Verified-Hash` trailers), and `pa escalate` (`--to-pa`/`--to-chief`/`--to-human`). | [PROJECT.md](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) |
| [pr-03-vcs-bus-models-and-memory-modes](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) | Added `pa sync`, `pa programme init/charter`, `pa pr start/claim/open-or-sync/post-audit/sync-audit/graduate/restack` (enforcing Rule R6 Graduation Audit Gate), `pa wo debug/resolve`, and `pa issue create` while preserving top-level stdlib-only lazy imports. | [PROJECT.md](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) |

## hooks (`hooks.json`, `pre_invocation.py`, `pre_tool_gate.py`, `post_tool_receipt.py`, `stop_gate.py`, `escalation.py`)
| Project | Scope | Context |
|---|---|---|
| [pr-02-agents-and-dual-mode-hooks](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) | Delivered `hooks.json` (`PreInvocation`, `PreToolUse`, `PostToolUse`, `Stop`, `timeout: 10`), `escalation.py` (`decide` for R1–R6 across `monitored` and `autonomous` modes, `is_structural_blocker`, `record_escalation`, `enqueue_attention`, `read_hook_input`, `write_hook_output`), `pre_tool_gate.py` (`<1ms` fast-exit, `os.path.realpath` traversal defense, R1–R6 enforcement), `post_tool_receipt.py` (`compute_tree_hash`, receipt invalidation/stamping, retry counters), `stop_gate.py` (two-tier retry ceiling `max_attempts=5` vs `max_structural_failures=2`, Case A/B + auditor checks, bounded continuations), and `pre_invocation.py` (`parse_spawn_header`, Turn 1 session binding, `CHECKPOINT`/rewind detection, `builtin` vs `external` memory injection). | [PROJECT.md](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) |

## agents-and-rules (`agents/pa-*.md`, `rules/`, in-plugin `skills/principal-architect/SKILL.md`)
| Project | Scope | Context |
|---|---|---|
| [pr-02-agents-and-dual-mode-hooks](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) | Delivered `agents/{pa-chief-architect,pa-principal-architect,pa-engineer,pa-auditor,pa-debugger}.md` with SPEC §5.2 capability scoping (`inheritCustomizations: false` + `.state/pa-skills.json` & `.state/pa-worker-rules.json` on `pa-engineer`/`pa-auditor`, `inheritMcp: false` on `pa-auditor`), `rules/00-pa-operating-model.md`, and in-plugin `skills/principal-architect/SKILL.md`. | [PROJECT.md](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) |

## vcs-bus (`scripts/vcs_sync.py` — local_git floor, GitHub PR/Review/Issue sync)
| Project | Scope | Context |
|---|---|---|
| [pr-03-vcs-bus-models-and-memory-modes](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) | Delivered `VcsBus`, `LocalGitBus` (stacked branches, `PA-*` commit trailers, `write_audit_round`, `append_deferred_backlog`, `sync_state`, `restack_branches`), `GitHubBus(LocalGitBus)` (branch push, `gh pr create/edit/view/diff`, `gh pr review --comment`, remote `<!-- pa:audit -->` ingestion, `pa:deferred` issues), and `get_vcs_bus`. | [PROJECT.md](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) |

## model-routing (`scripts/models.py`)
| Project | Scope | Context |
|---|---|---|
| [pr-03-vcs-bus-models-and-memory-modes](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) | Delivered `ARCHITECT_MODEL_PREFERENCE = ("gemini-3.1-pro-high", "claude-opus-4-6-thinking", "gemini-3.1-pro-low")`, `route`, `step_up` (`flash_lite -> flash -> inherit`, never downgrading to `"pro"`), `select_architect_model`, and `LanguageServerClient` (`start_conversation`, `set_pinned`, `send_message`, headless fallback). | [PROJECT.md](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) |

## memory-modes (`scripts/memory_grad.py`, `memory/` templates)
| Project | Scope | Context |
|---|---|---|
| [pr-03-vcs-bus-models-and-memory-modes](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) | Delivered `graduate(repo_root, pr_id, *, memory_mode=None, completed_date=None)` enforcing zero-touch on `memory/` in `external` mode (`repo-memory`) and 5-PR window roll-off into `PROJECT_INDEX.md` + byte-stable `MODULE_INDEX.md` updates in `builtin` mode. | [PROJECT.md](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) |

## cockpit (`daemon/sidecars/pa_cockpit/`, `scripts/cockpit.py`)
| Project | Scope | Context |
|---|---|---|
| [pr-04-cockpit-auxpane-ui](../pr-04-cockpit-auxpane-ui/PROJECT.md) | Delivered `daemon/sidecars/pa_cockpit/sidecar.json` (`SIDECAR_UI_ENTRYPOINT_AUX_PANE`, zero `agent_permissions`), stdlib `CockpitHTTPServer` + `create_server` + `build_workspace_state` in `daemon/workspace-plugin/principal-architect/scripts/cockpit.py` (`GET /api/workspaces`, `GET /api/state`, `GET /api/events` SSE with `?once=1` and live mtime fingerprinting, `POST /api/{mode,pr/approve-plan,escalation/resolve,pr/start,wo/debug,pr/graduate,sync}`), and `daemon/sidecars/pa_cockpit/ui/{index.html,styles.css,app.js}` implementing Zone 1/2/3 with host CSS variables and guarded `window.sidecar` bindings. | [PROJECT.md](../pr-04-cockpit-auxpane-ui/PROJECT.md) |

## templates (`skills/principal-architect/templates/*.tpl`)
| Project | Scope | Context |
|---|---|---|
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | Delivered the seven `.md.tpl` templates (`PROGRAM`, `PROJECT`, `WORKORDER`, `AUDIT`, `MEMORY`, `MODULE_INDEX`, `PROJECT_INDEX`) validated against `schemas.py` models and required H2 sections. | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) |

## tests (`tests/`)
| Project | Scope | Context |
|---|---|---|
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | Delivered `tests/conftest.py` (`tmp_repo`, `daemon_home`, `fake_runner`), `tests/test_schemas.py` (17 tests), and `tests/test_state_db_and_sync.py` (34 tests). | [PROJECT.md](../pr-01-core-schemas-and-enrollment/PROJECT.md) |
| [pr-02-agents-and-dual-mode-hooks](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) | Delivered `tests/test_hooks_monitored_vs_autonomous.py` (34 unit, subprocess, CLI, and dogfood tests; total floor 85 passed). | [PROJECT.md](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) |
| [pr-03-vcs-bus-models-and-memory-modes](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) | Delivered `tests/test_github_and_local_git_bus.py` (23 tests covering `LocalGitBus`, `GitHubBus`, `models.py`, and end-to-end `pa` CLI lifecycles + R6 graduation gate) and `tests/test_memory_modes.py` (7 tests covering `external` vs. `builtin` graduation and byte-stability; total floor 115 passed). | [PROJECT.md](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) |
| [pr-04-cockpit-auxpane-ui](../pr-04-cockpit-auxpane-ui/PROJECT.md) | Delivered `tests/test_cockpit_api.py` (6 integration tests covering `sidecar.json` contract, `GET /api/{workspaces,state}`, `GET /api/events` SSE once & live push, all 7 `POST` mutation endpoints, frontend DOM/CSS/JS contracts, and isolated `tmp_path` `install.sh`/`uninstall.sh` registry preservation; total floor 121 passed). | [PROJECT.md](../pr-04-cockpit-auxpane-ui/PROJECT.md) |
| [pr-05-dogfood-self-enrollment-and-release](../pr-05-dogfood-self-enrollment-and-release/PROJECT.md) | Updated `test_workspace_dir_dogfood` and added `test_dogfood_self_enroll_sync_and_status_on_repo_workspace` in `tests/test_state_db_and_sync.py` verifying `pa enroll`, `pa sync`, `pa status --json`, `charter_hash` locks across `PR-01`..`PR-05`, and `spec_hash` locks across all `WORKORDER.md` files (total floor 122 passed). | [PROJECT.md](../pr-05-dogfood-self-enrollment-and-release/PROJECT.md) |
