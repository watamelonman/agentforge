"""OpenCode argv (`opencode run`) and its per-run permissions."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .grok import grok_prompt_file
from .sandbox import sandbox_wrap

# ------------------------------------------------------------------ opencode
# One [agents.<name>] table with harness = "opencode" = one model driven by `opencode run`
# (e.g. OpenCode Go's kimi-k3). OpenCode has no OS sandbox of its own and `--auto` approves
# every tool call that isn't denied, so forge runs it inside bubblewrap by default.
OPENCODE_ARGV_MAX = 100_000   # bytes; bigger prompts go via --file (Linux caps one argv string at 128 KiB)


def opencode_cmd(proj, vendor, a, role, prompt, cwd, out_file):
    """argv for one headless `opencode run` (docs/VENDORS.md, "OpenCode").

    `--format json` prints one JSON event per line (parse_opencode_output). Workers get
    `--auto` (approve whatever OPENCODE_PERMISSION doesn't deny); review/plan/audit don't,
    and their permissions deny edit/bash/webfetch. The prompt is the message argument, or an
    attached file when it is too long for argv. Wrapped in bwrap unless sandbox = "none"."""
    model = a.get("model")
    if not model:
        raise RuntimeError(f"[agents.{vendor}] needs model = \"provider/model\", e.g. \"opencode-go/kimi-k3\"")
    # OpenCode 2.x dropped `--dir` and `--variant` (verified on 2.1.2, 2026-10-21): the working
    # directory comes from Popen(cwd=...) / bwrap --chdir, the variant from `-m provider/model#variant`.
    if a.get("variant"):
        model = f"{model}#{a['variant']}"
    # --standalone: OpenCode 2.x otherwise hands the run to its background service
    # (`opencode serve --service`), which executes tools OUTSIDE the bwrap sandbox and outside
    # the worktree. A private server keeps every tool call inside the sandbox, in `cwd`.
    inner = [a.get("bin", "opencode"), "run", "--standalone", "--format", "json", "-m", model]
    if role == "work":
        inner += ["--auto"]
    inner += list(a.get("extra_args", []))
    pfile = grok_prompt_file(out_file)   # <log stem>.prompt.md, written by run_agent
    ro_files = []
    if len(prompt.encode()) > OPENCODE_ARGV_MAX:
        inner += ["--file", str(pfile), f"Your complete instructions are in the attached file {pfile.name}. "
                  "Follow them exactly."]
        ro_files.append(pfile)
    else:
        inner += [prompt]
    return sandbox_wrap(proj, a, cwd, inner, writable_cwd=(role == "work"), ro_files=ro_files)


def claude_bash_denies(root):
    """Bash deny patterns from the project's .claude/settings.json ("Bash(git push*)" -> "git push*"),
    so OpenCode workers get the same command blocklist as Claude Code workers."""
    try:
        cfg = json.loads((Path(root) / ".claude" / "settings.json").read_text())
    except (OSError, ValueError):
        return []
    out = []
    for rule in cfg.get("permissions", {}).get("deny", []):
        m = re.fullmatch(r"Bash\((.+)\)", rule)
        if m:
            out.append(m.group(1))
    return out


def opencode_permissions(proj, a, role):
    """OPENCODE_PERMISSION for one run. Read-only roles: no edits, no shell, no web.
    Workers: edits allowed, shell allowed except the .claude deny list, web only if web_search.
    "*" comes first so the specific deny patterns after it win under last-match rules."""
    web = "allow" if a.get("web_search") else "deny"
    if role != "work":
        return {"edit": "deny", "bash": "deny", "webfetch": "deny"}
    bash = {"*": "allow"}
    for pat in claude_bash_denies(getattr(proj, "root", ".")):
        bash[pat] = "deny"
    return {"edit": "allow", "bash": bash, "webfetch": web}
