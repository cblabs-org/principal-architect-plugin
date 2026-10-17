---
schema_version: 1
wo_id: WO-02.5
pr_id: PR-02
title: "PreInvocation session role binding, CHECKPOINT/rewind detection, and memory-mode-aware userMessage injection"
complexity: standard
status: COMPLETED
allowed_files:
  - daemon/workspace-plugin/principal-architect/scripts/pre_invocation.py
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
spec_hash: 6748b6571c16ecd05fcc47f68ec04ab1cad6c6105f0e8c16acbce451d5245060
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: rcpt_72a39d4c72d7
  commit_sha: 2374a4747e1923b9deb21c15286a402e90385f0a
  files_modified:
    - daemon/workspace-plugin/principal-architect/scripts/pre_invocation.py
    - tests/test_hooks_monitored_vs_autonomous.py
  verification_summary: "81 passed in 13.95s across test_schemas, test_state_db_and_sync, and test_hooks_monitored_vs_autonomous; ruff check clean."
  out_of_scope_findings: []
  escalation_request: null
  decisions_made:
    - "Combined compaction (CHECKPOINT step_index > prev_cp) and step-count rewind (step_watermark < prev_cp) into a single watermark tracker on sessions.last_checkpoint_step."
    - "Enforced strict memory_mode boundary so external mode completely omits memory/MEMORY.md and memory/MODULE_INDEX.md while instructing Succinct Write-Back Mode."
  dead_ends: []
---

# WO-02.5 — `PreInvocation` Role Binding, Compaction/Rewind Detection, and Context Injection

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-02` (`pr-02-agents-and-dual-mode-hooks`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T20:05:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/workspace-plugin/principal-architect/scripts/pre_invocation.py` (`parse_spawn_header`, `evaluate_pre_invocation`, and `main()`) enforcing SPEC §7.1 & §9.1–9.2 and PR-02 Charter G6, R1, and R2:
1. `< 1 ms` unenrolled fast-exit (`common.is_repo_enrolled`) with zero top-level imports of `pydantic`, `yaml`, or `schemas`.
2. `parse_spawn_header(text: str) -> dict[str, str]` parsing `PA_ROLE:`, `PR_ID:`, `WO_ID:`, and `PROGRAMME_ID:` headers from subagent spawn prompts and transcript steps.
3. Automatic Turn 1 session binding in `.state/state.db` (`sessions` table) when an unbound `conversationId` has a spawn header in its prompt or `transcript.jsonl`.
4. Compaction (`CHECKPOINT` step) and step-rewind detection on `transcript.jsonl` to re-arm context injection when a bound conversation compacts or rewinds.
5. Role-specific persistent `{"injectSteps": [{"userMessage": "..."}]}` payload generation honoring the strict `memory_mode` boundary (`builtin` injects `memory/MEMORY.md` + matching `memory/MODULE_INDEX.md` sections and **Full Distillation Mode**; `external` omits `memory/` completely and instructs **Succinct Write-Back Mode**; `engineer` injects bound `WORKORDER.md` Part I summary + explicit `SKILL.md` paths for `required_skills`).
6. Comprehensive unit and subprocess tests in `tests/test_hooks_monitored_vs_autonomous.py`.

## 2. Boundary Box & Invariants

