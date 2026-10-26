# Engine presets (adapters)

A preset is a folder under `template/presets/<name>/` that `forge init` copies over
`template/common/`. The engine adapter is just data: `forge.toml` sections `[gates]`,
`[layers]`, `[policy]` plus whatever tools/scripts the gates call. `bin/forge` has no
engine-specific code apart from the GDScript typing/doc heuristics.

| Preset | Status | Notes |
|---|---|---|
| `godot` | verified on Godot 4.5-stable + GdUnit4 v6.2.2 + gdtoolkit 4 | Typed GDScript, warnings as errors. |
| `godot-csharp` (default) | verified with .NET SDK 8 (xUnit, dotnet format, Godot.NET.Sdk 4.5.0 build) | Pure C# `Game.Core` plus thin Godot scripts. |
| `c-raylib` | headless `ci` preset verified (CMake + ctest + ASan/UBSan + clang-format); raylib targets not built | Secondary option. |
| `python` | verified (used by the e2e test) | Tools and prototypes. |
| `love2d`, `renpy` | **unverified** templates | Example adapters for other FOSS engines. |

## Adding a preset
1. `mkdir template/presets/<name>` and add a `forge.toml`. Copy one and change `[engine]`,
   `[gates]`, `[layers]`, and `[policy]`. Keep the `[agents]` and `[budget]` blocks.
2. Add a `docs/ENGINE.md` for agents: the layer map, file rules (which files are human-owned),
   determinism rules, and how to run the tests. AGENTS.md tells agents to read docs/ENGINE.md.
3. Add minimal sample code plus one test, so the gates have something to pass on day one.
4. Put the gate scripts and engine config files in `policy.protected`, and the
   editor-owned files in `policy.scene_globs`. Don't repeat these lists in prose: `forge init`
   renders them into `AGENTS.md` (`forge sync-agents`), and `tests/check_docs.py` fails if a
   preset's render misses an entry or a hand-written "never modify" list appears.
5. Run `forge init /tmp/x --preset <name>`. Commit a good change and a bad change and run
   `forge gates --base HEAD~1` for each: the first must pass and the second must fail.
6. Document it in this table.

Text in file names or in `forge.toml`/`project.godot`/`CMakeLists.txt`/`conf.lua`/`<name>.csproj`
that reads `@NAME@` becomes the project folder name.

## Sample code (`.forge-samples`)
A preset may ship a small sample (e.g. a dice roller plus its tests) so that every gate has
something to pass on day one. The preset's `.forge-samples` file lists those paths, one per
line (`#` starts a comment). `forge init --no-sample` deletes them and the manifest. Otherwise
they stay, and the manifest tells planners and humans that the samples are disposable.
Specs may say that the first card deletes them.

## godot-csharp: network and restore
The preset sets `[agents.codex] network_access = true` (NuGet needs api.nuget.org) and
`[setup] restore = "dotnet restore ..."`, which forge runs in every task worktree before the
worker starts, outside any sandbox. Either one alone makes builds work; together they cover
both an offline sandbox and new package references added by a worker. Projects created
before this need both added to `forge.toml` by hand (see docs/TROUBLESHOOTING.md).
