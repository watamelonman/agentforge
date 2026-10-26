# Engine: Godot 4 .NET (C#)

Agents build systems in portable C#; humans own the Godot editor (scenes, UI, art).

## Layout and layers (enforced by the `layers` gate)
```
Game.Core/        Pure C# (net8.0) rules: combat, stats, maps, save data. NO `using Godot`,
                  no unseeded Random, no DateTime.Now. Portable to any engine or a CLI sim.
Game.Core.Tests/  xUnit tests for Game.Core. Runs with plain `dotnet test`, no Godot needed.
src/game/         Godot Node scripts (partial classes). Thin glue: input -> Core -> display.
content/          JSON data loaded by Game.Core loaders (validated, with a test loading every file).
scenes/           .tscn owned by humans in the editor.
@NAME@.csproj     Godot.NET.Sdk project referencing Game.Core.
```
Gates: `dotnet format --verify-no-changes`, `dotnet build -warnaserror` (nullable, analyzers at
latest-recommended, CS1591 missing XML docs = error), `dotnet test`, then a build of the Godot
assembly. Scene-file rules are the same as the GDScript preset: `scene_edits = true` cards only,
small diffs, never hand-renumber ids/uids; .csproj files are human-owned too.

## Godot-side tests (optional)
GdUnit4 supports C# via the `gdUnit4.api` + `gdUnit4.test.adapter` NuGet packages, running
Node-level tests through `dotnet test` with `GODOT_BIN` set. Use it only for scene/node
integration tests; keep rules tests in xUnit (faster, no engine). Not wired by default
(unverified on your machines).

## Tradeoffs vs GDScript
+ Real static typing, nullable analysis, refactoring, NuGet ecosystem; agents are very strong at C#;
  core logic is portable and testable without the engine.
- Needs the .NET build of Godot + dotnet SDK 8; no Godot 4 C# web export; compile step on
  iteration; most community addons/tutorials are GDScript.

## Install
Arch: `sudo pacman -S dotnet-sdk-8.0 godot-mono` (godot-mono may be AUR/extra depending on date).
Fedora: `sudo dnf install dotnet-sdk-8.0`; Godot .NET: official "Godot Engine - .NET" Linux binary
from godotengine.org (set `[engine] godot_bin` to its path). Fedora's `godot` package is non-.NET.
