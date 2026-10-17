#!/usr/bin/env python3
"""Principal Architect Cockpit AuxPane HTTP + Server-Sent Events (SSE) backend (`cockpit.py`).

Implements SPEC.md §10.2 and PR-04 Charter G1 & R1-R4:
- Stdlib-only `CockpitHTTPServer(ThreadingHTTPServer)` and `create_server(host, port, *, daemon_home)`.
- Static asset serving for `/`, `/index.html`, `/styles.css`, `/app.js`, and a safe `/preload.js`
  shim when accessed outside the Antigravity IDE proxy.
- `GET /api/workspaces` listing enrolled repositories from `<daemon_home>/state/registry.json`.
- `GET /api/state?workspace=<uri_or_path>` returning reconciled `env`, `programmes`, `prs`
  (with `charter_locked`, `charter_hash`, `pa_conversation_id`, `latest_audit`, and enriched
  `work_orders`), `attention_queue`, and `escalations`.
- `GET /api/events?workspace=<uri_or_path>[&once=1]` streaming real-time `event: state` SSE frames
  whenever `.state/state.db` or workspace Markdown specifications change.
- `POST /api/mode`, `POST /api/pr/approve-plan`, `POST /api/escalation/resolve`,
  `POST /api/pr/start`, `POST /api/wo/debug`, `POST /api/pr/graduate`, and `POST /api/sync`.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time
import urllib.parse
from collections.abc import Mapping, Sequence
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import common
import models
import pa_cli
import pre_tool_gate
import schemas
import state_db
import vcs_sync

_FALLBACK_HTML = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "<head>\n"
    '  <meta charset="utf-8">\n'
    "  <title>Principal Architect Cockpit</title>\n"
    '  <link rel="stylesheet" href="/styles.css">\n'
    '  <script src="/preload.js"></script>\n'
    "</head>\n"
    "<body>\n"
    '  <div id="app">Principal Architect Cockpit</div>\n'
    '  <script src="/app.js"></script>\n'
    "</body>\n"
    "</html>\n"
)

_FALLBACK_CSS = "/* Principal Architect Cockpit fallback styles */\n"
_FALLBACK_JS = "// Principal Architect Cockpit fallback script\n"
_PRELOAD_SHIM_JS = (
    "window.sidecar = window.sidecar || {\n"
    "  getWorkspaceUris: function() { return []; },\n"
    "  onWorkspaceChange: function() {},\n"
    "  ui: { toggleConversation: function() {}, toggleAuxPane: function() {} },\n"
    "  agent: { sendMessage: function() {} }\n"
    "};\n"
    "window.addEventListener('message', function(event) {\n"
    "  if (event.data && event.data.type === 'theme-change') {\n"
    "    var payload = event.data.payload || {};\n"
    "    var vars = payload.cssVariables || {};\n"
    "    for (var k in vars) { document.documentElement.style.setProperty(k, vars[k]); }\n"
    "    if (payload.themeType) {\n"
    "      document.documentElement.setAttribute('data-theme', payload.themeType);\n"
    "      document.documentElement.classList.toggle('dark', payload.themeType === 'dark');\n"
    "      document.documentElement.classList.toggle('light', payload.themeType === 'light');\n"
    "    }\n"
    "    if (payload.theme) { document.documentElement.setAttribute('data-theme-name', payload.theme); }\n"
    "  }\n"
    "});\n"
)


def _repo_ui_dir() -> Path:
    """Return the repository's default `daemon/sidecars/pa_cockpit/ui` directory path."""
    return Path(__file__).resolve().parents[3] / "sidecars" / "pa_cockpit" / "ui"


def _resolve_daemon_home(daemon_home: str | Path | None = None) -> Path:
    """Resolve `daemon_home` from explicit argument or `common.daemon_home()`."""
    if daemon_home is not None and str(daemon_home).strip():
        return Path(os.path.realpath(os.path.expanduser(str(daemon_home).strip())))
    return common.daemon_home()


def _list_enrolled_workspaces(daemon_home: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str | None]:
    """Read `<daemon_home>/state/registry.json` and return `(workspaces_list, raw_repos, active_workspace)`."""
    reg = state_db.Registry(daemon_home / "state" / "registry.json")
    raw_repos = reg.list()

    workspaces: list[dict[str, Any]] = []
    for repo_path, meta in raw_repos.items():
        real_repo = os.path.realpath(repo_path)
        slug = str(meta.get("slug") or Path(real_repo).name)
        ws_dir = str(meta.get("workspace_dir") or common.workspace_dir(real_repo))
        workspaces.append(
            {
                "repo_root": real_repo,
                "path": real_repo,
                "uri": f"file://{real_repo}",
                "slug": slug,
                "enrolled_at": meta.get("enrolled_at"),
                "workspace_dir": ws_dir,
            }
        )

    active_workspace: str | None = None
    default_env = os.environ.get("PA_DEFAULT_WORKSPACE", "").strip()
    if default_env:
        cleaned_default = os.path.realpath(common._strip_file_uri(default_env))
        for ws in workspaces:
            if ws["repo_root"] == cleaned_default:
                active_workspace = cleaned_default
                break
        if (
            active_workspace is None
            and Path(cleaned_default).exists()
            and common.workspace_dir(cleaned_default).is_dir()
        ):
            active_workspace = cleaned_default

    if active_workspace is None and workspaces:
        active_workspace = workspaces[0]["repo_root"]

    return workspaces, raw_repos, active_workspace


def _resolve_workspace(raw_workspace: str | None, daemon_home: Path) -> Path:
    """Resolve a workspace URI or path to an enrolled repository root `Path`.

    Raises `LookupError` if no matching enrolled workspace directory exists.
    """
    candidate_str = (raw_workspace or "").strip()
    if candidate_str:
        stripped = common._strip_file_uri(candidate_str).strip()
        if not stripped:
            raise LookupError("Empty workspace path")
        cand_path = Path(stripped).expanduser()
        if not cand_path.exists():
            raise LookupError(f"Workspace path does not exist: {stripped}")
        real_cand = Path(os.path.realpath(cand_path))
        if common.workspace_dir(real_cand).is_dir():
            return real_cand
        repo_root = common.find_repo_root(real_cand)
        if repo_root is not None and common.workspace_dir(repo_root).is_dir():
            return repo_root
        raise LookupError(f"Workspace is not enrolled: {stripped}")

    # No explicit workspace parameter provided: check PA_DEFAULT_WORKSPACE, then Registry, then cwd
    _, _, active_ws = _list_enrolled_workspaces(daemon_home)
    if active_ws:
        cand_active = Path(os.path.realpath(active_ws))
        if cand_active.exists() and common.workspace_dir(cand_active).is_dir():
            return cand_active

    cwd_root = common.find_repo_root(Path.cwd())
    if cwd_root is not None and common.workspace_dir(cwd_root).is_dir():
        return cwd_root

    raise LookupError("No enrolled workspace found")


