# Glossary
- **Card / task card:** one `tasks/*.md` file describing a single small, testable change.
- **Owns:** the globs a card may modify. They also act as the parallelism lock.
- **Worktree:** a separate git checkout per task (`.forge/worktrees/<ID>`, branch `forge/<ID>`).
- **Gate:** an objective, scripted check. Built in: `policy` and `layers`. Plus engine commands.
- **Policy gate:** anti-cheat, scope, size, docs, typing, and scene rules on the diff.
- **Layer:** a top-level folder under `layers.root` with an allowed-dependency list.
- **Worker:** the agent that implements a card. **Reviewer:** the read-only agent that judges a
  diff. **Planner:** turns the spec into cards. **Auditor/monitor:** a read-only whole-repo
  check that can propose FIX cards.
- **Cross review:** the reviewer is another vendor, preferably another model family on another CLI.
- **Vendor / harness / family:** a vendor is one model plus the CLI that runs it; the harness is
  the CLI (Claude Code, Codex, Grok Build, OpenCode); the family is the lab behind the model.
- **Cooldown:** a vendor that hit a usage limit sits out until its reset time; others keep working.
- **Allowance window:** `monthly_usd` share per 5 h / 7 d / 30 d that forge keeps a vendor under.
- **Attempt:** one worker run plus its gates and review. Capped by `max_attempts`.
- **Blocked:** forge gave up on the task. It needs a human decision, then `forge reset`.
- **Milestone:** a spec phase. With `strict_milestones`, phases run strictly in order.
- **Preset / engine adapter:** a template folder plus forge.toml sections for one engine.
- **Mock mode:** scripted fake agents for testing the pipeline without spending tokens.
- **Scene files:** editor-owned engine files (`.tscn`, `.tres`, `project.godot`, `.csproj`)
  that agents may only change in small diffs, and only on cards with `scene_edits = true`.
