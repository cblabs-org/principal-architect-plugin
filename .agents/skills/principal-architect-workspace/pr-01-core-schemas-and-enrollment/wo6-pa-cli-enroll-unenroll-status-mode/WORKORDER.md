---
schema_version: 1
wo_id: WO-01.6
pr_id: PR-01
title: "pa CLI entrypoint (enroll, unenroll, status --json, mode), wrapper scripts, and README"
complexity: architect
status: IN_PROGRESS
allowed_files:
  - daemon/workspace-plugin/principal-architect/scripts/pa_cli.py
  - scripts/enroll.sh
  - scripts/unenroll.sh
  - README.md
  - tests/test_state_db_and_sync.py
  - tests/test_schemas.py
forbidden_files:
  - SPEC.md
  - docs/positioning-paper.md
  - .agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/PROJECT.md
  - .agents/skills/principal-architect-workspace/programme-principal-architect-plugin/PROGRAM.md
required_skills: []
verification_command: "./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests"
max_attempts: 5
max_structural_failures: 2
spec_hash: "d17839779a7329303dec333d4cb2f19de03d03be284ca01b718626793448e196"
completion: null
---

# WO-01.6 — `pa` CLI (`enroll`, `unenroll`, `status`, `mode`), Wrapper Scripts & `README.md`

## 1. Role & Objective

> You are an expert senior software engineer and execution-focused Tier 3 Worker (`pa-engineer`). You are NOT the Principal Architect. Do not make high-level architectural decisions, do not create or switch branches, and do not modify Part I of this `WORKORDER.md` or `PROJECT.md`.

**Parent PR:** `PR-01` (`pr-01-core-schemas-and-enrollment`) — decomposition approved (`PROJECT.md` `status: APPROVED`, `approved_at: 2026-10-16T18:50:00Z`; see `.agents/rules/00-operating-model.md`).

**Objective:** Implement `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py` (with `build_parser()`, `main(argv)`, `COMMAND_MODULES`, lazy heavy imports, and the `enroll`, `unenroll`, `status [--json]`, and `mode` commands), convenience wrapper scripts `scripts/enroll.sh` and `scripts/unenroll.sh`, `README.md`, and comprehensive offline integration tests in `tests/test_state_db_and_sync.py` (plus adding `WO-01.6` to the dogfood test in `tests/test_schemas.py`).

## 2. Strict Boundary Box & Constraints

- **Allowed files (`allowed_files`):**
  - `daemon/workspace-plugin/principal-architect/scripts/pa_cli.py`
  - `scripts/enroll.sh`
  - `scripts/unenroll.sh`
  - `README.md`
  - `tests/test_state_db_and_sync.py`
  - `tests/test_schemas.py`
  - Plus Part II (`## Completion Report` and frontmatter `status` / `completion`) of this file (`.agents/skills/principal-architect-workspace/pr-01-core-schemas-and-enrollment/wo6-pa-cli-enroll-unenroll-status-mode/WORKORDER.md`).
- **Forbidden:** Do NOT edit any file outside `allowed_files` and this `WORKORDER.md`. Do NOT edit Part I (`## 1.`–`## 4.` or any YAML frontmatter field other than `status` and `completion`) of this `WORKORDER.md` — doing so will invalidate `spec_hash`.
- **Lazy Import Rule (Charter R1):** `pa_cli.py` MUST NOT import `pydantic`, `yaml`, or `schemas` at module top-level. Import `schemas` lazily inside the command handlers that require it (such as `status`) so `pa --help`, `pa mode`, and fast paths stay sub-millisecond without importing `pydantic` or `yaml`.
- **Git & Shell constraints:** Do NOT run `git checkout`, `git switch`, `git branch`, `git push`, `git rebase`, or `gh`. Commit only on the currently checked-out branch `pr-01-core-schemas-and-enrollment/wo6-pa-cli-enroll-unenroll-status-mode` using `-c user.name="Matt McNeill" -c user.email="matthewmcneill@users.noreply.github.com"`.
- **Hygiene (Invariant I10 & Charter R13):** Never include absolute machine paths or employer-internal identifiers/emails/shortlinks in any file or commit message.

## 3. Line-Item Instructions

