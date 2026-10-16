---
schema_version: 1
wo_id: WO-03.4
pr_id: PR-03
title: Dynamic complexity model routing, retry step-up, LanguageServerClient with
  headless fallback (models.py), and pa wo debug/resolve
complexity: standard
status: COMPLETED
allowed_files:
- daemon/workspace-plugin/principal-architect/scripts/models.py
- daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
- tests/test_github_and_local_git_bus.py
forbidden_files:
- SPEC.md
- docs/positioning-paper.md
- .agents/skills/principal-architect-workspace/pr-03-vcs-bus-models-and-memory-modes/PROJECT.md
- .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py
  tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py
  tests/test_memory_modes.py && ./.venv/bin/ruff check daemon tests
max_attempts: 5
max_structural_failures: 2
spec_hash: b1032705889a3fd4442f6a2dfdadaa0ae32c8be88028d9ee4b2bac9d7f2ad942
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: rcpt_d5e922b5681b
  commit_sha: f56e9cbd00d8c8420332068a4a6cc5c86308ad92
  files_modified:
  - daemon/workspace-plugin/principal-architect/scripts/models.py
  - daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
  - tests/test_github_and_local_git_bus.py
  verification_summary: "pytest (112 passed) and ruff check (All checks passed)"
  out_of_scope_findings: []
  escalation_request: null
  decisions_made:
  - "Enforced top-tier ceiling in step_up and route so 'flash' and 'inherit' never step to 'pro'."
  - "Implemented graceful headless bridge-prompt fallback in LanguageServerClient when ANTIGRAVITY_LS_ADDRESS/ANTIGRAVITY_CSRF_TOKEN is unset or RPC fails."
  - "Preserved stdlib-only top-level imports in pa_cli.py by importing models, schemas, pre_tool_gate, post_tool_receipt, and escalation lazily inside _cmd_wo_debug and _cmd_wo_resolve."
  dead_ends: []
---

