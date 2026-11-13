# Antigravity 1.5.2+ / 1.5.8 Workspace Plugin Migration Guide

> **Applies to:** Per-repository Antigravity plugins using the two-tier `*-daemon` + `<repo>/.agents/plugins/...` pattern — specifically **`principal-architect`** (implemented in PR #23), **`repo-memory`** (`repo-memory-daemon`), and **`bug-fixer`** (`bug-fixer-daemon`).

---

## 1. Executive Summary

After upgrading to Antigravity `1.5.8` (following security hardening shipped in `1.5.2`), per-repository workspace plugins registered via external paths in `<repo>/.agents/plugins.json` or symlinked under `<repo>/.agents/plugins/<plugin>` silently stopped loading — making slash commands (`/principal-architect`, etc.), workspace subagents, rules, and workspace-scoped hooks disappear inside enrolled repositories.

Moving workspace hooks or agents into the **global** `~/.gemini/config/plugins/<name>-daemon/` plugin is an anti-pattern: global hooks fire unconditionally across **every** repository opened in Antigravity ("hook storms"), blocking tools and mutating context in unenrolled repos.

The clean solution is to keep admin/daemon plumbing global (with **zero global hooks**) and **stage a real, non-symlink, git-excluded copy** of each workspace plugin directly inside `<repo>/.agents/plugins/<plugin-name>/`, paired with strict manifest validation fixes and automatic upgrade synchronization via `<cli> doctor --fix`.

---

## 2. Root Cause 1: Antigravity `1.5.2+` Workspace Boundary Enforcement

From `agy changelog` (`1.5.2`):

> *"Improved protection against untrusted repositories: plugins and skills listed in a workspace's `.agents/plugins.json` or `.agents/skills.json` now load only from inside the workspace or its repository root, and entries that point elsewhere through absolute paths, `../`, or symbolic links are skipped."*

### What Antigravity `1.5.8` Silently Skips

Querying the Antigravity Language Server (`LanguageServerService/GetAllPlugins` and `GetAllSkills`) confirmed that all of the following are silently ignored:

1. **External or `~` paths in `<repo>/.agents/plugins.json`:**
   - e.g., `~/.gemini/config/plugins/<daemon>/workspace-plugin/<plugin>`
   - e.g., `$HOME/.gemini/config/plugins/<daemon>/workspace-plugin/<plugin>`
2. **Symbolic links inside `<repo>/.agents/plugins/`:**
   - e.g., `<repo>/.agents/plugins/bug-fixer -> ~/.gemini/config/plugins/bug-fixer-daemon/workspace-plugin/bug-fixer`
3. **External paths, `../` traversals, or external symlinks inside `.agents/skills.json` or subagent capability manifests:**
   - e.g., absolute paths or symlinks in `.agents/plugins/<ws>/.state/pa-skills.json`, `.state/pa-worker-rules.json`, or `--extra-skill` targets.

Only **real files and directories rooted inside the workspace / repository root** (discovered natively via `<repo>/.agents/plugins/<plugin-name>/plugin.json`) load reliably under Antigravity `1.5.2+`.

---

## 3. Root Cause 2: Strict Plugin Validation Rules (`agy plugin validate --strict`)

Running `agy plugin validate --strict <plugin-dir>` revealed four additional validation and bundling constraints required for clean `1.5.8` loading:

1. **Plain-markdown plugin rules must be `rules/AGENTS.md`:**
   - Rule files under `rules/` without `trigger:` YAML frontmatter (`always_on`, `manual`, `glob`, or `model_decision`) are flagged in strict mode unless named `rules/AGENTS.md`.
   - In `principal-architect`, `rules/00-pa-operating-model.md` was renamed to `rules/AGENTS.md` (and agent prompt references were updated accordingly).
2. **Duplicate agent definitions fail `--strict` validation:**
   - Defining the same agent name twice (e.g., both `agents/<name>.md` and `agents/<name>/agent.md`) emits a validation warning and fails `--strict` mode.
3. **Hook commands in `hooks.json`:**
   - Prefer relative `./scripts/<hook>.py` commands for Python scripts bundled inside `<repo>/.agents/plugins/<plugin>/scripts/` (avoiding stale warnings around `${PLUGIN_ROOT}`), or invoke a compiled global binary by path (`~/.gemini/config/plugins/<daemon>/bin/<cli>`).
   - Note: Antigravity `1.5.3` also introduced runtime `PLUGIN_ROOT` and `PLUGIN_DATA` environment variables for plugin hooks.
4. **Build artifact stripping during staging/install:**
   - Strip `__pycache__`, `*.pyc`, `.DS_Store`, and `*.egg-info` directories when installing `daemon/` and when staging `<repo>/.agents/plugins/<plugin>/`.

---

## 4. Reference Architecture: How `principal-architect-plugin` Fixed It

### Two-Tier Split (Zero Global Hook Leakage)

- **Global tier (`~/.gemini/config/plugins/pa-daemon/`):**
  - Holds only `plugin.json`, `sidecars/`, global admin skill (`skills/principal-architect-admin/`), `bin/pa`, `.venv/`, `state/registry.json`, and the canonical template `workspace-plugin/principal-architect/`.
  - **No `hooks.json` in `pa-daemon`**, so unenrolled repositories never trigger PA hooks.
- **Per-repo tier (`<repo>/.agents/plugins/principal-architect/`):**
  - Holds a **real, non-symlink copy** (`shutil.copytree(..., symlinks=False)`) of the workspace plugin (`plugin.json`, `hooks.json`, `scripts/`, `skills/`, `agents/`, `rules/AGENTS.md`, `templates/`).
  - Keeps `<repo>/.agents/plugins/principal-architect-workspace/` separate for tracked project specs (`PROGRAM.md`, `PROJECT.md`, `WORKORDER.md`) and untracked runtime state (`.state/`).

### Lifecycle Operations Implemented in `pa_cli.py`, `install.sh`, and `install-release.sh`

1. **Enrollment (`pa enroll`):**
   - Copies `~/.gemini/config/plugins/<daemon>/workspace-plugin/<plugin>` into `<repo>/.agents/plugins/<plugin>/` with `symlinks=False` (explicitly `unlink()`ing any legacy symlink before `shutil.copytree`).
   - Scrubs legacy PA entries from `<repo>/.agents/plugins.json` while **preserving sibling entries** (such as `repo-memory-daemon` or `bug-fixer-daemon`), deleting `.agents/plugins.json` if `entries` becomes empty.
   - Adds `/.agents/plugins/<plugin>/` and `/.agents/plugins.json` to `<repo>/.git/info/exclude` (wrapped in `# >>> <plugin> (managed) ... # <<< <plugin> (managed)`) so staged runtime copies never appear in `git status` or pollute the project's `.gitignore`.
   - Writes workspace-relative paths (`.agents/skills`, `.agents/rules`, and local copies under `.state/extra-skills/<name>`) into `.state/pa-skills.json` and `.state/pa-worker-rules.json` so subagents remain inside workspace boundaries.
2. **Unenrollment (`pa unenroll`):**
   - Removes `<repo>/.agents/plugins/<plugin>/` (`unlink()` if symlink, else `shutil.rmtree()`) and scrubs legacy PA entries from `.agents/plugins.json`.
3. **Version Stamping, Drift Detection, and Auto-Upgrade (`pa doctor --fix` + Installers):**
   - `scripts/install.sh` and `scripts/install-release.sh` stamp the identical resolved semantic `"version"` into **both** `~/.gemini/config/plugins/pa-daemon/plugin.json` and `~/.gemini/config/plugins/pa-daemon/workspace-plugin/principal-architect/plugin.json`.
   - `pa doctor` iterates over every registered repo in `<PA_DAEMON_HOME>/state/registry.json` and warns if `<repo>/.agents/plugins/principal-architect/` is missing, is a symlink, has a `"version"` mismatch against the installed daemon, or still has legacy PA entries in `.agents/plugins.json`.
   - `pa doctor --fix` re-stages `<repo>/.agents/plugins/principal-architect/`, scrubs `.agents/plugins.json`, refreshes `.git/info/exclude`, and regenerates role capability manifests across every registered repository.
   - Both `scripts/install.sh` and `scripts/install-release.sh` invoke `"${PA_DAEMON_HOME}/bin/pa" doctor --fix >/dev/null 2>&1 || true` at the end of installation so upgrades automatically refresh all enrolled repos.

### Subtle Gotchas Caught During Implementation

- **Exclude staged plugin paths from git hygiene & tree hashing:**
  - `stop_gate.py` (`_is_ephemeral_runtime_path`), `pa_cli.py` (`_is_ephemeral_runtime_path` and `_collect_existing_allowed_files`), and `post_tool_receipt.py` (`compute_tree_hash`) must ignore `.agents/plugins/<plugin>` so staging/upgrading the plugin never fails dirty-working-tree checks, Work Order scope boxes, or cryptographic verification receipts.
- **Python `str.lstrip("./")` bug (critical!):**
  - Never normalize repo-relative POSIX paths with `rel_posix.lstrip("./")`. Python's `str.lstrip` strips a **character set**, turning `".agents/plugins/..."` into `"agents/plugins/..."` (stripping the leading dot from `.agents` and silently breaking every path comparison)!
  - Always use:
    ```python
    norm = rel_posix.strip().removeprefix("./").lstrip("/")
    ```
- **Avoid symlinks anywhere inside `.agents/plugins/<plugin>/`:**
  - Because `1.5.2+` rejects external symlinks and workspace-escaping targets, always use `copytree(..., symlinks=False)` when copying both the staged workspace plugin and any `--extra-skill` folders into `.state/extra-skills/`.

---

## 5. Migration Checklists for Sibling Plugins

### A. `repo-memory` (`repo-memory-daemon` — Compiled Binary Archetype)

Live inspection of `~/.gemini/config/plugins/repo-memory-daemon/workspace-plugin/repo-memory/` showed:

1. **Current broken state in enrolled repos:**
   - Enrolled repositories currently list `{"path": "<HOME>/.gemini/config/plugins/repo-memory-daemon/workspace-plugin"}` inside `<repo>/.agents/plugins.json`. Antigravity `1.5.8` skips this entry completely, so `repo-memory`'s workspace plugin (`hooks.json`, `mcp_config.json`, `agents/`) does not load.
2. **Existing strict validation failure:**
   - Running `agy plugin validate --strict ~/.gemini/config/plugins/repo-memory-daemon/workspace-plugin/repo-memory` fails with:
     ```text
     ⚠ agents/repo-memory-distiller/agent.md: skipped: agents/repo-memory-distiller.md already defines an agent named "repo-memory-distiller"
     Error: validation failed in strict mode: 1 warning
     ```
   - **Fix:** Remove the duplicate agent definition (keep either `agents/repo-memory-distiller.md` or `agents/repo-memory-distiller/agent.md`, not both) so `--strict` passes with zero warnings.
3. **Why staging is ultra-lightweight for `repo-memory`:**
   - Its `workspace-plugin/repo-memory/hooks.json` and `mcp_config.json` already invoke the compiled global binary `~/.gemini/config/plugins/repo-memory-daemon/bin/repo-memory` directly.
   - You do **not** need to copy any compiled binary into enrolled repos — only copy the small `workspace-plugin/repo-memory/` manifest/markdown tree (`plugin.json`, `hooks.json`, `mcp_config.json`, `agents/`, and any `skills/` / `rules/`).
4. **Checklist for `repo-memory`:**
   - [ ] Deduplicate `agents/repo-memory-distiller` and run `agy plugin validate --strict` until exit `0`.
   - [ ] Ensure `workspace-plugin/repo-memory/plugin.json` carries a `"version"` field stamped identically to `repo-memory-daemon/plugin.json` during install/build.
   - [ ] Update `repo-memory enroll` to copy `workspace-plugin/repo-memory/` (non-symlink) to `<repo>/.agents/plugins/repo-memory/`, scrub `repo-memory-daemon` entries from `<repo>/.agents/plugins.json` (preserving sibling plugins), and add `/.agents/plugins/repo-memory/` to `<repo>/.git/info/exclude`. *(Note: `principal-architect`'s `detect_memory_mode()` already detects `<repo>/.agents/plugins/repo-memory`!)*
   - [ ] Update `repo-memory unenroll` to remove `<repo>/.agents/plugins/repo-memory/` and clean `.agents/plugins.json`.
   - [ ] Add stale/missing/symlinked staged-plugin detection and `--fix` re-staging to `repo-memory doctor`, iterating over enrolled repos in `registry`, and call `repo-memory doctor --fix` from `install.sh` / `install-release.sh`.
   - [ ] Ignore `.agents/plugins/repo-memory` in any `repo-memory` indexing/hash/dirty-tree scans (using `.removeprefix("./").lstrip("/")`, not `.lstrip("./")`).

---

### B. `bug-fixer` (`bug-fixer-daemon` — Interpreted Python Script Archetype)

Live inspection of `~/.gemini/config/plugins/bug-fixer-daemon/` and an enrolled repo revealed **two compounding issues**:

1. **Broken per-repo workspace plugin in enrolled repos:**
   - Enrolled repos currently have **both** `~/.gemini/config/plugins/bug-fixer-daemon/workspace-plugin/bug-fixer` in `<repo>/.agents/plugins.json` **and** a symlink at `<repo>/.agents/plugins/bug-fixer -> ~/.gemini/config/plugins/bug-fixer-daemon/workspace-plugin/bug-fixer`.
   - Antigravity `1.5.8` skips **both** the external `.agents/plugins.json` entry and the symlink, so `bug-fixer` workspace agents, rules, and skills do not load in enrolled repos.
2. **Global hook leakage across unenrolled repos:**
   - `~/.gemini/config/plugins/bug-fixer-daemon/hooks.json` currently registers `PreToolUse` and `PostToolUse` hooks (`pre_tool_gate.py`, `integrity_monitor.py`, `github_url_gate.py` via `python3 workspace-plugin/bug-fixer/scripts/...`) on the **global** daemon plugin.
   - Because that `hooks.json` sits at the root of `~/.gemini/config/plugins/bug-fixer-daemon/`, those security gates execute in **every workspace on the machine**, including unrelated repositories not enrolled in `bug-fixer`.
3. **Checklist for `bug-fixer`:**
   - [ ] **Eliminate global hook leakage:** Move `hooks.json` out of the global `bug-fixer-daemon/` root and into `workspace-plugin/bug-fixer/hooks.json`, rewriting hook commands to relative `"python3 ./scripts/<script>.py"` paths (or verify global `hooks.json` is removed completely on install/upgrade).
   - [ ] **Make `workspace-plugin/bug-fixer/` self-contained:** Ensure `workspace-plugin/bug-fixer/` contains a valid `plugin.json` (with `"name"` and `"version"`), `hooks.json`, `scripts/` (all hook entrypoints and imported helpers such as `shell_analysis.py` and `security_audit.py`), `agents/`, `skills/`, and `rules/`.
   - [ ] **Pass `agy plugin validate --strict`:** Ensure every rule file under `workspace-plugin/bug-fixer/rules/` either has valid `trigger:` frontmatter or is consolidated into `rules/AGENTS.md`, ensure no duplicate agent names exist, and validate both `daemon` and `workspace-plugin/bug-fixer` with `--strict`.
   - [ ] **Stage real copies instead of symlinks on `enroll`:** When enrolling a repo, explicitly `unlink()` any legacy `<repo>/.agents/plugins/bug-fixer` symlink first, then `shutil.copytree(..., symlinks=False)` into `<repo>/.agents/plugins/bug-fixer/`.
   - [ ] **Clean `.agents/plugins.json` and update `.git/info/exclude`:** Remove `bug-fixer` entries from `<repo>/.agents/plugins.json` (without clobbering sibling entries) and add `/.agents/plugins/bug-fixer/` to `<repo>/.git/info/exclude`.
   - [ ] **Ignore `.agents/plugins/bug-fixer` in integrity & git hygiene monitors:** Update `integrity_monitor.py` / tree-hash / dirty-tree checks so staged plugin files inside `<repo>/.agents/plugins/bug-fixer/` are ignored (again using `.removeprefix("./").lstrip("/")`, not `.lstrip("./")`).
   - [ ] **Auto-refresh on upgrade:** Stamp matching `"version"` into `bug-fixer-daemon/plugin.json` and `workspace-plugin/bug-fixer/plugin.json`, add staged-plugin version drift detection & repair (`doctor --fix` or equivalent), and run it automatically during `install.sh` / `install-release.sh` across all enrolled repos.

---

## 6. End-to-End Verification Playbook

Run these checks after migrating `repo-memory` or `bug-fixer`:

### 1. Strict Plugin Validation

```bash
agy plugin validate --strict <repo-checkout>/workspace-plugin/<plugin-name>
agy plugin validate --strict <repo-checkout>/daemon  # or global plugin root
```

Expected: `✔ Validation passed` with **0 warnings** and **0 errors**.

### 2. Inspect Staged Repo Layout

Confirm `<enrolled-repo>/.agents/plugins/<plugin-name>` is a real directory (`drwxr-xr-x`, **not** `l...` symlink), contains `plugin.json` with a matching `"version"`, `<enrolled-repo>/.agents/plugins.json` no longer contains that plugin's external path, and `git -C <enrolled-repo> status --short` shows zero untracked `.agents/plugins/...` entries.

### 3. Verify Live Antigravity `1.5.8` Language Server Isolation

Query `GetAllPlugins` against an **enrolled** repository:

```bash
curl -sS -X POST "http://${ANTIGRAVITY_LS_ADDRESS:-localhost:5387}/exa.language_server_pb.LanguageServerService/GetAllPlugins" \
  -H "Content-Type: application/json" \
  -H "x-codeium-csrf-token: ${ANTIGRAVITY_CSRF_TOKEN}" \
  -d '{"workspaceUris":["file:///ABS/PATH/TO/ENROLLED_REPO"]}' \
  | jq '[.plugins[] | select(.isGlobal | not) | {name, dir: (.path | split("/") | last), disabled: (.disabled // false), skills: [.skills[]?.name], agents: [.agents[]?.agent.name], hooks: ((.hooksJson // "") | length > 0)}]'
```

Expected: returns `<plugin-name>` with `"disabled": false` and the expected `skills`, `agents`, and `hooks: true`.

Query `GetAllPlugins` against an **unenrolled** repository:

```bash
curl -sS -X POST "http://${ANTIGRAVITY_LS_ADDRESS:-localhost:5387}/exa.language_server_pb.LanguageServerService/GetAllPlugins" \
  -H "Content-Type: application/json" \
  -H "x-codeium-csrf-token: ${ANTIGRAVITY_CSRF_TOKEN}" \
  -d '{"workspaceUris":["file:///ABS/PATH/TO/UNENROLLED_REPO"]}' \
  | jq '[.plugins[] | select(.isGlobal | not) | {name, dir: (.path | split("/") | last)}]'
```

Expected: returns `[]` (confirming zero cross-repo hook or plugin leakage).
