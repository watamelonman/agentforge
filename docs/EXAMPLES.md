# Worked examples

Each example uses only commands and keys documented in [CLI](CLI.md) and [CONFIG](CONFIG.md).
Paths such as `~/games/mygame` and `~/specs/mygame.md` are placeholders.

## 1. A new project

```bash
forge doctor                                   # tools present, claude/codex logged in
forge init ~/games/mygame --spec ~/specs/mygame.md            # default preset: godot-csharp
# other presets: --preset godot | c-raylib | python | love2d | renpy; --no-sample drops the sample code
cd ~/games/mygame
forge plan                                     # planner (agents.planner, default claude) writes tasks/*.md
$EDITOR tasks/*.md docs/SPEC_ISSUES.md         # check owns/deps/acceptance criteria
git add -A && git commit -m "plan M1"
forge up -j 3                                  # tmux dashboard: orchestrator | status | event log
```

To see the whole loop without spending tokens first, run `tests/e2e.sh` from the AgentForge
checkout (mock agents in a throwaway project), or prefix commands with `forge --mock`.

`forge init` copies `template/common` plus the preset, writes `forge.toml`, runs `git init -b main`
and makes the first commit. `forge plan` only plans the first milestone without cards (or
`--milestone N`); cards are scheduled in milestone order while `project.strict_milestones = true`.
When the milestone is done: `forge audit` (may add `FIX-nnn` cards), commit, `forge plan` again.

To use a different planner for one call: `forge plan --agent codex`.

## 2. Parallel runs and `--wait`

```bash
forge run -j 3                 # up to 3 cards at once, each in .forge/worktrees/<ID> on forge/<ID>
forge run -j 3 --wait          # same, but sleep while only cooling vendors block the remaining cards
forge up -j 3 -d --wait        # detached tmux session; attach later with `tmux attach -t forge-<name>`
forge run --task M1-T004 M1-T005   # only these cards
forge run -j 2 --audit         # run an audit when the run finishes
```

`forge run` refuses to start when the main checkout has uncommitted changes or is not on
`project.main_branch`, so commit card and config edits first.

Cards with overlapping `owns` globs never run at the same time, and a card starts only when all
its `deps` are `done`. Merges into `main` are serialized: each passing branch is merged with
`main`, gated again and fast-forwarded.

Without `--wait`, when every remaining card is waiting for a vendor that is cooling down, the
run stops and prints which vendor is free next, e.g.
`run: ... next one is free at 14:05 - rerun then, or use forge run --wait`. With `--wait` the
same process sleeps until that time and carries on. Unattended runs can also use the systemd
unit (see [INSTALL](INSTALL.md)).

## 3. A blocked card

```bash
forge status                                       # M1-T007 ... blocked
jq '.tasks["M1-T007"].history[-3:]' .forge/state.json   # last gate reports / review verdicts
forge review M1-T007 --gates-only                  # re-run the gates on its worktree, no agent
```

Typical causes and fixes:

- **Gate failed the same way twice** (`identical failure twice - blocking to save tokens`): the
  card is impossible as written. Fix the card (wider `owns`, `may_edit_tests = true`,
  `tests_required = false` for pure data, a clearer acceptance criterion) or the spec, commit,
  then `forge reset M1-T007`. Add `--hard` to throw the branch away and start from `main`.
- **Out of attempts** (`budget.max_attempts`, default 3): read the history, fix the card, `forge reset`.
- **The work is fine but a gate was wrong** (e.g. you fixed a gate command in `forge.toml`):
  `forge regate M1-T007` runs gates, review and merge on the existing branch without a worker.
  `forge regate M1-T007 --continue` lets workers retry if it still fails.
- **Reviewer rejected it and you disagree**: `forge review M1-T007 --agent codex` asks another
  vendor for a verdict on the same worktree.

## 4. A stale cooldown

A vendor hit a usage limit, then you bought more usage (or the guessed reset time was wrong),
but forge still skips it:

```bash
forge limits                     # codex  codex  openai  cooling until 18:30 (usage limit ...)
```

A running `forge run` loads per-vendor cooldowns from `.forge/state.json` once, at start, so
clearing them from another shell doesn't change that process. Stop it first:

```bash
pgrep -af 'forge.* run'                  # find the running forge process
kill <PID>                               # SIGTERM: stop cleanly
forge limits --clear codex               # or `forge limits --clear` for every vendor
forge run -j 3                           # or forge up -j 3
```

On SIGTERM, forge stops starting new steps; agent runs already in flight finish, and their cards
go back to `todo` if they have attempts left. Cooldowns of a shared pool (`[pools.<name>]`) are
re-read from the machine-wide ledger on every check, so `forge limits --clear <pooled vendor>`
lifts a plan-level cooldown for running processes too. Clearing never deletes spend history:
allowance windows (`monthly_usd`, `pools.<name>.usd_*`) still apply.

## 5. Raising a cap

Budget caps are cumulative per project (they live in `.forge/state.json`), so raising them means
editing `forge.toml` and running again:

```toml
[budget]
max_agent_runs = 400      # was 200; "global run cap 200 reached" stopped the run
max_total_usd = 60        # Claude only: "claude budget $40 exhausted; claude disabled"
max_attempts = 4          # per card
```

```bash
git commit -am "raise budget caps"
forge run -j 3
forge reset M1-T009 M1-T011      # cards already blocked by max_attempts need a reset
```

- `max_agent_runs` counts every agent run of every vendor; reaching it stops the run.
- `max_total_usd` only counts Claude's reported cost; reaching it disables claude and the other
  vendors carry on.
- For a vendor billed by a monthly plan, raise `[agents.<name>] monthly_usd` (or
  `allowance_margin`); for a plan shared by several vendors or projects, raise
  `[pools.<name>] usd_5h` / `usd_7d` / `usd_30d`.
- Per-run limits are per vendor: `[agents.<name>] max_turns`, `review_max_turns`, `timeout_min`,
  and for Claude `max_budget_usd`.
