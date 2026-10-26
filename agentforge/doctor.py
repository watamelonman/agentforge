"""`forge doctor`: tools on PATH, CLI logins, and per-vendor checks (no secrets printed)."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from .detect import GROK_AUTH_RE
from .glm import DEFAULT_ZAI_ENV_FILE, GLM_DEFAULT_MODEL, ZAI_BASE_URL, glm_env, glm_key, redact
from .parsers.claude import api_retry_stop
from .project import ConfigView
from .util import sh, tail
from .vendors import family_of

GLM_PING_TIMEOUT = 180   # seconds for the one-turn `claude -p` ping through Z.ai


def cmd_doctor(args):
    """`forge doctor`: tool presence, CLI login status and glm checks (no secrets printed)."""
    ok = True
    for b in ("git", "tmux", "jq", "python3", "node", "claude", "codex", "godot", "gdlint", "gdformat",
              "cmake", "cc", "shellcheck"):
        p = shutil.which(b)
        print(f"{'ok ' if p else 'MISSING'}  {b:10} {p or ''}")
        ok &= bool(p) or b in ("shellcheck", "jq", "cmake", "cc", "godot", "gdlint", "gdformat")
    if shutil.which("claude"):
        r = sh(["claude", "auth", "status", "--text"], check=False)
        print(f"claude auth: {'logged in' if r.returncode == 0 else 'NOT logged in -> run `claude auth login`'}")
    if shutil.which("codex"):
        r = sh(["codex", "login", "status"], check=False)
        print(f"codex auth:  {'logged in' if r.returncode == 0 else 'NOT logged in -> run `codex login`'}")
    ok &= doctor_glm(Path(args.root))
    ok &= doctor_grok(Path(args.root))
    ok &= doctor_opencode(Path(args.root))
    if sys.version_info < (3, 11):
        print("python >= 3.11 required"); ok = False
    sys.exit(0 if ok else 1)


def _forge_toml(root):
    """The project's forge.toml as a dict; {} when missing or invalid (doctor runs anywhere)."""
    try:
        return tomllib.loads((root / "forge.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _project_uses(ag, vendor):
    """True when [agents] names `vendor` as a worker, reviewer-pool member or role."""
    return vendor in (list(ag.get("workers", [])) + list(ag.get("review_pool", []) or [])
                      + [ag.get("planner"), ag.get("auditor"), ag.get("reviewer")])


def doctor_glm(root):
    """glm checks for `forge doctor`: key present (never printed), endpoint reachable, and a
    one-turn `claude -p` ping through glm_env. Returns False only when the project's
    forge.toml actually uses glm (workers/review_pool/planner/auditor) and a check fails."""
    ag = _forge_toml(root).get("agents", {})
    a = ag.get("glm", {})
    used = _project_uses(ag, "glm")
    key, src = glm_key(a)
    print(f"glm key:     {'present (' + src + ')' if key else src}" + ("" if used else "  [glm not used by this project]"))
    good = bool(key)
    f = Path(a.get("key_file", DEFAULT_ZAI_ENV_FILE)).expanduser()
    if f.exists() and f.stat().st_mode & 0o077:
        print(f"glm key:     WARNING {f} is readable by others -> chmod 600 {f}")
    url = a.get("base_url", ZAI_BASE_URL)
    good &= _glm_url_reachable(url)
    if key:
        good &= _glm_api_probe(a, url, key)
    good &= _glm_ping(a, key)
    return good or not used


def _glm_url_reachable(url):
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=10)
        print(f"glm url:     reachable {url}")
    except urllib.error.HTTPError as e:   # any HTTP answer means the endpoint is reachable
        print(f"glm url:     reachable {url} (HTTP {e.code} without auth, expected)")
    except Exception as e:
        print(f"glm url:     UNREACHABLE {url}: {type(e).__name__}: {e}")
        return False
    return True


def _glm_api_probe(a, url, key):
    """Direct API probe (1 output token): shows Z.ai's own status/code without Claude Code."""
    body = json.dumps({"model": a.get("model") or GLM_DEFAULT_MODEL, "max_tokens": 1,
                       "messages": [{"role": "user", "content": "ping"}]}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/v1/messages", data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=60)
        print("glm api:     ok (HTTP 200, key accepted)")
    except urllib.error.HTTPError as e:
        msg = redact(e.read().decode(errors="replace")[:300], key)
        print(f"glm api:     FAILED HTTP {e.code}: {msg}")
        return False
    except Exception as e:
        print(f"glm api:     FAILED {type(e).__name__}: {e}")
        return False
    return True


def _glm_ping(a, key):
    """One-turn `claude -p` through glm_env; True when it answers pong or the ping is skipped."""
    claude_bin = a.get("bin", "claude")
    if not key:
        print("glm ping:    skipped (no key)")
        return True
    if not shutil.which(claude_bin):
        print(f"glm ping:    skipped ({claude_bin} not on PATH)")
        return True
    env = glm_env(a, dict(os.environ))
    cmd = [claude_bin, "-p", "Reply with exactly the word pong.", "--output-format", "stream-json",
           "--verbose", "--max-turns", "1", "--tools", "", "--no-session-persistence"]
    out, rc, why = _run_ping(cmd, env, key)
    res = next((json.loads(l) for l in reversed(out.splitlines()) if l.startswith('{"type":"result"')), {})
    if not why and rc == 0 and not res.get("is_error") and "pong" in str(res.get("result", "")).lower():
        print(f"glm ping:    ok via Claude Code, model {env['ANTHROPIC_MODEL']} ({res.get('duration_ms', '?')} ms)")
        return True
    reason = {"auth": "Z.ai rejected the key (401/403)", "limit": "Z.ai returned 429 (limit)"}.get(why, why)
    print(f"glm ping:    FAILED ({reason or 'rc=' + str(rc)}): {tail(out, 3)[:500]}")
    return False


def _run_ping(cmd, env, key):
    """(redacted output, returncode, why) for the ping; why is "auth"/"limit" when Claude Code
    kept retrying a 401/429, "timeout 180 s" when it hung, else None."""
    with tempfile.TemporaryFile("w+") as fh:
        pr = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                              text=True, env=env, start_new_session=True)
        deadline, why = time.time() + GLM_PING_TIMEOUT, None
        while pr.poll() is None:
            fh.seek(0)
            why = api_retry_stop(fh.read(), min_attempt=2)
            if why or time.time() > deadline:
                os.killpg(pr.pid, signal.SIGKILL)
                pr.wait()
                why = why or "timeout 180 s"
                break
            time.sleep(1)
        fh.seek(0)
        out = redact(fh.read(), key)
    return out, pr.returncode, why


def doctor_grok(root):
    """grok checks for `forge doctor`: binary, version, login state (via `grok models`, which
    makes no model call). Returns False only when this project's forge.toml uses grok."""
    ag = _forge_toml(root).get("agents", {})
    a = ag.get("grok", {})
    used = _project_uses(ag, "grok")
    note = "" if used else "  [grok not used by this project]"
    b = shutil.which(a.get("bin", "grok"))
    if not b:
        print(f"grok:        not installed (AUR grok-build-bin){note}")
        return not used
    v = sh([b, "--version"], check=False, timeout=30)
    print(f"grok:        {b} {(v.stdout or '').strip()}{note}")
    try:
        m = sh([b, "models"], check=False, timeout=60)
        out = (m.stdout or "") + (m.stderr or "")
    except subprocess.TimeoutExpired:
        out = "timeout"
    authed = m.returncode == 0 and not GROK_AUTH_RE.search(out) if out != "timeout" else False
    if not authed and os.environ.get("XAI_API_KEY"):
        print("grok auth:   XAI_API_KEY set in environment (not printed)")
        authed = True
    print(f"grok auth:   {'logged in' if authed else 'NOT logged in -> run `grok login` (or `grok login --device-code`)'}")
    dm = re.search(r"Default model:\s*(\S+)", out)
    if dm:
        print(f"grok model:  {a.get('model') or dm.group(1)}" + ("" if a.get("model") else " (CLI default)"))
    return authed or not used


def doctor_opencode(root):
    """opencode checks for `forge doctor`, one line per [agents.<name>] table with
    harness = "opencode": binary, model set, bubblewrap present (unless sandbox = "none") and
    `opencode auth list` output (no model call). Fails doctor only when such vendors exist."""
    cfg = _forge_toml(root)
    tables = {k: v for k, v in (cfg.get("agents") or {}).items()
              if isinstance(v, dict) and v.get("harness") == "opencode"}
    good, authed = True, None
    for name, a in tables.items():
        b = shutil.which(a.get("bin", "opencode"))
        problems = []
        if not b:
            problems.append("opencode not installed (npm i -g opencode-ai, or AUR opencode-bin)")
        if not a.get("model"):
            problems.append('no model (e.g. model = "opencode-go/kimi-k3")')
        if a.get("sandbox", "bwrap") != "none" and not shutil.which(a.get("bwrap", "bwrap")):
            problems.append("bubblewrap missing (package `bubblewrap`)")
        if b and authed is None:
            try:
                r = sh([b, "auth", "list"], check=False, timeout=60)
                authed = r.returncode == 0 and bool((r.stdout or "").strip())
            except subprocess.TimeoutExpired:
                authed = False
        print(f"opencode:    {name:10} {a.get('model', '?')}  "
              + ("; ".join(problems) if problems else "ok") + f"  family {family_of(ConfigView(cfg), name)}")
    if tables and authed is False:
        print("opencode auth: no saved credentials -> run `opencode auth login` (OpenCode Go: paste the console key)")
        good = False
    return good
