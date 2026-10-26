# Usage limits, cooldowns and allowances

Subscriptions and coding plans cap usage per 5 hours, per week or per month. forge treats a
limit as a property of **one vendor**, not of the run: the vendor that hit it pauses, and the
others keep working. The code lives in `agentforge/limits.py`
(`set_cooldown`, `cooldown_until`, `available`, `allowance_until`), `agentforge/resettime.py`
(`limit_reset_time`), `agentforge/detect.py` (`detect_limit`) and in `run_task`
(`agentforge/task.py`) / `cmd_run` (`agentforge/scheduler.py`).

## What happens when a vendor hits a limit
1. `run_agent` sees the limit (`detect_limit`: the vendor's limit messages, Claude Code
   `rate_limit_event`, Z.ai 13xx codes, OpenCode `error` events with status 429, Claude
   overage when `allow_overage = false`).
2. It works out when the limit lifts (`limit_reset_time`): Claude Code's `resetsAt`, or text
   such as `try again in 2 hours 13 minutes` or `resets at 2026-10-19T18:00:00Z`. Times
   without a time zone are ignored, because forge can't know whose clock they mean. With no
   usable time, the vendor pauses for `cooldown_min` (per vendor) or
   `budget.limit_cooldown_min` (default 60 minutes). A parsed time gets one extra minute.
3. The vendor is put in a **cooldown**: in memory, in `.forge/state.json` under `cooldowns`
   (so the next `forge run` respects it), and as a line in `events.log`:
   `codex: cooling down until 14:05 (usage limit message); other vendors keep working`.
4. The card is not charged an attempt:
   - **Worker hit the limit:** whatever it already wrote is committed as
     `<ID>: partial work by <vendor> (stopped by usage limit)`, and the card goes straight
     to the next free worker, with feedback saying the worktree holds partial work. A card
     pinned to a vendor waits for that vendor (until `swap_on_retry` rotation applies from
     attempt 3).
   - **Reviewer hit the limit:** the next allowed reviewer takes over (see the ranking in
     CONFIG.md under `[agents]`). If none is free, the card is parked as `todo` with
     `pending_review = true`. When a reviewer frees up, forge re-runs the gates on the branch
     and reviews it, **without running the worker again**.
5. The scheduler skips cards whose next step needs a vendor that is cooling down. When
   nothing else can run, `forge run` ends and says when the next vendor is free; with
   `forge run --wait` (or `forge up --wait`) it sleeps until then and carries on.

Login or key problems (HTTP 401/403, "not signed in", missing Z.ai key, missing bubblewrap,
an OpenCode vendor without a model) are different: they don't end at a reset time, so the
vendor is **disabled for the rest of this process** (`SETUP PROBLEM` in `events.log`) and
used again on the next run, after you fix it.

`budget.max_total_usd` is not a stop either: once Claude's cumulative estimate reaches it,
only `claude` is disabled for the rest of the run. `budget.max_agent_runs` and SIGTERM do stop
the whole run.

## Fallbacks when vendors are out
- `[agents] fallback_workers`: vendors that work cards only when every vendor in `workers` is
  cooling down or disabled.
- `[agents] self_review_fallback = true`: when every other reviewer is cooling down, the
  author's own vendor reviews instead of the card being parked.

## A cooldown that is wrong or stale
Cooldowns are loaded from `state.json` when `forge run` starts and then kept in memory. A
`forge limits --clear` from another shell updates `state.json` (and the pool ledger), but a
**running** `forge run` keeps its own copy of per-vendor cooldowns until it exits (pool
cooldowns are re-read from the ledger, so clearing those takes effect everywhere). To lift a
per-vendor cooldown for a run in progress: stop the run, clear, start again. See
[EXAMPLES](EXAMPLES.md#4-a-stale-cooldown).

## Allowance windows (`monthly_usd`)
Some plans count usage in dollars at API prices. OpenCode Go, for example, gives each model a
monthly allowance and lets any 5 hours use at most 20% of it, and any 7 days at most 50%.
With `monthly_usd` set on a vendor, forge records the cost each run reports (in
`state.json` under `spend_log`, 31 days kept) and stops starting that vendor once a window
reaches `allowance_margin` (default 90%) of its share. It becomes available again when
enough old runs have aged out of the window. That way forge rotates to another model before
the provider refuses requests, instead of discovering the limit mid-run.

```toml
[agents.oc-glm]
harness = "opencode"
model = "opencode-go/glm-5.3"
monthly_usd = 120          # Go Plus allowance for this model; check opencode.ai for yours
```

The recorded cost is what the CLI reports. OpenCode reports a per-step `cost`; whether it
matches OpenCode Go's own accounting exactly is **unverified**, which is what the margin is
for. Codex reports no cost, so `monthly_usd` does nothing for it.

## Shared pools (`pool`)
Some plans share one allowance across models, and several forge projects (and other agents on
the same machine) may draw from it at once. Give each such vendor `pool = "<name>"` and add a
`[pools.<name>]` table:

```toml
[agents.oc-deepseek]
harness = "opencode"
model = "opencode-go/deepseek-v4.1-flash"
pool = "opencode-go"

[pools.opencode-go]
usd_5h = 2.25     # estimates: OpenCode Go publishes per-model limits only
usd_7d = 5.50
usd_30d = 11.0
```

Each window is optional: leave a key out, or set it to `0`, to turn that window off (for
example `usd_7d = 0` and `usd_30d = 0` keep only the 5-hour cap and let the provider's own
limit message stop the pool). A provider limit message still cools the whole pool either way.

- Every pooled run appends `{"kind": "spend", "usd", "vendor", "project", "t"}` to
  `~/.local/state/agentforge/pools/<name>.jsonl` (`$XDG_STATE_HOME` or `$FORGE_POOL_DIR`
  override the directory) under an exclusive `flock`, so runs in every repo see each other.
- Before starting a pooled vendor forge sums each window. Once a window reaches its cap,
  every vendor in the pool counts as cooling until enough of the oldest runs age out, so
  `forge run --wait` sleeps instead of exiting.
- A plan-level limit message (`plan_limit_re`, default "Go usage limit") or any 429 / rate
  limit from a pooled vendor appends a `{"kind": "cooldown", "until"}` record: every vendor in
  the pool pauses until then, in every project.
- `forge limits --clear` for a pooled vendor appends a `clear` record, lifting the shared
  cooldown everywhere. Recorded spend is kept.
- Per-vendor `monthly_usd` windows still apply on top of the pool caps.

## Commands
- `forge limits`: one row per vendor: harness, family, `free` / `cooling until HH:MM (why)`,
  and allowance use per window for vendors with `monthly_usd`; then one row per shared pool
  with spend/cap per window, `free` or `cooling until HH:MM`, and the ledger path.
- `forge limits --clear [VENDOR ...]`: lift cooldowns early (for example after buying more
  usage). Recorded spend is kept.
- `forge status`: also prints a line per vendor that is cooling down.

## Getting the most out of several plans
- List every vendor you pay for in `workers`. When one pauses, the others take its cards.
- Give the vendors you trust most the review role (`review_pool`), since reviews use far fewer
  tokens than work and cheap gates run before every review.
- Use `forge run --wait` (or `forge up --wait`) for unattended runs, so a run that hits limits
  at 2 a.m. resumes by itself when the first vendor resets.
