---
schema_version: 1
wo_id: WO-01.2
pr_id: PR-01
title: "Stdlib-only common.py foundations, fast enrollment check, and shared pytest fixtures"
complexity: standard
status: COMPLETED
allowed_files:
  - daemon/workspace-plugin/principal-architect/scripts/common.py
  - tests/conftest.py
  - tests/test_state_db_and_sync.py
forbidden_files:
  - SPEC.md
  - docs/positioning-paper.md
  - .agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/PROJECT.md
  - .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: "./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests"
max_attempts: 5
max_structural_failures: 2
spec_hash: "cbcf948d9e9e2aaead617ca05f9b6c867123b01bb537a1cc9cce8b61747b521f"
completion:
  status: COMPLETED
  attempt_num: 1
  receipt_id: "92b8d003bca042784cf561da79e51c8651a24d5e27863fa98e3b4a229a8f27aa"
  commit_sha: "HEAD"
  files_modified:
    - daemon/workspace-plugin/principal-architect/scripts/common.py
    - tests/conftest.py
    - tests/test_state_db_and_sync.py
  verification_summary: "15 passed in 1.43s (pytest); ruff check passed with 0 errors across daemon/ and tests/."
  tree_hash: "f850519dcf810840d2272fc843cee9330915ca1ce77c8b7226822f0f8db1f6e7"
  out_of_scope_findings: []
  escalation_request: null
  decisions_made:
    - "Strictly implemented all common.py primitives in Python stdlib with zero external imports (verified via clean subprocess sys.modules assertion)."
    - "Implemented sub-ms is_repo_enrolled by parsing daemon_home()/state/registry.json and walking directory hierarchy."
    - "Provided tmp_repo, daemon_home, and fake_runner fixtures in tests/conftest.py."
  dead_ends: []
---