- [ ] **`daemon/workspace-plugin/principal-architect/scripts/pa_cli.py` (mark executable `chmod +x`):**
  1. **Entrypoint & Extension Contract (Charter G7, R1, R11, §2.2):**
     - Start with `#!/usr/bin/env python3` and insert `str(Path(__file__).resolve().parent)` at `sys.path[0]` if not already present so `pa_cli.py` runs both via `python3 -m pa_cli` and directly as a script/symlink.
     - Export `COMMAND_MODULES: list[str] = []`.
     - Export `build_parser() -> argparse.ArgumentParser`: builds the `pa` parser with subcommands `enroll`, `unenroll`, `status`, `mode`, then iterates over `COMMAND_MODULES`, dynamically importing each module (`importlib.import_module(mod_name)`) and calling `mod.register(subparsers)`.
     - Export `main(argv: Sequence[str] | None = None, *, runner: common.Runner = common.run) -> int`: parses `argv` (converting `SystemExit` from argparse error code `2` into exit code `1` for usage/validation errors per Charter R11: exit `0` success, `1` validation/usage error, `2` environment/precondition error; `--help` exits `0`), dispatches to the command handler passing `runner`, and returns the integer exit code.
  2. **Injectable Detectors (Charter R6):**
     - `detect_vcs_mode(repo_root: Path, *, runner: common.Runner = common.run) -> Literal["github", "local_git"]`:
       - Run `runner(["git", "remote", "get-url", "origin"], cwd=repo_root)`. If `returncode != 0` or `"github.com"` not in `stdout.lower()`, return `"local_git"`.
       - Resolve `gh_bin = os.environ.get("PA_GH_BIN", "gh")`. Run `runner([gh_bin, "auth", "status"], cwd=repo_root)`. If `returncode == 0`, return `"github"`, else `"local_git"`.
     - `detect_memory_mode(repo_root: Path) -> Literal["external", "builtin"]`:
       - Return `"external"` if any of the following holds:
         1. `(repo_root / ".memory").exists()`
         2. `(repo_root / ".agents" / "plugins.json").is_file()` and any entry in its `"entries"` list has a `"path"` string containing `"repo-memory"`.
         3. `(Path(os.path.realpath(Path.home())) / ".gemini" / "config" / "plugins" / "repo-memory-daemon" / "state" / "registry.json").is_file()` and lists `os.path.realpath(repo_root)` (either as a top-level key or under `"repos"`, or in a list/dict of registered paths).
       - Otherwise return `"builtin"`.
  3. **`pa enroll [path] [--memory-mode auto|external|builtin] [--vcs-mode auto|github|local_git] [--extra-skill NAME]... [--exclude-rule PATTERN]...` (Charter §2.3, R6, R7, R8, R9):**
     - Follow the exact 9-step normative sequence of Charter §2.3:
       1. Resolve `target = Path(os.path.realpath(args.path))`. If `not target.exists()`, print error to `sys.stderr` and return `2`. Check `common.find_repo_root(target, runner=runner)`. If `None` (not inside a git repo), run `runner(["git", "init"], cwd=target)` (if `returncode != 0`, print error to `sys.stderr` and return `2`) and set `repo_root = target`.
       2. **Legacy migration check (R8):** Let `legacy_ws = repo_root / common.LEGACY_WORKSPACE_REL` and `new_ws = repo_root / common.NEW_WORKSPACE_REL`.
          - If `legacy_ws.exists()` and `new_ws.exists()`: print explanatory error to `sys.stderr` (`"Cannot migrate workspace: both .agents/skills/principal-architect-workspace and .agents/plugins/principal-architect-workspace exist"`) and return `2` (never merge silently).
          - If `legacy_ws.exists()` and not `new_ws.exists()`: create `new_ws.parent.mkdir(parents=True, exist_ok=True)`. Check whether `legacy_ws` has tracked files via `runner(["git", "ls-files", "--error-unmatch", str(common.LEGACY_WORKSPACE_REL)], cwd=repo_root)`. If `returncode == 0`, run `runner(["git", "mv", str(common.LEGACY_WORKSPACE_REL), str(common.NEW_WORKSPACE_REL)], cwd=repo_root)` (falling back to `shutil.move` if `git mv` fails); otherwise move with `shutil.move(str(legacy_ws), str(new_ws))`.
       3. Ensure `new_ws.mkdir(parents=True, exist_ok=True)` and `(new_ws / ".state").mkdir(parents=True, exist_ok=True)`. Open `StateDB(new_ws / ".state" / "state.db")`.
       4. Resolve `memory_mode`: if `args.memory_mode in ("external", "builtin")` use it, else `detect_memory_mode(repo_root)`. If `memory_mode == "builtin"`, scaffold `new_ws / "memory" / "MEMORY.md"`, `"MODULE_INDEX.md"`, and `"PROJECT_INDEX.md"` using `common.render_template_file(..., {"updated_at": state_db.utc_now_iso()})` **only for files that do not already exist** (never overwrite existing memory files!).
       5. Resolve `vcs_mode`: if `args.vcs_mode in ("github", "local_git")` use it, else `detect_vcs_mode(repo_root, runner=runner)`.
       6. **Generated manifests (R7):**
          - If `--extra-skill` was explicitly passed on CLI, use deduplicated list of `args.extra_skill`; else if `db.get_config("extra_skills_json")` exists in `state.db`, reuse that stored JSON list (so idempotent re-run of `pa enroll` reproduces identical manifests!).
          - Similarly, if `--exclude-rule` was explicitly passed on CLI, use deduplicated list of `args.exclude_rule`; else if `db.get_config("exclude_rules_json")` exists, reuse that stored JSON list.
          - Compute `user_config_dir = Path(os.path.realpath(Path.home())) / ".gemini" / "config"`.
          - Write `new_ws / ".state" / "pa-skills.json"`:
            ```json
            {
              "entries": [
                {"path": "<abs-repo-root>/.agents/skills"},
                {"path": "<abs-user-config>/skills", "include_only": ["..."]}
              ]
            }
            ```
            (Include the second entry **only** when `extra_skills` is non-empty, per Charter R7!)
          - Write `new_ws / ".state" / "pa-worker-rules.json"`:
            ```json
            {
              "entries": [
                {
                  "path": "<abs-repo-root>/.agents/rules",
                  "exclude": ["01-plan-before-execute.md", "bug-fixer-*", ...]
                }
              ]
            }
            ```
            (where `exclude` starts with `["01-plan-before-execute.md", "bug-fixer-*"]` plus any `exclude_rules` not already in the list).
          - Ensure `new_ws / ".gitignore"` exists and contains `.state/` (without duplicating lines on re-run).
       7. Persist config in `StateDB`:
          - Preserve existing `execution_mode` if already set in `repo_config`, else set `"monitored"`.
          - Set `memory_mode`, `vcs_mode`, `extra_skills_json = json.dumps(extra_skills)`, `exclude_rules_json = json.dumps(exclude_rules)`.
       8. Write/merge `<repo_root>/.agents/plugins.json`:
          - Resolve `wp_path = str(common.daemon_home() / "workspace-plugin")` ( note: SPEC §4.2 shows `/abs/path/to/pa-daemon/workspace-plugin`, and Charter §2.3 step 7 states: `Write/merge <repo>/.agents/plugins.json with the absolute path of <daemon_home>/workspace-plugin (deduplicated)`).
          - Preserve any other existing entries in `<repo_root>/.agents/plugins.json` `"entries"`, deduplicating by `"path"`.
          - Ensure `.agents/plugins.json` is listed in `<repo_root>/.git/info/exclude` (creating parent dir if needed, without duplicating the line on re-run).
       9. Register `repo_root` in `Registry()` (`<daemon_home>/state/registry.json`), print a concise summary to `sys.stderr`, and return `0`.
  4. **`pa unenroll [path]` (Charter R9):**
     - Resolve `repo_root = common.find_repo_root(args.path, runner=runner) or Path(os.path.realpath(args.path))`.
     - Remove the entry matching `str(common.daemon_home() / "workspace-plugin")` (or ending with `/workspace-plugin` / `/workspace-plugin/principal-architect`) from `<repo_root>/.agents/plugins.json` if that file exists (preserving any other plugin entries).
     - Call `Registry().unregister(repo_root)`.
     - Never delete committed files in `.agents/plugins/principal-architect-workspace/`.
     - Print confirmation to `sys.stderr` and return `0`.
  5. **`pa status [path] [--json]` (Charter R10):**
     - Lazy-import `schemas`.
     - Resolve `repo_root = common.find_repo_root(args.path, runner=runner)`. If `None`, print error to `sys.stderr` and return `2`.
     - Resolve `ws_dir = common.workspace_dir(repo_root)`.
     - Read `repo_config` from `StateDB(ws_dir / ".state" / "state.db")` if `state.db` exists (without creating `.state/state.db` if the repo is unenrolled and `.state/` doesn't exist! If `state.db` exists, open it and read `vcs_mode`, `memory_mode`, `execution_mode`, and `list_open()` from `attention_queue`; otherwise fall back to auto-detected `vcs_mode`, `memory_mode`, and `"monitored"`).
     - Scan `ws_dir` (if it exists):
       - `programme-*/PROGRAM.md` (sorted by directory name): load via `schemas.load_program`, extracting `programme_id`, `title`, `base_branch`, `status`, and `prs`.
       - `pr-*/PROJECT.md` (sorted by directory name): load via `schemas.load_project`. Also inspect `pr-*/wo*/WORKORDER.md` (sorted) via `schemas.load_workorder` and `pr-*/AUDIT-round-*.md` (sorted) via `schemas.load_audit`, and reconcile with local git commit trailers (`git log --format=%H%x00%(trailers:key=PA-WorkOrder,valueonly=true)%x00%(trailers:key=PA-Verified-Hash,valueonly=true)` via `runner`) when available:
         - For each PR entry in `"prs"`: include exact required keys `{"pr_id", "slug", "title", "status", "branch", "base_branch", "github_pr", "charter_locked", "work_orders": [...]}` (plus optional `"latest_audit"` if an audit file exists), where each item in `"work_orders"` reconciles `PROJECT.md`'s `work_orders` rows with any `wo*/WORKORDER.md` files and git trailers.
     - If `--json` is passed:
       - Emit `json.dumps(payload, indent=2)` to `sys.stdout` with exact top-level shape:
         `{"env": {"vcs_mode": ..., "memory_mode": ..., "execution_mode": ..., "workspace_dir": str(ws_dir)}, "programmes": [...], "prs": [...], "attention_queue": [...]}`
       - **Zero emoji characters in `--json` output** (PROGRAM.md §2.2(4)).
     - If `--json` is not passed:
       - Print a clean human-readable Programme -> PR -> WO tree with status glyphs (`✅`, `⚡`, `⏳`, `🔒`, etc.) and any open attention queue items to `sys.stdout`, and return `0`.
  6. **`pa mode [monitored|autonomous] [--path PATH]` (Charter G7, R12):**
     - Resolve `repo_root = common.find_repo_root(args.path, runner=runner)`. If `None`, print error to `sys.stderr` and return `2`.
     - Resolve `ws_dir = common.workspace_dir(repo_root)`.
     - Open `StateDB(ws_dir / ".state" / "state.db")`.
     - If no mode argument is given: read `db.get_config("execution_mode", "monitored")`, print it to `sys.stdout`, and return `0`.
     - If mode argument is given: validate it is `"monitored"` or `"autonomous"` (if invalid, print diagnostic to `sys.stderr` and return `1`), call `db.set_config("execution_mode", mode_val)`, print `mode_val` to `sys.stdout`, and return `0`.
- [ ] **`scripts/enroll.sh` and `scripts/unenroll.sh` (mark executable `chmod +x`):**
  - Bash wrapper scripts (`#!/usr/bin/env bash`, `set -euo pipefail`) that locate the repository root via `BASH_SOURCE[0]`, select `"$REPO_ROOT/.venv/bin/python3"` if executable else `"python3"`, and `exec "$PYTHON_BIN" "$REPO_ROOT/daemon/workspace-plugin/principal-architect/scripts/pa_cli.py" enroll "$@"` (and `unenroll "$@"` respectively).
- [ ] **`README.md` (Charter G1):**
  - Concise, high-signal documentation covering:
    1. Overview of `principal-architect-plugin` (Split-Authority contracts, dual-mode hooks, capability scoping, local-Git floor + GitHub bus, memory boundary).
    2. Developer bootstrap (`./scripts/dev-bootstrap.sh`).
    3. Running tests & linter (`./.venv/bin/pytest`, `./.venv/bin/ruff check daemon tests`).
    4. Repository enrollment & CLI usage (`./scripts/enroll.sh <repo>`, `pa status [--json]`, `pa mode [monitored|autonomous]`, `./scripts/unenroll.sh <repo>`).
- [ ] **`tests/test_state_db_and_sync.py` & `tests/test_schemas.py` (Charter R12):**
  - Add comprehensive tests in `tests/test_state_db_and_sync.py`:
    - Lazy import test: running `pa_cli.py --help` and `pa_cli.py mode` in a subprocess or checking `sys.modules` confirms `pydantic` and `yaml` are not imported at `import pa_cli` time.
    - Enrollment 2×2 matrix (`external|builtin` × `github|local_git`) via explicit flags AND via auto-detection:
      - Auto-detect `external` via `.memory/` dir, via `.agents/plugins.json` containing `repo-memory`, and via `$HOME/.gemini/config/plugins/repo-memory-daemon/state/registry.json`.
      - Auto-detect `github` when `fake_runner` returns a `github.com` URL for `git remote get-url origin` and `0` for `gh auth status`, and fallback to `local_git` when either fails.
      - Verify `builtin` mode scaffolds `memory/{MEMORY.md, MODULE_INDEX.md, PROJECT_INDEX.md}` and never overwrites existing content on re-enroll, while `external` mode does not create `memory/`.
    - Generated manifests (`pa-skills.json` with and without `--extra-skill pio`, and `pa-worker-rules.json` with default exclusions + `--exclude-rule custom-*`), plus preservation of `extra_skills` and `exclude_rules` on idempotent re-run of `pa enroll`.
    - Legacy migration (R8):
      - Tracked `.agents/skills/principal-architect-workspace/` moved via `git mv` to `.agents/plugins/principal-architect-workspace/`.
      - Untracked `.agents/skills/principal-architect-workspace/` moved via filesystem move.
      - Both `.agents/skills/principal-architect-workspace/` and `.agents/plugins/principal-architect-workspace/` exist -> aborts with exit code `2` and error message on stderr.
    - Non-git directory enrollment (`pa enroll` runs `git init` automatically).
    - Idempotency: running `pa enroll` twice exits `0`, does not duplicate `.agents/plugins.json` entries or `.git/info/exclude` lines or `.gitignore` lines, and preserves `enrolled_at`.
    - `pa unenroll`: removes `<daemon_home>/workspace-plugin` from `.agents/plugins.json` (preserving other plugins) and unregisters from `Registry`, while keeping committed files in `.agents/plugins/principal-architect-workspace/` intact.
    - `pa status` and `pa status --json`:
      - Test on enrolled `tmp_repo` with a sample `PROGRAM.md`, `PROJECT.md`, `WORKORDER.md`, and `attention_queue` item.
      - Dogfood test running `pa status --json` against this repository root and asserting the JSON output parses cleanly, contains zero emoji characters, lists `prog-principal-architect-plugin` and `PR-01` with `WO-01.1`..`WO-01.6`, and has all required keys!
    - `pa mode`: default `"monitored"`, set `"autonomous"`, get `"autonomous"`, set `"monitored"`, and invalid value returns exit code `1`.
  - In `tests/test_schemas.py`: include `wo6-pa-cli-enroll-unenroll-status-mode/WORKORDER.md` in the dogfood `load_workorder` / `verify_spec_hash` test so all 6 Work Orders of PR-01 are dogfood-verified!

## 4. Verification, Cryptographic Receipt & Issue Surfacing

1. Run the verification floor:
   ```bash
   ./.venv/bin/pytest tests/test_schemas.py tests/test_state_db_and_sync.py && ./.venv/bin/ruff check daemon tests
   ```
2. Compute `tree_hash`, update this `WORKORDER.md` frontmatter (`status: COMPLETED` and `completion:` block — using strictly valid `CompletionReport` keys: `status`, `attempt_num`, `receipt_id`, `commit_sha`, `files_modified`, `verification_summary`, `out_of_scope_findings`, `escalation_request`, `decisions_made`, `dead_ends`) and Part II `## Completion Report` (preserving Part I untouched so `spec_hash` remains valid), and commit on `pr-01-core-schemas-and-enrollment/wo6-pa-cli-enroll-unenroll-status-mode` with message:
   ```text
   WO-01.6: pa CLI enroll, unenroll, status, and mode with wrapper scripts and README

   PA-WorkOrder: WO-01.6
   PA-Verified-Hash: <tree_hash>
   ```
3. **Issue Surfacing:** Surface any out-of-scope findings in `out_of_scope_findings` in your Completion Report.

## Completion Report
<!-- Written by the Tier 3 Worker at task completion -->

_Pending execution by Tier 3 Worker (`WO-01.6`)._
