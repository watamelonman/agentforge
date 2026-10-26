# CLI reference

Every command and option below is checked against the real parser by
`tests/check_docs.py`. Global options go **before** the subcommand.

```
forge [-C ROOT] [--mock] <command> [options]
```

### forge (global options)
| Option | Default | Meaning |
|---|---|---|
| `-C ROOT` | `.` | Project root, the folder that contains `forge.toml`. |
| `--mock` | off | Use `tests/mock_agent.py` instead of the real CLIs. No tokens are spent. Same as `FORGE_MOCK=1`. |
| `-h`, `--help` | | Show help. |

### forge init
Create a project from the template: common files plus one preset. Runs `git init -b main` and
makes a first commit.

| Option | Default | Meaning |
|---|---|---|
| `dir` (positional) | required | Destination folder. It's created if missing. The command refuses if `forge.toml` already exists there. |
| `--preset NAME` | `godot-csharp` | One of `godot`, `godot-csharp`, `c-raylib`, `python`, `love2d`, `renpy` (the folders in `template/presets/`). |
| `--spec FILE` | none | Copy this file to `spec/SPEC.md`. |
| `--no-sample` | off | Leave out the preset's sample code (the files listed in the preset's `.forge-samples`, e.g. `Dice.cs`, `DiceTests.cs`, `DiceLabel.cs`) and the manifest. Without this flag the samples are kept, and `.forge-samples` marks them as disposable: the first task card may delete them (with `may_edit_tests = true`). |

`@NAME@` in file names and in `forge.toml`, `project.godot`, `CMakeLists.txt`, `conf.lua`, and
`<name>.csproj` is replaced with the folder name. The `AGENTS.md` scope and protected-path
lists are generated from the preset's `[policy]` (see `forge sync-agents`).
```
forge init ~/games/mygame --preset godot-csharp --spec ~/specs/mygame.md --no-sample
```

### forge plan
Run the planner agent (read-only) on the spec. It writes new task cards to `tasks/` and spec
problems to `docs/SPEC_ISSUES.md`. That file is **overwritten on every run** (it says
"No issues." when there are none), so it only ever reflects the latest plan. Cards whose IDs
already exist are skipped.

| Option | Default | Meaning |
|---|---|---|
| `--spec PATH` | `[project] spec` | Spec file the planner reads. |
| `--milestone N` | first milestone without cards | Which milestone to break down. |
| `--agent VENDOR` | `[agents] planner` | Which vendor plans: `claude`, `codex`, `glm`, `grok` or an `[agents.<name>]` OpenCode vendor. |
```
forge plan --milestone 2 --agent codex
```
Review and edit the cards, then `git commit` them before you run.

### forge run
Schedule and execute ready cards in parallel worktrees until nothing more can run. The main
checkout must be clean (tracked files) and on `main_branch`.

| Option | Default | Meaning |
|---|---|---|
| `--parallel N`, `-j N` | `2` | Maximum number of tasks running at once. |
| `--task ID [ID ...]` | all cards | Only consider these cards. Their dependencies must already be `done`. |
| `--audit` | off | When the run ends, run `forge audit` if at least one of the considered cards is done and `[agents] auditor` is set. |
| `--wait` | off | When the only cards left are waiting for vendors that are cooling down, sleep until the next one is free and carry on, instead of exiting. Good for overnight runs. |

A usage limit pauses only the vendor that hit it (see [LIMITS](LIMITS.md)): its card goes to
the next free vendor in the same run, without charging an attempt. Without `--wait` the run
ends when nothing else can start and tells you when the next vendor frees up.
```
forge run -j 3
forge run --task M1-T004 M1-T005
FORGE_MOCK=1 forge run      # dry run
```

### forge up
Start `forge run` inside a tmux session named `forge-<project>`. Window `forge` has three
panes: the orchestrator, `watch forge status`, and a tail of `events.log`. Window `shell` is
a plain shell. Attaches to the session unless you pass `-d`.

| Option | Default | Meaning |
|---|---|---|
| `--parallel N`, `-j N` | `2` | Passed to `run`. |
| `--detach`, `-d` | off | Don't attach. Later: `tmux attach -t forge-<project>`. |
| `--wait` | off | Passed to `run`. |