# WO-01.2 — Stdlib-Only `common.py` Foundations & Pytest Fixtures

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-01` (`pr-01-core-schemas-and-enrollment`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T18:50:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement the stdlib-only `daemon/workspace-plugin/principal-architect/scripts/common.py` module providing sub-millisecond repository/workspace resolution, `<1ms` enrollment check (`is_repo_enrolled`) without importing `pydantic` or `yaml`, JSONL transcript parsing (`read_transcript`, `latest_checkpoint_step`), an injectable subprocess runner (`run`), and template rendering helpers, alongside the shared pytest fixtures in `tests/conftest.py` (`tmp_repo`, `daemon_home`, `fake_runner`) and comprehensive unit tests in `tests/test_state_db_and_sync.py`.

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/common.py`
  - `tests/conftest.py`
  - `tests/test_state_db_and_sync.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/wo2-common-stdlib-foundations/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Import Purity (Invariant I4 / Charter G6 & R1):** `common.py` MUST use only the Python standard library (`json`, `os`, `pathlib`, `re`, `subprocess`, `typing`, `urllib.parse`, etc.). Importing `common` MUST NEVER import `pydantic` or `yaml`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh`. Commit only on the currently checked-out branch `pr-01-core-schemas-and-enrollment/wo2-common-stdlib-foundations` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/common.py` (stdlib-only):**
  - Define constants:
    - `NEW_WORKSPACE_REL = Path(".agents/plugins/principal-architect-workspace")`
    - `LEGACY_WORKSPACE_REL = Path(".agents/skills/principal-architect-workspace")`
  - `run(cmd: Sequence[str], *, cwd: str | Path | None = None, env: Mapping[str, str] | None = None, timeout: float = 10.0, input_text: str | None = None) -> subprocess.CompletedProcess[str]`:
    - Default subprocess runner calling `subprocess.run(list(cmd), cwd=str(cwd) if cwd is not None else None, env=dict(env) if env is not None else None, input=input_text, text=True, capture_output=True, timeout=timeout, check=False)`.
    - Export `Runner = Callable[..., subprocess.CompletedProcess[str]]`.
  - `find_repo_root(path: str | Path = ".", *, runner: Runner = run) -> Path | None`:
    - Normalize `path` (strip `file://` scheme if passed as a URI via `urllib.parse.unquote(urllib.parse.urlparse(str(path)).path)`), resolve with `Path(os.path.realpath(p))`, if it is a file start from `.parent`.
    - Walk `[cur, *cur.parents]`: if `(d / ".git").exists()` (either a directory or a worktree `.git` file), return `d`.
    - Fallback to `runner(["git", "rev-parse", "--show-toplevel"], cwd=cur)` if needed; if `returncode == 0` and stdout is non-empty, return `Path(os.path.realpath(res.stdout.strip()))`, else `None`.
  - `workspace_dir(repo_root: str | Path) -> Path`:
    - Resolve `root = Path(os.path.realpath(repo_root))`.
    - If `(root / NEW_WORKSPACE_REL).exists()`, return `root / NEW_WORKSPACE_REL`.
    - Else if `(root / LEGACY_WORKSPACE_REL).exists()`, return `root / LEGACY_WORKSPACE_REL`.
    - Else return `root / NEW_WORKSPACE_REL`.
  - `daemon_home() -> Path`:
    - Check `os.environ.get("PA_DAEMON_HOME")`: if set and non-empty, return `Path(os.path.realpath(os.path.expanduser(env_val)))`.
    - Otherwise return `Path(os.path.realpath(Path.home())) / ".gemini" / "config" / "plugins" / "pa-daemon"`.
  - `is_repo_enrolled(workspace_paths: Sequence[str | Path]) -> bool`:
    - Fast-exit enrollment check (`< 1 ms`, stdlib `json` and `os.path` only).
    - If `not workspace_paths`, return `False`.
    - Read `registry_path = daemon_home() / "state" / "registry.json"`. If not a file or unreadable or invalid JSON, return `False`.
    - Extract `repos = data.get("repos")` (must be a `dict`). Normalize enrolled keys via `os.path.realpath` into a `set[str]`.
    - For each item in `workspace_paths`: strip `file://` prefix if present (using `urllib.parse.unquote(urllib.parse.urlparse(s).path)`), resolve via `os.path.realpath`, and check whether that path or any of its parent directories is in the enrolled repo set. Return `True` on first match, else `False`.
  - `read_transcript(path: str | Path) -> list[dict[str, Any]]`:
    - Read a JSONL transcript file (`transcript.jsonl`). If the file does not exist, return `[]`.
    - Parse each non-empty line with `json.loads`; ignore malformed lines without raising; keep only `dict` objects.
  - `latest_checkpoint_step(steps: Sequence[Mapping[str, Any]]) -> int | None`:
    - Inspect `steps` for entries where `step.get("type") in ("CHECKPOINT", "CORTEX_STEP_TYPE_CHECKPOINT")`.
    - For each matching step, use `int(step["step_index"])` if `"step_index"` is present and an int/numeric, else its 0-based index in `steps`. Return the maximum checkpoint step index, or `None` if no checkpoint step is present.
  - `templates_dir() -> Path` and `render_template(template_text: str, values: Mapping[str, Any]) -> str`:
    - `templates_dir()` returns `Path(__file__).resolve().parent.parent / "skills" / "principal-architect" / "templates"`.
    - `render_template(template_text, values)` replaces `{{name}}` placeholders using `re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", ...)` (raising `KeyError` if a placeholder in the template is missing from `values`).
- [ ] **`tests/conftest.py`:**
  - Implement and export the three required fixtures (Charter R12, §2.2):
    - `tmp_repo(tmp_path: Path) -> Path`: creates `repo = tmp_path / "repo"`, runs `git init -b main` (or `git init` + `git symbolic-ref HEAD refs/heads/main`), sets local `user.name = "Test User"` and `user.email = "test@example.com"`, writes a README and creates an initial commit on `main`, and returns `repo.resolve()`.
    - `daemon_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path`: creates `fake_home = tmp_path / "home"` and `d_home = tmp_path / "pa-daemon"`, sets `HOME` and `PA_DAEMON_HOME` via `monkeypatch.setenv`, and returns `d_home.resolve()`.
    - `fake_runner`: returns a callable `FakeRunner` object (with `.calls: list[list[str]]` and `.set_response(prefix_tuple, returncode=0, stdout="", stderr="")` or similar helper) that matches scripted commands (such as `("git", "remote", "get-url", "origin")` and `("gh", "auth", "status")` or `$PA_GH_BIN auth status`) and falls back to `common.run` for unscripted local `git` commands.
