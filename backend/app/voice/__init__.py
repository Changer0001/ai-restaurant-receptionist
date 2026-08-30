"""
Voice Package

Wires the Phase 4 conversation engine to a live Twilio phone call:
receives caller audio from a Media Streams WebSocket, runs it through
STT, feeds the transcript to the conversation engine, synthesizes the
response via TTS, and streams synthesized audio back. See session.py.
"""
