# Quickstart

```bash
./install.sh --yes                 # add --with-csharp for Godot C#
claude auth login && codex login   # once per machine
forge init ~/games/mygame --spec ~/specs/mygame.md          # Godot C# by default; --preset godot for typed GDScript
cd ~/games/mygame && tools/setup_addons.sh && git add -A && git commit -m "addons"   # GDScript: GdUnit4
forge plan                         # writes tasks/*.md + docs/SPEC_ISSUES.md
$EDITOR tasks/*.md                 # sanity-check the cards
git add -A && git commit -m "plan M1"
forge up -j 3                      # tmux: orchestrator | status | event log
```
- Is it working? `forge status`, or the right-hand panes in tmux.
- Something blocked? `forge review <ID> --gates-only`, fix the card or spec, then `forge reset <ID>`.
- After a milestone: `forge audit`, commit any FIX cards, run `forge plan` again.
- Want to try it without spending tokens first? `forge --mock ...` or `tests/e2e.sh`.
- You work in the Godot editor on scenes, UI, and art. Agents work on `src/` systems. Commit
  your editor changes between runs.
