"""Codex (and the mock agent): the final message is written to a separate file."""
from __future__ import annotations


def read_out_file(out_file):
    """Text of `codex exec --output-last-message` (or the mock's) file; '' when absent."""
    return out_file.read_text(errors="replace") if out_file.exists() else ""
