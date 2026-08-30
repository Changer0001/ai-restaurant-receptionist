"""Tests for app.conversation.intent."""

from app.conversation.intent import classify_intent
from app.conversation.state import ConversationContext
from tests.fakes import ScriptedLLMProvider


async def test_classifies_faq():
    llm = ScriptedLLMProvider([], default="FAQ")
    context = ConversationContext(restaurant_id="r1")
    assert await classify_intent(llm, "Test Bistro", context, "Do you have outdoor seating?") == "FAQ"


async def test_classifies_reservation():
    llm = ScriptedLLMProvider([], default="RESERVATION")
    context = ConversationContext(restaurant_id="r1")
    assert await classify_intent(llm, "Test Bistro", context, "I'd like a table for four") == "RESERVATION"


async def test_strips_thinking_block_before_parsing():
    llm = ScriptedLLMProvider([], default="<think>hmm, this sounds like ordering</think>ORDER")
    context = ConversationContext(restaurant_id="r1")
    assert await classify_intent(llm, "Test Bistro", context, "I want to order food") == "ORDER"


async def test_invalid_label_falls_back_to_unclear():
    llm = ScriptedLLMProvider([], default="BANANA")
    context = ConversationContext(restaurant_id="r1")
    assert await classify_intent(llm, "Test Bistro", context, "asdf") == "UNCLEAR"


async def test_empty_response_falls_back_to_unclear():
    llm = ScriptedLLMProvider([], default="")
    context = ConversationContext(restaurant_id="r1")
    assert await classify_intent(llm, "Test Bistro", context, "asdf") == "UNCLEAR"


async def test_trailing_punctuation_is_stripped():
    llm = ScriptedLLMProvider([], default="FAQ.")
    context = ConversationContext(restaurant_id="r1")
    assert await classify_intent(llm, "Test Bistro", context, "hours?") == "FAQ"


async def test_prompt_includes_conversation_history():
    llm = ScriptedLLMProvider([], default="FAQ")
    context = ConversationContext(restaurant_id="r1")
    context.add_turn("caller", "Hi there")
    context.add_turn("assistant", "Hello! How can I help?")

    await classify_intent(llm, "Test Bistro", context, "What are your hours?")

    assert len(llm.calls) == 1
    assert "Hi there" in llm.calls[0]
    assert "Hello! How can I help?" in llm.calls[0]
