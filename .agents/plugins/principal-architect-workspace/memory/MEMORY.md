# Principal Architect Memory
<!-- Last updated: 2026-10-16T23:50:45Z -->
<!-- memory_mode: builtin (no external memory plugin enrolled on this repository) -->

## Active Programs
| Program | Plan | Status |
|---|---|---|
| [principal-architect-plugin](../programme-principal-architect-plugin/PROGRAM.md) | [PROGRAM-PLAN.md](../programme-principal-architect-plugin/PROGRAM-PLAN.md) | Approved (`status: APPROVED`); autonomous execution authorized; 4/5 PRs graduated (`PR-01`, `PR-02`, `PR-03`, `PR-04`); Next: PR-05 |

## Active Projects
| Project | Status | Modules | Context |
|---|---|---|---|
| pr-05-dogfood-self-enrollment-and-release | STAGED_FOR_AUDIT (WO3/3 completed; base `feat/pr-04-cockpit-auxpane-ui`) | dogfood-enrollment, release-v0.1.0, tests | [PROJECT.md](../pr-05-dogfood-self-enrollment-and-release/PROJECT.md) |

## Recently Completed (last 5)
| Project | Completed | Modules | Key Outcome |
|---|---|---|---|
| [pr-04-cockpit-auxpane-ui](../pr-04-cockpit-auxpane-ui/PROJECT.md) | 2026-10-16 | cockpit-backend, cockpit-ui, sidecar.json, install/uninstall, README, tests | Delivered `daemon/sidecars/pa_cockpit/sidecar.json` (`SIDECAR_UI_ENTRYPOINT_AUX_PANE`, zero `agent_permissions`), stdlib `CockpitHTTPServer` + `create_server` + `build_workspace_state` in `cockpit.py` implementing all 10 `GET`/`SSE`/`POST` routes (with `/preload.js` fallback shim, `?once=1` SSE mode, and live mtime-fingerprint SSE push), adaptive host-themed Cockpit AuxPane UI (`daemon/sidecars/pa_cockpit/ui/{index.html,styles.css,app.js}`) across Zone 1/2/3 with guarded `window.sidecar` bindings, environment-isolatable `scripts/{install,uninstall}.sh` preserving `<PA_DAEMON_HOME>/state/registry.json`, full user-facing `README.md`, and 121 passing tests (Audit Round 1 `APPROVED`). |
| [pr-03-vcs-bus-models-and-memory-modes](../pr-03-vcs-bus-models-and-memory-modes/PROJECT.md) | 2026-10-16 | vcs-bus, model-routing, memory-modes, pa-cli (lifecycle commands), tests | Delivered `vcs_sync.py` (`VcsBus`, `LocalGitBus`, `GitHubBus`, `get_vcs_bus`, commit trailers, `write_audit_round`, `format_pa_audit_comment`/`parse_pa_audit_comment`, `gh pr review --comment`, `append_deferred_backlog`, `sync_state`, `restack_branches`), `memory_grad.py` (`graduate` enforcing zero-touch on `memory/` in `external` mode and 5-PR window roll-off + idempotent `MODULE_INDEX.md` updates in `builtin` mode), `models.py` (`ARCHITECT_MODEL_PREFERENCE`, `route`, `step_up`, `select_architect_model`, `LanguageServerClient` with headless fallback), complete `pa_cli.py` lifecycle commands (`sync`, `programme init/charter`, `pr start/claim/open-or-sync/post-audit/sync-audit/graduate/restack` enforcing R6, `wo debug/resolve`, `issue create`), and 115 passing tests (Audit Round 1 `APPROVED`). |
| [pr-02-agents-and-dual-mode-hooks](../pr-02-agents-and-dual-mode-hooks/PROJECT.md) | 2026-10-16 | agents, hooks.json, escalation, pre-invocation, pre-tool-gate, post-tool-receipt, stop-gate, pa-cli (approve-plan/wo-verify/escalate) | Delivered `escalation.py` (`decide` for R1–R6 across `monitored` and `autonomous` modes, `is_structural_blocker`, `record_escalation`), `hooks.json` + `<1ms` fast-exit hooks (`pre_invocation.py`, `pre_tool_gate.py`, `post_tool_receipt.py`, `stop_gate.py`), five custom role agents (`agents/pa-*.md`), `rules/00-pa-operating-model.md`, `skills/principal-architect/SKILL.md`, `pa pr approve-plan`/`pa wo verify`/`pa escalate`, and 85 passing tests (Audit Round 1 `APPROVED`). |
| [pr-01-core-schemas-and-enrollment](../pr-01-core-schemas-and-enrollment/PROJECT.md) | 2026-10-16 | daemon-package, schemas, state-db, common, pa-cli (enroll/unenroll/status/mode), templates, tests, dev-bootstrap | Delivered `daemon/` package skeleton, `scripts/dev-bootstrap.sh` (3-strategy venv provisioning), stdlib-only `common.py` (`<1ms` `is_repo_enrolled`), `schemas.py` (Split-Authority Pydantic v2 models, lossless H2 parser/renderer, `charter_hash`/`spec_hash`), `state_db.py` (`StateDB` WAL + 5 SPEC §6.5 tables, atomic `Registry`), 7 `.md.tpl` templates, `pa_cli.py` (`enroll`/`unenroll`/`status [--json]`/`mode`), and 51 passing tests (Audit Round 1 `APPROVED`). |

## Older Projects
4 completed projects (`pr-01-core-schemas-and-enrollment`, `pr-02-agents-and-dual-mode-hooks`, `pr-03-vcs-bus-models-and-memory-modes`, `pr-04-cockpit-auxpane-ui`).
Full project history: [PROJECT_INDEX.md](PROJECT_INDEX.md)
Cross-cutting module index: [MODULE_INDEX.md](MODULE_INDEX.md)