# WO-03.4 — Model Routing, Retry Step-Up, `LanguageServerClient` (`models.py`), & `pa wo debug`/`resolve`

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-03` (`pr-03-vcs-bus-models-and-memory-modes`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T21:37:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/workspace-plugin/principal-architect/scripts/models.py` (`ARCHITECT_MODEL_PREFERENCE`, `route`, `step_up`, `select_architect_model`, and `LanguageServerClient` with graceful headless bridge-prompt fallback), add `pa wo debug <WO-ID>` and `pa wo resolve <WO-ID> --summary "..."` to `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py` (preserving top-level stdlib-only lazy imports), and add unit and CLI tests in `tests/test_github_and_local_git_bus.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/models.py`
  - `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`
  - `tests/test_github_and_local_git_bus.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-03-vcs-bus-models-and-memory-modes/wo4-models-routing-and-ide-client/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh` on the workspace repository. Commit only on the currently checked-out branch `pr-03-vcs-bus-models-and-memory-modes/wo4-models-routing-and-ide-client` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R7):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/models.py`:**
  1. **Constants & Tier Step-Up (`ARCHITECT_MODEL_PREFERENCE`, `step_up`):**
     - `ARCHITECT_MODEL_PREFERENCE: tuple[str, ...] = ("gemini-4-argon-high", "gemini-3.1-pro-high", "claude-opus-5-5-high")`
     - `step_up(tier: str) -> str`:
       - Steps up one model tier: `"flash_lite" -> "flash"`, `"flash" -> "inherit"`, `"inherit" -> "inherit"`.
       - **CRITICAL (Charter R4 & SPEC §5.3):** Never return `"pro"` when stepping up from `"flash"` or `"inherit"` — top tier is strictly `"inherit"` so a parent running on Argon or Opus is never downgraded to `"pro"`.
       - Raise `ValueError` for unrecognized tier names.
  2. **Complexity Router (`route`, Charter G2 & R4, SPEC §5.3):**
     - `route(complexity: str | Any, attempt: int = 1, parent_model: str = "inherit") -> str`:
       - Normalize `complexity` (`complexity.value` if enum, or lowercase string):
         - `"mechanical" -> "flash_lite"`
         - `"standard" -> "flash"`
         - `"architect" -> "inherit"`
         - `"interactive" -> "inherit"`
         - Raise `ValueError` for unknown complexity values or `attempt < 1`.
       - **Retry Step-Up Rule:** On `attempt <= 2` (attempts 1 and 2), return the base tier for `complexity`. On `attempt >= 3` (attempts 3, 4, 5+, after 2 failed attempts), step up one tier via `step_up(base_tier)` (`"flash_lite" -> "flash"`, `"flash" -> "inherit"`, `"inherit" -> "inherit"`).
       - Never return `"pro"` when the architect/top tier is `"inherit"` (regardless of `parent_model`).
  3. **Architect Model Selection (`select_architect_model`):**
     - `select_architect_model(catalog: Sequence[str] | None = None, *, preferred: str | None = None, repo_root: str | Path | None = None, runner: common.Runner = common.run) -> str`:
       - If `preferred` is not passed and `repo_root` is provided, check `<ws_dir>/.state/state.db` (`db.get_config("architect_model")`).
       - If `preferred` is set and either `catalog` is empty/None or `preferred` matches an entry in `catalog`, return `preferred`.
       - If `catalog` is provided and non-empty, iterate through `ARCHITECT_MODEL_PREFERENCE` and return the first candidate present in `catalog` (supporting exact match or case-insensitive substring match); if none of the 3 preferred models are in `catalog`, return `catalog[0]`.
       - If `catalog` is None or empty, default to `ARCHITECT_MODEL_PREFERENCE[0]` (`"gemini-4-argon-high"`).
  4. **Antigravity IDE Language Server Client (`LanguageServerClient`, Charter G2 & SPEC §5.3):**
     - `__init__(self, *, address: str | None = None, csrf_token: str | None = None, transport: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]] | None = None, timeout: float = 3.0) -> None`:
       - Read `self.address = (address if address is not None else os.environ.get("ANTIGRAVITY_LS_ADDRESS", "")).strip()` and `self.csrf_token = (csrf_token if csrf_token is not None else os.environ.get("ANTIGRAVITY_CSRF_TOKEN", "")).strip()`.
       - `self.transport = transport` (optional callable `(endpoint, payload, headers) -> response_dict` for testing; when `None`, uses `urllib.request.Request` / `urlopen` against `http://{self.address}/{endpoint.lstrip('/')}` with JSON body and header `{"Content-Type": "application/json", "x-codeium-csrf-token": self.csrf_token}`).
     - `is_connected(self) -> bool`:
       - Return `True` if `self.transport is not None` or (`bool(self.address)` and `bool(self.csrf_token)`), else `False`.
     - `start_conversation(self, *, title: str, prompt: str, role: str = "pa", model: str | None = None, workspace_root: str | Path | None = None, pin: bool = True) -> dict[str, Any]`:
       - Resolve `resolved_model = model or select_architect_model(repo_root=workspace_root)`.
       - If `is_connected()`, attempt RPC call to start conversation (e.g. endpoint `"exa.language_server_pb.LanguageServerService/StartConversation"` with payload `{"title": title, "prompt": prompt, "role": role, "model": resolved_model, "workspaceRoot": str(workspace_root) if workspace_root else ""}`) and if `pin=True`, call `self.set_pinned(conv_id, True)`.
       - **Graceful Headless Fallback:** If not connected or if the RPC raises any exception (`OSError`, `URLError`, `ValueError`, `RuntimeError`), do NOT raise — return:
         ```python
         {
             "connected": False,
             "conversation_id": f"headless-{role}-{uuid.uuid4().hex[:8]}",
             "pinned": False,
             "title": title,
             "role": role,
             "model": resolved_model,
             "bridge_prompt": prompt,
             "fallback": "bridge_prompt",
         }
         ```
     - `set_pinned(self, conversation_id: str, pinned: bool = True) -> dict[str, Any]`:
       - If connected and not a `"headless-*"` ID, invoke endpoint `"exa.language_server_pb.LanguageServerService/SetPinned"` with `{"conversationId": conversation_id, "pinned": bool(pinned)}` and return `{"connected": True, "conversation_id": conversation_id, "pinned": bool(pinned)}`.
       - On headless or RPC error, return `{"connected": False, "conversation_id": conversation_id, "pinned": False, "fallback": "headless"}`.
     - `send_message(self, conversation_id: str, message: str) -> dict[str, Any]`:
       - If connected and not `"headless-*"`, invoke endpoint `"exa.language_server_pb.LanguageServerService/SendMessage"` with `{"conversationId": conversation_id, "message": message}` and return `{"connected": True, "conversation_id": conversation_id, "delivered": True}`.
       - On headless or RPC error, return `{"connected": False, "conversation_id": conversation_id, "delivered": False, "bridge_prompt": message, "fallback": "bridge_prompt"}`.
