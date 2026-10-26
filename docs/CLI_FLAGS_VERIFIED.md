# Agent CLI flags used by forge

Checked on 2026-10-13 against code.claude.com/docs (CLI reference) and
developers.openai.com/codex/cli/reference (OpenCode: 2026-10-19, section below). Neither CLI was run with real auth on the build
machine. Flags were checked against the docs, not executed.

## Claude Code (`build_cmd`, vendor `claude`)
| Flag | Use |
|---|---|
| `-p PROMPT` | Headless print mode. |
| `--output-format stream-json --verbose` | Event stream to the log. The last `result` event carries `result`, `total_cost_usd`, and `structured_output`. |
| `--max-turns N` | Turn cap (print mode). |
| `--no-session-persistence` | Don't save sessions (print mode). |
| `--max-budget-usd X` | Per-run spend cap (print mode). |
| `--model M` | Model alias or ID. |
| `--permission-mode acceptEdits` | Workers. Bash is limited by settings allow/deny. |
| `--tools Read,Grep,Glob` | Reviewer, planner, and auditor are read-only. |
| `--json-schema '<schema>'` | Validated structured output (print mode). |
Also used: `CLAUDE.md` with `@AGENTS.md` import, `.claude/settings.json` `permissions.allow/deny`,
`hooks.PreToolUse` command hooks (exit 2 = block), `.claude/agents/*.md` subagents,
`claude auth status` (exit 0 = logged in).
**Unverified:** that `structured_output` is the field name in the stream-json `result` event.
forge falls back to parsing JSON out of `result` if it isn't.

## Codex (`build_cmd`, vendor `codex`)
| Flag | Use |
|---|---|
| `codex exec ... -` | Non-interactive. The prompt is read from stdin. |
| `--json` | JSONL events to the log. |
| `-C DIR` | Workspace root, i.e. the worktree. |
| `--sandbox workspace-write` / `read-only` | Workers vs reviewer, planner, and auditor. |
| `-o FILE` | Final message to a file. |
| `--output-schema FILE` | Structured final response. |
| `-m MODEL` | Model. |
`codex exec` has no max-turns flag, so the wall-clock `timeout_min` is the cap. `codex login status`
exits 0 when logged in. **Unverified:** that the project-level `.codex/config.toml` is honored
(the docs say this happens only for trusted projects). forge passes sandbox flags explicitly,
so it doesn't depend on that file.

## Codex sandbox network (checked 2026-10-13)
- `-c key=value` overrides any `config.toml` key for one `codex exec` run.
- `sandbox_workspace_write.network_access` (boolean): "Allow outbound network access inside the
  workspace-write sandbox" (developers.openai.com/codex/config-reference). Off by default.
  forge passes `-c sandbox_workspace_write.network_access=true` to **worker** runs when
  `[agents.codex] network_access = true`; read-only review/plan/audit runs never get it.
- Not verified by a live authenticated run here; verified against the official reference only.

## GLM via Claude Code (`build_cmd` + `glm_env`, vendor `glm`)
Same argv as the claude vendor minus `--model` and `--max-budget-usd`. Environment, from Z.ai's
Claude Code guide (docs.z.ai/devpack/tool/claude, read 2026-10-14):

| Variable | Value | Source |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `https://api.z.ai/api/anthropic` | Z.ai guide |
| `ANTHROPIC_AUTH_TOKEN` | Z.ai API key | Z.ai guide; Claude Code sends it as `Authorization: Bearer` and it takes precedence over a saved claude.ai login (code.claude.com/docs/en/llm-gateway-connect) |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_MODEL` / `_HAIKU_MODEL` | `glm-5.3` / `glm-5.3` / `glm-5.3-flash` | Z.ai guide (its manual example uses the `[1m]` suffix variants) |
| `ANTHROPIC_MODEL` | `glm-5.3` | Claude Code model-selection variable; not in the Z.ai guide |
| `API_TIMEOUT_MS` | `3000000` | Z.ai guide |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | Z.ai guide |
| `CLAUDE_CONFIG_DIR` | `~/.config/agentforge/glm-claude` | Claude Code auth docs: each config dir has its own settings, history and login. Used so the gateway token never meets the claude.ai login (avoids the "auth conflict" warning) |

Z.ai error codes treated as usage limits come from docs.z.ai/api-reference/api-code.
**Unverified on a real account:** exact text Claude Code prints for a Z.ai 429 (forge matches
both `API Error: 429` and `"code":"13xx"`), and whether Z.ai's endpoint emits Claude Code
`rate_limit_event` lines at all.

## Claude overage fields
`rate_limit_event.rate_limit_info.isUsingOverage` was seen in real Claude Code logs
(2026-10-14). `overageInUse` is also accepted in case of renames. **Unverified:** how quickly
the event appears after the switch to overage in a long run (forge polls every 2 s).

## OpenCode (`opencode_cmd`, vendors with `harness = "opencode"`)
Checked on 2026-10-19 against opencode.ai/en/docs/cli and a third-party event reference
(takopi.dev, "OpenCode run --format json Event Cheatsheet"). Not run with real auth here.

| Flag / variable | Use |
|---|---|
| `opencode run [message..]` | Non-interactive run with the prompt as the message. |
| `--standalone` | Run in a private server instead of OpenCode 2.x's background service (keeps tools inside the sandbox). |
| `--format json` | Raw JSON events, one per line. |
| `-m provider/model[#variant]` | Model; the `#variant` suffix carries the reasoning effort. OpenCode 2.x (checked on 2.1.2, 2026-10-21) dropped `--dir` and `--variant`; the working directory is the process cwd. |
| `--auto` | Approve permissions that aren't explicitly denied (workers only). |
| `--file FILE` | Attach the prompt file when the prompt is over 100 KB. |
| `OPENCODE_PERMISSION` | Inline JSON permission config (documented on the CLI page). |

Event shapes used by `parse_opencode_output`: `text` (`part.text`, `part.messageID`),
`step_finish` (`part.cost`, `part.tokens.{input,output,reasoning,cache.read,cache.write}`),
`error` (`error.name`, `error.data.message`, `error.data.statusCode`).
**Unverified:** that `OPENCODE_PERMISSION` accepts the `edit`/`bash`/`webfetch` keys with
pattern maps exactly like the config file, and the precedence of bash patterns; whether
`opencode run` without `--auto` denies or waits on an `ask` permission when nobody can answer
(forge's read-only roles deny everything, so they never ask); how OpenCode reports a provider
429 after its own retries; whether its per-step `cost` matches OpenCode Go's allowance
accounting.

## bubblewrap (`sandbox_wrap`)
`--ro-bind / /`, `--dev /dev`, `--proc /proc`, `--tmpfs PATH`, `--bind SRC DEST`,
`--chdir DIR`, `--die-with-parent`: standard bwrap options. Later mounts are layered over
earlier ones, which is how the worktree reappears inside the hidden `.forge/`. **Not executed
on the build machine** (no bwrap there); the argv is unit-tested.