- [ ] **`tests/test_state_db_and_sync.py`:**
  - Keep existing smoke test and add comprehensive unit tests for `common.py` and the `conftest.py` fixtures:
    - Import purity test running `sys.executable -c "import sys, common; assert 'pydantic' not in sys.modules and 'yaml' not in sys.modules"`.
    - `find_repo_root` on repo root, nested subdirectory, `file://` URI, and non-repo directory (`None`).
    - `workspace_dir` preference order: `.agents/plugins/principal-architect-workspace` over legacy `.agents/skills/principal-architect-workspace`, legacy fallback when only `.agents/skills/principal-architect-workspace` exists (plus dogfood check on this repo root!), and default to `.agents/plugins/principal-architect-workspace` when neither exists.
    - `daemon_home` honouring `PA_DAEMON_HOME` and fallback to `$HOME/.gemini/config/plugins/pa-daemon`.
    - `is_repo_enrolled`: missing registry (`False`), malformed JSON (`False`), unenrolled repo (`False`), enrolled repo (`True`), nested subdirectory inside enrolled repo (`True`), `file://` URI (`True`), and sub-millisecond timing check.
    - `read_transcript` and `latest_checkpoint_step` (empty, no checkpoints -> `None`, multiple checkpoints -> highest `step_index`, malformed trailing line ignored).
    - `render_template` placeholder substitution and missing-key `KeyError`.

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute `tree_hash`, update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-01-core-schemas-and-enrollment/wo2-common-stdlib-foundations` with message:
   ```text
   WO-01.2: Stdlib-only common.py foundations and shared pytest fixtures

   PA-WorkOrder: WO-01.2
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report

### 1. Summary of Changes
- Implemented `daemon/workspace-plugin/principal-architect/scripts/common.py` using strictly Python standard library modules (`collections.abc`, `json`, `os`, `pathlib`, `re`, `subprocess`, `typing`, `urllib.parse`), ensuring zero third-party dependencies (`pydantic` and `yaml` are completely absent from imports).
- Implemented `run` subprocess execution wrapper with injectable runner typing (`Runner`).
- Implemented `find_repo_root` supporting direct paths, parent hierarchy searching for `.git` (directory or worktree file), `file://` URIs, and fallback to `git rev-parse --show-toplevel`.
- Implemented `workspace_dir` resolving the active repository workspace with precedence for `.agents/plugins/principal-architect-workspace` over legacy `.agents/skills/principal-architect-workspace`.
- Implemented `daemon_home` resolving `PA_DAEMON_HOME` or falling back to `~/.gemini/config/plugins/pa-daemon`.
- Implemented `is_repo_enrolled` with sub-millisecond execution (< 0.1 ms average), inspecting `daemon_home() / "state" / "registry.json"` for enrolled roots and parent paths with `file://` URI support.
- Implemented `read_transcript` parsing JSONL transcripts into dictionary steps while tolerating malformed lines.
- Implemented `latest_checkpoint_step` resolving checkpoint indices across `CHECKPOINT` and `CORTEX_STEP_TYPE_CHECKPOINT` step types.
- Implemented `templates_dir` and `render_template` supporting `{{name}}` placeholder substitution with `KeyError` verification on missing keys.
- Implemented `tests/conftest.py` exporting `tmp_repo`, `daemon_home`, and `fake_runner` fixtures.
- Implemented comprehensive unit tests in `tests/test_state_db_and_sync.py` covering import purity, repo/workspace resolution, dogfood resolution against the repository root, daemon home resolution, registry enrollment edge cases & sub-ms timing, transcript reading and checkpoint indexing, template rendering, and fake runner scripting.

### 2. Verification Floor Results
- Ran verification command:
  ```bash
  ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests
  ```
- Output: 15 passed in 2.10s, `ruff check` passed with zero errors.

### 3. Tree Hash & Artifacts
- **Verified Tree Hash:** `f850519dcf810840d2272fc843cee9330915ca1ce77c8b7226822f0f8db1f6e7`
- **Allowed Files Modified:**
  - `daemon/workspace-plugin/principal-architect/scripts/common.py`
  - `tests/conftest.py`
  - `tests/test_state_db_and_sync.py`
  - `.agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/wo2-common-stdlib-foundations/WORKORDER.md`
