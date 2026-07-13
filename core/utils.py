"""
Shared text-processing utilities.

Kept intentionally small — only things genuinely used by ≥2 modules
belong here. Module-specific helpers stay in their own module.
"""

from __future__ import annotations


def strip_code_fences(text: str) -> str:
    """Strip markdown code fences (```…```) that LLMs sometimes wrap
    around JSON or HTML responses, returning the inner content.

    Handles both bare ``` and language-tagged fences (```json, ```html).
    Safe to call on text that doesn't have fences — returns it unchanged.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop the opening fence line (```json, ```html, or bare ```)
        lines = lines[1:]
        # Drop the closing fence line if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()
