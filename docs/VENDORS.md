# Vendors: claude, codex, glm, grok, and OpenCode models

A **vendor** is a coding model plus the CLI forge launches it with. A **harness** is the CLI.

| Vendor | Harness | Command | Login / key | Cost in `forge status` |
|---|---|---|---|---|
| `claude` | Claude Code | `claude -p ... --output-format stream-json` | `claude auth login` (claude.ai or API) | `total_usd`, counted toward `budget.max_total_usd` |
| `codex` | Codex CLI | `codex exec --json ... -` | `codex login` | not reported |
| `glm` | Claude Code | same as claude, with a private Z.ai environment | Z.ai API key (`ZAI_API_KEY`) | `glm_usd_nominal`, an Anthropic-price estimate, **not** a Z.ai charge and not counted in the budget |
| `grok` | Grok Build | `grok --prompt-file ... --output-format streaming-messages-json` | `grok login` (your own SuperGrok/X plan) or `XAI_API_KEY` | `grok_usd_reported` when xAI reports it (usually absent on subscription logins); not counted in the budget |
| any `[agents.<name>]` with `harness = "opencode"` | OpenCode | `opencode run --standalone --format json -m <provider/model> ...` inside bubblewrap | `opencode auth login` (OpenCode Go key, ChatGPT login, any provider OpenCode supports) | `vendor_usd.<name>` (OpenCode's API-price figure); not counted in the budget |

The built-in vendors live in `VENDORS`, `HARNESS` and `FAMILY` at the top of `bin/forge`;
OpenCode vendors come from `forge.toml` (`vendor_names()`).

## How vendors are chosen
- **Workers:** cards with `agent = "any"` round-robin over the free vendors in `[agents] workers`.
  When all of them are out, `[agents] fallback_workers` (if set) take over. A card can pin
  `agent = "claude" | "codex" | "glm" | "grok"` or any OpenCode vendor name.
- **Retry rotation (`swap_on_retry`):** from attempt 3, the card moves to a different vendor
  in `workers`, rotating in list order (attempt 3 to the first other vendor, attempt 4 to the
  next, ...).
- **Cross review (`reviewer = "cross"`):** never the author. It prefers a vendor from another
  model **family** on another harness (codex for claude/glm work, claude for an OpenCode Kimi
  vendor's work), then another family on the same harness, then the same family on another
  harness, then the legacy partner (codex, or claude for codex). Cooling-down vendors are
  skipped; with `self_review_fallback = true` the author reviews when no one else is free.
  Exact rules: `CONFIG.md`, `[agents]`.
- **Usage limits:** a limit pauses that vendor only; its card moves to the next free vendor.
  See [LIMITS](LIMITS.md).

Two-vendor configs (`workers = ["claude","codex"]`) behave exactly as before.

## GLM (Z.ai) via Claude Code
Z.ai serves GLM models through an Anthropic-compatible endpoint, and its docs officially
support Claude Code (docs.z.ai/devpack/tool/claude). forge doesn't need another CLI: a `glm`
run is the same `claude -p` command as a `claude` run, started with a different environment.

### What forge sets for each glm run
`glm_env()` copies forge's environment, drops credentials that would conflict
(`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK`,
`CLAUDE_CODE_USE_VERTEX`, `ANTHROPIC_SMALL_FAST_MODEL`, and the `ZAI_API_KEY` variable itself),
then sets:

| Variable | Default | From |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `https://api.z.ai/api/anthropic` | `agents.glm.base_url` |
| `ANTHROPIC_AUTH_TOKEN` | your Z.ai key | `agents.glm.key_env` / `key_file` |
| `ANTHROPIC_MODEL` | `glm-5.3` | `agents.glm.model` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | `glm-5.3` | `opus_model`, else `model` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | `glm-5.3` | `sonnet_model`, else `model` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `glm-5.3-flash` | `haiku_model` |
| `API_TIMEOUT_MS` | `3000000` | `api_timeout_ms` |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | fixed (Z.ai recommends it) |
| `CLAUDE_CONFIG_DIR` | `~/.config/agentforge/glm-claude` | `config_dir` |

What is never touched: your shell environment, `~/.claude`, `~/.claude.json`, your claude.ai
login, and the environment of `claude` vendor runs. Z.ai's own setup script edits
`~/.claude/settings.json` globally. **Don't run it**, because it would send your normal Claude
Code sessions (and forge's `claude` vendor) to Z.ai too.

**Why a separate `CLAUDE_CONFIG_DIR`:** `ANTHROPIC_AUTH_TOKEN` already takes precedence over a
saved claude.ai login, but when both exist Claude Code warns about an auth conflict, and the
two would share history, settings and caches. Separate config directories are Claude Code's
documented way to keep identities apart. The project's own `.claude/settings.json`
(allow/deny lists, hooks) still applies, because it lives in the repo, not in the config dir.

### The key
forge looks for the key in this order:
1. the process environment variable named by `agents.glm.key_env` (default `ZAI_API_KEY`);
2. that name in `agents.glm.key_file` (default `~/.config/agentforge/zai.env`), a
   `KEY=VALUE` file.

```bash
mkdir -p ~/.config/agentforge
printf 'ZAI_API_KEY=%s\n' 'PASTE_KEY_HERE' > ~/.config/agentforge/zai.env
chmod 600 ~/.config/agentforge/zai.env
```

forge never prints or logs the key. `forge doctor` reports only where it was found. If a CLI
ever echoes the key into a run log, `run_agent` replaces it with `[REDACTED]` before the log is
kept. If no key is found when a glm run starts, forge logs a `glm: SETUP PROBLEM (glm: Z.ai API
key not found ...)` line, disables glm for the rest of the process (other vendors keep
working), and doesn't charge the card an attempt.

### Usage limits
GLM Coding Plans have their own 5-hour and weekly caps. forge treats these like any other
vendor's usage limit (glm pauses until the reset, its card moves to another vendor, attempt
not charged; see [LIMITS](LIMITS.md)):
- `API Error: 429` in the failed run's output;
- a Z.ai business code in the error body: 1113 (no balance), 1302 (request rate), 1305
  (overloaded), 1308 (usage limit), 1309 (plan expired), 1310 (weekly/monthly limit), 1313
  (fair-use throttle), 1316-1321 (5-hour/7-day limits). Source: docs.z.ai/api-reference/api-code;
- a Claude Code `rate_limit_event` with `status: "rejected"`;
- Claude Code retrying the same request: Claude Code retries failed API calls itself (up to 10
  times with growing backoff, logged as `{"type":"system","subtype":"api_retry",
  "error_status":...}`). From the 3rd retry with status 429, forge kills the run and treats it
  as a usage limit. With 401/403 (bad or expired key) it kills the run, logs `API keeps
  returning 401/403`, and also stops without charging an attempt. Other statuses (e.g. 529
  overloaded) are left to Claude Code's own retries. This also applies to the claude vendor.

Codes such as 1211 (unknown model) or 1311 (model not in plan) are configuration errors. They
fail the attempt normally.

### Try it
1. Get a GLM Coding Plan and API key at z.ai and save the key as above.
2. `forge -C <project> doctor` should show `glm key: present`, `glm url: reachable` and
   `glm ping: ok`.
3. Add glm to the project's `forge.toml`, e.g. `workers = ["claude", "codex", "glm"]`, and
   optionally an `[agents.glm]` table (all keys optional; see `CONFIG.md`).
4. To trial it on a few cards only, pin them with `agent = "glm"` instead of adding it to
   `workers`. Cross review still sends their work to codex.
5. Compare `forge status` (`runs by vendor`), retries and review verdicts in
   `.forge/logs/*-review-*.json`.

### Privacy
Z.ai is run by Zhipu AI, a company based in China. With glm enabled, the prompts forge
builds, including task cards, diffs, file contents the agent reads, and gate output, are sent to
Z.ai's servers and fall under PRC jurisdiction and Z.ai's terms. Don't enable glm for code
you can't share with that provider. Pinning cards (`agent = "glm"`) limits what it sees, but any
file in the worktree can be read by the agent.

## Grok (xAI Grok Build CLI)
`grok` runs xAI's own coding CLI (Arch: AUR `grok-build-bin`, binary `/usr/bin/grok`) headless.
Use your own Grok plan or an API key in your name; a shared account breaks xAI's terms.

### Argv (`grok_cmd` in `bin/forge`)
- Always: `--prompt-file <log>.prompt.md` (the prompt forge already logs, so no argv size
  limit), `--cwd <worktree>`, `--no-alt-screen`, `--max-turns`, optional `-m`/`--reasoning-effort`.
- work: `--sandbox workspace --always-approve --output-format streaming-messages-json`, plus
  `--disable-web-search` unless `web_search = true`. Headless runs can't answer permission
  prompts, so tools are auto-approved; the workspace sandbox (bubblewrap) keeps writes inside
  the worktree, and the deny rules in the project's `.claude/settings.json` still apply.
- review/plan/audit: `--sandbox read-only --tools read_file,grep,list_dir --disable-web-search
  --no-subagents` and, with a schema, `--json-schema <schema>` (implies `--output-format json`).

### Output, cost and limits
`parse_grok_output` reads the last JSON line of the log: the `result` line of
streaming-messages-json, the single `--output-format json` object (`text`), or
`{"type":"error","message":...}`. Review/audit verdicts are taken from the text with the same
JSON extraction as codex. On a failed run or an error result, `detect_limit` treats
"not signed in"/401/403 as a setup problem (grok is disabled for the rest of the process) and
429/"rate limit"/"usage limit"/quota messages as a usage limit (grok cools down). Either way
the card is **not charged an attempt** and moves to another vendor, like claude and codex.
Grok's `total_cost_usd` is usually absent on subscription logins; when present it goes to
`grok_usd_reported`, never `total_usd`.

### Try it
1. `grok login` (browser) or `grok login --device-code`, then `grok models` should list models.
2. `forge -C <project> doctor` shows `grok auth: logged in`.
3. Trial on a few cards: pin them with `agent = "grok"` (needs the project's `schemas/plan.json`
   from this version, `forge upgrade`), or use it as a reviewer only with
   `review_pool = ["grok"]`. Full use: `workers = ["claude", "codex", "grok"]`. Cross review
   then sends grok's work to claude/codex and vice versa (different harness).
4. As a backup when codex is limited: `workers = ["claude", "grok"]`, `reviewer = "cross"`,
   `auditor = "claude"` or `"grok"`.

## OpenCode
OpenCode (`opencode`, npm `opencode-ai`) is a coding CLI that can drive many providers' models.
In forge it is a **harness type**: each `[agents.<name>]` table with `harness = "opencode"` is
one vendor, i.e. one model. That is how one OpenCode Go subscription becomes several workers
with separate allowances:

```toml
[agents]
workers = ["claude", "oc-kimi", "oc-glm", "oc-qwen"]
review_pool = ["claude", "grok"]     # frontier models review; cheap models work

[agents.oc-kimi]
harness = "opencode"
model = "opencode-go/kimi-k3"         # `opencode models` lists the exact ids
monthly_usd = 60                      # optional: per-model allowance (docs/LIMITS.md)

[agents.oc-glm]
harness = "opencode"
model = "opencode-go/glm-5.3"
monthly_usd = 120

[agents.oc-qwen]
harness = "opencode"
model = "opencode-go/qwen3.8-max"
extra_rw = ["~/.nuget", "~/.dotnet"]  # godot-csharp: let dotnet write its caches in the sandbox
```

The allowance figures above are an example (OpenCode Go Plus as of October 2026, from a
third-party summary); check opencode.ai for your plan. The model ids are illustrative too;
use what `opencode models` prints.

### Argv (`opencode_cmd` in `bin/forge`)
`opencode run --standalone --format json -m <model>[#<variant>] [--auto] [extra_args...] <prompt>`
- OpenCode 2.x has no `--dir` or `--variant`: the working directory is the process cwd
  (bubblewrap `--chdir` to the worktree), and `variant` rides on the model id as `#<variant>`.
- `--standalone` keeps the run in a private server. Without it OpenCode 2.x hands the run to
  its background service, which would execute tools outside the sandbox and the worktree.
- `--format json`: one JSON event per line (`text`, `tool_use`, `step_start`,
  `step_finish` with `cost` and `tokens`, `error` with `statusCode`). `parse_opencode_output`
  takes the final answer from the last message's text, sums cost and tokens, and collects errors.
  Token totals per vendor go to `vendor_tokens` in `state.json`.
- Workers get `--auto` (approve every tool call that isn't denied). Review/plan/audit don't.
- Prompts over 100 KB go in as an attached file (`--file <log>.prompt.md`), because Linux limits
  one argv string to 128 KiB.
- There is no structured-output flag, so for review/plan/audit forge appends the JSON schema to
  the prompt and parses the reply with the same JSON extraction as codex.
- There is no max-turns flag either: `timeout_min` is the cap.
- Don't use `--attach` in `extra_args`: OpenCode issue #38661 reports that `run --attach` can
  exit after the first tool step and drop the final answer.

### Permissions (`opencode_permissions`)
Passed as `OPENCODE_PERMISSION` (inline JSON). Review/plan/audit:
`{"edit": "deny", "bash": "deny", "webfetch": "deny"}`. Workers: edits allowed, shell
allowed except every `Bash(...)` deny rule from the project's `.claude/settings.json`
(`git commit*`, `git push*`, `curl *`, ...), web fetch only with `web_search = true`.
Exact pattern-precedence rules in OpenCode are **unverified**; the sandbox below is the real
boundary, and the gates still judge every diff.

### Sandbox (`sandbox_wrap`)
OpenCode has no OS-level sandbox, and with `--auto` it runs any command that isn't denied.
Worktrees live under the project's `.forge/`, so an unsandboxed agent could reach
`../../state.json` or the main checkout. forge therefore runs OpenCode in bubblewrap by
default (`sandbox = "bwrap"`, package `bubblewrap` on Arch and Fedora):
- `/` read-only; `/dev`, `/proc`, a fresh `/tmp`;
- the project's `.forge/` and `~/.config/agentforge` replaced by empty tmpfs (other tasks,
  logs, `state.json`, the Z.ai key file are invisible), the project's `.git` read-only;
- writable: the card's worktree (workers only; reviewers get it read-only), OpenCode's state
  dirs (`~/.local/share/opencode`, `~/.local/state/opencode`, `~/.cache/opencode`,
  `~/.config/opencode`) and anything in `extra_rw`;
- network on (the model API needs it).

If `bwrap` is missing, the vendor is disabled for the run with a `SETUP PROBLEM` line rather
than running unsandboxed. Build tools that write to your home directory (dotnet, cargo, pip)
need their cache dirs in `extra_rw`, or the build gate will report the error. Environment
variables are inherited as for the other vendors, so don't export secrets you don't want an
agent to see.

### Limits and logins
`detect_limit` reads OpenCode's `error` events: status 401/403 or wording such as
"unauthorized" means a login problem (vendor disabled for this run; run `opencode auth login`),
and status 429 or limit/quota wording means a usage limit (vendor cools down; see
[LIMITS](LIMITS.md)). Whether OpenCode retries 429s itself before printing the error, and how
long it waits, is **unverified**; `timeout_min` bounds it.

### Try it
1. Install OpenCode and bubblewrap; run `opencode auth login` and pick your provider
   (OpenCode Go: paste the key from the OpenCode console). `opencode models` should list the
   models.
2. Add one table, e.g. `[agents.oc-kimi]` above, and pin two or three cards to it with
   `agent = "oc-kimi"`. `forge -C <project> doctor` checks the binary, model, bubblewrap and
   saved credentials; `forge limits` shows the vendor's family and state.
3. Compare its gate failures, review verdicts and attempts with your other vendors before
   adding it to `workers`.

### Privacy
With an OpenCode vendor, prompts, diffs and every file the agent reads go to OpenCode's
gateway and the model provider behind it. Check each provider's data-retention terms (some
OpenCode Go models are served under time-limited zero-retention agreements) before you send
code you can't share.

## Codex
`codex exec --json -C <worktree> --sandbox workspace-write|read-only -o <out> [-m model]
[-c sandbox_workspace_write.network_access=true] [--output-schema schema] [extra_args...] -`,
with the prompt on stdin. Workers get `workspace-write`; review/plan/audit get `read-only`
(and `--output-schema`). `codex exec` has no turn limit, so `timeout_min` is the only cap.
Codex reports no cost, so `monthly_usd` and `max_total_usd` don't apply; use
`budget.max_agent_runs` and timeouts.

- `[agents.codex] network_access = true` lets workers reach the network inside Codex's
  sandbox (NuGet, pip, ...). Read-only roles stay offline.
- `[agents.codex] sandbox = "bwrap"` (opt-in) replaces Codex's own seccomp sandbox for
  **workers** with forge's bubblewrap sandbox: Codex runs with `--sandbox danger-full-access`
  inside bwrap, where `/` is read-only, the worktree and `~/.codex` are writable, and `.forge/`
  and `~/.config/agentforge` are hidden. Use it when Codex's sandbox kills tools it shouldn't
  (e.g. 32-bit or Win32 shims dying with SIGSYS). Review/plan/audit runs are unchanged.

## Claude overage guard
Claude subscriptions can spill into paid "extra usage". Claude Code's stream-json reports this
in `rate_limit_event.rate_limit_info.isUsingOverage` (forge also accepts `overageInUse`). With
`[agents.claude] allow_overage = false` (the default), `run_agent` checks the log every 2 seconds
and kills the run as soon as overage shows up, then handles it as a usage limit (claude
pauses until the reported reset; see [LIMITS](LIMITS.md)). The guard is
claude-only: glm and codex never set this field.

## Adding another vendor
More models through OpenCode need no code: add an `[agents.<name>]` table (see above).
A new **CLI** needs code:
1. Add the name to `VENDORS`, its CLI to `HARNESS` and its lab to `FAMILY` in `bin/forge`.
2. Add its argv in `build_cmd` (`role != "work"` must be read-only) and, if it needs a special
   environment, an equivalent of `glm_env` applied in `run_agent`.
3. If its output isn't Claude Code stream-json, make sure the final message lands in the
   `.out` file (`-o`-style), or parse it in `run_agent`.
4. Teach `detect_limit` its limit messages, and `run_agent`'s spend block whether its cost
   counts toward `total_usd`.
5. Add `[agents.<name>]` keys to `CONFIG.md` (tests/check_docs.py enforces this), the
   `--agent` text in `CLI.md`, the `agent` enums in `schemas/plan.json` and
   `schemas/audit.json`, and mock cases in `tests/`.
