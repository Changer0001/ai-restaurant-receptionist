"""
Spoken-Form Text Normalization

Rewrites a reply into the way a person would say it out loud, just
before it reaches the speech synthesizer.

This is not cosmetic. Kokoro phonemizes what it is given, so written
forms get read literally, and the results are the single most obviously
robotic thing on a call:

    "18.99"        -> "eighteen point nine nine"
    "619-401-1055" -> "six hundred nineteen, four hundred one, ..."
    "92020"        -> "ninety-two thousand and twenty"

A person says "eighteen ninety-nine", reads a phone number in digits,
and spells out a zip. No model — local or hosted — fixes this, because
the text really does say "18.99"; the fix belongs between the words and
the synthesizer.

Applied only to what is spoken. The stored transcript keeps the original
text, so the dashboard shows "18.99" as written.
"""

import re

_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
)
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")

# "oh" rather than "zero" — it's how digits are read aloud in a phone
# number, and reading one out is exactly when this matters.
_DIGIT_WORDS = ("oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def _small_number_to_words(number: int) -> str:
    """0-999 spelled out. Prices and party sizes never exceed this."""
    if number < 20:
        return _ONES[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        return _TENS[tens] if ones == 0 else f"{_TENS[tens]}-{_ONES[ones]}"
    hundreds, remainder = divmod(number, 100)
    if remainder == 0:
        return f"{_ONES[hundreds]} hundred"
    return f"{_ONES[hundreds]} hundred {_small_number_to_words(remainder)}"


def _digits_to_words(digits: str) -> str:
    return " ".join(_DIGIT_WORDS[int(digit)] for digit in digits)


def _speak_price(match: re.Match) -> str:
    dollars = int(match.group("dollars"))
    cents = int(match.group("cents"))

    if cents == 0:
        unit = "dollar" if dollars == 1 else "dollars"
        return f"{_small_number_to_words(dollars)} {unit}"

    # "eighteen ninety-nine", the way a price is actually said — not
    # "eighteen dollars and ninety-nine cents", which nobody says at a
    # counter.
    return f"{_small_number_to_words(dollars)} {_small_number_to_words(cents)}"


def _speak_phone(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return str(match.group(0))

    # Grouped with commas so the synthesizer pauses where a person
    # pauses, giving the listener time to write it down.
    return (
        f"{_digits_to_words(digits[:3])}, "
        f"{_digits_to_words(digits[3:6])}, "
        f"{_digits_to_words(digits[6:])}"
    )


_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
_PRICE = re.compile(r"\$?(?P<dollars>\d{1,3})\.(?P<cents>\d{2})(?!\d)")
# Five digits standing alone is a zip code in this domain; read as digits
# rather than as ninety-two thousand and twenty.
_ZIP = re.compile(r"(?<!\d)(\d{5})(?!\d)")

# Written shorthand that a person would say in full. Deliberately short:
# every entry here is a rewrite that fires on real caller-facing text, and
# a wrong one is a mispronunciation on a live call.
_ABBREVIATIONS = (
    (re.compile(r"\bSt\.(?=\s|$)"), "Street"),
    (re.compile(r"\bAve\.(?=\s|$)"), "Avenue"),
    (re.compile(r"\bBlvd\.(?=\s|$)"), "Boulevard"),
    (re.compile(r"\bRd\.(?=\s|$)"), "Road"),
    (re.compile(r"\bapprox\.?"), "about"),
    (re.compile(r"&"), " and "),
    (re.compile(r"%"), " percent"),
)

_DIRECTIONS = {
    "N": "North", "S": "South", "E": "East", "W": "West",
    "NE": "Northeast", "NW": "Northwest", "SE": "Southeast", "SW": "Southwest",
}

# A compass abbreviation in a street name. With a period ("388 E. Main
# St") it can't be anything else. Without one ("388 E Main St") a bare
# capital letter is too ordinary to rewrite on sight, so it only counts
# when a house number sits right in front of it.
_DIRECTION_DOTTED = re.compile(r"\b(NE|NW|SE|SW|N|S|E|W)\.\s+(?=[A-Za-z])")
_DIRECTION_AFTER_NUMBER = re.compile(r"(?<=\d\s)(NE|NW|SE|SW|N|S|E|W)\s+(?=[A-Z])")

# US state codes, spelled out so an address is read the way it's spoken.
# Matched only in the "City, ST" position — several of these codes are
# also ordinary words (OR, IN, OK, ME, HI), and rewriting those wherever
# they appear would mangle sentences that have nothing to do with an
# address.
_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "Washington D C", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE_AFTER_CITY = re.compile(r",\s*([A-Z]{2})\b(?=[\s,.]|$)")


def _expand_state(match: re.Match) -> str:
    return f", {_STATES.get(match.group(1), match.group(1))}"


def to_spoken(text: str) -> str:
    """Rewrite text into the form it should be read aloud in."""
    spoken = _PHONE.sub(_speak_phone, text)
    spoken = _PRICE.sub(_speak_price, spoken)
    spoken = _ZIP.sub(lambda m: _digits_to_words(m.group(1)), spoken)

    spoken = _DIRECTION_DOTTED.sub(lambda m: f"{_DIRECTIONS[m.group(1)]} ", spoken)
    spoken = _DIRECTION_AFTER_NUMBER.sub(lambda m: f"{_DIRECTIONS[m.group(1)]} ", spoken)
    spoken = _STATE_AFTER_CITY.sub(_expand_state, spoken)

    for pattern, replacement in _ABBREVIATIONS:
        spoken = pattern.sub(replacement, spoken)

    # A stray dollar sign left by a price the pattern didn't match (an
    # unusual format, a bare "$5") would otherwise be voiced as the
    # symbol's name in the middle of a sentence.
    spoken = re.sub(r"\$(\d+)", lambda m: f"{_small_number_to_words(int(m.group(1)))} dollars", spoken)

    return re.sub(r"\s{2,}", " ", spoken).strip()
