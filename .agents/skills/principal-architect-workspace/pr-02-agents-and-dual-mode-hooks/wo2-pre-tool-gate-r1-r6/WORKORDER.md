---
schema_version: 1
wo_id: WO-02.2
pr_id: PR-02
title: "PreToolUse gate enforcing R1, R1b, R2, R3, R4, R5, R6 with realpath traversal defense and <1ms fast-exit"
complexity: architect
status: PENDING
allowed_files:
  - daemon/workspace-plugin/principal-architect/scripts/pre_tool_gate.py
  - tests/test_hooks_monitored_vs_autonomous.py
forbidden_files:
  - SPEC.md
  - docs/positioning-paper.md
  - .agents/skills/principal-architect-workspace/pr-02-agents-and-dual-mode-hooks/PROJECT.md
  - .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: "./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests"
max_attempts: 5
max_structural_failures: 2
spec_hash: a6e4e0c9d37450362c8a9e2f040b9dafab8990c5a6cde5febeb2224ea46e5400
completion: null
---

# WO-02.2 — `PreToolUse` Gate (`R1`, `R1b`, `R2`, `R3`, `R4`, `R5`, `R6`) & Traversal Defense

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-02` (`pr-02-agents-and-dual-mode-hooks`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T20:05:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/workspace-plugin/principal-architect/scripts/pre_tool_gate.py` (with `<1ms` unenrolled fast-exit before heavy imports, `os.path.realpath` canonical path resolution and traversal defense, and `evaluate_pre_tool(payload, *, repo_root=None)` / `main()` enforcing rules `R1`, `R1b`, `R2`, `R3`, `R4`, `R5`, and `R6` across `monitored` and `autonomous` modes), and add comprehensive unit and subprocess tests in `tests/test_hooks_monitored_vs_autonomous.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/pre_tool_gate.py`
  - `tests/test_hooks_monitored_vs_autonomous.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-02-agents-and-dual-mode-hooks/wo2-pre-tool-gate-r1-r6/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Lazy Import Rule (Charter G2 & R1):** `pre_tool_gate.py` MUST NOT import `pydantic`, `yaml`, or `schemas` at module top-level. Import `common` and `escalation` at top-level, check `common.is_repo_enrolled(workspace_paths)` first, and if `False`, return `{}` / exit `0` in `< 1 ms` without importing `pydantic`, `yaml`, or `schemas`. Import `schemas` lazily only on the enrolled evaluation path when inspecting Markdown documents.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh`. Commit only on the currently checked-out branch `pr-02-agents-and-dual-mode-hooks/wo2-pre-tool-gate-r1-r6` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R9):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/pre_tool_gate.py` (mark executable `chmod +x`):**
  1. **Entrypoint & Unenrolled Fast-Exit (Charter G2, R1, R2, §2.2):**
     - Start with `#!/usr/bin/env python3` and insert `str(Path(__file__).resolve().parent)` into `sys.path[0]` if not present.
     - Import only stdlib modules, `common`, `state_db`, and `escalation` at top-level (zero `pydantic`, `yaml`, or `schemas` at top-level).
     - Export `evaluate_pre_tool(payload: Mapping[str, Any], *, repo_root: str | Path | None = None, runner: common.Runner = common.run) -> dict[str, Any]` and `main(argv: Sequence[str] | None = None) -> int`.
     - Fast-exit check:
       - If `repo_root is None`: extract `workspace_paths = escalation.extract_workspace_paths(payload)`. If `not common.is_repo_enrolled(workspace_paths)`, return `{}` immediately! Otherwise resolve `repo_root` by finding the first `wp` in `workspace_paths` where `common.find_repo_root(wp)` is enrolled in `common.is_repo_enrolled([wp])` (falling back to `common.find_repo_root(workspace_paths[0])`).
       - If `repo_root is not None`: if `not (Path(repo_root) / common.NEW_WORKSPACE_REL / ".state" / "state.db").is_file()` and `not (Path(repo_root) / common.LEGACY_WORKSPACE_REL / ".state" / "state.db").is_file()` and `not common.is_repo_enrolled([str(repo_root)])`, return `{}` immediately!
     - `main()` reads `payload = escalation.read_hook_input()`, calls `evaluate_pre_tool(payload)` wrapped in a top-level `try/except Exception` (logging any unexpected error to `sys.stderr` and returning `{}` so the harness is never crashed), writes the output via `escalation.write_hook_output(res)`, and returns `0`.
  2. **Canonical Path Resolution & Pattern Matching (`resolve_repo_rel_path`, `matches_pattern`, `matches_any_pattern`, Charter G3 & R3):**
     - `resolve_repo_rel_path(repo_root: Path, raw_path: str) -> tuple[bool, str, Path]`:
       - Strip `file://` if present (`common._strip_file_uri` or `urllib.parse`).
       - Resolve `real_root = Path(os.path.realpath(repo_root))`.
       - Candidate path: if `Path(cleaned).is_absolute()`, `cand = Path(cleaned)`, else `cand = real_root / cleaned`.
       - Resolve `real_target = Path(os.path.realpath(cand))`.
       - Check whether `real_target == real_root` or `real_root in real_target.parents`.
       - If inside `real_root`: return `(True, real_target.relative_to(real_root).as_posix(), real_target)`.
       - If outside `real_root` (e.g. `../../etc/passwd` traversal or symlink escape pointing outside `real_root`): return `(False, str(raw_path), real_target)`.
     - `matches_pattern(rel_posix: str, pattern: str) -> bool`:
       - Normalize `pat = pattern.strip().lstrip("./")`.
       - Support exact match (`rel_posix == pat.rstrip("/")`), directory prefix (`pat.endswith("/")` and `rel_posix.startswith(pat)`, or `pat.endswith("/**")` and `(rel_posix == pat[:-3] or rel_posix.startswith(pat[:-2]))`, or `rel_posix.startswith(pat.rstrip("/") + "/")`), and `fnmatch.fnmatch(rel_posix, pat)`.
     - `matches_any_pattern(rel_posix: str, patterns: Sequence[str]) -> bool`: returns `any(matches_pattern(rel_posix, p) for p in patterns)`.
  3. **Extracting Target Path & Simulating Edits for File Tools:**
     - Recognize mutating file tools: `FILE_MUTATION_TOOLS = frozenset({"write_to_file", "write_file", "replace_file_content", "edit_file", "multi_replace_file_content"})`.
     - Extract target path from `toolCall.args` checking keys in order: `"TargetFile"`, `"Path"`, `"file_path"`, `"path"`, `"FilePath"`, `"TargetPath"`.
     - Helper `simulate_file_edit(existing_text: str, tool_name: str, args: Mapping[str, Any]) -> str | None`:
       - If `tool_name in ("write_to_file", "write_file")`: extract `content = args.get("CodeContent") if "CodeContent" in args else (args.get("Content") if "Content" in args else args.get("content"))`. If `not isinstance(content, str)`, return `None`. If `args.get("Append")` is True, return `existing_text + content`, else return `content`.
       - If `tool_name in ("replace_file_content", "edit_file")`:
         - If `"ReplacementChunks"` in `args` and isinstance(args["ReplacementChunks"], list): apply each chunk (`TargetContent` -> `ReplacementContent`) sequentially; if any `TargetContent` is not in current text, return `None`.
         - Else extract `target = args.get("TargetContent") if "TargetContent" in args else args.get("Target")` and `replacement = args.get("ReplacementContent") if "ReplacementContent" in args else args.get("Replacement")`. If both are strings and `target in existing_text`, return `existing_text.replace(target, replacement)`. Else return `None`.
       - If `tool_name == "multi_replace_file_content"`: apply each chunk in `args.get("ReplacementChunks", [])` (`TargetContent` -> `ReplacementContent`); if any fails, return `None`.
       - Return `None` for unknown tools.
  4. **Enforcing Rules `R1`, `R1b`, `R2`, `R3`, `R4`, `R5`, `R6` (Charter G3 & SPEC §7.2):**
     - Open `StateDB(ws_dir / ".state" / "state.db")`.
     - Read `mode = db.get_config("execution_mode", "monitored") or "monitored"`.
     - Look up session row via `conversation_id = str(payload.get("conversationId") or "")`: `session = db.get_session(conversation_id)` if `conversation_id` else `None`.Also allow `payload.get("role")` / `payload.get("prId")` / `payload.get("woId")` as fallback when testing or when session is not yet bound. Normalize `role`:
       - Map `"pa-chief-architect"` / `"chief-architect"` / `"chief"` -> `"chief"`
       - Map `"pa-principal-architect"` / `"principal-architect"` / `"pa"` -> `"pa"`
       - Map `"pa-engineer"` / `"engineer"` / `"worker"` -> `"engineer"`
       - Map `"pa-auditor"` / `"auditor"` -> `"auditor"`
       - Map `"pa-debugger"` / `"debugger"` -> `"debugger"`
     - Helper `_finalize_decision(db, session, decision_dict) -> dict[str, Any]`:
       - If `decision_dict.get("increment_structural_failures")` and `session` is not None:
         `db.update_session(session["conversation_id"], structural_failures=int(session.get("structural_failures") or 0) + 1)`
       - If `decision_dict.get("escalation")` is a dict:
         `esc = decision_dict["escalation"]`
         Call `escalation.record_escalation(db, level=esc["level"], source_role=esc["source_role"], target_role=esc["target_role"], pr_id=esc.get("pr_id"), wo_id=esc.get("wo_id"), blocker_type=esc["blocker_type"], reason_code=esc["reason_code"], requested_files=esc.get("requested_files"), summary=esc["summary"], enqueue_if_needed=bool(esc.get("enqueue_attention")), attention_kind=esc.get("attention_kind"), attention_title=esc.get("attention_title"), attention_priority=int(esc.get("attention_priority", 20)))`
       - Return `decision_dict`.
     - **Rule R6 (Graduation Audit Gate — applies to any role running `run_command` with `pa pr graduate` or `gh pr merge`):**
       - When `tool_name == "run_command"` and command string matches `r"\b(?:pa(?:\s+|_cli\.py\s+)pr\s+graduate|gh\s+pr\s+merge)\b"`:
         - Lazy-import `schemas`.
         - Determine `head_sha`: run `runner(["git", "rev-parse", "HEAD"], cwd=real_root)` (or fallback `"HEAD"`).
         - Determine target `pr_id` (from command tokens like `PR-\d+[a-z]?`, or `session.get("pr_id")`, or single `pr-*/PROJECT.md`).
         - Scan `ws_dir.glob("pr-*/AUDIT-round-*.md")` (filtered to matching `pr_id` if known): check if any `AuditReport` loaded via `schemas.load_audit` has `verdict == "APPROVED"` and (`head_sha.startswith(report.head_sha)` or `report.head_sha.startswith(head_sha)`).
         - If no matching `APPROVED` audit report exists for current `HEAD`, return `_finalize_decision(db, session, escalation.decide("R6", mode, {"pr_id": pr_id, "head_sha": head_sha[:12]}))`.
     - **Rule R5 (Auditor Read-Only Lockdown — `role == "auditor"`):**
       - If `tool_name in FILE_MUTATION_TOOLS` or `tool_name == "invoke_subagent"`:
         return `_finalize_decision(db, session, escalation.decide("R5", mode, {"path": raw_path or tool_name, "command": tool_name}))`.
       - If `tool_name == "run_command"`:
         - Check if command mutates git/files: block if command matches any mutating pattern such as `r"\bgit\s+(?:commit|push|checkout|switch|branch|rebase|merge|reset|clean|mv|rm|tag|stash)\b"`, `r"\bgh\s+(?:pr\s+(?:create|merge|close|edit)|issue\s+(?:create|close|edit))\b"`, `r"\b(?:rm|mv|cp|touch|mkdir|rmdir|chmod|chown|dd|tee)\b"`, `r"\bsed\s+-i\b"`, or shell redirection `r"(?:^|[^0-9<>])>{1,2}\s*(?!/dev/null\b)\S"` (while allowing `2>&1`, `>/dev/null`, `pytest`, `ruff`, `git diff`, `git log`, `git status`, `git show`, `gh pr diff`, `gh pr view`, and `pa pr post-audit`).
         - If mutating, return `_finalize_decision(db, session, escalation.decide("R5", mode, {"command": cmd_str}))`.
     - **Rules R1 & R1b (Architect Gates — `role in ("chief", "pa")`):**
       - When `tool_name in FILE_MUTATION_TOOLS`:
         - Resolve `(inside_repo, rel_posix, real_target) = resolve_repo_rel_path(real_root, raw_path)`.
         - Workspace prefixes: `ws_rel = ws_dir.relative_to(real_root).as_posix()` (and check both `common.NEW_WORKSPACE_REL.as_posix()` and `common.LEGACY_WORKSPACE_REL.as_posix()`).
         - If `not inside_repo` or not (`rel_posix == ws_rel` or `rel_posix.startswith(ws_rel + "/")` or `rel_posix.startswith(common.NEW_WORKSPACE_REL.as_posix() + "/")` or `rel_posix.startswith(common.LEGACY_WORKSPACE_REL.as_posix() + "/")`):
           - Target is outside `.agents/{plugins,skills}/principal-architect-workspace/`!
           - Trigger **`R1`**: return `_finalize_decision(db, session, escalation.decide("R1", mode, {"path": rel_posix if inside_repo else raw_path, "pr_id": pr_id}))`.
         - Inside workspace directory:
           - If `role == "pa"`:
             - Lazy-import `schemas`.
             - **Case 1: Target is `pr-*/PROJECT.md`:**
               - If `real_target.is_file()`: load `existing_proj = schemas.load_project(real_target)`.
               - If `existing_proj.spec.charter.charter_locked`:
                 - Simulate edit via `proposed_text = simulate_file_edit(real_target.read_text(encoding="utf-8"), tool_name, args)`.
                 - Verify `proposed_text is not None`, `schemas.parse_document` + `schemas.ProjectSpec.model_validate` succeeds on `proposed_text`, and `schemas.compute_charter_hash(proposed_text) == existing_proj.spec.charter.charter_hash` (and `proposed_spec.charter == existing_proj.spec.charter`).
                 - If any check fails (Part I Charter YAML or Sections 1–2 was modified!), trigger **`R1b`**: return `_finalize_decision(db, session, escalation.decide("R1b", mode, {"path": rel_posix, "pr_id": existing_proj.spec.charter.pr_id}))`.
             - **Case 2: Target is `programme-*/PROGRAM.md`:**
               - `pa` cannot modify `PROGRAM.md` (Chief-owned) -> trigger **`R1b`**.
             - **Case 3: Target is `pr-*/wo*/WORKORDER.md`:**
               - Simulate edit (`proposed_text`). If `proposed_text` parses as a `WorkOrderSpec`, locate parent `PROJECT.md` (`real_target.parent.parent / "PROJECT.md"`). If parent `PROJECT.md` exists, check that every pattern/file in `wo_spec.allowed_files` is within `proj_doc.spec.charter.allowed_modules` (i.e. `matches_any_pattern(af.rstrip("/"), proj_doc.spec.charter.allowed_modules)` or prefix match). If any `allowed_file` falls outside `charter.allowed_modules`, trigger **`R1b`** (`path=offending_file`)!
           - If `role == "chief"`:
             - If target is `pr-*/wo*/WORKORDER.md`, trigger **`R1`** (Chief is forbidden from editing individual `WORKORDER.md` files per SPEC §3.1 / §5.2).
       - When `tool_name == "run_command"` and `role in ("chief", "pa")`:
         - If command mutates application source files outside `.agents/` (e.g., `rm src/...`, `mv src/...`, `sed -i ... src/...`, or redirects `> src/...`), trigger **`R1`**.
     - **Rule R2 (Plan Approval Gate — `role == "pa"` calling `invoke_subagent`):**
       - When `tool_name == "invoke_subagent"` and `role == "pa"`:
         - Inspect `args`: `sub_type = str(args.get("TypeName") or args.get("subagent_type") or "")`, `sub_role = str(args.get("Role") or "")`, `sub_prompt = str(args.get("Prompt") or "")`.
         - Check if this is spawning an Execution Worker (`sub_type == "pa-engineer"` or `"engineer" in sub_role.lower()` or `"worker" in sub_role.lower()` or `"pa_role: engineer"` in `sub_prompt.lower()`; do not block `pa-auditor`).
         - Locate active `PROJECT.md` (by `pr_id` from `session` or `sub_prompt`, or single `pr-*/PROJECT.md` in `ws_dir`).
         - If `proj_doc` exists and `proj_doc.spec.status == schemas.PRState.PLANNED`:
           - Read `auto_approve = (db.get_config("auto_approve_pr_plans", "false") or "false").lower() in ("true", "1", "yes")`.
           - Compute `plan_valid`: check `schemas.verify_charter_hash(proj_doc)` is `True`, `len(proj_doc.spec.work_orders) >= 1`, and all `wo*/WORKORDER.md` in `pr_dir` validate via `schemas.load_workorder` and have `allowed_files` within `proj_doc.spec.charter.allowed_modules`.
           - Call `decision = escalation.decide("R2", mode, {"pr_id": proj_doc.spec.charter.pr_id, "auto_approve_pr_plans": auto_approve, "plan_valid": plan_valid})`.
           - If `decision.get("auto_approve_plan")`:
             - Update `proj_doc.spec.status = schemas.PRState.APPROVED`, `proj_doc.spec.approved_at = datetime.now(UTC)` (or ISO string), stamp `spec_hash` on each `wo*/WORKORDER.md` if `spec_hash is None`, and write `proj_path.write_text(schemas.dump_document(proj_doc.spec, proj_doc.sections), encoding="utf-8")`.
           - Return `_finalize_decision(db, session, decision)`.
     - **Rules R3 & R4 (Worker Boundary Box, Spec Lock & Git/GH Lockdown — `role == "engineer"`):**
       - Locate bound `WORKORDER.md` via `wo_id = session.get("wo_id")` / `pr_id = session.get("pr_id")` (searching `ws_dir.glob("pr-*/wo*/WORKORDER.md")` for matching `wo_id` or folder slug).
       - **Rule R4 (`tool_name == "run_command"`):**
         - Check if `cmd_str` matches forbidden worker git/gh operations:
           `r"\bgit\s+(?:push|checkout|switch|branch|rebase|merge)\b"`, `r"\bgit\s+reset\s+--hard\b"`, `r"\bgh\s+(?:pr|issue)\b"`.
         - If matched, return `_finalize_decision(db, session, escalation.decide("R4", mode, {"command": cmd_str, "pr_id": pr_id, "wo_id": wo_id}))`.
       - **Rule R3 (`tool_name in FILE_MUTATION_TOOLS`):**
         - Resolve `(inside_repo, rel_posix, real_target) = resolve_repo_rel_path(real_root, raw_path)`.
         - If `not inside_repo`:
           - Path traversal (`../`) or symlink escape outside `repo_root`! Trigger **`R3`** immediately:
             return `_finalize_decision(db, session, escalation.decide("R3", mode, {"path": raw_path, "pr_id": pr_id, "wo_id": wo_id, "reason_code": "PATH_TRAVERSAL_BLOCKED"}))`.
         - If `wo_doc` is found (`wo_md_path = wo_doc.path.resolve()`):
           - **Case A: Worker is editing its own bound `WORKORDER.md` (`real_target == wo_md_path`):**
             - If `wo_doc.spec.spec_hash`:
               - Simulate edit (`proposed_text = simulate_file_edit(wo_md_path.read_text(encoding="utf-8"), tool_name, args)`).
               - Check that `proposed_text is not None`, `schemas.load_workorder` / `parse_document` + `WorkOrderSpec.model_validate` succeeds on `proposed_text`, and `schemas.verify_spec_hash(proposed_text)` is `True` (and `proposed_spec.spec_hash == wo_doc.spec.spec_hash`).
               - If Part I or `spec_hash` was mutated, trigger **`R3`** (`reason_code="SPEC_LOCK_VIOLATION"`):
                 return `_finalize_decision(db, session, escalation.decide("R3", mode, {"path": rel_posix, "pr_id": pr_id, "wo_id": wo_id, "reason_code": "SPEC_LOCK_VIOLATION"}))`.
               - Otherwise (only Part II `status`, `completion`, and `## Completion Report` modified), allow!
           - **Case B: Worker is editing any other file:**
             - If `matches_any_pattern(rel_posix, wo_doc.spec.forbidden_files)` or not `matches_any_pattern(rel_posix, wo_doc.spec.allowed_files)`:
               return `_finalize_decision(db, session, escalation.decide("R3", mode, {"path": rel_posix, "pr_id": pr_id, "wo_id": wo_id, "reason_code": "BOUNDARY_EXPANSION_NEEDED"}))`.
     - If no rule blocks or asks, return `{"permissionDecision": "allow", "decision": "allow", "reason": "Allowed by pre_tool_gate"}`.
