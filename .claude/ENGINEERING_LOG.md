# Engineering Log

Persistent memory for the autonomous engineering loop on this AI phone
receptionist. **Read this file first** after any context loss, then
continue from `## Next Autonomous Action

Audit the remaining provider boundaries for the same defect GAP-006
found, rather than waiting to be surprised by each one on a live call.
GAP-006 covered the engine raising during a turn. Three sibling paths
are not yet covered and are reachable on a real call:

1. `CallSession.start()` — the greeting. If TTS raises here the call is
   answered and then silent from the very first second, which is worse
   than the case just fixed. Read the method, decide whether a failure
   there should fall back to Twilio's own `<Say>` or hang up honestly,
   and test it.
2. `_speak()` mid-reply — TTS raising on the second sentence of a
   three-sentence answer leaves a truncated reply and no recovery.
3. `caller_service.get_caller_profile` — already wrapped in try/except,
   but confirm the same is true of `describe_reservation`, which now
   runs on the booking path where a formatting error would fail a turn
   that had already written a reservation to the database.

Write the reproduction tests first, as with GAP-006 — each must fail
before its fix.