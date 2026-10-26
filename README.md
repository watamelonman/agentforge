# AgentForge

`forge` runs coding agents (Claude Code, Codex CLI, Grok Build, GLM through Claude Code, and
OpenCode models) **headless and in parallel** on a spec-driven project. Every task runs in its
own git worktree. Objective gates and a reviewer from another model family check the work before
it is merged into `main`, so sloppy or cheating work doesn't get in.

It was built for game projects (Godot 4 C# and GDScript presets ship by default), but the gates
are plain shell commands, so any project with a build/lint/test command can use it.

## How it works
1. You write a spec (`spec/SPEC.md`). `forge plan` asks a planner agent to split the next
   milestone into small **task cards** (`tasks/<ID>-<slug>.md`): owned files, dependencies,
   testable acceptance criteria.
2. `forge run -j N` runs up to N cards at once. For each card:
   worker agent → forge commits → merge `main` → **gates** → **reviewer** → serialized
   fast-forward merge into `main`. Failures become the next attempt's feedback.
3. Cards that can't pass after `budget.max_attempts` are marked `blocked` for you to look at.

## Features
- **Task cards** with `owns` globs (no two overlapping cards run together), `deps`, milestones
  (`strict_milestones`), per-card permission to edit tests or scenes.
- **Gates**: built-in policy gate (test tampering, stubs and test-mode detection, scope, file
  and diff size, required docs, scene edits) and architecture layers, plus the preset's
  build / lint / format / test commands. See [GATES](docs/GATES.md).
- **Cross review**: the reviewer comes from a different model family than the author
  (`reviewer = "cross"`), with an optional `self_review_fallback`.
- **Vendors**: `claude`, `codex`, `glm` (Z.ai via Claude Code), `grok`, and any number of
  OpenCode vendors (`harness = "opencode"`), sandboxed with bubblewrap. See [VENDORS](docs/VENDORS.md).
- **Usage limits pause one vendor, not the run**: the card moves to the next free vendor, the
  attempt isn't charged, reviews resume later, and `--wait` sleeps until a reset. Optional
  monthly allowances and machine-wide shared pools (e.g. one OpenCode Go plan used by several
  vendors and projects). See [LIMITS](docs/LIMITS.md).
- **Budgets**: per-run turns and timeouts, per-card attempts, a cumulative cap on agent runs,
  and a Claude-only spend cap. Every prompt and agent log is saved under `.forge/logs/`.
- **Context packs**: each prompt carries only the card, the relevant spec sections and owned
  files, within `context.max_chars`. See [CONTEXT_PACK](docs/CONTEXT_PACK.md).
- **Presets**: Godot 4 C# (default), Godot 4 typed GDScript, C/raylib, Python, LÖVE, Ren'Py.
- One stdlib Python file (`bin/forge`), no services or databases; state is a JSON file in the
  project. A tmux dashboard (`forge up`) and a systemd user unit for unattended runs.

## Requirements
- Linux (the installer supports Arch and Fedora; other distros work with manual installs)
- Python ≥ 3.11 (uses `tomllib`), git, tmux, Node.js
- At least one agent CLI, logged in: Claude Code (`claude`) and/or Codex CLI (`codex`);
  optionally Grok Build (`grok`), OpenCode (`opencode`), a Z.ai API key for `glm`
- `bwrap` (bubblewrap) for OpenCode vendors and Codex `sandbox = "bwrap"`
- Whatever your preset's gates need (Godot, .NET SDK, gdtoolkit, cmake, shellcheck, ...)

## Install
```bash
git clone <this repo> agentforge && cd agentforge
./install.sh --yes                  # --with-csharp for Godot C#, --with-raylib for C, --no-agents to skip CLIs
claude auth login && codex login    # once per machine
forge doctor                        # tools and logins (reads no secrets)
```
`install.sh` installs system packages, gdtoolkit, Claude Code and Codex if missing, symlinks
`bin/forge` to `~/.local/bin/forge` and installs the `forge-run@.service` user unit. Manual
install: put `bin/forge` on your `PATH`. Details: [INSTALL](docs/INSTALL.md).

## Quickstart
```bash
forge init ~/games/mygame --spec ~/specs/mygame.md    # --preset godot | c-raylib | python | love2d | renpy
cd ~/games/mygame
forge plan                    # writes tasks/*.md and docs/SPEC_ISSUES.md
$EDITOR tasks/*.md            # check the cards
git add -A && git commit -m "plan M1"
forge up -j 3                 # tmux: orchestrator | status | event log  (or: forge run -j 3)
forge status
```
More in [QUICKSTART](QUICKSTART.md) and [EXAMPLES](docs/EXAMPLES.md). Try it without
spending tokens: `forge --mock ...` or `tests/e2e.sh`.

## Documentation
[docs/README.md](docs/README.md) indexes everything: [CLI](docs/CLI.md) (every command and
option), [CONFIG](docs/CONFIG.md) (every `forge.toml` key and default), [TASKS](docs/TASKS.md),
[GATES](docs/GATES.md), [REVIEW_AND_BUDGETS](docs/REVIEW_AND_BUDGETS.md),
[LIFECYCLE](docs/LIFECYCLE.md), [VENDORS](docs/VENDORS.md), [LIMITS](docs/LIMITS.md),
[EXAMPLES](docs/EXAMPLES.md), [TROUBLESHOOTING](docs/TROUBLESHOOTING.md).

## Tests
`bash tests/run_all.sh` runs shellcheck (if installed), a compile check, the docs drift check
(`tests/check_docs.py`: every CLI option and config key must be documented), unit tests and an
end-to-end run with mock agents. No tokens are spent.

## Status and license
Version 0.1.0, see [CHANGELOG](CHANGELOG.md). Agents run with write access to their worktree
and use your paid CLI subscriptions or API keys; read [GATES](docs/GATES.md) and
[VENDORS](docs/VENDORS.md) before running unattended. Licensed under the GNU Affero General Public License v3.0 only (AGPL-3.0-only), see
[LICENSE](LICENSE).
