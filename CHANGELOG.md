# Changelog

## Unreleased

### Fixed
- love2d preset: `policy.skip_markers` had a Lua pattern (`%-%-%s*it%(`) that is not a valid
  Python regex, so the policy gate crashed on every love2d project. It is now `--\s*it\(`
  (a commented-out busted `it(`). New `tests/test_presets.py` compiles every preset's regex
  keys and runs the policy gate on a scratch love2d project.

### Changed
- Split the single-file `bin/forge` into the `agentforge/` package (about 40 modules, none
  over 260 lines; map in ARCHITECTURE). `bin/forge` is now a thin entry point that imports the
  package from next to its resolved path, so the `~/.local/bin/forge` symlink keeps working.
  Copying `bin/forge` alone does not work (`forge init` always needed the checkout's
  `template/` anyway). No change to CLI flags, output, config keys, `state.json` or the
  `.forge/` layout.
- Broke up the longest functions (`run_agent`, `run_task`, `gate_policy`, `doctor_glm`,
  `cmd_run`, `build_cmd`, `cmd_limits`, `cmd_init`, `detect_limit`, `build_context`,
  `doc_coverage`, `gate_layers`) into named steps with early returns; the longest function is
  now 45 lines (was 200) and nesting is at most 5 levels (was 7).
- The reset-time and Z.ai limit regexes are written with `re.VERBOSE` and comments;
  `duration_secs`, `next_wakeup`, `glob_match` and the Grok JSON event scanner document
  concrete examples, checked by the new `tests/test_parsers.py` (doctests included).
- `install.sh` checks that `agentforge/` is next to `bin/forge` before linking it.
- Tests that patch the pool directory set `agentforge.pools.POOL_DIR`; `tests/check_docs.py`
  scans the package for config keys.

### Docs
- LIMITS: say that a shared-pool window set to `0` (or left out) is off, matching the code
  and CONFIG.

## v0.1.0 (2026-10-26)
First public release.

### Features
- `forge` CLI: `init`, `plan`, `run`, `up`, `status`, `limits`, `review`, `audit`, `reset`,
  `regate`, `gates`, `doctor`, `sync-agents`, `upgrade`; global `-C` and `--mock`.
- Spec → task cards (TOML front matter: `owns`, `deps`, `milestone`, `agent`, test/scene flags).
- One git worktree per card; worker → gates → cross-family reviewer → serialized fast-forward merge.
- Policy gate (anti-cheat, scope, size, docs, scenes), architecture-layer gate and preset gates.
- Presets: Godot 4 C# (default), Godot 4 typed GDScript, C/raylib, Python, LÖVE, Ren'Py.
- Vendors: Claude Code, Codex CLI, GLM via Claude Code (Z.ai), Grok Build, OpenCode vendors
  sandboxed with bubblewrap.
- Per-vendor usage-limit cooldowns, `--wait`, `forge limits [--clear]`, monthly allowances and
  machine-wide shared pools.
- Budgets: turns, timeouts, attempts, cumulative agent-run cap, Claude spend cap.
- tmux dashboard, systemd user unit, Arch/Fedora installer, mock agents and self-tests.

### Included fixes and additions from pre-release patches
- Claude `Edit`/`Write` deny rules for `policy.protected` globs are anchored to the project
  root, so they no longer match nested directories with the same name.
- `budget.max_total_usd` counts and caps Claude spend only, disabling claude instead of
  stopping the run.
- Codex `sandbox = "bwrap"`: run Codex workers inside forge's bubblewrap sandbox.
- `agents.fallback_workers`: vendors used only when every worker vendor is out.
- `agents.self_review_fallback`: let the author review when no other reviewer is free.
- Grok Build output parsing: camelCase/snake_case result fields, and a short retry when the
  final JSON lands after the process exits.
- OpenCode 2.x: `--standalone`, `-m model#variant`, HTTP status from `error.status`; account
  settings that block a model and argv/usage mismatches are setup problems, not card failures.
- OpenCode Go shared pools (`agents.<name>.pool`, `[pools.<name>]`).
