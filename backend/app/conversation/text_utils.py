"""
LLM Output Post-Processing

Small, defensive helpers applied to every raw LLM response before it's
used — models don't reliably follow "respond with only X" instructions.
"""

import json
import re
from typing import Any, Optional

# Qwen3 (and other "thinking" models) can emit a <think>...</think> block
# before its actual answer, even when asked for a single-word/JSON-only
# response. Never let that reach a caller or a parser expecting clean
# output.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> str:
    """Remove any <think>...</think> block and surrounding whitespace."""
    return _THINK_BLOCK_RE.sub("", text).strip()


def _find_balanced_object_end(text: str, start: int) -> Optional[int]:
    """Scan from `start` (a '{') for the index of its matching '}',
    respecting quoted strings so a brace inside a string value doesn't
    miscount. Returns None if the braces never balance."""
    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        char = text[i]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i

    return None


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """
    Find and parse the first balanced {...} JSON object in text.

    Models asked for "only JSON" sometimes still wrap it in a code fence
    or add a stray sentence — this scans for a structurally balanced
    brace span rather than assuming the whole response is clean JSON.
    Returns None if no valid object is found, rather than raising —
    callers should treat that as "couldn't understand" and fail soft,
    not crash the conversation.
    """
    start = text.find("{")
    if start == -1:
        return None

    end = _find_balanced_object_end(text, start)
    if end is None:
        return None

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, dict) else None