def _parse_json_list_str(raw: Any) -> list[str]:
    """Parse a JSON string list or Python sequence into a list of strings."""
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return []


def _format_dt(val: Any) -> str | None:
    """Format an optional datetime or string value as ISO 8601 string."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat().replace("+00:00", "Z")
    return str(val)


def _is_pr_merged(
    proj_doc: schemas.Document[schemas.ProjectSpec],
    work_orders: list[dict[str, Any]],
    git_trailers: dict[str, tuple[str, str | None]],
    repo_root: Path,
) -> bool:
    """Determine whether a PR is merged into base_branch in git or has status GRADUATED/CLOSED."""
    status_str = proj_doc.spec.status.value.upper()
    if status_str in ("GRADUATED", "CLOSED"):
        return True

    ch = proj_doc.spec.charter
    base_branch = ch.base_branch or "main"

    # 1. Check if git trailers on HEAD (e.g. main) contain all of this PR's work orders
    if work_orders:
        all_wos_in_git = all(
            (wo.get("wo_id", "") in git_trailers or wo.get("wo_id", "").upper() in git_trailers)
            for wo in work_orders
        )
        if all_wos_in_git:
            return True

    # 2. Check if git ancestry confirms the branch is merged into base_branch
    if (repo_root / ".git").is_dir():
        for cand in (ch.branch, f"feat/{ch.slug}", ch.slug):
            if not cand:
                continue
            try:
                res = common.run(
                    ["git", "merge-base", "--is-ancestor", cand, base_branch],
                    cwd=repo_root,
                    check=False,
                )
                if res.returncode == 0:
                    return True
            except (OSError, RuntimeError):
                pass

    return False


def build_workspace_state(
    repo_root: str | Path,
    *,
    daemon_home: str | Path | None = None,
) -> dict[str, Any]:
    """Synthesize the complete Cockpit state dictionary for `repo_root` (`SPEC.md §10.2`)."""
    _ = daemon_home
    stripped_root = common._strip_file_uri(str(repo_root).strip())
    real_root = Path(os.path.realpath(stripped_root))
    ws_dir = common.workspace_dir(real_root)
    if not ws_dir.is_dir():
        raise LookupError(f"Workspace directory not found for repository: {real_root}")

    db_file = ws_dir / ".state" / "state.db"
    git_trailers = pa_cli._scan_git_trailers(real_root)

    with state_db.StateDB(db_file) as db:
        vcs_mode = db.get_config("vcs_mode") or "local_git"
        memory_mode = db.get_config("memory_mode") or "builtin"
        execution_mode = db.get_config("execution_mode") or "monitored"
        architect_model = db.get_config("architect_model") or models.select_architect_model(
            repo_root=real_root
        )

        env: dict[str, Any] = {
            "vcs_mode": vcs_mode,
            "memory_mode": memory_mode,
            "execution_mode": execution_mode,
            "architect_model": architect_model,
            "architect_model_options": list(models.ARCHITECT_MODEL_PREFERENCE),
            "workspace_dir": str(ws_dir),
            "repo_root": str(real_root),
        }

        # 1. Programmes
        programmes: list[dict[str, Any]] = []
        for prog_dir in sorted(ws_dir.glob("programme-*")):
            prog_md = prog_dir / "PROGRAM.md"
            if not prog_md.is_file():
                continue
            try:
                prog_doc = schemas.load_program(prog_md)
            except Exception:  # noqa: BLE001, S112
                continue
            status_val = getattr(prog_doc.spec.status, "value", str(prog_doc.spec.status))
            prog_prs = [p.model_dump(mode="json") for p in prog_doc.spec.prs]
            is_completed = (
                status_val.upper() in ("COMPLETED", "GRADUATED", "ARCHIVED")
                or (
                    bool(prog_prs)
                    and all(
                        str(p.get("status", "")).upper() in ("GRADUATED", "CLOSED")
                        for p in prog_prs
                    )
                )
            )
            programmes.append(
                {
                    "programme_id": prog_doc.spec.programme_id,
                    "slug": prog_dir.name,
                    "title": prog_doc.spec.title,
                    "base_branch": prog_doc.spec.base_branch,
                    "status": status_val,
                    "vcs_mode": vcs_mode,
                    "memory_mode": memory_mode,
                    "execution_mode": execution_mode,
                    "architect_model": architect_model,
                    "prs": prog_prs,
                    "approved_at": _format_dt(getattr(prog_doc.spec, "approved_at", None)),
                    "created_at": _format_dt(getattr(prog_doc.spec, "created_at", None)),
                    "is_completed": is_completed,
                    "is_active": not is_completed,
                }
            )

        # 2. Pull Requests & Work Orders
        pr_docs: list[tuple[Path, schemas.Document[schemas.ProjectSpec]]] = []
        for pr_dir in sorted(ws_dir.glob("pr-*")):
            proj_md = pr_dir / "PROJECT.md"
            if not proj_md.is_file():
                continue
            try:
                proj_doc = schemas.load_project(proj_md)
            except Exception:  # noqa: BLE001, S112
                continue
            pr_docs.append((pr_dir, proj_doc))

        pr_docs.sort(key=lambda item: item[1].spec.charter.pr_id)

        prs: list[dict[str, Any]] = []
        for pr_dir, proj_doc in pr_docs:
            ch = proj_doc.spec.charter
            pr_id = ch.pr_id
            charter_valid = schemas.verify_charter_hash(proj_doc) if ch.charter_hash else False

            # Resolve pa_conversation_id
            pa_conv_id = db.get_config(f"pa_session:{pr_id}") or db.get_config(
                f"pa_session:{pr_id.upper()}"
            )
            if not pa_conv_id:
                cur_pa = db.conn.execute(
                    """
                    SELECT conversation_id FROM sessions
                    WHERE UPPER(pr_id) = UPPER(?)
                      AND LOWER(role) IN (
                          'pa', 'pa-principal-architect', 'principal-architect',
                          'chief', 'pa-chief-architect', 'chief-architect'
                      )
                    ORDER BY updated_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (pr_id,),
                )
                row_pa = cur_pa.fetchone()
                if row_pa is not None:
                    pa_conv_id = str(row_pa["conversation_id"])

            # Resolve latest_audit
            latest_audit: dict[str, Any] | None = None
            raw_audit_cfg = (
                db.get_config(f"latest_audit:{pr_id.upper()}")
                or db.get_config(f"latest_audit:{pr_id}")
                or db.get_config(f"last_audit_{pr_id.upper()}")
            )
            if raw_audit_cfg:
                try:
                    parsed_audit = json.loads(raw_audit_cfg)
                    if isinstance(parsed_audit, dict):
                        latest_audit = parsed_audit
                except json.JSONDecodeError:
                    latest_audit = None

            audit_docs: list[schemas.Document[schemas.AuditReport]] = []
            for audit_md in sorted(pr_dir.glob("AUDIT-round-*.md")):
                if not audit_md.is_file():
                    continue
                try:
                    audit_docs.append(schemas.load_audit(audit_md))
                except Exception:  # noqa: BLE001, S112
                    continue
            if audit_docs:
                audit_docs.sort(key=lambda d: d.spec.audit_round)
                top_audit = audit_docs[-1].spec
                disk_round = int(top_audit.audit_round)
                cfg_round = int(latest_audit.get("audit_round", 0)) if latest_audit else 0
                if latest_audit is None or disk_round >= cfg_round:
                    latest_audit = {
                        "pr_id": top_audit.pr_id,
                        "github_pr": top_audit.github_pr,
                        "audit_round": top_audit.audit_round,
                        "head_sha": top_audit.head_sha,
                        "auditor_harness": top_audit.auditor_harness,
                        "verdict": top_audit.verdict,
                        "findings_count": len(top_audit.findings),
                        "findings": [f.model_dump(mode="json") for f in top_audit.findings],
                    }

            # Load WORKORDER.md files in this PR directory
            wo_docs_by_id: dict[str, tuple[str, schemas.Document[schemas.WorkOrderSpec]]] = {}
            for wo_dir in sorted(pr_dir.glob("wo*")):
                wo_md = wo_dir / "WORKORDER.md"
                if not wo_md.is_file():
                    continue
                try:
                    wdoc = schemas.load_workorder(wo_md)
                except Exception:  # noqa: BLE001, S112
                    continue
                wo_docs_by_id[wdoc.spec.wo_id.upper()] = (wo_dir.name, wdoc)

            work_orders: list[dict[str, Any]] = []
            seen_wo_keys: set[str] = set()

            def _build_wo_entry(
                wo_id_val: str,
                slug_val: str,
                row_obj: schemas.WOSummaryRow | None,
                wdoc_obj: schemas.Document[schemas.WorkOrderSpec] | None,
                _pr_id: str = pr_id,
                _pr_slug: str = ch.slug,
            ) -> dict[str, Any]:
                wspec = wdoc_obj.spec if wdoc_obj is not None else None
                comp = wspec.completion if wspec is not None else None

                title_val = (
                    wspec.title
                    if wspec is not None
                    else (row_obj.title if row_obj is not None else wo_id_val)
                )
                comp_tier = (
                    wspec.complexity.value
                    if wspec is not None
                    else (row_obj.complexity.value if row_obj is not None else "standard")
                )

                row_status = row_obj.status.value if row_obj is not None else "PENDING"
                if wspec is not None:
                    if wspec.status != schemas.WorkOrderStatus.PENDING or row_status == "PENDING":
                        status_val = wspec.status.value
                    else:
                        status_val = row_status
                else:
                    status_val = row_status

                # Attempts
                attempts_val = row_obj.attempts if row_obj is not None else 0
                if comp is not None:
                    attempts_val = max(attempts_val, comp.attempt_num)

                cur_sess = db.conn.execute(
                    """
                    SELECT conversation_id, attempt_num FROM sessions
                    WHERE UPPER(wo_id) = UPPER(?)
                    ORDER BY updated_at DESC, rowid DESC
                    """,
                    (wo_id_val,),
                )
                sess_rows = cur_sess.fetchall()
                for srow in sess_rows:
                    if srow["attempt_num"] is not None:
                        attempts_val = max(attempts_val, int(srow["attempt_num"]))

                # Subagent / session ID
                subagent_id = db.get_config(f"wo_session:{wo_id_val}") or db.get_config(
                    f"wo_session:{wo_id_val.upper()}"
                )
                if not subagent_id and sess_rows:
                    subagent_id = str(sess_rows[0]["conversation_id"])

                # Receipt & commit_sha & tree_hash
                rcpt_row = db.latest_valid_receipt(wo_id_val)
                commit_sha = row_obj.commit_sha if row_obj is not None else None
                receipt_id: str | None = None
                tree_hash: str | None = None
                verified_at: str | None = None

                if comp is not None:
                    if comp.commit_sha:
                        commit_sha = comp.commit_sha
                    if comp.receipt_id:
                        receipt_id = comp.receipt_id

                if rcpt_row is not None:
                    receipt_id = str(rcpt_row["receipt_id"])
                    tree_hash = str(rcpt_row["tree_hash"])
                    verified_at = str(rcpt_row["created_at"])
                    if rcpt_row.get("git_head_sha"):
                        commit_sha = str(rcpt_row["git_head_sha"])

                if wo_id_val in git_trailers:
                    t_sha, t_hash = git_trailers[wo_id_val]
                    if t_sha:
                        commit_sha = t_sha
                    if t_hash:
                        tree_hash = t_hash
                        if not receipt_id:
                            receipt_id = f"rcpt_{t_hash[:12]}"

                spec_hash_val = wspec.spec_hash if wspec is not None else None
                spec_valid_val = (
                    schemas.verify_spec_hash(wdoc_obj)
                    if (wdoc_obj is not None and spec_hash_val)
                    else False
                )

                return {
                    "wo_id": wo_id_val,
                    "id": wo_id_val,
                    "pr_id": _pr_id,
                    "slug": slug_val,
                    "title": title_val,
                    "branch": f"{_pr_slug}/{slug_val}",
                    "status": status_val,
                    "complexity": comp_tier,
                    "model_tier": models.route(comp_tier, attempt=max(1, attempts_val)),
                    "required_skills": list(wspec.required_skills) if wspec is not None else [],
                    "allowed_files": list(wspec.allowed_files) if wspec is not None else [],
                    "verification_command": (
                        wspec.verification_command if wspec is not None else ""
                    ),
                    "spec_hash": spec_hash_val,
                    "spec_valid": spec_valid_val,
                    "attempts": attempts_val,
                    "max_attempts": int(wspec.max_attempts) if wspec is not None else 5,
                    "commit_sha": commit_sha,
                    "receipt_id": receipt_id,
                    "tree_hash": tree_hash,
                    "verified_at": verified_at,
                    "subagent_id": subagent_id,
                }

            for row in proj_doc.spec.work_orders:
                key = row.id.upper()
                seen_wo_keys.add(key)
                matched_pair = wo_docs_by_id.get(key)
                wdoc_match = matched_pair[1] if matched_pair is not None else None
                slug_match = matched_pair[0] if matched_pair is not None else row.slug
                work_orders.append(_build_wo_entry(row.id, slug_match, row, wdoc_match))

            for key, (wo_dir_name, wdoc) in wo_docs_by_id.items():
                if key in seen_wo_keys:
                    continue
                work_orders.append(
                    _build_wo_entry(wdoc.spec.wo_id, wo_dir_name, None, wdoc)
                )

            is_merged = _is_pr_merged(proj_doc, work_orders, git_trailers, real_root)
            is_active = not is_merged and proj_doc.spec.status.value.upper() not in (
                "GRADUATED",
                "CLOSED",
                "CANCELLED",
            )
            prs.append(
                {
                    "pr_id": pr_id,
                    "programme_id": ch.programme_id,
                    "slug": ch.slug,
                    "title": ch.title,
                    "branch": ch.branch,
                    "base_branch": ch.base_branch,
                    "depends_on": list(ch.depends_on),
                    "allowed_modules": list(ch.allowed_modules),
                    "required_skills": list(ch.required_skills),
                    "verification_floor": list(ch.verification_floor),
                    "charter_locked": bool(ch.charter_locked),
                    "charter_hash": ch.charter_hash,
                    "charter_valid": charter_valid,
                    "status": proj_doc.spec.status.value,
                    "approved_at": _format_dt(proj_doc.spec.approved_at),
                    "github_pr": proj_doc.spec.github_pr,
                    "pa_conversation_id": pa_conv_id,
                    "latest_audit": latest_audit,
                    "work_orders": work_orders,
                    "is_merged": is_merged,
                    "is_active": is_active,
                }
            )

        # 3. Escalations (open)
        raw_escalations = db.open_escalations()
        escalations: list[dict[str, Any]] = []
        esc_by_id: dict[str, dict[str, Any]] = {}
        for erow in raw_escalations:
            req_files = _parse_json_list_str(erow.get("requested_files_json"))
            enriched_esc = {
                **erow,
                "requested_files": req_files,
                "trigger_code": erow.get("reason_code"),
                "reason": erow.get("summary"),
            }
            escalations.append(enriched_esc)
            esc_by_id[str(erow["escalation_id"])] = enriched_esc

        # Also index any non-open escalations referenced by open attention items
        cur_all_esc = db.conn.execute("SELECT * FROM escalations")
        all_esc_by_id: dict[str, dict[str, Any]] = {}
        for erow in cur_all_esc.fetchall():
            ed = dict(erow)
            req_files = _parse_json_list_str(ed.get("requested_files_json"))
            all_esc_by_id[str(ed["escalation_id"])] = {
                **ed,
                "requested_files": req_files,
                "trigger_code": ed.get("reason_code"),
                "reason": ed.get("summary"),
            }

        # 4. Attention Queue (open, sorted by priority ASC, created_at ASC)
        raw_attention = db.list_open()
        attention_queue: list[dict[str, Any]] = []
        for item in raw_attention:
            payload_raw = item.get("action_payload_json") or "{}"
            try:
                action_payload = json.loads(payload_raw)
                if not isinstance(action_payload, dict):
                    action_payload = {}
            except json.JSONDecodeError:
                action_payload = {}

            linked_esc_id = action_payload.get("escalation_id") or item.get("escalation_id")
            linked_esc: dict[str, Any] | None = None
            if linked_esc_id and str(linked_esc_id) in all_esc_by_id:
                linked_esc = all_esc_by_id[str(linked_esc_id)]
            elif item.get("wo_id") or item.get("pr_id"):
                for cand_esc in escalations:
                    if (
                        item.get("wo_id")
                        and cand_esc.get("wo_id") == item.get("wo_id")
                    ) or (
                        not item.get("wo_id")
                        and item.get("pr_id")
                        and cand_esc.get("pr_id") == item.get("pr_id")
                    ):
                        linked_esc = cand_esc
                        linked_esc_id = cand_esc["escalation_id"]
                        break

            esc_details: dict[str, Any] | None = None
            if linked_esc is not None:
                esc_details = {
                    "escalation_id": linked_esc["escalation_id"],
                    "trigger_code": linked_esc.get("reason_code"),
                    "reason_code": linked_esc.get("reason_code"),
                    "reason": linked_esc.get("summary"),
                    "summary": linked_esc.get("summary"),
                    "requested_files": linked_esc.get("requested_files", []),
                    "blocker_type": linked_esc.get("blocker_type"),
                    "level": linked_esc.get("level"),
                    "source_role": linked_esc.get("source_role"),
                    "target_role": linked_esc.get("target_role"),
                    "pr_id": linked_esc.get("pr_id"),
                    "wo_id": linked_esc.get("wo_id"),
                    "status": linked_esc.get("status"),
                }

            attention_queue.append(
                {
                    **item,
                    "action_payload": action_payload,
                    "escalation_id": linked_esc_id,
                    "escalation": esc_details,
                }
            )

    return {
        "ok": True,
        "env": env,
        "programmes": programmes,
        "prs": prs,
        "attention_queue": attention_queue,
        "escalations": escalations,
    }


