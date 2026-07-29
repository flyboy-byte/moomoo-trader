"""Thin Haiku wrapper for embedded research interpretation.

Usage in any script:
    if args.interpret:
        from mm.analyst import haiku_interpret
        print(haiku_interpret(captured_output, question="What stands out?"))
"""
from __future__ import annotations

import anthropic

from . import config as _config

_HAIKU = "claude-haiku-4-5-20251001"


def haiku_interpret(table_text: str, question: str = "") -> str:
    """Send table_text to Haiku, return its interpretation."""
    q = question or (
        "What stands out in these results? Highlight the most actionable pattern "
        "or anomaly in 3-5 sentences. Be specific about numbers."
    )
    prompt = f"{table_text}\n\n{q}"
    client = anthropic.Anthropic(api_key=_config.cfg.anthropic_api_key)
    msg = client.messages.create(
        model=_HAIKU,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in msg.content:
        if hasattr(block, "text"):
            return block.text.strip()
    raise ValueError(f"No text block in Haiku response: {msg.content}")