- [ ] **`daemon/workspace-plugin/principal-architect/scripts/pa_cli.py` (`pa wo debug` & `pa wo resolve`):**
  - **Preserve top-level stdlib-only lazy imports (Charter R6 & Invariant I4)!** Import `models`, `schemas`, `pre_tool_gate`, `post_tool_receipt`, `escalation` inside `_cmd_wo_debug` and `_cmd_wo_resolve`.
  - **`pa wo debug <wo_id> [--path .] [--reason "..."]` (`_cmd_wo_debug`):**
    1. Locate `<wo_id>` via `pre_tool_gate._find_bound_workorder(ws_dir, None, wo_id_arg)`. Return `1` if not found.
    2. Transition `wo_doc.spec.status = schemas.WorkOrderStatus.BLOCKED` and write `wo_doc.path` (verifying `schemas.verify_spec_hash(wo_doc.path)` remains `True`!).
    3. Gather failure context (any open escalations for `wo_id` in `state.db`, `wo_doc.spec.completion.verification_summary` if present, and `git status --short`) and build the `PA_ROLE: debugger\nPR_ID: <pr_id>\nWO_ID: <wo_id>\n\n...` bridge prompt.
    4. Call `models.LanguageServerClient().start_conversation(title=f"🔬 [Debug {wo_doc.spec.wo_id}] {wo_doc.spec.title}", prompt=bridge_prompt, role="debugger", workspace_root=real_root, pin=True)`.
    5. Record the `debugger` session in `state.db` (`db.upsert_session(conv_id, role="debugger", pr_id=wo_doc.spec.pr_id, wo_id=wo_doc.spec.wo_id, model_tier="inherit", status="ACTIVE", pinned=1 if ls_res["pinned"] else 0)`), and record/update an escalation (`reason_code="DEBUG_ESCALATION"`, `target_role="debugger"`) in `state.db`.
    6. Print JSON or structured output containing `conversation_id` and `bridge_prompt` to stdout and return `0`.
  - **`pa wo resolve <wo_id> --summary "..." [--path .]` (`_cmd_wo_resolve`):**
    1. Locate `<wo_id>` via `pre_tool_gate._find_bound_workorder(ws_dir, None, wo_id_arg)`. Return `1` if not found or if `--summary` is empty.
    2. Run `wo_doc.spec.verification_command` via `runner(["/bin/sh", "-c", wo_doc.spec.verification_command], cwd=real_root, timeout=300.0)`. If it fails (`returncode != 0`), print error to stderr and return `1`.
    3. Compute `t_hash = post_tool_receipt.compute_tree_hash(real_root, wo_doc.spec.allowed_files)` and `receipt_id = f"rcpt_{t_hash[:12]}"`.
    4. Update `wo_doc.spec.status = schemas.WorkOrderStatus.COMPLETED` and `wo_doc.spec.completion` (recording `summary` in `verification_summary` and `decisions_made`), write `wo_doc.path`, and verify `schemas.verify_spec_hash(wo_doc.path)`.
    5. Upsert the valid receipt in `state.db`, resolve open escalations and `attention_queue` items for `wo_doc.spec.wo_id`, find any active `debugger` session for `wo_id` in `sessions`, unpin it via `models.LanguageServerClient().set_pinned(debug_conv_id, False)`, mark the `debugger` session `COMPLETED` (`pinned=0`), and if an owning `pa` session exists for `wo_doc.spec.pr_id`, send a wakeup message via `LanguageServerClient().send_message(...)`.
    6. Print confirmation to stdout/stderr and return `0`.
- [ ] **`tests/test_github_and_local_git_bus.py`:**
  - Add unit and CLI tests covering:
    1. `models.route` for `"mechanical"`, `"standard"`, `"architect"`, and `"interactive"` across attempts `1..5` (verifying `flash_lite -> flash` and `flash -> inherit` step-up on `attempt >= 3`, and verifying `"inherit"` never downgrades to `"pro"`).
    2. `models.step_up` and `models.select_architect_model` (`ARCHITECT_MODEL_PREFERENCE` order matching, custom catalog, `state.db` config lookup, fallback).
    3. `models.LanguageServerClient`: connected mode with a mock `transport` (`start_conversation`, `set_pinned`, `send_message`) and headless fallback mode when `ANTIGRAVITY_LS_ADDRESS` is unset or transport raises `OSError`.
    4. `pa wo debug <WO-ID>` and `pa wo resolve <WO-ID> --summary "..."` CLI workflow end-to-end against `tmp_repo`.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py tests/test_hooks_monitored_vs_autonomous.py tests/test_github_and_local_git_bus.py tests/test_memory_modes.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute the SHA-256 `tree_hash` over `allowed_files` (`post_tool_receipt.compute_tree_hash`), update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (leaving Part I untouched so `spec_hash` remains valid), and commit on `pr-03-vcs-bus-models-and-memory-modes/wo4-models-routing-and-ide-client` with message:
   ```text
   WO-03.4: model routing, retry step-up, LanguageServerClient (models.py), and pa wo debug/resolve

   PA-WorkOrder: WO-03.4
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report rather than filing issues directly.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

- **Status:** `COMPLETED` (attempt 1)
- **Receipt ID:** `rcpt_d5e922b5681b` (`tree_hash: d5e922b5681bee1fb12243a4b5581a6e4b42b26c9a523b4a957712a273604e93`)
- **Files Modified:**
  - `daemon/workspace-plugin/principal-architect/scripts/models.py`
  - `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`
  - `tests/test_github_and_local_git_bus.py`
- **Verification Summary:** `pytest` (`112 passed`) and `ruff check daemon tests` (`All checks passed!`).
- **Key Decisions:**
  - Enforced the `step_up` and `route` top-tier ceiling (`"flash_lite" -> "flash" -> "inherit" -> "inherit"`) so `"inherit"` never downgrades a parent running on Argon or Opus to `"pro"`.
  - Built `LanguageServerClient` (`start_conversation`, `set_pinned`, `send_message`) with injectable `transport` for unit testing and graceful headless fallback (`"connected": False`, `"fallback": "bridge_prompt"` / `"headless"`).
  - Added `pa wo debug` and `pa wo resolve` to `pa_cli.py` while preserving top-level stdlib-only lazy imports (`test_pa_cli_lazy_import_purity` passes).