def _workspace_fingerprint(repo_root: Path, daemon_home: Path) -> tuple[Any, ...]:
    """Compute a fast stat + SQLite header fingerprint over state.db, registry.json, and specs."""
    real_root = Path(os.path.realpath(repo_root))
    ws_dir = common.workspace_dir(real_root)
    entries: list[tuple[str, int, int, bytes]] = []

    candidates: list[Path] = [
        ws_dir / ".state" / "state.db",
        ws_dir / ".state" / "state.db-wal",
        ws_dir / ".state" / "state.db-shm",
        daemon_home / "state" / "registry.json",
    ]
    if ws_dir.is_dir():
        candidates.extend(sorted(ws_dir.rglob("*.md")))

    for p in candidates:
        try:
            st = p.stat()
        except OSError:
            continue
        header_bytes = b""
        if p.name in ("state.db", "state.db-wal"):
            try:
                with open(p, "rb") as f:
                    header_bytes = f.read(32)
            except OSError:
                header_bytes = b""
        entries.append((str(p), st.st_mtime_ns, st.st_size, header_bytes))

    return tuple(entries)


def _run_pa_cli_captured(argv: Sequence[str]) -> tuple[int, str, str]:
    """Execute `pa_cli.main(argv)` while capturing stdout and stderr."""
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = pa_cli.main(list(argv))
    return rc, out_buf.getvalue(), err_buf.getvalue()


