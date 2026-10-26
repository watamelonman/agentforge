"""argv for one headless agent run, per CLI ("harness"). See docs/VENDORS.md."""
from __future__ import annotations

import sys

from ..util import MOCK_AGENT
from ..vendors import CLAUDE_CODE_VENDORS, harness_of
from .claude import claude_code_cmd
from .codex import codex_cmd
from .grok import grok_cmd
from .opencode import opencode_cmd


def build_cmd(proj, vendor, role, prompt, cwd, out_file, schema):
    """Return argv for a headless agent run. role: work | review | plan | audit."""
    a = proj.c("agents", vendor, default={})
    readonly = role != "work"
    if proj.mock:
        return [sys.executable, str(MOCK_AGENT), vendor, role, str(out_file)]
    if vendor in CLAUDE_CODE_VENDORS:
        return claude_code_cmd(vendor, a, readonly, prompt, schema)
    if vendor == "codex":
        return codex_cmd(proj, a, readonly, cwd, out_file, schema)
    if vendor == "grok":
        return grok_cmd(a, readonly, cwd, out_file, schema)
    if harness_of(proj, vendor) == "opencode":
        return opencode_cmd(proj, vendor, a, role, prompt, cwd, out_file)
    raise ValueError(vendor)
