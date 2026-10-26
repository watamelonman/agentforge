# forge.toml reference

`forge.toml` lives in the project root. Agents can't change it: it's in `[policy] protected`
and in the Claude deny rules. Defaults below are the values `bin/forge` uses when a key is
**missing**. The preset files set many keys explicitly. `tests/check_docs.py` fails if code
reads a key that isn't listed here.

## [project]
| Key | Type | Default | Meaning |
|---|---|---|---|
| `project.name` | string | — | Informational. |
| `project.main_branch` | string | `"main"` | Integration branch. Worktrees branch from it and merges fast-forward into it. |
| `project.spec` | string | `"spec/SPEC.md"` | Spec path that the planner and auditor are told to read. |
| `project.strict_milestones` | bool | `true` | Only schedule cards from the lowest milestone that still has unfinished cards. |

## [engine]
| Key | Type | Default | Meaning |
|---|---|---|---|
| `engine.name` | string | — | Informational adapter name. |
| `engine.godot_bin` | string | `"godot"` (script) | Read by `tools/godot_check.sh`. Can contain spaces, e.g. `"flatpak run org.godotengine.Godot"`. |

## [agents]
| Key | Type | Default | Meaning |
|---|---|---|---|
| `agents.workers` | list of vendors: `"claude"`/`"codex"`/`"glm"`/`"grok"` or any `[agents.<name>]` OpenCode vendor | `["claude"]` | Round-robin pool for cards with `agent = "any"`. Also the default review pool and the rotation pool for `swap_on_retry`. |
| `agents.reviewer` | `"cross"`/`"none"`/a vendor | `"cross"` | `cross` picks a reviewer that is never the author vendor (see below). A vendor name always uses that vendor, even for its own work (while it cools down, cards wait for it). `none` disables review. |
| `agents.review_pool` | list of vendors | unset (= `workers`) | Vendors `cross` may choose from. Lets a vendor review without doing work, e.g. `workers = ["claude","codex"]` with `review_pool = ["glm"]`. |
| `agents.planner` | vendor | `"claude"` | Default for `forge plan`. |
| `agents.auditor` | vendor | `"codex"` | Default for `forge audit`. If empty, `run --audit` skips the audit. |
| `agents.fallback_workers` | list of vendors | `[]` | Workers used **only** when every vendor in `workers` is cooling down or disabled, for cards with `agent = "any"` (or an agent that is not a known vendor). Example: `workers = ["codex", "oc-kimi"]`, `fallback_workers = ["claude"]` lets Claude write only when the others are out. |
| `agents.self_review_fallback` | bool | `false` | With `reviewer = "cross"`: when every other reviewer candidate is cooling down, let the author's own vendor review rather than park the card. Off by default, because self-review is weaker. |
| `agents.swap_on_retry` | bool | `true` | From attempt 3 on, rotate to a different vendor in `workers` (if it has more than one): attempt 3 goes to the first other vendor in list order, attempt 4 to the next, and so on. With two vendors that is the old plain swap. |

How `reviewer = "cross"` chooses (`review_candidates()` and `cross_reviewer()` in `bin/forge`):

1. Take `review_pool` (or `workers`), drop the author vendor and unknown names.
2. Rank what is left by distance from the author, keeping list order inside each rank:
   1. other model **family** and other **harness** (CLI): codex reviews claude, claude reviews
      an OpenCode Kimi vendor;
   2. other family, same harness: glm reviews claude (both Claude Code), an OpenCode GLM
      vendor reviews an OpenCode Kimi vendor;
   3. same family, other harness: an OpenCode GLM vendor reviews `glm`;
   4. same family, same harness.
3. If the pool has nothing but the author, fall back to the legacy partner: codex for every
   vendor except codex, claude for codex. This keeps old configs such as `workers = ["claude"]`
   working exactly as before.
4. Take the first candidate that is not cooling down (see [LIMITS](LIMITS.md)). If all of them
   are, and `self_review_fallback = true` and the author is free, the author reviews its own
   work. Otherwise the card waits for review; the worker isn't run again.

Families: claude `anthropic`, codex `openai`, glm `zhipu`, grok `xai`; OpenCode vendors use
their `family` key or a guess from the model id (kimi `moonshot`, glm `zhipu`, deepseek
`deepseek`, qwen `alibaba`, gpt `openai`, claude/haiku/sonnet/opus `anthropic`, grok `xai`,
mimo `xiaomi`, gemini `google`, minimax `minimax`). `forge limits` shows what each vendor got.
For configs made only of the built-in vendors this ranking picks exactly what the old
harness-only rule picked.