class CockpitHTTPServer(ThreadingHTTPServer):
    """Multi-threaded stdlib HTTP server for Principal Architect Cockpit with clean SSE shutdown."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        daemon_home: Path,
        ui_dir: Path,
    ) -> None:
        self.daemon_home: Path = daemon_home
        self.ui_dir: Path = ui_dir
        self._pa_stop_sse: bool = False
        super().__init__(server_address, request_handler_class)

    def server_close(self) -> None:
        """Signal any active SSE loops to terminate immediately before closing the socket."""
        self._pa_stop_sse = True
        super().server_close()


class CockpitRequestHandler(BaseHTTPRequestHandler):
    """HTTP + SSE request handler for Principal Architect Cockpit."""

    server: CockpitHTTPServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:
        """Silence default BaseHTTPRequestHandler stderr logging."""
        _ = (format, args)

    def _send_json(self, status_code: int, payload: Mapping[str, Any]) -> None:
        body = (json.dumps(dict(payload), ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _send_text(self, status_code: int, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _read_json_body(self) -> dict[str, Any] | None:
        content_len_str = self.headers.get("Content-Length", "0").strip()
        try:
            content_len = int(content_len_str) if content_len_str else 0
        except ValueError:
            return None

        if content_len <= 0:
            return {}

        raw_bytes = self.rfile.read(content_len)
        if not raw_bytes or not raw_bytes.strip():
            return {}
        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    def _read_ui_asset(self, filename: str, fallback: str) -> str:
        primary = self.server.ui_dir / filename
        if primary.is_file():
            try:
                return primary.read_text(encoding="utf-8")
            except OSError:
                pass
        secondary = _repo_ui_dir() / filename
        if secondary.is_file():
            try:
                return secondary.read_text(encoding="utf-8")
            except OSError:
                pass
        return fallback

    def do_OPTIONS(self) -> None:
        """Respond to CORS preflight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        """Handle static UI assets, `/api/workspaces`, `/api/state`, and `/api/events` (SSE)."""
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path or "/"
        query = urllib.parse.parse_qs(parsed.query)

        # Static UI routes
        if route in ("/", "/index.html"):
            content = self._read_ui_asset("index.html", _FALLBACK_HTML)
            self._send_text(200, content, "text/html; charset=utf-8")
            return

        if route == "/styles.css":
            content = self._read_ui_asset("styles.css", _FALLBACK_CSS)
            self._send_text(200, content, "text/css; charset=utf-8")
            return

        if route == "/app.js":
            content = self._read_ui_asset("app.js", _FALLBACK_JS)
            self._send_text(200, content, "application/javascript; charset=utf-8")
            return

        if route == "/preload.js":
            content = self._read_ui_asset("preload.js", _PRELOAD_SHIM_JS)
            self._send_text(200, content, "application/javascript; charset=utf-8")
            return

        # API routes
        if route == "/api/workspaces":
            workspaces, raw_repos, active_ws = _list_enrolled_workspaces(
                self.server.daemon_home
            )
            self._send_json(
                200,
                {
                    "ok": True,
                    "workspaces": workspaces,
                    "repos": raw_repos,
                    "active_workspace": active_ws,
                },
            )
            return

        raw_ws = (query.get("workspace") or [None])[0]

        if route == "/api/state":
            try:
                repo_root = _resolve_workspace(raw_ws, self.server.daemon_home)
                state = build_workspace_state(repo_root, daemon_home=self.server.daemon_home)
            except LookupError as exc:
                self._send_json(404, {"ok": False, "error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
                return

            self._send_json(200, state)
            return

        if route == "/api/events":
            try:
                repo_root = _resolve_workspace(raw_ws, self.server.daemon_home)
                initial_state = build_workspace_state(
                    repo_root, daemon_home=self.server.daemon_home
                )
            except LookupError as exc:
                self._send_json(404, {"ok": False, "error": str(exc)})
                return

            once_raw = ((query.get("once") or [""])[0] or "").strip().lower()
            is_once = once_raw in ("1", "true", "yes")

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close" if is_once else "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            try:
                init_frame = f"event: state\ndata: {json.dumps(initial_state)}\n\n".encode()
                self.wfile.write(init_frame)
                self.wfile.flush()
                if is_once:
                    return

                last_fp = _workspace_fingerprint(repo_root, self.server.daemon_home)
                last_keepalive = time.monotonic()

                while not getattr(self.server, "_pa_stop_sse", False):
                    time.sleep(0.75)
                    if getattr(self.server, "_pa_stop_sse", False):
                        break
                    cur_fp = _workspace_fingerprint(repo_root, self.server.daemon_home)
                    now_mono = time.monotonic()
                    if cur_fp != last_fp:
                        last_fp = cur_fp
                        updated_state = build_workspace_state(
                            repo_root, daemon_home=self.server.daemon_home
                        )
                        frame = f"event: state\ndata: {json.dumps(updated_state)}\n\n".encode()
                        self.wfile.write(frame)
                        self.wfile.flush()
                        last_keepalive = now_mono
                    elif now_mono - last_keepalive >= 5.0:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last_keepalive = now_mono
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            return

        self._send_json(404, {"ok": False, "error": f"Not found: {route}"})

    def do_POST(self) -> None:
        """Handle Cockpit mutation endpoints (`/api/mode`, `/api/pr/*`, `/api/wo/*`, `/api/escalation/resolve`, `/api/sync`)."""
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path or "/"
        query = urllib.parse.parse_qs(parsed.query)

        body = self._read_json_body()
        if body is None:
            self._send_json(400, {"ok": False, "error": "Invalid JSON body"})
            return

        raw_ws = body.get("workspace") or (query.get("workspace") or [None])[0]
        try:
            repo_root = _resolve_workspace(
                str(raw_ws) if raw_ws is not None else None,
                self.server.daemon_home,
            )
        except LookupError as exc:
            self._send_json(404, {"ok": False, "error": str(exc)})
            return

        ws_dir = common.workspace_dir(repo_root)
        db_file = ws_dir / ".state" / "state.db"

        if route == "/api/mode":
            self._handle_post_mode(repo_root, db_file, body)
            return

        if route == "/api/pr/approve-plan":
            self._handle_post_approve_plan(repo_root, ws_dir, db_file, body)
            return

        if route == "/api/escalation/resolve":
            self._handle_post_escalation_resolve(ws_dir, db_file, body)
            return

        if route == "/api/pr/start":
            self._handle_post_pr_start(repo_root, ws_dir, db_file, body)
            return

        if route == "/api/wo/debug":
            self._handle_post_wo_debug(repo_root, ws_dir, db_file, body)
            return

        if route == "/api/pr/graduate":
            self._handle_post_pr_graduate(repo_root, ws_dir, body)
            return

        if route == "/api/sync":
            self._handle_post_sync(repo_root)
            return

        self._send_json(404, {"ok": False, "error": f"Not found: {route}"})

    def _handle_post_mode(
        self,
        repo_root: Path,
        db_file: Path,
        body: dict[str, Any],
    ) -> None:
        raw_mode = body.get("mode") if "mode" in body else body.get("execution_mode")
        raw_model = body.get("architect_model")

        if raw_mode is None and raw_model is None:
            self._send_json(
                400,
                {"ok": False, "error": "At least one of 'mode' or 'architect_model' is required"},
            )
            return

        if raw_mode is not None:
            if not isinstance(raw_mode, str) or raw_mode.strip() not in (
                "monitored",
                "autonomous",
            ):
                self._send_json(
                    400,
                    {
                        "ok": False,
                        "error": f"Invalid mode '{raw_mode}'. Expected 'monitored' or 'autonomous'.",
                    },
                )
                return
            mode_clean = raw_mode.strip()
            rc, _, err_out = _run_pa_cli_captured(
                ["mode", mode_clean, "--path", str(repo_root)]
            )
            if rc != 0:
                self._send_json(400, {"ok": False, "error": err_out.strip() or "Failed to set mode"})
                return

        if raw_model is not None:
            if not isinstance(raw_model, str) or not raw_model.strip():
                self._send_json(
                    400,
                    {"ok": False, "error": "'architect_model' must be a non-empty string"},
                )
                return
            with state_db.StateDB(db_file) as db:
                db.set_config("architect_model", raw_model.strip())

        with state_db.StateDB(db_file) as db:
            exec_mode = db.get_config("execution_mode") or "monitored"
            arch_model = db.get_config("architect_model") or models.select_architect_model(
                repo_root=repo_root
            )

        self._send_json(
            200,
            {
                "ok": True,
                "mode": exec_mode,
                "execution_mode": exec_mode,
                "architect_model": arch_model,
            },
        )

    def _handle_post_approve_plan(
        self,
        repo_root: Path,
        ws_dir: Path,
        db_file: Path,
        body: dict[str, Any],
    ) -> None:
        pr_id = str(body.get("pr_id") or "").strip()
        if not pr_id:
            self._send_json(400, {"ok": False, "error": "'pr_id' is required"})
            return

        approved_by = str(body.get("approved_by") or "human").strip() or "human"
        _, proj_doc = vcs_sync._find_pr_dir_and_project(ws_dir, pr_id)
        if proj_doc is None:
            self._send_json(404, {"ok": False, "error": f"PR '{pr_id}' not found"})
            return

        canonical_pr_id = proj_doc.spec.charter.pr_id
        rc, _, err_out = _run_pa_cli_captured(
            ["pr", "approve-plan", canonical_pr_id, "--path", str(repo_root)]
        )
        if rc != 0:
            self._send_json(
                400,
                {"ok": False, "error": err_out.strip() or f"Failed to approve plan for {pr_id}"},
            )
            return

        pa_conv_id: str | None = None
        with state_db.StateDB(db_file) as db:
            db.set_config(f"plan_approved_by:{canonical_pr_id}", approved_by)
            for esc in db.open_escalations(pr_id=canonical_pr_id):
                if esc.get("reason_code") in (
                    "PLAN_APPROVAL_REQUIRED",
                    "R1_MON_PLAN_APPROVAL",
                    "R2_PLAN_APPROVAL",
                ) or esc.get("blocker_type") == "plan_approval":
                    db.resolve_escalation(str(esc["escalation_id"]), status="RESOLVED")

            for item in db.list_open(pr_id=canonical_pr_id):
                if item.get("kind") in (
                    "plan_approval",
                    "R1_MON_PLAN_APPROVAL",
                    "R2_PLAN_APPROVAL",
                ):
                    db.dequeue(str(item["item_id"]), status="RESOLVED")

            pa_conv_id = db.get_config(f"pa_session:{canonical_pr_id}")
            if not pa_conv_id:
                cur = db.conn.execute(
                    """
                    SELECT conversation_id FROM sessions
                    WHERE UPPER(pr_id) = UPPER(?)
                      AND LOWER(role) IN ('pa', 'pa-principal-architect', 'principal-architect')
                    ORDER BY updated_at DESC, rowid DESC
                    LIMIT 1
                    """,
                    (canonical_pr_id,),
                )
                row = cur.fetchone()
                if row is not None:
                    pa_conv_id = str(row["conversation_id"])

        if pa_conv_id:
            models.LanguageServerClient().send_message(
                pa_conv_id,
                f"PROJECT.md Part II plan for {canonical_pr_id} approved by {approved_by}.",
            )

        self._send_json(
            200,
            {
                "ok": True,
                "pr_id": canonical_pr_id,
                "status": "APPROVED",
                "approved_by": approved_by,
                "conversation_id": pa_conv_id,
            },
        )

    def _handle_post_escalation_resolve(
        self,
        ws_dir: Path,
        db_file: Path,
        body: dict[str, Any],
    ) -> None:
        escalation_id = str(body.get("escalation_id") or "").strip()
        decision = str(body.get("decision") or "").strip().lower()
        resolution_note = str(body.get("resolution_note") or "").strip()

        if not escalation_id:
            self._send_json(400, {"ok": False, "error": "'escalation_id' is required"})
            return
        if decision not in ("approve", "deny"):
            self._send_json(
                400,
                {"ok": False, "error": "'decision' must be 'approve' or 'deny'"},
            )
            return

        with state_db.StateDB(db_file) as db:
            cur = db.conn.execute(
                "SELECT * FROM escalations WHERE escalation_id = ?",
                (escalation_id,),
            )
            row = cur.fetchone()
            if row is None:
                self._send_json(
                    404,
                    {"ok": False, "error": f"Escalation '{escalation_id}' not found"},
                )
                return

            esc_dict = dict(row)
            pr_id = esc_dict.get("pr_id")
            wo_id = esc_dict.get("wo_id")

            req_override = body.get("requested_files")
            if isinstance(req_override, list):
                files_to_add = [str(f).strip() for f in req_override if str(f).strip()]
            else:
                files_to_add = _parse_json_list_str(esc_dict.get("requested_files_json"))

            updated_allowed_files: list[str] = []
            wo_doc = (
                pre_tool_gate._find_bound_workorder(ws_dir, pr_id, wo_id)
                if wo_id
                else None
            )

            if decision == "approve":
                if wo_doc is not None and wo_doc.path is not None:
                    existing_allowed = list(wo_doc.spec.allowed_files)
                    for fpath in files_to_add:
                        if fpath not in existing_allowed:
                            existing_allowed.append(fpath)
                    wo_doc.spec.allowed_files = existing_allowed
                    if wo_doc.spec.status in (
                        schemas.WorkOrderStatus.BLOCKED,
                        schemas.WorkOrderStatus.ESCALATED_TO_PA,
                    ):
                        wo_doc.spec.status = schemas.WorkOrderStatus.IN_PROGRESS
                    wo_doc.spec.spec_hash = schemas.compute_spec_hash(wo_doc)
                    wo_doc.path.write_text(
                        schemas.dump_document(wo_doc.spec, wo_doc.sections),
                        encoding="utf-8",
                    )
                    updated_allowed_files = list(wo_doc.spec.allowed_files)

                    proj_md = wo_doc.path.parent.parent / "PROJECT.md"
                    if proj_md.is_file():
                        try:
                            proj_doc = schemas.load_project(proj_md)
                            proj_changed = False
                            for wrow in proj_doc.spec.work_orders:
                                if wrow.id.upper() == wo_doc.spec.wo_id.upper() and wrow.status in (
                                    schemas.WorkOrderStatus.BLOCKED,
                                    schemas.WorkOrderStatus.ESCALATED_TO_PA,
                                ):
                                    wrow.status = schemas.WorkOrderStatus.IN_PROGRESS
                                    proj_changed = True
                            if proj_changed:
                                proj_md.write_text(
                                    schemas.dump_document(proj_doc.spec, proj_doc.sections),
                                    encoding="utf-8",
                                )
                        except Exception:  # noqa: BLE001, S110
                            pass

                db.resolve_escalation(escalation_id, status="RESOLVED")
                target_attn_status = "RESOLVED"
            else:
                if wo_doc is not None:
                    updated_allowed_files = list(wo_doc.spec.allowed_files)
                db.resolve_escalation(escalation_id, status="DENIED")
                target_attn_status = "DISMISSED"

            for item in db.list_open():
                payload_raw = item.get("action_payload_json") or "{}"
                try:
                    ap = json.loads(payload_raw)
                except json.JSONDecodeError:
                    ap = {}
                ap_esc_id = ap.get("escalation_id") if isinstance(ap, dict) else None
                if ap_esc_id == escalation_id or (
                    wo_id
                    and item.get("wo_id") == wo_id
                    and "escalation" in str(item.get("kind") or "")
                ):
                    db.dequeue(str(item["item_id"]), status=target_attn_status)

        self._send_json(
            200,
            {
                "ok": True,
                "escalation_id": escalation_id,
                "decision": decision,
                "status": "RESOLVED" if decision == "approve" else "DENIED",
                "allowed_files": updated_allowed_files,
                "resolution_note": resolution_note or None,
            },
        )

    def _handle_post_pr_start(
        self,
        repo_root: Path,
        ws_dir: Path,
        db_file: Path,
        body: dict[str, Any],
    ) -> None:
        pr_id = str(body.get("pr_id") or "").strip()
        if not pr_id:
            self._send_json(400, {"ok": False, "error": "'pr_id' is required"})
            return

        pr_dir, proj_doc = vcs_sync._find_pr_dir_and_project(ws_dir, pr_id)
        if proj_doc is None:
            self._send_json(404, {"ok": False, "error": f"PR '{pr_id}' not found"})
            return

        canonical_pr_id = proj_doc.spec.charter.pr_id
        rc, std_out, err_out = _run_pa_cli_captured(
            ["pr", "start", canonical_pr_id, "--path", str(repo_root)]
        )
        if rc != 0:
            self._send_json(
                409,
                {"ok": False, "error": err_out.strip() or f"Failed to start {canonical_pr_id}"},
            )
            return

        try:
            cli_payload = json.loads(std_out) if std_out.strip() else {}
        except json.JSONDecodeError:
            cli_payload = {}

        explicit_conv_id = str(body.get("conversation_id") or "").strip()
        final_conv_id = explicit_conv_id or str(cli_payload.get("conversation_id") or "")

        with state_db.StateDB(db_file) as db:
            if final_conv_id:
                db.bind_session(
                    final_conv_id,
                    role="pa",
                    programme_id=proj_doc.spec.charter.programme_id,
                    pr_id=canonical_pr_id,
                    pinned=1,
                )
                db.set_config(f"pa_session:{canonical_pr_id}", final_conv_id)

        proj_md = pr_dir / "PROJECT.md"
        if proj_md.is_file():
            try:
                reloaded = schemas.load_project(proj_md)
                if reloaded.spec.status == schemas.PRState.APPROVED:
                    reloaded.spec.status = schemas.PRState.IN_PROGRESS
                    proj_md.write_text(
                        schemas.dump_document(reloaded.spec, reloaded.sections),
                        encoding="utf-8",
                    )
            except Exception:  # noqa: BLE001, S110
                pass

        self._send_json(
            200,
            {
                "ok": True,
                **cli_payload,
                "pr_id": canonical_pr_id,
                "conversation_id": final_conv_id,
                "pa_conversation_id": final_conv_id,
            },
        )

    def _handle_post_wo_debug(
        self,
        repo_root: Path,
        ws_dir: Path,
        db_file: Path,
        body: dict[str, Any],
    ) -> None:
        wo_id = str(body.get("wo_id") or "").strip()
        if not wo_id:
            self._send_json(400, {"ok": False, "error": "'wo_id' is required"})
            return

        wo_doc = pre_tool_gate._find_bound_workorder(ws_dir, None, wo_id)
        if wo_doc is None:
            self._send_json(404, {"ok": False, "error": f"Work Order '{wo_id}' not found"})
            return

        canonical_wo_id = wo_doc.spec.wo_id
        canonical_pr_id = wo_doc.spec.pr_id

        with state_db.StateDB(db_file) as db:
            prior_open_escs = [
                str(e["escalation_id"])
                for e in db.open_escalations(wo_id=canonical_wo_id)
            ]

        cmd = ["wo", "debug", canonical_wo_id, "--path", str(repo_root)]
        reason = str(body.get("reason") or "").strip()
        if reason:
            cmd.extend(["--reason", reason])

        rc, std_out, err_out = _run_pa_cli_captured(cmd)
        if rc != 0:
            self._send_json(
                400,
                {"ok": False, "error": err_out.strip() or f"Failed to debug {canonical_wo_id}"},
            )
            return

        try:
            cli_payload = json.loads(std_out) if std_out.strip() else {}
        except json.JSONDecodeError:
            cli_payload = {}

        explicit_conv_id = str(body.get("conversation_id") or "").strip()
        with state_db.StateDB(db_file) as db:
            # Resolve existing worker session if present so it is also marked pinned=1
            cur_existing = db.conn.execute(
                """
                SELECT conversation_id FROM sessions
                WHERE UPPER(wo_id) = UPPER(?)
                ORDER BY updated_at DESC, rowid DESC
                """,
                (canonical_wo_id,),
            )
            existing_rows = cur_existing.fetchall()
            for srow in existing_rows:
                db.update_session(str(srow["conversation_id"]), pinned=1)

            final_conv_id = explicit_conv_id or str(
                cli_payload.get("conversation_id")
                or (existing_rows[0]["conversation_id"] if existing_rows else "")
            )
            if final_conv_id:
                db.bind_session(
                    final_conv_id,
                    role="debugger",
                    pr_id=canonical_pr_id,
                    wo_id=canonical_wo_id,
                    pinned=1,
                )
                db.set_config(f"wo_session:{canonical_wo_id}", final_conv_id)

            # Resolve open escalations and attention queue items for this WO now that debug is launched
            for esc in db.open_escalations(wo_id=canonical_wo_id):
                db.resolve_escalation(str(esc["escalation_id"]), status="RESOLVED")
            for esc_id in prior_open_escs:
                db.resolve_escalation(esc_id, status="RESOLVED")
            for item in db.list_open():
                if str(item.get("wo_id") or "").upper() == canonical_wo_id.upper():
                    db.dequeue(str(item["item_id"]), status="RESOLVED")

        self._send_json(
            200,
            {
                "ok": True,
                **cli_payload,
                "wo_id": canonical_wo_id,
                "pr_id": canonical_pr_id,
                "conversation_id": final_conv_id,
                "pinned": True,
            },
        )

    def _handle_post_pr_graduate(
        self,
        repo_root: Path,
        ws_dir: Path,
        body: dict[str, Any],
    ) -> None:
        pr_id = str(body.get("pr_id") or "").strip()
        if not pr_id:
            self._send_json(400, {"ok": False, "error": "'pr_id' is required"})
            return

        _, proj_doc = vcs_sync._find_pr_dir_and_project(ws_dir, pr_id)
        if proj_doc is None:
            self._send_json(404, {"ok": False, "error": f"PR '{pr_id}' not found"})
            return

        canonical_pr_id = proj_doc.spec.charter.pr_id
        cmd = ["pr", "graduate", canonical_pr_id, "--path", str(repo_root)]
        if body.get("skip_floor"):
            cmd.append("--skip-floor")

        rc, std_out, err_out = _run_pa_cli_captured(cmd)
        if rc != 0:
            self._send_json(
                409,
                {
                    "ok": False,
                    "error": err_out.strip() or f"Cannot graduate {canonical_pr_id}",
                },
            )
            return

        try:
            grad_payload = json.loads(std_out) if std_out.strip() else {}
        except json.JSONDecodeError:
            grad_payload = {}

        self._send_json(
            200,
            {
                "ok": True,
                "pr_id": canonical_pr_id,
                "status": "GRADUATED",
                **grad_payload,
            },
        )

    def _handle_post_sync(self, repo_root: Path) -> None:
        try:
            sync_res = vcs_sync.sync_state(repo_root)
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"ok": False, "error": str(exc)})
            return

        self._send_json(
            200,
            {
                "ok": True,
                "sync": sync_res,
                **sync_res,
            },
        )


