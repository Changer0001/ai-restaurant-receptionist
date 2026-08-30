"""Tests for app.conversation.text_utils."""

from app.conversation.text_utils import extract_json_object, strip_thinking


def test_strip_thinking_removes_block():
    assert strip_thinking("<think>reasoning here</think>FAQ") == "FAQ"


def test_strip_thinking_handles_no_block():
    assert strip_thinking("  RESERVATION  ") == "RESERVATION"


def test_strip_thinking_is_case_insensitive():
    assert strip_thinking("<THINK>hmm</THINK>ORDER") == "ORDER"


def test_extract_json_object_clean():
    assert extract_json_object('{"a": 1, "b": "hello"}') == {"a": 1, "b": "hello"}


def test_extract_json_object_with_surrounding_text():
    assert extract_json_object('Sure, here you go: {"a": 1} Hope that helps!') == {"a": 1}


def test_extract_json_object_with_brace_inside_string():
    result = extract_json_object('{"note": "call {back} later", "x": 2}')
    assert result == {"note": "call {back} later", "x": 2}


def test_extract_json_object_code_fenced():
    text = '```json\n{"a": null, "b": 5}\n```'
    assert extract_json_object(text) == {"a": None, "b": 5}


def test_extract_json_object_no_json_returns_none():
    assert extract_json_object("no json here") is None


def test_extract_json_object_malformed_returns_none():
    assert extract_json_object('{"a": }') is None


def test_extract_json_object_non_dict_returns_none():
    assert extract_json_object("[1, 2, 3]") is None
