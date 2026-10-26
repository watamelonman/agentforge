"""Small shared helpers: install paths, subprocess/git wrappers, time formatting, globbing.

Everything here is dependency-free inside the package, so any module may import it.
"""
from __future__ import annotations

import fnmatch
import subprocess
import sys
import time
from pathlib import Path

# The repository root (this file is <root>/agentforge/util.py). bin/forge, template/ and
# tests/mock_agent.py are found from here, also when bin/forge is reached through a symlink.
FORGE_HOME = Path(__file__).resolve().parent.parent
TEMPLATE = FORGE_HOME / "template"
MOCK_AGENT = FORGE_HOME / "tests" / "mock_agent.py"
FORGE_SCRIPT = FORGE_HOME / "bin" / "forge"


def sh(cmd, cwd=None, check=True, capture=True, timeout=None, env=None):
    """Run a command (list or shell string) and return CompletedProcess."""
    r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), text=True,
                       capture_output=capture, timeout=timeout, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {cmd}\n{r.stdout}\n{r.stderr}")
    return r


def git(repo, *args, check=True):
    """Run git -C repo ARGS and return stripped stdout (raises on failure if check)."""
    return sh(["git", "-C", str(repo), *args], check=check).stdout.strip()


def die(msg):
    """Print an error and exit 1. Used for user errors, never inside worker threads."""
    print(f"forge: {msg}", file=sys.stderr)
    sys.exit(1)


def now():
    """Local wall-clock timestamp for logs and history."""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def tail(text, n):
    """Keep only the last n lines: gate output fed to agents must stay small (token budget)."""
    lines = text.splitlines()
    return "\n".join(lines[-n:]) if len(lines) > n else text


def glob_match(path, patterns):
    """True if `path` (relative, '/'-separated) matches any of the glob `patterns`.

    fnmatch's `*` already crosses '/', so '**' needs no special case; on top of that each
    pattern is also tried with every '**/' removed (so 'src/**/a.py' matches 'src/a.py'), and
    'dir/**' matches everything under dir.

    >>> glob_match("src/game/player.cs", ["src/**"])
    True
    >>> glob_match("src/a.py", ["src/**/a.py"]), glob_match("docs/x.md", ["src/**"])
    (True, False)
    """
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.replace("**/", "")):
            return True
        if pattern.endswith("/**") and path.startswith(pattern[:-3] + "/"):
            return True
    return False


def fmt_time(epoch):
    """Local HH:MM (with the date when it isn't today) for log lines."""
    t = time.localtime(epoch)
    return time.strftime("%H:%M" if t[:3] == time.localtime()[:3] else "%Y-%m-%d %H:%M", t)


def event_excerpt(report, max_lines=25, max_chars=2500):
    """Gate report trimmed for events.log: indented, at most max_lines / max_chars."""
    lines = report.strip().splitlines()
    out = "\n".join("    " + l[:300] for l in lines[:max_lines])
    if len(lines) > max_lines:
        out += f"\n    [... {len(lines) - max_lines} more lines; see `forge status` / .forge/state.json]"
    return out[:max_chars]


def render(tpl, **kw):
    """Fill {{KEY}} placeholders in a prompt template (no templating engine, by design)."""
    for k, v in kw.items():
        tpl = tpl.replace("{{" + k + "}}", str(v))
    return tpl
