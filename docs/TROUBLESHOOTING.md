# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `main checkout has uncommitted changes` | Commit or stash. Only tracked files count, and a pending edit to `docs/SPEC_ISSUES.md` (rewritten by `forge plan`) is ignored. The error lists the offending files. |
| Task `blocked` after "identical failure twice" | The worker can't fix it as specified. Read `jq '.tasks["ID"].history[-2:]' .forge/state.json`, fix the card, spec, or environment, then `forge reset ID` (add `--hard` to start fresh). |
| Branch work looks right but the gate that failed it was wrong or has been fixed | `forge regate ID` judges the existing `forge/ID` branch (gates, review, merge) without a worker run. Add `--continue` to let workers retry if it still fails. |
| `TAMPER: test file deleted` for the preset sample (`DiceTests.cs`) in a project made before `.forge-samples` existed | `forge upgrade --preset godot-csharp`, commit `.forge-samples`, then `forge regate ID`. A card with `may_edit_tests = true` is also allowed to delete tests, as long as the net assertion count doesn't drop. |
| NuGet restore fails in Codex (`api.nuget.org`, `SocketException (13)`) | The Codex `workspace-write` sandbox has no network by default. Set `[agents.codex] network_access = true` (default in godot-csharp) and/or `[setup] restore = "dotnet restore ..."` so forge restores packages before the worker starts. |
| `events.log` only shows that a gate failed | `events.log` shows the first 25 lines of the report. The full report is in `jq '.tasks["ID"].history[-1]' .forge/state.json`. |
| `ff merge failed` | Someone committed to `main` during the run. `forge reset ID` and run again. |
| `SCOPE` failures on generated files | Add build outputs to `.gitignore` (e.g. `__pycache__/`, `.godot/`, `bin/`, `obj/`, `reports/` are already in it). |
| `SCOPE` on a file the task really needs | The card's `owns` is too narrow. Edit the card and `forge reset ID`. |
| Claude does nothing, or `Bash ... denied` in the log | The command isn't in `.claude/settings.json` `permissions.allow`. Add it if it's safe. |
| Codex can't write the build cache | The `workspace-write` sandbox only writes inside the worktree. Point caches inside it, or add `--add-dir` through `extra_args`. |
| `addons/gdUnit4 missing` | Run `tools/setup_addons.sh` once, open the editor, and commit `addons/`. |
| Godot gate: `Class "X" hides a global script class` | Wrong addon folder casing. It must be `addons/gdUnit4`. |
| GdUnit4 CLI runs fewer tests than the editor | A known upstream issue (gdUnit4 #1174). Keep suites small and check the totals in the log. |
| Planner output invalid | Look at `.forge/logs/plan-plan-*.log`. Try `--agent codex` (strict schema) or a smaller `--milestone`. |
| tmux session exists | `tmux attach -t forge-<name>`, or `tmux kill-session -t forge-<name>`. |
| `claude auth: NOT logged in` | Run `claude auth login` (or start `claude` interactively and use `/login`). |
| Spend shows $0 with Codex | That's expected: Codex reports no cost. Use `max_agent_runs` and timeouts. |

## Vendor usage limits
When a worker or reviewer run fails and its output mentions a usage/rate limit (for example
Codex's "You've hit your usage limit ... try again at <time>"), forge logs
`<ID>: <vendor> USAGE LIMIT hit`, puts **only that vendor** in a cooldown until the reset time
(or `cooldown_min` / `budget.limit_cooldown_min` when no time is given), does **not** charge the
attempt, and hands the card to the next free vendor. The rest of the run keeps going. When
every remaining card needs a vendor that is cooling down, `forge run` exits and says when the
next vendor is free; `forge run --wait` sleeps until then instead. Nothing needs `forge reset`.
Full rules: [LIMITS](LIMITS.md).

The same handling covers (see `detect_limit` in `agentforge/detect.py`):
- Claude Code's stream-json `rate_limit_event` with `status: "rejected"` (claude and glm);
- glm: `API Error: 429` or a Z.ai limit code in the error body (1113, 1302, 1305, 1308, 1309,
  1310, 1313, 1316-1321). The log line reads `USAGE LIMIT hit (Z.ai quota/rate limit ...)`;
- claude/glm: Claude Code's own `api_retry` events reaching the 3rd retry with HTTP 429
  (limit) or 401/403 (bad key/login; logged as `API keeps returning 401/403`);
- claude: paid overage (`isUsingOverage`/`overageInUse` true) unless `[agents.claude]
  allow_overage = true`. The run is killed as soon as the event appears, logged as
  `USAGE LIMIT hit (paid overage in use ...)`, and its partial work is committed;
- grok and OpenCode limit / 429 messages.

Login and key problems (401/403, "not signed in", a missing Z.ai key, a missing `bwrap`, an
OpenCode vendor without `model`) are logged as `<vendor>: SETUP PROBLEM (...)`. That vendor is
not used again by the current process; fix the problem and rerun.

| Symptom | Fix |
|---|---|
| A vendor stays `cooling until ...` after you bought more usage, or the guessed reset was wrong | Stop the run, `forge limits --clear <vendor>`, start it again. A running `forge run` keeps its in-memory cooldowns (see [LIMITS](LIMITS.md#a-cooldown-that-is-wrong-or-stale)). |
| `claude budget $N exhausted; claude disabled` | `budget.max_total_usd` reached (cumulative). Raise it in `forge.toml` and rerun, or let the other vendors finish. |
| `global run cap N reached` | `budget.max_agent_runs` reached (cumulative). Raise it in `forge.toml` and rerun. |
| glm runs fail with 401 / code 1000-1003 | Wrong or expired key. Check with `forge doctor`; rewrite `~/.config/agentforge/zai.env`. |
| glm fails with code 1211 / 1311 | Model name unknown or not in your plan: set `[agents.glm] model` (e.g. `"glm-5.3"`). These are not treated as usage limits. |
