"""
Conversation Package

The AI receptionist's "brain": conversation state, intent classification,
reservation slot-filling, RAG-grounded FAQ answering, and the state
machine that ties them together (app/conversation/engine.py).

This package produces and consumes plain text. It has no knowledge of
Twilio, audio, or telephony — Phase 5 wires it to a live call by feeding
it STT output and speaking its responses via TTS. That separation is
deliberate: the conversation logic is fully testable without a phone
call, a GPU, or a live Ollama server (see tests/fakes.py's
ScriptedLLMProvider).
"""
