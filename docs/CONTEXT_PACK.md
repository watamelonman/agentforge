# Context pack

The context pack is a short block forge puts into each worker and reviewer prompt. It holds
the parts of the spec and the decision log that the card cites, plus (for workers) the exact
gate commands. It exists to save tokens. Agents still have every file and can grep anything
the pack lacks; no gate, anti-cheat check, review step or test is changed.

## Why it exists (evidence)
Headless agents re-send their whole conversation on every turn, so a file an agent reads
early is paid for again on every later turn. Measured on one real Godot C# project (called `myproject` here)
(`.forge/logs`, 190 work/review runs up to M7, Oct 14 2026):

| | Claude work | Codex work |
|---|---|---|
| Runs | 57 | 47 |
| Input tokens per run (incl. cache reads) | ~826K | ~378K |
| Average turns per run | 26.5 | n/a (Codex reports none) |

- 63 of 85 Codex runs and 19 of 105 Claude runs opened `spec/SPEC.md` (50 KB, ~12.5K tokens)
  or `docs/DECISIONS.md` (78 KB, ~20K tokens) whole, or in large ranges.
- Weighted by the turns left after the read, that is an estimated ~76K input tokens per Codex
  run and ~52K per Claude run.
- Workers also opened `forge.toml` to find the gate commands.

These numbers are upper bounds. The log scan counts `sed -n` ranges as whole-file reads.

## What goes in
`build_context()` in `bin/forge` assembles these parts, in this order:

1. **Spec sections** from `[project] spec`:
   - every section whose heading number the card cites as `§N` or `§N.M`;
   - every heading that names the card's milestone as a whole word, e.g. `### M7 — Combat core`
     and `### 9.8 M7 decisions` (M17 does not match M1);
   - every number in `[context] always_spec`.

   A section includes its sub-sections. A child is never repeated when its parent is already in.
   Headings inside ``` fences are ignored.
2. **Decisions the card names.** These are the full `## DEC-…` entries for every `DEC-…` id the
   card text mentions.
3. **Decision index** (only with `decision_index = true`). This is one line per decision title.
4. **Gate commands** (worker prompts only). These are the `[gates.cmd]` entries, so the worker
   runs exactly what the gates run, with their quiet flags, and doesn't open `forge.toml`.

The pack is cut at `[context] max_chars` with a visible marker. It is built once per card, so
every attempt of a card gets identical text.

## Where it goes
The pack goes wherever the prompt template has `{{CONTEXT}}`. In `template/common/prompts`, the
worker template has it after the task card and the reviewer template has it before the diff.
A project whose own `prompts/*.md` predate this feature has no placeholder, so the pack is
appended to the end of the prompt. Nothing has to be edited for an existing project to benefit.
`forge review <ID>` uses the same reviewer pack.

## Cost and the default sizes
The pack is part of the prompt, so it is also re-sent on every turn. One KB in the pack costs
about 250 tokens × turns (≈ 6.6K tokens for a 26-turn Claude run). That is why the defaults
are small: no `always_spec`, no decision index, and a 16 KB cap. On myproject the default pack has
these sizes:

- median **6.0 KB** (~1.5K tokens) per card;
- largest 16 KB, for cards that cite many sections;
- M7-T017: 5.8 KB.

With `always_spec = ["2"]` and the index on, the median was 14.8 KB. That costs more per run
than the whole-file reads it replaces, so those options are off by default.

Expected net effect on myproject, per run (estimates, not yet measured on new runs):

- **Codex work and review:** reads avoided ≈ 76K, pack cost ≈ 1.5K × turns. The net saving
  is likely 30–50K tokens per run.
- **Claude:** reads avoided ≈ 52K, pack ≈ 40K. This is roughly neutral; the gain is fewer
  tool round-trips.

To check after a change, compare the per-run token totals in `.forge/logs` before and after.
For Claude, read the `result` line `usage`. For Codex, read the `turn.completed` `usage`.
Each run's full prompt is saved as `<card>-<role>-<vendor>-<ts>.prompt.md`.

## Turning it off
Set `[context] enabled = false`. The prompts are then exactly as before.