def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    daemon_home: str | Path | None = None,
) -> CockpitHTTPServer:
    """Create and bind a `CockpitHTTPServer` instance on `(host, port)`."""
    resolved_home = _resolve_daemon_home(daemon_home)
    cand_ui = resolved_home / "sidecars" / "pa_cockpit" / "ui"
    ui_dir = cand_ui if cand_ui.is_dir() else _repo_ui_dir()
    return CockpitHTTPServer(
        (host, int(port)),
        CockpitRequestHandler,
        daemon_home=resolved_home,
        ui_dir=ui_dir,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint starting the Principal Architect Cockpit HTTP + SSE server."""
    parser = argparse.ArgumentParser(
        prog="cockpit.py",
        description="Principal Architect Cockpit AuxPane HTTP + SSE backend.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "127.0.0.1"),
        help="Bind host address (default: 127.0.0.1 or $HOST).",
    )
    default_port = int(
        os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT")
        or os.environ.get("PORT")
        or "0"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help="Bind port (default: $ANTIGRAVITY_SIDECAR_WEB_PORT, $PORT, or 0 ephemeral).",
    )
    parser.add_argument(
        "--daemon-home",
        default=None,
        help="Optional PA_DAEMON_HOME override.",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    server = create_server(
        host=str(args.host),
        port=int(args.port),
        daemon_home=args.daemon_home,
    )
    bound_host, bound_port = server.server_address[:2]
    print(
        json.dumps({"listening": f"http://{bound_host}:{bound_port}", "port": bound_port}),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