- **Allowed Files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/pre_invocation.py`
  - `tests/test_hooks_monitored_vs_autonomous.py`
- **Forbidden Files (`forbidden_files`):**
  - `SPEC.md`, `docs/positioning-paper.md`, `PROJECT.md`, `PROGRAM.md`, and any file outside `allowed_files` (except Part II of this `WORKORDER.md`).
- **Architectural Invariants:**
  - **Lazy Imports & `< 1 ms` Fast-Exit (Charter R1):** `pre_invocation.py` MUST NOT import `pydantic`, `yaml`, or `schemas` at module top-level. Import `schemas` lazily inside functions only after confirming the repository is enrolled.
  - **Strict Memory Boundary (SPEC §7.1.3 & §9.1–9.2):** When `memory_mode == "external"`, `pre_invocation.py` MUST NOT read or inject `memory/MEMORY.md`, `memory/MODULE_INDEX.md`, or `memory/PROJECT_INDEX.md`.
  - **Hook I/O Contract (Charter R2):** Output `{"injectSteps": [{"userMessage": "..."}]}` when injecting or `{}` when no injection is needed, and always exit `0`.

## 3. Concrete Implementation Checklist

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/pre_invocation.py`:**
  - Top-level imports: stdlib (`os`, `re`, `sys`, `collections.abc`, `pathlib.Path`, `typing.Any`) plus `common`, `escalation`, `state_db`, and `pre_tool_gate` (NO top-level `pydantic`, `yaml`, or `schemas`!).
  - **`parse_spawn_header(text: str) -> dict[str, str]`:**
    - Scans lines of `text` for `PA_ROLE:`, `PR_ID:`, `WO_ID:`, and `PROGRAMME_ID:` (case-insensitive header keys, optional leading markdown quote `>` or bullet `-`, stripping surrounding whitespace/backticks/quotes).
    - Normalizes `PA_ROLE` via `pre_tool_gate._normalize_role(val)` into `"role"` (e.g. `"chief"`, `"pa"`, `"engineer"`, `"auditor"`, `"debugger"`), and populates `"pr_id"`, `"wo_id"`, `"programme_id"` when present.
    - Returns the dictionary of parsed non-empty fields.
  - Helper `_extract_matching_module_index_sections(module_index_text: str, allowed_modules: Sequence[str]) -> str`:
    - Splits `module_index_text` by H2 headings (`^## `).
    - Filters H2 sections where any token/path in `allowed_modules` appears in the section heading or body (or if no specific section matches, returns the full `module_index_text.strip()`).
  - Helper `_resolve_skill_paths(repo_root: Path, required_skills: Sequence[str]) -> list[str]`:
    - For each skill slug `s` in `required_skills`:
      - Check `(repo_root / ".agents" / "skills" / s / "SKILL.md")`, `(common.daemon_home() / "workspace-plugin" / "principal-architect" / "skills" / s / "SKILL.md")`, and `(Path(os.path.realpath(Path.home())) / ".gemini" / "config" / "skills" / s / "SKILL.md")`.
      - Return the resolved path string if found on disk, or `str(repo_root / ".agents" / "skills" / s / "SKILL.md")` as a deterministic fallback.
  - **`evaluate_pre_invocation(payload: Mapping[str, Any], *, repo_root: Path | str | None = None, runner: common.Runner = common.run) -> dict[str, Any]`:**
    - **1. Unenrolled Fast-Exit:**
      - If `repo_root is None`:
        - `workspace_paths = escalation.extract_workspace_paths(payload)`
        - If `not common.is_repo_enrolled(workspace_paths)`: return `{}` immediately!
        - Resolve `resolved_root` via `common.find_repo_root`. If `None`: return `{}`.
      - Else:
        - Check local `state.db` or `common.is_repo_enrolled([str(repo_root)])`.
      - `real_root = Path(os.path.realpath(resolved_root))`
      - `ws_dir = common.workspace_dir(real_root)`
      - `db_file = ws_dir / ".state" / "state.db"`
      - If `not db_file.is_file()`: return `{}`.
    - **2. Read Transcript & Session Binding (SPEC §7.1.1):**
      - Extract `conv_id = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()`.
      - If `not conv_id`: return `{}`.
      - Read transcript steps if `transcriptPath` / `transcript_path` is provided:
        - `t_path = payload.get("transcriptPath") or payload.get("transcript_path")`
        - `steps = common.read_transcript(common._strip_file_uri(str(t_path))) if t_path else []`
      - Open `state_db.StateDB(db_file) as db`:
        - `session = db.get_session(conv_id)`
        - Compute `latest_cp = common.latest_checkpoint_step(steps)` and `step_watermark = latest_cp if latest_cp is not None else len(steps)`.
        - `should_inject = False`
        - If `session is None`:
          - Collect candidate prompt strings from `payload` (`prompt`, `userMessage`, `message`, `initialPrompt`) and from `steps` (`step.get("content")` across `USER_INPUT`, `USER_EXPLICIT`, `SYSTEM`, or any step with string content).
          - Parse headers via `parse_spawn_header` until a non-empty `"role"` is found.
          - If not found: return `{}`.
          - Bind session via `session = db.bind_session(conv_id, role=parsed["role"], programme_id=parsed.get("programme_id"), pr_id=parsed.get("pr_id"), wo_id=parsed.get("wo_id"), attempt_num=1, structural_failures=0, pinned=0, last_checkpoint_step=step_watermark)`.
          - `should_inject = True`
        - Else (`session` already exists):
          - Also check if `session` is missing `pr_id`, `wo_id`, or `programme_id` and a spawn header in `payload`/`steps` supplies them; if so, update those fields on `session`.
          - **Compaction & Rewind Detection (SPEC §7.1.2):**
            - `prev_cp = session.get("last_checkpoint_step")`
            - `inv_num = payload.get("invocationNum") if "invocationNum" in payload else payload.get("invocation_num")`
            - Detect if injection should fire:
              1. `prev_cp is None` or `inv_num == 1`: `should_inject = True`
              2. `latest_cp is not None and int(latest_cp) > int(prev_cp)`: new `CHECKPOINT` compaction occurred -> `should_inject = True`
              3. `steps` is non-empty and `step_watermark < int(prev_cp)`: step rewind occurred -> `should_inject = True`
            - Update `last_checkpoint_step` in `sessions`:
              - When `should_inject` is `True` or `step_watermark != prev_cp` (when `steps` is non-empty): `db.update_session(conv_id, last_checkpoint_step=step_watermark)`
        - If `not should_inject`:
          - Return `{}`.
    - **3. Build Role-Specific `userMessage` Injection (SPEC §7.1.3 & §9.1–9.2):**
      - Lazily import `schemas`.
      - Read `memory_mode = db.get_config("memory_mode") or "builtin"` and `execution_mode = db.get_config("execution_mode") or "monitored"`.
      - Normalize `role = pre_tool_gate._normalize_role(str(session.get("role") or ""))`.
      - **`role in ("chief", "pa")`:**
        - Format header with `role`, `execution_mode`, and `memory_mode`.
        - If `programme-*/PROGRAM.md` exists in `ws_dir`, include Programme ID, title, and status.
        - Locate active `PROJECT.md` (matching `session.get("pr_id")` or first `pr-*/PROJECT.md` in `ws_dir`):
          - Include `pr_id`, `title`, `status`, `branch -> base_branch`, `charter_locked`, `allowed_modules`, `verification_floor`, and WO ledger summary.
        - Query open escalations in `state.db` (`SELECT * FROM escalations WHERE status = 'OPEN'`) where `target_role == role` (or all open escalations for that PR/programme) and include them if any exist.
        - **Memory Mode Branch:**
          - If `memory_mode == "builtin"`:
            - State: `Memory Mode: builtin — Use Full Distillation Mode (update MEMORY.md, MODULE_INDEX.md, and Outcome & Session Log).`
            - If `(ws_dir / "memory" / "MEMORY.md").is_file()`, include its contents under `### Builtin Memory (MEMORY.md)`.
            - If `(ws_dir / "memory" / "MODULE_INDEX.md").is_file()`, include matching domain sections for `allowed_modules` under `### Module Index (MODULE_INDEX.md)`.
          - If `memory_mode == "external"`:
            - State: `Memory Mode: external — Use Succinct Write-Back Mode (defer codebase memory to repo-memory-plugin; record only mechanical status, WO table, and cross-PR notes in PROJECT.md Part III).`
            - Do NOT include `MEMORY.md`, `MODULE_INDEX.md`, or `PROJECT_INDEX.md`!
      - **`role == "engineer"`:**
        - Locate bound `WORKORDER.md` (`wo_doc = pre_tool_gate._find_bound_workorder(ws_dir, session.get("pr_id"), session.get("wo_id"))`).
        - Format Worker contract block:
          - `WO_ID`, `PR_ID`, `title`, `complexity`, `execution_mode`
          - Retry budget: `attempt <attempt_num> of <max_attempts>` (`structural_failures: <structural_failures>/<max_structural_failures>`)
          - `allowed_files` and `forbidden_files`
          - `verification_command`
          - Explicit `SKILL.md` paths for `wo_doc.spec.required_skills` (via `_resolve_skill_paths(real_root, wo_doc.spec.required_skills)`).
          - Memory write-back instruction:
            - If `memory_mode == "external"`: `Write-Back Mode: Succinct Mode (memory_mode=external) — keep Completion Report strictly mechanical (status, attempt_num, receipt_id, commit_sha, files_modified, 1-line verification_summary <= 280 chars; omit narrative decisions_made/dead_ends unless escalating).`
            - If `memory_mode == "builtin"`: `Write-Back Mode: Full Distillation Mode (memory_mode=builtin) — populate decisions_made and dead_ends in Completion Report while prompt cache is warm.`
      - **`role in ("auditor", "debugger")`:**
        - Format concise role reminder (`role`, `pr_id`, `wo_id`, `execution_mode`, `memory_mode`).
      - Return `{"injectSteps": [{"userMessage": message_text}]}`.
  - **`main() -> int`:**
    - Reads hook payload via `escalation.read_hook_input()`, calls `evaluate_pre_invocation(payload)`, writes output via `escalation.write_hook_output(res)`, catches any unexpected exception to `sys.stderr` and outputs `{}` with exit `0`.
