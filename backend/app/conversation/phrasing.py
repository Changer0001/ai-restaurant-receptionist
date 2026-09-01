"""
Varied Phrasing

Picking which wording to use for a line the assistant says often.

Hearing the identical sentence twice in a row is the fastest way a
caller works out they're talking to a machine — people rephrase
themselves without thinking about it, and a line repeated word for word
is something only a recording does. Real calls have shown it repeatedly:
the same "I don't have that information on hand" twice in a row, and
"anything else I can help with?" after every single acknowledgement.

So each of these lines has several phrasings, and the one just used is
excluded rather than merely made less likely — "randomly different" and
"never the same twice running" are not the same thing, and it's the
immediate repeat that gives the game away.
"""

import random
from typing import Optional


def pick(options: tuple[str, ...], avoid: Optional[str] = None) -> str:
    """
    One of `options`, never the one in `avoid` if there's an alternative.

    Falls back to the full set when every option is excluded, so a
    single-option list still works and this can never fail to produce a
    line to say.
    """
    candidates = tuple(option for option in options if option != avoid) or options
    return random.choice(candidates)
