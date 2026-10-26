"""Claude Code argv (`claude -p`), shared by claude and glm."""
from __future__ import annotations

from pathlib import Path


def claude_code_cmd(vendor, a, readonly, prompt, schema):
    """argv for claude/glm; glm differs only in its environment (glm_env), so --model and
    --max-budget-usd apply to claude only. `a` is the vendor's [agents.<vendor>] table."""
    cmd = [a.get("bin", "claude"), "-p", prompt,
           "--output-format", "stream-json", "--verbose",
           "--max-turns", str(a.get("review_max_turns" if readonly else "max_turns", 30 if readonly else 60)),
           "--no-session-persistence"]
    if a.get("max_budget_usd") and vendor == "claude":
        cmd += ["--max-budget-usd", str(a["max_budget_usd"])]
    if a.get("model") and vendor == "claude":
        cmd += ["--model", a["model"]]   # glm: model comes from ANTHROPIC_MODEL in glm_env
    if readonly:
        # Read-only tool set; structured verdict via JSON schema.
        cmd += ["--tools", "Read,Grep,Glob"]
        if schema:
            cmd += ["--json-schema", Path(schema).read_text()]
    else:
        # Edits allowed; Bash limited by .claude/settings.json allow/deny lists.
        cmd += ["--permission-mode", a.get("permission_mode", "acceptEdits")]
    return cmd + list(a.get("extra_args", []))
