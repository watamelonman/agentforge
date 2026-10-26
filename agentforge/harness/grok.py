"""Grok Build argv (`grok --prompt-file ...`)."""
from __future__ import annotations

from pathlib import Path

# grok = xAI's Grok Build CLI (`grok`, AUR grok-build-bin), run headless with -p/--prompt-file.
GROK_DEFAULT_TOOLS_RO = "read_file,grep,list_dir"   # review/plan/audit: read-only tool allowlist


def grok_prompt_file(out_file):
    """Prompt file run_agent writes before starting the CLI: <log stem>.prompt.md."""
    return Path(out_file).with_suffix(".prompt.md")


def grok_cmd(a, readonly, cwd, out_file, schema):
    """argv for one headless Grok Build run (docs: ~/.grok/docs/user-guide/14-headless-mode.md).

    Prompt comes from --prompt-file (the .prompt.md forge already logs), so long prompts never
    hit argv limits. work: workspace sandbox (writes only inside the worktree) and
    always-approve, since headless runs cannot answer permission prompts; deny rules from
    .claude/settings.json still apply. review/plan/audit: read-only sandbox, read-only tool
    allowlist and, with a schema, --json-schema (which implies --output-format json).
    Otherwise output is streaming-messages-json so the final `result` line parses like Claude's."""
    cmd = [a.get("bin", "grok"), "--prompt-file", str(grok_prompt_file(out_file)),
           "--cwd", str(cwd), "--no-alt-screen",
           "--max-turns", str(a.get("review_max_turns" if readonly else "max_turns", 30 if readonly else 60))]
    if a.get("model"):
        cmd += ["-m", a["model"]]
    if a.get("reasoning_effort"):
        cmd += ["--reasoning-effort", str(a["reasoning_effort"])]
    if readonly:
        cmd += ["--sandbox", a.get("review_sandbox", "read-only"),
                "--tools", a.get("review_tools", GROK_DEFAULT_TOOLS_RO), "--disable-web-search",
                "--no-subagents"]
        if schema:
            cmd += ["--json-schema", Path(schema).read_text()]
        else:
            cmd += ["--output-format", "streaming-messages-json"]
    else:
        cmd += ["--sandbox", a.get("sandbox", "workspace"), "--always-approve",
                "--output-format", "streaming-messages-json"]
        if not a.get("web_search", False):
            cmd += ["--disable-web-search"]
    return cmd + list(a.get("extra_args", []))
