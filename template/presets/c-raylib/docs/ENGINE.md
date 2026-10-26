# Engine: C11 + raylib + CMake (secondary preset)
Layers: `core` (types, arena, check) <- `sim` (deterministic rules, no raylib/time) <- `game`
(game.so: rendering/UI via raylib) ; `platform` (window, input, reload) uses only `core` and the
game API header. Gates build `ci` preset headless (core+sim+tests with ASan/UBSan), so no display
or raylib is needed for CI. Lessons from the previous attempt: one module per card, layers enforced
by gate, content as data (CSV/JSON -> compiled tables), every gate has a failing self-test.
