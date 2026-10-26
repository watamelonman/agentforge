"""Vendor registry: which vendors exist, which CLI (harness) and model family each one uses."""
from __future__ import annotations

from .util import die

# Built-in vendors. More vendors come from forge.toml: every [agents.<name>] table with
# harness = "opencode" is one OpenCode-driven model (vendor_names()).
VENDORS = ("claude", "codex", "glm", "grok")
# Which CLI ("harness") each built-in vendor runs. glm is Claude Code pointed at Z.ai, so it
# shares claude's harness (docs/VENDORS.md).
HARNESS = {"claude": "claude-code", "glm": "claude-code", "codex": "codex", "grok": "grok-build"}
# Harness types a forge.toml vendor table may declare with `harness = "..."`.
CUSTOM_HARNESSES = ("opencode",)
# Model family (lab) per built-in vendor. Cross review prefers a reviewer from another family:
# two models from one lab share more blind spots than two CLIs running different labs' models.
FAMILY = {"claude": "anthropic", "codex": "openai", "glm": "zhipu", "grok": "xai"}
# Family guesses for forge.toml vendors without an explicit `family`, matched in order against
# the model id after its provider prefix ("opencode-go/kimi-k3" -> "kimi-k3" -> moonshot).
FAMILY_GUESS = (("claude", "anthropic"), ("haiku", "anthropic"), ("sonnet", "anthropic"),
                ("opus", "anthropic"), ("gpt", "openai"), ("codex", "openai"), ("glm", "zhipu"),
                ("kimi", "moonshot"), ("deepseek", "deepseek"), ("qwen", "alibaba"),
                ("grok", "xai"), ("mimo", "xiaomi"), ("gemini", "google"), ("minimax", "minimax"))
CLAUDE_CODE_VENDORS = ("claude", "glm")


def agent_cfg(proj, vendor):
    """The [agents.<vendor>] table ({} when absent)."""
    return proj.c("agents", vendor, default={}) or {}


def vendor_names(proj):
    """All vendors this project can use: the built-ins plus every [agents.<name>] table that
    declares a custom harness (today only harness = "opencode"), in forge.toml order."""
    agents = proj.c("agents", default={}) or {}
    extra = [k for k, v in agents.items()
             if isinstance(v, dict) and k not in VENDORS and v.get("harness") in CUSTOM_HARNESSES]
    return list(VENDORS) + extra


def harness_of(proj, vendor):
    """CLI a vendor runs: fixed for built-ins, `harness` from its table otherwise (None if unknown)."""
    return HARNESS.get(vendor) or agent_cfg(proj, vendor).get("harness")


def family_of(proj, vendor):
    """Model family (lab) of a vendor: explicit `family` key, else the built-in table, else a
    guess from the model id (FAMILY_GUESS), else the vendor's own name (a family of one)."""
    a = agent_cfg(proj, vendor)
    if a.get("family"):
        return a["family"]
    if vendor in FAMILY:
        return FAMILY[vendor]
    model = str(a.get("model") or "").lower().split("/")[-1]
    for needle, fam in FAMILY_GUESS:
        if needle in model:
            return fam
    return vendor


def check_vendor(proj, vendor):
    """Exit with a clear message when a --agent value is not a vendor of this project."""
    if vendor not in vendor_names(proj):
        die(f"unknown vendor {vendor!r}; this project has: {', '.join(vendor_names(proj))} "
            f"(add an [agents.<name>] table with harness = \"opencode\" for more)")
    return vendor


def used_vendors(proj):
    """Vendors this project's config refers to (workers, review pool, roles), plus opencode tables."""
    ag = proj.c("agents", default={}) or {}
    names = list(ag.get("workers", ["claude"])) + list(ag.get("review_pool", []) or [])
    names += [ag.get(k) for k in ("planner", "auditor", "reviewer")]
    names += vendor_names(proj)[len(VENDORS):]
    known = vendor_names(proj)
    return [v for v in dict.fromkeys(names) if v in known]
