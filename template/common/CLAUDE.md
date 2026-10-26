@AGENTS.md

<!-- Claude-specific notes only. All shared rules live in AGENTS.md. -->
- Use subagents only for read-only investigation, never for parallel edits.
- Bash permissions are restricted by .claude/settings.json; if a command is denied, use an
  allowed alternative rather than retrying.
