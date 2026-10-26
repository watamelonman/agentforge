"""glm = Claude Code pointed at Z.ai: API key lookup and the per-run environment."""
from __future__ import annotations

import os
from pathlib import Path

ZAI_BASE_URL = "https://api.z.ai/api/anthropic"      # docs.z.ai/devpack/tool/claude
GLM_DEFAULT_MODEL = "glm-5.3"
GLM_DEFAULT_HAIKU = "glm-5.3-flash"
DEFAULT_ZAI_ENV_FILE = "~/.config/agentforge/zai.env"
DEFAULT_GLM_CONFIG_DIR = "~/.config/agentforge/glm-claude"
# Credentials/endpoints a parent shell may export that must never leak into a glm run
# (they would override or conflict with the Z.ai token).
GLM_STRIP_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                 "CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_SMALL_FAST_MODEL")


def read_env_file(path):
    """Parse a KEY=VALUE file (blank lines, # comments, `export ` prefix and quotes allowed)."""
    out = {}
    try:
        lines = Path(path).expanduser().read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k] = v
    return out


def glm_key(a):
    """Return (key, source) for the Z.ai API key; key is None when not found.

    Order: the process env var named by key_env (default ZAI_API_KEY), then that name in
    key_file (default ~/.config/agentforge/zai.env). The key is never logged or printed."""
    name = a.get("key_env", "ZAI_API_KEY")
    if os.environ.get(name):
        return os.environ[name], f"env ${name}"
    f = a.get("key_file", DEFAULT_ZAI_ENV_FILE)
    v = read_env_file(f).get(name)
    return (v, f"file {f}") if v else (None, f"not found (${name} unset, none in {f})")


def glm_env(a, base):
    """Environment for one glm run: `base` plus Z.ai overrides. Returns a new dict;
    os.environ, ~/.claude and the claude vendor's environment are never modified.

    Variable names follow docs.z.ai/devpack/tool/claude: ANTHROPIC_BASE_URL,
    ANTHROPIC_AUTH_TOKEN, ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL, API_TIMEOUT_MS,
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC; plus ANTHROPIC_MODEL (Claude Code's own
    model-selection variable) and CLAUDE_CONFIG_DIR, a separate config dir so glm sessions
    never see or touch the claude.ai login/state in ~/.claude."""
    key, src = glm_key(a)
    if not key:
        raise RuntimeError(f"glm: Z.ai API key {src}")
    env = {k: v for k, v in base.items() if k not in GLM_STRIP_ENV and k != a.get("key_env", "ZAI_API_KEY")}
    model = a.get("model") or GLM_DEFAULT_MODEL
    cfg = Path(a.get("config_dir", DEFAULT_GLM_CONFIG_DIR)).expanduser()
    cfg.mkdir(parents=True, exist_ok=True, mode=0o700)
    env.update({
        "ANTHROPIC_BASE_URL": a.get("base_url", ZAI_BASE_URL),
        "ANTHROPIC_AUTH_TOKEN": key,
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": a.get("opus_model") or model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": a.get("sonnet_model") or model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": a.get("haiku_model") or GLM_DEFAULT_HAIKU,
        "API_TIMEOUT_MS": str(a.get("api_timeout_ms", 3000000)),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CONFIG_DIR": str(cfg),
    })
    return env


def redact(text, secret):
    """Remove a secret from text before it is printed or written anywhere."""
    return text.replace(secret, "[REDACTED]") if secret else text