- [ ] **`tests/test_hooks_monitored_vs_autonomous.py`:**
  - Add unit and subprocess tests for `pre_invocation.py`:
    1. **Unenrolled fast-exit & import purity test for `pre_invocation.py` (Charter G2 & R1):**
       - Subprocess call on unenrolled directory outputs `{}` and exits `0`.
       - In-process timing `< 1.0 ms` and subprocess `sys.modules` check confirms `pydantic`, `yaml`, and `schemas` are NOT imported on the unenrolled path.
    2. **`parse_spawn_header` & Turn 1 subagent session binding test (Charter G6, SPEC §7.1.1):**
       - Unbound `conversationId` with `PA_ROLE: engineer`, `WO_ID: WO-01.1`, `PR_ID: PR-01`, `PROGRAMME_ID: prog-demo` in `transcript.jsonl` (or prompt) binds the session in `state.db` (`role == "engineer"`, `wo_id == "WO-01.1"`, `pr_id == "PR-01"`, `programme_id == "prog-demo"`) and returns `{"injectSteps": [{"userMessage": "..."}]}` containing `allowed_files`, `verification_command`, and explicit `SKILL.md` paths for `required_skills`.
       - Subsequent Turn 2 call on the same bound conversation (with more steps and no `CHECKPOINT` or rewind) returns `{}` (no duplicate injection).
    3. **`CHECKPOINT` compaction & step-rewind re-injection test (Charter G6, SPEC §7.1.2):**
       - Appending a `{"step_index": 10, "type": "CHECKPOINT"}` step to `transcript.jsonl` triggers re-injection (`"injectSteps"` returned) and updates `last_checkpoint_step` to `10`.
       - Rewinding `transcript.jsonl` to fewer steps than `last_checkpoint_step` (e.g., from 10 steps back to 3 steps) triggers re-injection and updates `last_checkpoint_step`.
    4. **Strict `memory_mode` (`builtin` vs. `external`) payload separation test (Charter G6, SPEC §7.1.3 & §9.1–9.2):**
       - When `memory_mode == "builtin"`, `pa` / `chief` injection includes `MEMORY.md` contents, matching `MODULE_INDEX.md` domain section, and `Full Distillation Mode`; `engineer` injection specifies `Full Distillation Mode`.
       - When `memory_mode == "external"`, `pa` / `chief` injection completely omits `MEMORY.md` and `MODULE_INDEX.md` contents and specifies `Succinct Write-Back Mode`; `engineer` injection specifies `Succinct Mode`.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 hash over `allowed_files` (or run `pa wo verify WO-02.5`), update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-02-agents-and-dual-mode-hooks/wo5-pre-invocation-role-binding-and-injection` with message:
   ```text
   WO-02.5: PreInvocation role binding, CHECKPOINT/rewind detection, and memory-mode injection

   PA-WorkOrder: WO-02.5
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

