# Engine: Godot 4 (GDScript, strict typing)

Agents build systems. Humans own the editor (UI layout, art, scene composition, feel).

## Layers (enforced by the `layers` gate)
```
src/game/   Nodes, scene scripts, input, UI glue, presentation   -> may use data, sim
src/data/   Resource classes (class_name X extends Resource), loaders, validation -> may use sim
src/sim/    Pure rules: RefCounted/static funcs, seeded RNG, no Node/Input/Time  -> nothing
content/    Data: .json / .tres instances of src/data Resources (designers add content here)
scenes/     .tscn owned by humans in the editor
test/       GdUnit4 suites mirroring src/ (test/sim/test_x.gd)
```
Game logic lives in `src/sim` so it runs headless and deterministically in tests. A scene
script in `src/game` should be thin: read input, call sim, show results via signals.

## Typing (warnings are errors in project.godot plus the forge TYPING gate)
Every `var`, parameter, and return is typed (`var hp: int`, `:=` only when the type is obvious,
`-> void`). Typed arrays/dicts (`Array[Skill]`, `Dictionary[StringName, int]`). No `Variant`
unless the card justifies it.

## Scene / resource file rules (.tscn/.tres/project.godot)
1. Default: agents do **not** edit scene files. Cards must set `scene_edits = true` to allow it,
   and even then each file's diff is capped (`max_scene_diff_lines`).
2. Prefer constructing node trees in code (`_ready()` building children) or exposing
   `@export` properties the human wires in the editor.
3. New scenes needed by a system: create a minimal `.tscn` (root node + script) and list the
   wiring the human must do in the final report under `LEFT OUT`.
4. Never renumber `ext_resource` ids, change `uid://` values, or reorder sections by hand.
   For bulk changes write an `@tool`/EditorScript in `tools/` and let a human run it.
5. Content data: `.json` under `content/` validated by a loader in `src/data` with a test that
   loads every shipped file. `.tres` content is authored by humans in the inspector.

## Determinism
Sim code takes a seeded `RandomNumberGenerator` (or the `Dice` wrapper) and integer ticks;
no `randf()`, `Time`, or frame delta inside `src/sim`.

## Option: C# (Godot .NET)
Possible (GdUnit4 supports C#; `runtest.sh` runs `dotnet build`). Tradeoffs:
+ real static typing, refactoring, NuGet ecosystem, faster heavy logic, agents are strong at C#.
- needs the .NET build of Godot and the dotnet SDK; **no web export** for Godot 4 C#; Arch has
  `godot-mono`, Fedora has no packaged .NET Godot (use the official binary/flatpak);
  two languages if addons are GDScript; slower iteration (compile step).
To switch: change `[gates.cmd]` to `dotnet format --verify-no-changes`, `dotnet build -warnaserror`,
and the GdUnit4 C# runner; add `*.cs` to `source_globs`; same layer folders.
