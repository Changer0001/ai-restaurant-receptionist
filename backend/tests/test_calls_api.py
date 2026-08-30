"""Integration tests for the read-only call-history endpoints and
tenant isolation. Calls are only ever created by the voice pipeline
(app/voice/session.py), never through this API — these tests insert
Call/CallTranscript rows directly via the ORM to set up fixtures."""

from app.db.models import Call, CallOutcomeEnum, CallTranscript
from tests.conftest import auth_headers


def _register(client, email, restaurant_name):
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
        "restaurant_name": restaurant_name,
        "restaurant_timezone": "America/New_York",
    }
    return client.post("/api/auth/register", json=payload).json()


async def test_list_calls_returns_most_recent_first(client, db_session, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    from datetime import datetime, timedelta, timezone

    older = Call(
        restaurant_id=rid,
        call_sid="CA_older",
        caller_number="+1",
        called_number="+2",
        start_time=datetime.now(timezone.utc) - timedelta(hours=2),
        outcome=CallOutcomeEnum.FAQ_ANSWERED,
    )
    newer = Call(
        restaurant_id=rid,
        call_sid="CA_newer",
        caller_number="+1",
        called_number="+2",
        start_time=datetime.now(timezone.utc),
        outcome=CallOutcomeEnum.RESERVATION_CREATED,
    )
    db_session.add_all([older, newer])
    await db_session.commit()

    resp = client.get(f"/api/restaurants/{rid}/calls", headers=auth_headers(tokens["access_token"]))

    assert resp.status_code == 200
    call_sids = [c["call_sid"] for c in resp.json()]
    assert call_sids == ["CA_newer", "CA_older"]


async def test_get_call_detail_includes_transcript_turns(client, db_session, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    from datetime import datetime, timezone

    call = Call(
        restaurant_id=rid,
        call_sid="CA_detail",
        caller_number="+1",
        called_number="+2",
        start_time=datetime.now(timezone.utc),
        outcome=CallOutcomeEnum.FAQ_ANSWERED,
    )
    db_session.add(call)
    await db_session.flush()
    db_session.add_all(
        [
            CallTranscript(
                restaurant_id=rid,
                call_id=call.id,
                role="assistant",
                message="Hi there",
                timestamp=datetime.now(timezone.utc),
            ),
            CallTranscript(
                restaurant_id=rid,
                call_id=call.id,
                role="caller",
                message="What time do you close?",
                timestamp=datetime.now(timezone.utc),
                confidence=0.95,
            ),
        ]
    )
    await db_session.commit()

    resp = client.get(
        f"/api/restaurants/{rid}/calls/{call.id}", headers=auth_headers(tokens["access_token"])
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["call_sid"] == "CA_detail"
    assert len(body["transcripts"]) == 2
    assert body["transcripts"][1]["message"] == "What time do you close?"
    assert body["transcripts"][1]["confidence"] == 0.95


async def test_get_unknown_call_is_404(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()

    resp = client.get(
        f"/api/restaurants/{me['restaurant_id']}/calls/does-not-exist",
        headers=auth_headers(tokens["access_token"]),
    )

    assert resp.status_code == 404


async def test_cannot_list_or_view_another_restaurants_calls(client, db_session, register_payload):
    tokens_a = client.post("/api/auth/register", json=register_payload).json()
    me_a = client.get("/api/auth/me", headers=auth_headers(tokens_a["access_token"])).json()

    from datetime import datetime, timezone

    call_a = Call(
        restaurant_id=me_a["restaurant_id"],
        call_sid="CA_a_secret",
        caller_number="+1",
        called_number="+2",
        start_time=datetime.now(timezone.utc),
        outcome=CallOutcomeEnum.FAQ_ANSWERED,
    )
    db_session.add(call_a)
    await db_session.commit()

    tokens_b = _register(client, "owner-b@example.io", "Restaurant B")

    list_resp = client.get(
        f"/api/restaurants/{me_a['restaurant_id']}/calls",
        headers=auth_headers(tokens_b["access_token"]),
    )
    assert list_resp.status_code == 404

    detail_resp = client.get(
        f"/api/restaurants/{me_a['restaurant_id']}/calls/{call_a.id}",
        headers=auth_headers(tokens_b["access_token"]),
    )
    assert detail_resp.status_code == 404