- [ ] **`tests/test_hooks_monitored_vs_autonomous.py`:**
  - Add comprehensive unit and subprocess tests for `pre_tool_gate.py`:
    1. **Unenrolled fast-exit & import purity test (Charter G2, R1):**
       - Calling `pre_tool_gate.py` via subprocess on an unenrolled directory outputs `{}` and exits `0`.
       - In-process timing benchmark: `evaluate_pre_tool({"workspacePaths": [str(unenrolled_dir)]})` executes in `< 1.0 ms` (average over 20 calls) and `sys.modules` check in a subprocess confirms `pydantic`, `yaml`, and `schemas` are NOT imported on the unenrolled path.
    2. **Full `rule × mode` matrix via `evaluate_pre_tool` and subprocess stdin/stdout:**
       - `R1` (`chief` and `pa` attempting to edit `src/app.py` outside `.agents/`): `"ask"` in `monitored`, `"deny"` in `autonomous` (and allowed when editing valid workspace artifacts).
       - `R1b` (`pa` attempting to modify locked Part I `## 1.` or `charter` YAML of `PROJECT.md`, vs. allowed when modifying Part II `## 3.` / `## 4.` / `status` / `work_orders` preserving `charter_hash`; plus `pa` attempting to write a `WORKORDER.md` with `allowed_files` outside `charter.allowed_modules`): `"ask"` in `monitored`, `"deny"` + `CHARTER_AMENDMENT_NEEDED` escalation in `autonomous`.
       - `R2` (`pa` calling `invoke_subagent` for `pa-engineer` when `PROJECT.md` is `PLANNED`): `"ask"` in `monitored`; `"deny"` + `plan_approval` attention item in `autonomous` when `auto_approve_pr_plans=false`; `"allow"` + auto-transition of `PROJECT.md` to `APPROVED` and `spec_hash` stamping when `auto_approve_pr_plans=true` and plan is valid.
       - `R3` (`engineer` editing file in `allowed_files` -> `"allow"`; editing file outside `allowed_files` -> `"ask"` in `monitored`, `"deny"` + `structural_failures` incremented + `BOUNDARY_EXPANSION_NEEDED` escalation in `autonomous`; editing file in `forbidden_files` -> blocked; editing Part II of bound `WORKORDER.md` preserving `spec_hash` -> `"allow"`; tampering with Part I `## 1.` or `allowed_files` of bound `WORKORDER.md` -> blocked with `SPEC_LOCK_VIOLATION`).
       - `R4` (`engineer` running `git push`, `git checkout -b`, `git switch`, `git rebase`, `git reset --hard`, `gh pr create`): hard `"deny"` in both `monitored` and `autonomous` modes, incrementing `structural_failures`; while `git status`, `git diff`, `git add`, `git commit`, and `pytest` are `"allow"`.
       - `R5` (`auditor` attempting `write_to_file`, `edit_file`, `invoke_subagent`, `git commit`, or `rm -rf`): hard `"deny"` in both modes; while `git diff`, `gh pr diff`, `pytest`, and `pa pr post-audit` are `"allow"`.
       - `R6` (`pa pr graduate` or `gh pr merge` when no `APPROVED` `AuditReport` matches current `HEAD`): `"ask"` in `monitored`, `"deny"` in `autonomous`; and `"allow"` once an `AuditReport` with `verdict: APPROVED` and matching `head_sha` is present in `pr-*/AUDIT-round-1.md`.
    3. **Traversal & symlink escape defense tests (Charter G3 & R3):**
       - `../` path traversal outside `repo_root` (e.g. `../../outside.py`) is blocked by `R3` (for `engineer`) and `R1` (for `pa`).
       - Symlink inside an allowed directory (`src/evil_link.py -> /tmp/outside_secret.txt` or pointing to a forbidden file `SPEC.md`) is resolved via `os.path.realpath` and blocked!

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 hash over `allowed_files`, update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-02-agents-and-dual-mode-hooks/wo2-pre-tool-gate-r1-r6` with message:
   ```text
   WO-02.2: PreToolUse gate enforcing R1-R6 with realpath traversal defense

   PA-WorkOrder: WO-02.2
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

_Pending execution._
