# Task cards and output schemas

## Card file: `tasks/<ID>-<slug>.md`
TOML front matter between `+++` lines, then a Markdown body. Workers get the whole file
verbatim.
```markdown
+++
id = "M1-T003"
title = "Seeded dice roller"
milestone = 1
deps = ["M1-T001"]
agent = "any"
owns = ["src/sim/dice.gd", "test/sim/test_dice.gd"]
docs = ["CHANGELOG.md"]
tests_required = true
may_edit_tests = false
scene_edits = false
+++
## Goal
...
## Acceptance criteria
- [ ] Same seed gives the same 20-roll sequence (test).
## Notes
```
| Field | Type | Default | Meaning |
|---|---|---|---|
| `id` | string | required | Unique. Planner IDs look like `M<n>-T<nnn>`; auditor IDs look like `FIX-<nnn>`. |
| `title` | string | required | Short. |
| `milestone` | int | `1` | Scheduling group (see `strict_milestones`). |
| `deps` | list of IDs | `[]` | Must be `done` before this card starts. |
| `agent` | `any` or a vendor name (`claude`, `codex`, `glm`, `grok`, or an `[agents.<name>]` OpenCode vendor) | `any` | Pins the worker vendor. A pinned card waits for its vendor while it cools down (until `swap_on_retry` rotation applies from attempt 3). A value that is not a known vendor behaves like `any`. |
| `owns` | list of globs | `[]` | Files the task may create or modify. Two cards with overlapping `owns` never run at the same time. |
| `docs` | list of globs | `[]` | At least one changed file must match each entry. |
| `tests_required` | bool | `true` | The diff must add assertions under `test_globs`. |
| `may_edit_tests` | bool | `false` | Allows modifying or deleting existing test files. The net count of assertions in tests still may not drop (deleted `.forge-samples` files excepted). |
| `scene_edits` | bool | `false` | Allows changes to `scene_globs` files, up to the size cap. |

Only cards that parse are loaded. A file without valid `+++` front matter is ignored.
Planner-written cards get the body sections Goal, Acceptance criteria, and Notes.

## Schemas (`schemas/*.json`)
These are strict JSON Schemas: every property is required and `additionalProperties` is
false, as Codex `--output-schema` structured output requires. The same file is passed to
Claude as `--json-schema`.

- `review.json` — `{verdict: PASS|FAIL, summary, issues[{severity: blocker|major|nit, file, problem, fix}], criteria[{criterion, met, evidence}]}`.
  Anything other than `PASS`, including a missing or unparseable verdict, counts as a rejection.
- `plan.json` — `{tasks[card fields + goal, acceptance[], notes], spec_issues[]}`.
- `audit.json` — `{verdict: HEALTHY|CONCERNS|CRITICAL, findings[{severity, file, issue}], new_tasks[card]}`.

## How output is parsed
- Claude: the last `{"type":"result"}` event of the stream-json log gives `result`
  (text), `structured_output` (when a schema was used), and `total_cost_usd`.
- Codex and mock: the `-o` file holds the final message.
- Grok: the last JSON line of the log (`result` event, or the `--output-format json` object).
- OpenCode: the text of the last message in the `--format json` event stream.
- If no structured object is found, forge falls back to the first `{...}` JSON block in the text.