- **Status:** `COMPLETED` (`attempt_num: 1`)
- **Receipt ID:** `rcpt_72a39d4c72d7` (`tree_hash`: `72a39d4c72d7a1206279d6f0bd3d6842ed8df32c5533573d884acf2f79a49ae7`)
- **Files Modified:**
  - `daemon/workspace-plugin/principal-architect/scripts/pre_invocation.py`
  - `tests/test_hooks_monitored_vs_autonomous.py`
- **Verification Summary:** `81 passed in 13.95s` (`./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py && ./.venv/bin/ruff check daemon tests`)
- **Key Implementation Details:**
  - Implemented `pre_invocation.py` with `< 1 ms` unenrolled fast-exit (`common.is_repo_enrolled`) and zero top-level `pydantic`, `yaml`, or `schemas` imports.
  - Implemented `parse_spawn_header(text)` to extract `PA_ROLE:`, `PR_ID:`, `WO_ID:`, and `PROGRAMME_ID:` from spawn prompts and transcript steps, normalizing `PA_ROLE` via `pre_tool_gate._normalize_role` and automatically binding unbound subagent sessions on Turn 1 in `.state/state.db`.
  - Implemented `CHECKPOINT` compaction and step-count rewind detection against `sessions.last_checkpoint_step` so context injection re-arms automatically whenever a bound conversation compacts or rewinds, while avoiding duplicate injections on normal turns.
  - Implemented role-specific `{"injectSteps": [{"userMessage": "..."}]}` payload construction honoring the strict `memory_mode` boundary (`builtin` injects `memory/MEMORY.md` + matching `memory/MODULE_INDEX.md` sections and Full Distillation Mode; `external` completely omits `memory/` and instructs Succinct Write-Back Mode; `engineer` injects bound `WORKORDER.md` contract + resolved `SKILL.md` paths for `required_skills`).
  - Added 4 unit and subprocess tests in `tests/test_hooks_monitored_vs_autonomous.py` covering unenrolled fast-exit/import purity, Turn 1 spawn-header session binding, `CHECKPOINT`/rewind re-injection, and `builtin` vs. `external` memory payload separation.
- **Out-of-Scope Findings:** None.

