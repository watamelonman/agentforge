# Reviewer, auditor, budgets, and logging

## Reviewer (per task, after gates pass)
- Vendor: `[agents] reviewer`. With `cross`, the reviewer is chosen from `review_pool` (default
  `workers`), never the author, preferring another model family on another harness (e.g.
  Codex reviews Claude's and GLM's work). With `self_review_fallback = true` the author may
  review its own work when every other candidate is cooling down. Rules in `CONFIG.md`.
- Read-only. Claude and GLM get `--tools Read,Grep,Glob` plus `--json-schema`; Codex runs in
  `--sandbox read-only` with `--output-schema`; Grok gets `--sandbox read-only` and a read-only
  tool list; OpenCode runs with edit/bash/webfetch denied and the schema appended to the prompt.
- Its input is `prompts/reviewer.md` with the card, the gate summary, and the diff (cut off at
  `max_review_diff_chars`).
- It rejects unmet acceptance criteria, weak or mirrored tests, hardcoded or special-cased
  outputs, hollow logic, architecture violations, messy code, and scope creep. Nits don't
  block.
- Anything other than `verdict: "PASS"` sends the formatted `issues` back to the worker as
  feedback and uses up one attempt. Every verdict is saved to
  `.forge/logs/<ID>-review-<attempt>.json`.

## Auditor (whole repo, on demand or with `run --audit`)
- Vendor: `[agents] auditor`. It's read-only and uses `prompts/auditor.md` and `schemas/audit.json`.
- It looks for cross-module duplication, architecture drift, stale docs, dead code, coverage
  gaps, spec requirements of finished milestones that are silently missing, and gate gaming.
- Its report goes to `.forge/audit-<ts>.md`. Proposed `FIX-*` cards are written to `tasks/`.
  Review them, then commit them and run.

## Budgets
| Limit | Where | Effect |
|---|---|---|
| Turns | `agents.<claude\|glm>.max_turns` / `review_max_turns` | `claude --max-turns`. |
| Per-run spend | `agents.claude.max_budget_usd` | `claude --max-budget-usd` (claude vendor only; never passed to glm). |
| Paid overage | `agents.claude.allow_overage` | `false`: a claude run that starts using overage is killed and treated as a usage limit. |
| Wall clock | `agents.<vendor>.timeout_min` | Kills the process group: SIGTERM, then SIGKILL after 3 s. |
| Attempts | `budget.max_attempts` | Then `blocked`. |
| Repeated failure | built in | An identical gate report twice blocks the task. |
| Claude spend | `budget.max_total_usd` | Once the cumulative Claude estimate reaches it, `claude` is disabled for the rest of the run; other vendors continue. |
| Global runs | `budget.max_agent_runs` | Sets the stop flag: no new agents start, in-flight cards return to `todo`, and the run ends. |
| Context size | `max_gate_output_lines`, `max_review_diff_chars`, `[context]`, AGENTS.md section 6 | Keeps prompts small. `[context]` hands each run only the spec sections and decisions its card cites (see CONTEXT_PACK.md). |

Spend is the Claude CLI's own client-side estimate (`total_cost_usd`). On a subscription it's
only indicative. Codex reports no cost, so control Codex with the run cap and timeouts.

## Logging
Every agent invocation leaves a `.prompt.md`, a raw `.log`, and (for Codex) an `.out` file in
`.forge/logs/`, plus one line per step in `events.log`. Task history (gate reports, review
issues, conflicts, resets) lives in `.forge/state.json`:
```
jq '.tasks["M1-T003"].history' .forge/state.json
```
