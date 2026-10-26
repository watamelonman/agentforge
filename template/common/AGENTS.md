# AGENTS.md — rules for every coding agent (Claude Code and Codex)

This file is canonical. `CLAUDE.md` imports it. Humans edit it; agents never do.

## 0. How you are being run
- You are one of several agents working **in parallel**, each in its own git worktree,
  on exactly one task card. The orchestrator commits, merges, and runs the gates. **Do not
  `git commit`, `git push`, switch branches, or rewrite history.**
- After you finish, objective gates run (build, tests, sanitizers, lint, format,
  architecture layers, anti-cheat, docs). Then a reviewer agent from a *different vendor*
  reads your diff against the task card. Failures come back to you verbatim.
- You have a hard budget (turns, wall-clock time, attempts). Spend it on the task.

## 1. Scope
<!-- forge:policy-lists BEGIN (generated from forge.toml [policy] by `forge sync-agents`; do not edit by hand) -->
- Touch only files matching the card's `owns` globs, plus the always-allowed paths
  (none yet: run `forge sync-agents`) and **new** test files (test paths: none yet). Anything
  else fails the SCOPE gate.
- Never modify these protected paths: (none yet: run `forge sync-agents`). If one of them is
  wrong, say so in your final message under `SPEC/INFRA ISSUES`.
<!-- forge:policy-lists END -->
- If the card is ambiguous, choose the interpretation most consistent with `spec/SPEC.md`
  and `docs/ARCHITECTURE.md`, state it in your final message, and continue. Do not stall.
- If the spec contradicts itself, report it; do not silently pick a side.

## 2. Workflow (test-first)
1. Read the card, the relevant spec section, `docs/ARCHITECTURE.md`, `docs/ENGINE.md` (engine rules:
   layers, typing, which files are human-owned), and the code you will touch.
   Read only what you need.
2. Write failing tests that encode the acceptance criteria.
3. Implement until they pass. Run the project's build and tests yourself
   (see `forge.toml [gates.cmd]` for the exact commands) before finishing.
4. Update docs (below). Finish with the short report (section 7).

## 3. No cheating. These are detected automatically and fail the task.
- Deleting, weakening, skipping, or disabling tests (`skip`, `DISABLED_`, `#if 0`, removing asserts).
- Editing existing tests to match broken behaviour (unless the card says `may_edit_tests = true`).
- Hardcoding expected outputs, special-casing test inputs, or detecting test mode in
  production code.
- Stub or hollow implementations: `TODO`, `FIXME`, `UNIMPLEMENTED`, `NotImplementedError`,
  empty bodies, "placeholder" logic presented as done. If something truly can't be done
  in this task, leave it out, and say so in your report. Don't fake it.
- Tests that assert nothing meaningful (e.g. `assert(1)`, only checking "doesn't crash"
  when behaviour is specified).
- Suppressing warnings, sanitizers, or lints instead of fixing the cause.
A reviewer that finds any of these rejects the whole change.

## 4. Code standards
- Small, cohesive files (hard limit enforced by gate; aim for < 400 lines) and short functions.
- Respect the layer map in `docs/ARCHITECTURE.md` / `forge.toml [layers]`. Lower layers never
  include higher ones. Game logic is pure, deterministic, and testable headless: no
  rendering, windowing, audio, or wall-clock time in simulation code.
- Data-driven content: new monsters, skills, floors, and events are data files, not code.
- Boring, readable code. No clever macros or metaprogramming. No new dependencies unless
  the card allows them.
- Errors fail loudly with context. No silent fallbacks.

## 5. Documentation (gated)
- Every public function/type has a doc comment explaining **why** and any contract
  (units, ownership, ranges). Do not restate *what* the code says.
- Module boundary changes update `docs/ARCHITECTURE.md` in the same change.
- Non-obvious decisions get a `docs/DECISIONS.md` entry and a `See DEC-…` comment. Name new entries after your card, `DEC-<card ID>` (e.g. `DEC-M3-T002`, then `DEC-M3-T002b`), never the next free number: parallel cards would collide. Older `DEC-NNN` entries keep their IDs.
- Add a line to `CHANGELOG.md` under "Unreleased" describing what now exists.

## 6. Token discipline
- Don't re-read files you have already read, and don't dump whole large files or logs. Use
  grep/ranges.
- Don't explore unrelated parts of the repo, don't refactor beyond the card, and don't write
  essays.
- When a command fails, read the error and fix the cause. Don't retry blindly.
- Stop when acceptance criteria are met and gates pass locally.

## 7. Final message format (keep it under 25 lines)
```
DONE: <one line>
CHANGED: <files>
TESTS: <what the new tests prove>
INTERPRETATIONS: <assumptions, or none>
SPEC/INFRA ISSUES: <or none>
LEFT OUT: <anything not done, or none>
```
