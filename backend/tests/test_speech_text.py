"""
Tests for app.voice.speech_text — how text gets read aloud.

Every case here is shaped like content the assistant actually says on a
call — prices and a phone number from the knowledge base, an address
from the location document — but the rules under test are deliberately
restaurant-agnostic: a business in another state, on another street,
serving another cuisine gets read aloud correctly with no code change.
"""

from app.voice.speech_text import to_spoken


def test_a_price_is_said_the_way_a_price_is_said():
    assert to_spoken("Beef shawarma is 18.99.") == "Beef shawarma is eighteen ninety-nine."
    assert to_spoken("Hummus is $8.99.") == "Hummus is eight ninety-nine."


def test_a_whole_dollar_price_keeps_the_word_dollars():
    assert to_spoken("It's 24.00.") == "It's twenty-four dollars."
    assert to_spoken("It's $1.00.") == "It's one dollar."


def test_a_phone_number_is_read_as_digits():
    assert to_spoken("Our number is 619-401-1055.") == (
        "Our number is six one nine, four oh one, one oh five five."
    )


def test_phone_numbers_in_other_formats_are_handled():
    for written in ("(619) 401-1055", "619.401.1055", "6194011055", "+1 619-401-1055"):
        spoken = to_spoken(f"Call {written} please.")
        assert "six one nine, four oh one, one oh five five" in spoken, written


def test_a_zip_code_is_spelled_out():
    spoken = to_spoken("We're at 388 East Main Street, El Cajon, California, 92020.")
    assert "nine two oh two oh" in spoken
    # The street number is a normal number and stays one.
    assert "388" in spoken


def test_street_abbreviations_are_expanded():
    assert "Street" in to_spoken("We're on Main St.")
    assert "Avenue" in to_spoken("We're on Grand Ave.")


def test_state_codes_are_expanded_for_any_state():
    """Nothing here is specific to the restaurant this was built for —
    onboarding a business in another state must not need a code change."""
    assert "California" in to_spoken("We're in El Cajon, CA 92020.")
    assert "Texas" in to_spoken("We're in Austin, TX.")
    assert "New York" in to_spoken("Brooklyn, NY")


def test_a_two_letter_word_that_is_also_a_state_code_is_left_alone():
    """OR, IN, OK, ME and HI are state codes and ordinary words. Only the
    "City, ST" position is safe to rewrite."""
    assert to_spoken("Takeout OR delivery, either works.") == "Takeout OR delivery, either works."
    assert "Indiana" not in to_spoken("Everything IN the case is fresh.")


def test_compass_abbreviations_in_addresses_are_expanded():
    assert "East Main" in to_spoken("We're at 388 E. Main Street.")
    assert "East Main" in to_spoken("We're at 388 E Main Street.")
    assert "Southwest Broadway" in to_spoken("We're at 120 SW Broadway.")


def test_a_bare_capital_letter_is_not_treated_as_a_direction():
    """Without a period and without a house number in front of it, a lone
    capital is just a letter — rewriting it is a mispronunciation."""
    plain = "Ask for N Roberts when you get here."
    assert to_spoken(plain) == plain


def test_symbols_that_would_be_voiced_as_symbols():
    assert "and" in to_spoken("Hummus & falafel")
    assert "&" not in to_spoken("Hummus & falafel")


def test_ordinary_text_is_left_alone():
    plain = "Yes, everything we serve is halal."
    assert to_spoken(plain) == plain


def test_years_and_times_are_not_mistaken_for_zips_or_prices():
    assert "2018" in to_spoken("We opened in 2018.")
    assert "9 AM to 10 PM" in to_spoken("We're open every day, 9 AM to 10 PM.")


def test_party_sizes_and_street_numbers_survive():
    spoken = to_spoken("I have you down for 5 people at 388 East Main Street.")
    assert "5 people" in spoken
    assert "388" in spoken