### forge status
Print a table of every card: ID, milestone, status, agent, attempts, title, and the last
history event. It also shows status counts, total agent runs, and the estimated Claude spend
(real `claude` runs only). When present it adds `runs by vendor: ...` and a `glm nominal cost`
line: Claude Code's Anthropic-price estimate for glm runs, which is not what a Z.ai plan
charges and is not counted toward `budget.max_total_usd`.
Statuses are `todo`, `running`, `gates_failed`, `review_failed` (transient, a retry follows),
`done`, and `blocked`. It also prints the cost OpenCode vendors reported and one line per
vendor that is cooling down.

It takes no options.

### forge limits
Show every vendor the project uses: harness, model family (as cross review sees it), whether
it is free, cooling down until a time (and why), and for vendors with `monthly_usd` the spend
in the current 5-hour / 7-day / 30-day windows against their limits.

| Option | Default | Meaning |
|---|---|---|
| `--clear [VENDOR ...]` | off | Lift cooldowns early: all of them, or only the named vendors. Recorded spend is kept, so an allowance window can still hold a vendor back. |
```
forge limits
forge limits --clear codex
```

### forge review
Re-run the gates, and then a reviewer, on a task's existing worktree. This doesn't merge
anything. Use it to inspect a blocked task.

| Option | Default | Meaning |
|---|---|---|
| `task` (positional) | required | Card ID. Its worktree must still exist. |
| `--agent VENDOR` | `codex` | Reviewer vendor (any vendor of the project). |
| `--gates-only` | off | Skip the reviewer. |

### forge audit
Whole-repo audit by the monitor agent (read-only). Writes `.forge/audit-<ts>.md`. Any
`FIX-*` cards it proposes go into `tasks/`.

| Option | Default | Meaning |
|---|---|---|
| `--agent VENDOR` | `[agents] auditor` | Auditor vendor (any vendor of the project). |

### forge reset
Put tasks back to `todo` with 0 attempts, for example after you fix a card or the spec.

| Option | Default | Meaning |
|---|---|---|
| `task` (positional, 1+) | required | Card IDs. |
| `--hard` | off | Also delete the worktree and the `forge/<ID>` branch, so the next attempt starts fresh from `main`. The branch is only deleted when the worktree still exists; if you removed the worktree yourself, delete a leftover branch with `git branch -D forge/<ID>`. |

Without `--hard` the branch and worktree are **kept**: the next `forge run` hands the
existing work to a worker, who continues on top of it. If the work on the branch may
already be good (for example a gate was wrong and has since been fixed), use
`forge regate` instead; it judges the branch without spending a worker run.

### forge regate
Run gates, then the reviewer, then the normal serialized merge on the **existing**
`forge/<ID>` branch, without starting a worker. Uncommitted changes in the worktree are
committed first; `main` is merged in. The worktree is recreated from the branch if it was
removed. A re-gate never resets or discards the branch: if `main` conflicts, the task is
marked `blocked` and you resolve the merge by hand. If gates or review fail, the task stays
`gates_failed`/`review_failed` with the report in `forge status` and `events.log`, and the
branch is kept. The attempt counter starts again from 0.

| Option | Default | Meaning |
|---|---|---|
| `task` (positional, 1+) | required | Card IDs, processed one after another. |
| `--continue` | off | If the re-gate fails, carry on with normal worker attempts, using the failure report as feedback. |

### forge upgrade
Add files that newer forge versions expect to a project that was initialized with an older
one. Today that's `.forge-samples` (copied from the preset, keeping only the sample files that
still exist; an existing manifest is never overwritten) and, if `AGENTS.md` has the
policy-list markers, a `sync-agents` refresh. Nothing is committed; review with `git diff`
and commit it yourself. Gates read `.forge-samples` from `main`, so commit it before re-gating.

| Option | Default | Meaning |
|---|---|---|
| `--preset NAME` | `godot-csharp` | Preset the project was created from. |

### forge gates
Run the gate chain on the **main checkout** against a base ref, as if one card owned
everything (`owns=["**"]`, `may_edit_tests=true`, `tests_required=false`). Use it for CI or to
check your own changes. Exits 1 if any gate fails.

