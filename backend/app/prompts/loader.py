"""
Prompt Loader

Loads a prompt template file from this package and renders it with
variable substitution.
"""

import functools
from pathlib import Path
from typing import Any

_PROMPTS_DIR = Path(__file__).parent


@functools.lru_cache(maxsize=None)
def _read_prompt_file(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {filename}")
    return path.read_text(encoding="utf-8")


def render_prompt(filename: str, **variables: Any) -> str:
    """
    Load a prompt template file and substitute {placeholder} variables.

    Uses str.format(), so a template referencing a variable the caller
    forgot to pass raises KeyError immediately — failing loudly here beats
    silently sending a literal "{placeholder}" to the LLM.
    """
    template = _read_prompt_file(filename)
    return template.format(**variables)
