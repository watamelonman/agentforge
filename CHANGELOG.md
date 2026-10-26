# Changelog

## Unreleased

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