| Option | Default | Meaning |
|---|---|---|
| `--base REF` | `HEAD~1` | Diff base for the policy gate. |

### forge sync-agents
Rewrite the block between the `<!-- forge:policy-lists BEGIN ... -->` and
`<!-- forge:policy-lists END -->` markers in `AGENTS.md` using `forge.toml [policy]`
(`always_allowed`, `test_globs`, `protected`, `scene_globs`), so the rules agents read always
match what the gates enforce. It also regenerates the `Edit(...)`/`Write(...)` deny rules in
`.claude/settings.json` from `protected` (other deny rules are kept). `forge init` does this automatically. Run it yourself after
editing `[policy]`, then commit `AGENTS.md`. It takes no options and is idempotent.

### forge doctor
List the required and optional tools on `PATH` and check logins with `claude auth status`
and `codex login status`. These only report status; no credentials are read.

It then checks glm, reading `[agents.glm]` from `forge.toml` in the `-C` directory (built-in
defaults if there is none):

- `glm key:` whether the Z.ai key was found and where (`env $ZAI_API_KEY` or `file ...`).
  The key itself is never printed. It warns if the key file is readable by group or others.
- `glm url:` a plain unauthenticated GET to `agents.glm.base_url`. Any HTTP answer, including
  401/404, counts as reachable; only DNS, TLS, or connection errors fail.
- `glm api:` only if a key exists: one direct `POST <base_url>/v1/messages` with
  `max_tokens = 1`, showing Z.ai's own HTTP status and error body (e.g. 401 bad key, 429 with
  code 1308 when the plan's limit is used up).
- `glm ping:` only if a key exists: one `claude -p "Reply with exactly the word pong."
  --output-format stream-json --verbose --max-turns 1 --tools ""` run through the same private glm environment
  forge uses (Z.ai endpoint, token, models, separate `CLAUDE_CONFIG_DIR`). It's aborted early when
  Claude Code's second `api_retry` shows 401/403/429, otherwise after 180 s. Together the two
  checks cost two tiny requests on your Z.ai plan. Output is redacted before printing.

Exits non-zero if a required tool (git, tmux, python3, node, claude, codex) is missing,
Python is older than 3.11, or a glm check fails **and** the project uses glm (in `workers`,
`review_pool`, `planner`, `auditor` or `reviewer`). For projects without glm, the glm lines are
informational.

Last it checks grok (`[agents.grok]`): `grok:` binary path and `grok --version`; `grok auth:`
from `grok models` (lists models, makes no model call; "not authenticated" means run
`grok login`, or `grok login --device-code` over SSH), or `XAI_API_KEY` present in the
environment; `grok model:` the configured or CLI-default model. It fails doctor only when the
project uses grok.

Finally, one `opencode:` line per `[agents.<name>]` table with `harness = "opencode"`: binary
present, `model` set, bubblewrap present (unless `sandbox = "none"`) and the model family
cross review will use; then `opencode auth:` from `opencode auth list` (no model call). These
fail doctor only when such vendors exist.

## Environment variables
| Variable | Used by | Meaning |
|---|---|---|
| `FORGE_MOCK=1` | forge | Mock agents (same as `--mock`). |
| `FORGE_ROLE`, `FORGE_TASK`, `FORGE_SCHEMA` | set **for** agents | Role (`work`/`review`/`plan`/`audit`), card ID, and schema path. |
| `FORGE_BASE` | set for gate commands | Merge-base commit of the task branch. |
| `FORGE_POOL_DIR` | forge | Directory of the shared pool ledgers (default `$XDG_STATE_HOME/agentforge/pools`, i.e. `~/.local/state/agentforge/pools`). |
| `ZAI_API_KEY` | glm vendor | Z.ai key (name set by `agents.glm.key_env`); read from the environment or `agents.glm.key_file`. |
| `GODOT_BIN` | `tools/godot_check.sh` | Overrides `[engine] godot_bin`. |
| `GDUNIT_TAG` | `tools/setup_addons.sh` | GdUnit4 git tag to vendor (default `v6.2.2`). |
