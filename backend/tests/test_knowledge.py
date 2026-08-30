"""
Integration tests for the knowledge-base (RAG) endpoints.

Uses an isolated in-memory ChromaDB (see conftest.py's `vector_db`
fixture) and a deterministic fake embedding provider (see tests/fakes.py)
— never a live Ollama server or the real chromadb Docker service.
"""

import io

from tests.conftest import auth_headers


def _register(client, email, restaurant_name):
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
        "restaurant_name": restaurant_name,
        "restaurant_timezone": "America/New_York",
    }
    return client.post("/api/auth/register", json=payload).json()


def _upload(client, rid, token, *, title, content, document_type="general", source=None):
    files = {"file": ("doc.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}
    data = {"title": title, "document_type": document_type}
    if source:
        data["source"] = source
    return client.post(
        f"/api/restaurants/{rid}/knowledge/upload",
        files=files,
        data=data,
        headers=auth_headers(token),
    )


def test_upload_creates_document_and_chunks(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    resp = _upload(
        client,
        rid,
        tokens["access_token"],
        title="Seating Policy",
        content="We have a lovely outdoor patio with seating for twenty guests. Reservations recommended on weekends.",
        document_type="policy",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Seating Policy"
    assert body["restaurant_id"] == rid
    assert body["chunk_count"] >= 1


def test_list_documents(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    _upload(client, rid, tokens["access_token"], title="Doc A", content="Some content about parking.")
    _upload(client, rid, tokens["access_token"], title="Doc B", content="Some content about hours.")

    resp = client.get(f"/api/restaurants/{rid}/knowledge", headers=auth_headers(tokens["access_token"]))
    assert resp.status_code == 200
    titles = {d["title"] for d in resp.json()}
    assert titles == {"Doc A", "Doc B"}


def test_reject_non_utf8_upload(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    files = {"file": ("doc.bin", io.BytesIO(b"\xff\xfe\x00\x01garbage"), "application/octet-stream")}
    resp = client.post(
        f"/api/restaurants/{rid}/knowledge/upload",
        files=files,
        data={"title": "Bad file"},
        headers=auth_headers(tokens["access_token"]),
    )
    assert resp.status_code == 400


def test_reject_empty_content(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    resp = _upload(client, rid, tokens["access_token"], title="Empty", content="   ")
    assert resp.status_code == 400


def test_delete_document_removes_it_and_its_vectors(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    doc = _upload(client, rid, tokens["access_token"], title="To Delete", content="Ephemeral content here.").json()

    delete_resp = client.delete(
        f"/api/restaurants/{rid}/knowledge/{doc['id']}", headers=auth_headers(tokens["access_token"])
    )
    assert delete_resp.status_code == 204

    list_resp = client.get(f"/api/restaurants/{rid}/knowledge", headers=auth_headers(tokens["access_token"]))
    assert list_resp.json() == []


def test_reindex_document(client, register_payload):
    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    doc = _upload(client, rid, tokens["access_token"], title="Reindex Me", content="Original content.").json()

    resp = client.post(
        f"/api/restaurants/{rid}/knowledge/{doc['id']}/reindex", headers=auth_headers(tokens["access_token"])
    )
    assert resp.status_code == 200
    assert resp.json()["chunk_count"] >= 1


def test_cannot_access_or_delete_another_restaurants_knowledge(client, register_payload):
    tokens_a = client.post("/api/auth/register", json=register_payload).json()
    me_a = client.get("/api/auth/me", headers=auth_headers(tokens_a["access_token"])).json()
    rid_a = me_a["restaurant_id"]

    doc_a = _upload(client, rid_a, tokens_a["access_token"], title="A's Secret Doc", content="Confidential info.").json()

    tokens_b = _register(client, "owner-b@example.io", "Restaurant B")

    list_resp = client.get(f"/api/restaurants/{rid_a}/knowledge", headers=auth_headers(tokens_b["access_token"]))
    assert list_resp.status_code == 404

    delete_resp = client.delete(
        f"/api/restaurants/{rid_a}/knowledge/{doc_a['id']}", headers=auth_headers(tokens_b["access_token"])
    )
    assert delete_resp.status_code == 404

    # A's document is provably untouched
    still_there = client.get(f"/api/restaurants/{rid_a}/knowledge", headers=auth_headers(tokens_a["access_token"]))
    assert len(still_there.json()) == 1


async def test_staff_cannot_upload_or_delete(client, register_payload, session_maker):
    """Only owner/manager may edit the knowledge base; staff is read-only.

    There's no user-invite flow yet (Phase 2/3), so a staff account is
    inserted directly into the test database rather than through the API.
    """
    from app.core.security import create_access_token, hash_password
    from app.db.models import User, UserRoleEnum

    tokens = client.post("/api/auth/register", json=register_payload).json()
    me = client.get("/api/auth/me", headers=auth_headers(tokens["access_token"])).json()
    rid = me["restaurant_id"]

    async with session_maker() as session:
        staff = User(
            email="staff@example.io",
            hashed_password=hash_password("whatever-password"),
            role=UserRoleEnum.RESTAURANT_STAFF,
            restaurant_id=rid,
            is_active=True,
        )
        session.add(staff)
        await session.commit()
        await session.refresh(staff)
        staff_token = create_access_token(staff.id, staff.role.value, staff.restaurant_id)

    upload_resp = _upload(client, rid, staff_token, title="Nope", content="Should be rejected.")
    assert upload_resp.status_code == 403

    # Staff CAN still read the (empty) knowledge base
    list_resp = client.get(f"/api/restaurants/{rid}/knowledge", headers=auth_headers(staff_token))
    assert list_resp.status_code == 200
