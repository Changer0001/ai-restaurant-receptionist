"""Prompts Package

Versioned prompt template files, loaded and rendered by loader.py.
Kept as plain-text files (not inline strings) so a prompt can be
reviewed and edited independently of code.
"""

from app.prompts.loader import render_prompt

__all__ = ["render_prompt"]
