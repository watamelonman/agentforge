# Gates and anti-cheat rules

After each worker attempt, the orchestrator commits the worktree, merges `main` into it, and
runs `gates.order`. The first failing gate stops the chain. Its report (deduplicated, at most
40 items, command output trimmed to `max_gate_output_lines`) becomes the next attempt's
feedback. If the same report comes back twice in a row, the task is **blocked** right away so
it doesn't burn tokens repeating the same mistake.

## Built-in `policy` gate (diff of merge-base...HEAD)
| Tag | Fails when |
|---|---|
| `PROTECTED` | Any file matching `protected` was changed (instructions, config, gates, spec, cards, schemas). |
| `TAMPER` | An existing test file was deleted or modified and the card doesn't have `may_edit_tests = true` (deleting a file listed in `.forge-samples` on `main` is always allowed); an added test line matches `skip_markers`; or the net count of assertion lines in tests went down. Assertions in deleted `.forge-samples` files don't count as removed; assertions in other deleted tests do, so `may_edit_tests` can't be used to shed coverage. Workers may never change `.forge-samples` itself (`PROTECTED`). |
| `SCOPE` | A changed file is outside `owns` + `always_allowed`, and isn't a newly added test file. |
| `HOLLOW` | An added line in `source_globs` matches `forbid_added` (TODO, stubs, `NotImplemented*`, `pass`, warning suppressions, ...). |
| `CHEAT` | An added production line matches `test_detection` (code that behaves differently under test). |
| `TESTS` | `tests_required` is set and no assertion was added under the test paths. |
| `SIZE` | A changed source/test file is longer than `max_file_lines`, or the diff adds more than `max_diff_lines`. |
| `DOCS` | A `docs` entry of the card wasn't touched; a public C/C++ header prototype has no comment directly above it; a public Python def/class has no docstring; a public GDScript `func` has no `##` line above it. |
| `TYPING` | In a `.gd` file: an untyped parameter, a missing `-> T`, or an untyped `var`/`const` (use `: T` or `:=`). |
| `SCENE` | A `scene_globs` file changed without `scene_edits`, or its diff is larger than `max_scene_diff_lines`. |
| (none) | No changes were committed at all. |

## Built-in `layers` gate (whole tree)
Each file under `layers.root/<layer>/` may only reference the layers in `allow.<layer>`, may
not include `forbid_headers`, and may not contain lines matching `forbid_patterns` (comments
are skipped). Examples: Godot `src/sim` can't `extends Node`, use `Input`, `Time`, or unseeded
`randf()`. C# `Game.Core` can't contain `using Godot` or `DateTime.Now`.

## Command gates (`[gates.cmd]`)
Any shell command, run in the worktree with `FORGE_BASE` set. Exit code 0 means pass. The
presets ship with these:

| Preset | Gates |
|---|---|
| godot | `import` = `tools/godot_check.sh import` (headless `--import` + `tools/check_scripts.gd` compiles every script, so typing warnings-as-errors fail); `format` = `gdformat --check`; `lint` = `gdlint`; `test` = GdUnit4 headless (`tools/godot_check.sh test`). |
| godot-csharp | `format` = `dotnet format --verify-no-changes` (both projects); `build` = `dotnet build -warnaserror` (nullable, analyzers, CS1591 docs); `test` = `dotnet test` (xUnit); `godot_build` = build of the Godot.NET.Sdk assembly. |
| c-raylib | `build`/`test` = CMake `ci` preset (headless core+sim+tests with ASan/UBSan); `format` = clang-format. clang-tidy is commented out. |
| python | `test` = `unittest`. |
| love2d / renpy | stylua/luacheck/busted; `renpy.sh lint`/`test` (**unverified**). |

### Adding a gate
1. Write a script under `tools/` (or `gates/`). Keep its output short and actionable,
   because the worker reads it. Exit non-zero on failure.
2. Add `name = "command"` under `[gates.cmd]` and put `name` in `gates.order`. Cheap gates go
   first.
3. Add the script to `policy.protected` so workers can't edit it, then run `forge sync-agents`
   so AGENTS.md lists it too.
4. **Prove the gate works:** commit a deliberately bad change on a scratch branch and run
   `forge gates --base HEAD~1`. It must fail. Then revert and confirm it passes.

## Why the reviewer is still needed
Gates can't see whether tests are *meaningful*, whether outputs are hardcoded for specific
inputs, or whether the design matches the spec. The reviewer prompt (`prompts/reviewer.md`)
covers these and rejects them.

## Claude-only extra layer
`.claude/settings.json` denies git history commands, network fetches, `sudo`, and edits to
protected paths. `.claude/hooks/guard.sh` (a PreToolUse hook; exit 2 blocks) rejects adding
skip markers to tests while Claude is editing. Codex runs in `--sandbox workspace-write`
with no such hook (OpenCode gets the `Bash(...)` deny rules through `OPENCODE_PERMISSION`;
Grok honours the project's `.claude/settings.json` deny rules), so the gates are the
authority for every vendor.