The author is never its own reviewer under `cross`. The author is the vendor named in the
branch's newest `"<ID>: attempt N by <vendor>"` commit.

## Keys every vendor table accepts
Any `[agents.<vendor>]` table (built-in or OpenCode) may also set these.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `agents.<name>.family` | string | built-in table / guessed from `model` | Model family used by cross review. Set it when the guess is wrong or the model id is unusual. |
| `agents.<name>.cooldown_min` | float | `budget.limit_cooldown_min` | How long this vendor pauses after a usage limit whose message names no reset time. |
| `agents.<name>.monthly_usd` | float | unset (off) | Monthly allowance in USD at API prices, e.g. an OpenCode Go model's limit. forge then keeps this vendor's reported spend under 20% of it per 5 hours, 50% per 7 days and 100% per 30 days (times `allowance_margin`), pausing the vendor before the provider refuses it. Needs a CLI that reports cost (OpenCode does; Codex doesn't). |
| `agents.<name>.allowance_margin` | float | `0.9` | Share of each allowance window forge lets itself use, to absorb runs that overshoot after they start. |
| `agents.<name>.pool` | string | unset | Name of a shared plan this vendor draws from, e.g. `"opencode-go"`. Every run's reported cost goes into the machine-wide ledger for that pool, and the `[pools.<name>]` caps and plan-level cooldowns then apply to every vendor in the pool, in every project. See [LIMITS](LIMITS.md#shared-pools-pool). |

## [agents.<name>] with harness = "opencode"
Any table with `harness = "opencode"` adds one vendor named after the table, driven by
`opencode run`. Add as many as you like (one per model), then use the names in `workers`,
`review_pool`, `planner`, `auditor`, `reviewer` or a card's `agent`. Setup and caveats:
[VENDORS](VENDORS.md#opencode).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `agents.<name>.harness` | string | — | Must be `"opencode"`. Tables without a known harness are ignored. |
| `agents.<name>.model` | string | required | `provider/model` as OpenCode names it, e.g. `"opencode-go/kimi-k3"` (`opencode models` lists them). |
| `agents.<name>.variant` | string | unset | Provider-specific reasoning effort, e.g. `"high"`. OpenCode 2.x has no `--variant` flag, so forge passes it as `-m <model>#<variant>`. |
| `agents.<name>.bin` | string | `"opencode"` | Executable. |
| `agents.<name>.timeout_min` | int | `45` | Wall-clock cap; `opencode run` has no turn limit, so this is the only one. |
| `agents.<name>.web_search` | bool | `false` | Workers may use web fetch. Review/plan/audit never can. |
| `agents.<name>.sandbox` | string | `"bwrap"` | `"bwrap"` runs OpenCode in bubblewrap: filesystem read-only except the worktree (workers only) and OpenCode's own state dirs, with `.forge/` and `~/.config/agentforge` hidden. `"none"` runs it bare; OpenCode has no sandbox of its own, so don't. |
| `agents.<name>.bwrap` | string | `"bwrap"` | bubblewrap executable. |
| `agents.<name>.extra_rw` | list | `[]` | More paths writable inside the sandbox, e.g. `["~/.nuget", "~/.dotnet"]` for .NET builds, `["~/.cache/pip"]`. |
| `agents.<name>.hide` | list | `[]` | More paths hidden (empty tmpfs) inside the sandbox. |
| `agents.<name>.extra_args` | list | `[]` | Appended to `opencode run` verbatim, before the prompt. |
| `agents.<name>.max_turns`, `review_max_turns` | — | — | Ignored: `opencode run` has no turn limit. |


## [agents.claude]
| Key | Type | Default | Meaning |
|---|---|---|---|
| `agents.claude.bin` | string | `"claude"` | Executable. |
| `agents.claude.model` | string | `""` (CLI default) | Passed as `--model`. |
| `agents.claude.max_turns` | int | `60` | `--max-turns` for workers. |
| `agents.claude.review_max_turns` | int | `30` | `--max-turns` for review, plan, and audit. |
| `agents.claude.max_budget_usd` | float | unset | `--max-budget-usd` per run. Only applies to API billing estimates. |
| `agents.claude.permission_mode` | string | `"acceptEdits"` | Worker `--permission-mode`. Bash is still limited by `.claude/settings.json`. |
| `agents.claude.timeout_min` | int | `45` | Wall-clock cap. The process group is killed when it runs out. |
| `agents.claude.extra_args` | list | `[]` | Appended verbatim. |
| `agents.claude.allow_overage` | bool | `false` | Claude Code's stream-json reports `rate_limit_info.isUsingOverage` (or `overageInUse`) when a subscription spills into paid extra usage. With `false`, forge kills that run within about 2 seconds of the event, logs `USAGE LIMIT hit (paid overage ...)`, pauses claude until the reported reset and hands the card to another vendor without charging an attempt (see [LIMITS](LIMITS.md)). The stopped run's work is committed as partial work for the next worker. Set `true` only if you accept paid overage. |

## [agents.codex]
| Key | Type | Default | Meaning |
|---|---|---|---|
| `agents.codex.bin` | string | `"codex"` | Executable. |
| `agents.codex.model` | string | `""` | Passed as `-m`. |
| `agents.codex.timeout_min` | int | `45` | The only turn cap for Codex: `codex exec` has no max-turns flag. |
| `agents.codex.extra_args` | list | `[]` | E.g. `["-c", "model_reasoning_effort=\"high\""]`. |
| `agents.codex.sandbox` | string | unset (Codex's own sandbox) | `"bwrap"` (opt-in): worker runs use `--sandbox danger-full-access` **inside** forge's bubblewrap sandbox instead of Codex's own seccomp sandbox (which kills some 32-bit/Win32 shims with SIGSYS). The filesystem is read-only except the worktree and `~/.codex`; `.forge/` and `~/.config/agentforge` are hidden. Review/plan/audit stay `--sandbox read-only`. If `bwrap` is missing, codex is disabled for the run. |
| `agents.codex.bwrap`, `agents.codex.extra_rw`, `agents.codex.hide` | | | Same meaning as for OpenCode vendors; only used with `sandbox = "bwrap"`. |
| `agents.codex.network_access` | bool | `false` (`true` in godot-csharp) | Workers get `-c sandbox_workspace_write.network_access=true`, the official Codex config key for outbound network inside the `workspace-write` sandbox (needed for NuGet). Review/plan/audit runs stay `read-only` and offline. |

## [agents.glm]
GLM (Z.ai) runs through the Claude Code CLI with a private environment. Full guide: `docs/VENDORS.md`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `agents.glm.bin` | string | `"claude"` | Claude Code executable. The argv is the same as the claude vendor's (`-p`, `--output-format stream-json`, `--max-turns`, read-only `--tools Read,Grep,Glob` for review/plan/audit, `--permission-mode` for work), except that `--model` and `--max-budget-usd` are never passed. |
| `agents.glm.model` | string | `"glm-5.3"` | Exported as `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` and `ANTHROPIC_DEFAULT_SONNET_MODEL`. Z.ai's manual config uses `"glm-5.3[1m]"` for the 1M-context variant. |
| `agents.glm.opus_model` | string | = `model` | Override for `ANTHROPIC_DEFAULT_OPUS_MODEL`. |
| `agents.glm.sonnet_model` | string | = `model` | Override for `ANTHROPIC_DEFAULT_SONNET_MODEL`. |
| `agents.glm.haiku_model` | string | `"glm-5.3-flash"` | `ANTHROPIC_DEFAULT_HAIKU_MODEL`, which Claude Code uses for small background tasks. |
| `agents.glm.base_url` | string | `"https://api.z.ai/api/anthropic"` | `ANTHROPIC_BASE_URL`, Z.ai's Anthropic-compatible endpoint. |
| `agents.glm.key_env` | string | `"ZAI_API_KEY"` | Name of the variable holding the key. Looked up in the process environment first, then in `key_file`. The key is passed to Claude Code only as `ANTHROPIC_AUTH_TOKEN` and is never printed or logged. The variable itself is removed from the child's environment. |
| `agents.glm.key_file` | string | `"~/.config/agentforge/zai.env"` | `KEY=VALUE` file (comments, `export ` and quotes allowed). Should be `chmod 600`, and `forge doctor` warns if it isn't. |
| `agents.glm.config_dir` | string | `"~/.config/agentforge/glm-claude"` | `CLAUDE_CONFIG_DIR` for glm runs, created with mode 700. It keeps glm sessions away from `~/.claude` and your claude.ai login. |
| `agents.glm.api_timeout_ms` | int | `3000000` | `API_TIMEOUT_MS`, the value Z.ai's docs recommend. |
| `agents.glm.max_turns` | int | `60` | `--max-turns` for workers. |
| `agents.glm.review_max_turns` | int | `30` | `--max-turns` for review, plan and audit. |
| `agents.glm.permission_mode` | string | `"acceptEdits"` | Worker `--permission-mode`. Bash is still limited by the project's `.claude/settings.json`, which applies to glm too. |
| `agents.glm.timeout_min` | int | `45` | Wall-clock cap. |
| `agents.glm.extra_args` | list | `[]` | Appended verbatim. |

## [agents.grok]
xAI's Grok Build CLI (`grok`, AUR `grok-build-bin`), run headless. Opt-in: nothing uses it until
`"grok"` appears in `workers`, `review_pool`, `reviewer`, `planner` or `auditor`, or a card pins
`agent = "grok"`. Harness `grok-build`, so cross review treats it as a different CLI from both
Claude Code and Codex. See `VENDORS.md`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `agents.grok` | table | `{}` | All keys optional. |
| `agents.grok.bin` | string | `"grok"` | Grok Build executable. |
| `agents.grok.model` | string | unset (CLI default, `grok-4.6` today) | `-m`. `grok models` lists what your login can use. |
| `agents.grok.reasoning_effort` | string | unset | `--reasoning-effort`. |
| `agents.grok.max_turns` | int | `60` | `--max-turns` for workers. |
| `agents.grok.review_max_turns` | int | `30` | `--max-turns` for review, plan and audit. |
| `agents.grok.sandbox` | string | `"workspace"` | Worker `--sandbox` profile: writes only inside the card's worktree (plus temp and `~/.grok`). `"off"` disables Grok's sandbox; don't, unless bubblewrap is broken. |
| `agents.grok.review_sandbox` | string | `"read-only"` | `--sandbox` for review, plan and audit. |
| `agents.grok.review_tools` | string | `"read_file,grep,list_dir"` | `--tools` allowlist for review, plan and audit. |
| `agents.grok.web_search` | bool | `false` | Workers get `--disable-web-search` unless true. Review/plan/audit never search. |
| `agents.grok.timeout_min` | int | `45` | Wall-clock cap. |
| `agents.grok.extra_args` | list | `[]` | Appended verbatim. |

## [pools.<name>]
One table per shared plan named by some vendor's `pool`. Caps are in USD at API prices (what
OpenCode reports per run) over rolling windows, summed across every vendor and every project
on this machine that names the pool. A cap of `0` or unset is off.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `pools.<name>.usd_5h` | float | unset (off) | Spend allowed in any 5 hours. |
| `pools.<name>.usd_7d` | float | unset (off) | Spend allowed in any 7 days. |
| `pools.<name>.usd_30d` | float | unset (off) | Spend allowed in any 30 days. |
| `pools.<name>.plan_limit_re` | string (regex) | `Go usage limit` / `plan-wide limit` | Limit wording that means the whole plan is out. Such a message, or any 429 / rate limit from a pooled vendor, pauses every vendor in the pool in every project. |

Projects sharing a pool should use the same caps; each project enforces its own `[pools]` table
against the shared ledger.

## [setup]
| Key | Type | Default | Meaning |
|---|---|---|---|
| `setup.restore` | string | `""` (off) | Shell command run in each task worktree before the first worker starts (and before `forge regate`), outside any agent sandbox. godot-csharp: `dotnet restore` for both projects, so builds work even if the agent sandbox is offline. A failure is logged to `events.log` but doesn't stop the task. |
| `setup.timeout_sec` | int | `600` | Timeout for `setup.restore`. |

## [budget]
| Key | Type | Default | Meaning |
|---|---|---|---|
| `budget.max_attempts` | int | `3` | Worker attempts per task. Every gate, review, or conflict loop uses one. |
| `budget.max_total_usd` | float | `0` (off) | Cap on the estimated **Claude** spend (`total_usd` in `state.json`, cumulative across runs). When it is reached, only the `claude` vendor is refused: it sits out the rest of the run (logged as `claude budget $N exhausted; claude disabled`), no attempt is charged, and its cards move to other vendors. The run itself keeps going. Codex spend isn't reported, so it isn't counted. glm and grok runs are **not** counted either (grok's own `total_cost_usd`, when xAI sends one, is kept as `grok_usd_reported`): Claude Code's `total_cost_usd` for them is an estimate at Anthropic prices, which means nothing on a Z.ai plan. It is kept separately in `state.json` as `glm_usd_nominal` and shown by `forge status`, labelled as nominal. |
| `budget.max_agent_runs` | int | `0` (off) | Cap on the total number of agent invocations (`agent_runs` in `state.json`, cumulative across runs). When it is reached, the whole run stops (`global run cap N reached`): no new agents start and in-flight cards go back to `todo`. Raise it in `forge.toml` and rerun to continue. |
| `budget.limit_cooldown_min` | float | `60` | How long a vendor pauses after a usage limit when the CLI's message gives no reset time (per-vendor override: `cooldown_min`). See [LIMITS](LIMITS.md). |
| `budget.max_gate_output_lines` | int | `80` | Tail length of failing command output fed back to the worker. |
| `budget.max_review_diff_chars` | int | `60000` | The diff in the reviewer prompt is cut off after this many characters. |

## [context]
Controls the **context pack**: the spec sections and decisions forge extracts for each card and
puts into the worker and reviewer prompts, so agents don't open `spec/SPEC.md` and
`docs/DECISIONS.md` whole. See [CONTEXT_PACK](CONTEXT_PACK.md) for what is selected and why
the defaults are small. The whole table is optional; leaving it out uses these defaults.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `context.enabled` | bool | `true` | `false` turns the pack off; prompts are then exactly as before (the `{{CONTEXT}}` placeholder renders empty). |
| `context.always_spec` | list of strings | `[]` | Spec section numbers included on every card, as written in the heading (e.g. `["2"]` for `## 2. Non-negotiable architecture`, `["9.2"]`). Each one costs its size on every turn of every run, so add only short, always-relevant sections. |
| `context.decisions` | string | `"docs/DECISIONS.md"` | Decision log to pull entries from. Entries are `## DEC-<id> — title` headings. |
| `context.decision_index` | bool | `false` | Also include a one-line-per-entry index of every decision title. Off by default: on a large project it was about 3.5 KB on every turn. |
| `context.gate_commands` | bool | `true` | Put the `[gates.cmd]` commands into worker prompts so workers run the exact, quiet gate commands without opening `forge.toml`. |
| `context.max_chars` | int | `16000` | Hard cap on the pack; anything past it is cut with a visible `[... truncated ...]` marker telling the agent to grep the source files. |

## [gates]
| Key | Type | Default | Meaning |
|---|---|---|---|
| `gates.order` | list | `["policy","layers"]` | Gates run in this order and stop at the first failure. `policy` and `layers` are built in. Any other name must be a key of `gates.cmd`, and names without one are skipped. |
| `gates.timeout_sec` | int | `900` | Per-command timeout. |
| `gates.cmd.<name>` | string | — | Shell command run in the worktree. Exit code 0 means pass. `FORGE_BASE` is set. |

## [layers]
| Key | Type | Default | Meaning |
|---|---|---|---|
| `layers.root` | string | `"src"` | The folder whose first-level subfolders are layers (`"."` means repo top level). |
| `layers.allow.<layer>` | list | — | Layers this layer may reference. Only listed layers are checked. |
| `layers.forbid_headers.<layer>` | list | `{}` | C/C++ header basenames this layer may not `#include`. |
| `layers.forbid_patterns.<layer>` | list of regex | `{}` | Code lines in this layer that may not match. Comment lines are ignored. |

References are detected from `#include "x/..."` (C/C++), `import`/`from` (Python), and
`res://<root>/<layer>/` (GDScript). For C#/Lua, use `forbid_patterns` (e.g. `using\s+Godot`).

## [policy]
| Key | Type | Default | Meaning |
|---|---|---|---|
| `policy.test_globs` | list | `["tests/**"]` | What counts as a test file. |
| `policy.source_globs` | list | `["src/**"]` | Production code: hollow/cheat patterns and size limits apply here. |
| `policy.protected` | list | `[]` | Workers may never change these. |
| `policy.always_allowed` | list | `["docs/**","CHANGELOG.md"]` | Allowed outside a card's `owns`. |
| `policy.scene_globs` | list | `[]` | Engine scene/resource files, with scene rules applied (see GATES.md). |
| `policy.max_scene_diff_lines` | int | `40` | Per-file cap on scene diffs when the card has `scene_edits=true`. |
| `policy.forbid_added` | list of regex | `[]` | Added source lines must not match (e.g. `TODO`, `NotImplementedException`). |
| `policy.skip_markers` | list of regex | `[]` | Added test lines must not match. |
| `policy.test_detection` | list of regex | `[]` | Production code must not detect test mode. |
| `policy.assert_regex` | regex | `\bassert\|EXPECT_\|ASSERT_\|CHECK\(` | What counts as an assertion. |
| `policy.max_file_lines` | int | `600` | Max lines per changed source/test file. |
| `policy.max_diff_lines` | int | `1500` | Max lines added per task. |
| `policy.doc_check` | bool | `true` | Doc-comment check for `.h/.hpp` prototypes, Python public defs, and GDScript public funcs (`##`). |
| `policy.gd_strict_typing` | bool | `true` | Static-typing check for changed `.gd` files outside tests. |

Globs use Python `fnmatch`, so `*` also matches `/`. `dir/**` matches everything under `dir`. A pattern containing `**/` is also tried with `**/` removed.
