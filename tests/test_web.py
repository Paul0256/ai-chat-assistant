from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from assistant.adapters.web import create_app

CID = "test-conversation-1"


@pytest.fixture
def client(assistant):
    return TestClient(create_app(assistant))


def test_greeting(client):
    r = client.get("/api/greeting")
    assert r.status_code == 200 and "Riverside Dental Studio" in r.json()["text"]


def test_chat_answers_from_documents(client):
    r = client.post("/api/chat", json={"conversation_id": CID, "message": "What are your opening hours?"})
    assert r.json() == {
        "kind": "answer",
        "text": "Monday to Thursday 8:00 to 18:00, Friday 8:00 to 15:00, Saturday 9:00 to 13:00. "
        "We are closed on Sundays and public holidays.",
        "offer_handoff": False,
    }


def test_unknown_question_offers_handoff_and_button_notifies_staff(client, notifier):
    r = client.post("/api/chat", json={"conversation_id": CID, "message": "Do you sell gift cards?"})
    assert r.json()["kind"] == "not_found" and r.json()["offer_handoff"]
    r = client.post("/api/handoff", json={"conversation_id": CID})
    assert r.json()["kind"] == "handoff"
    assert notifier.requests[0].channel == "web" and notifier.requests[0].transcript


@pytest.mark.parametrize("cid", ["short", "has spaces in it", "x" * 65, "<script>alert(1)</script>"])
def test_bad_conversation_ids_are_rejected(client, cid):
    r = client.post("/api/chat", json={"conversation_id": cid, "message": "hi"})
    assert r.status_code in (400, 422)


def test_huge_body_is_rejected_before_the_core(client, conversation_log):
    r = client.post("/api/chat", json={"conversation_id": CID, "message": "x" * 5000})
    assert r.status_code == 422 and conversation_log.entries == []


def test_per_ip_limit(assistant):
    client = TestClient(create_app(assistant, per_ip_per_minute=2))
    for i in range(2):
        assert (
            client.post("/api/chat", json={"conversation_id": f"conversation-{i}", "message": "hours?"}).status_code
            == 200
        )
    r = client.post("/api/chat", json={"conversation_id": "conversation-9", "message": "hours?"})
    assert r.status_code == 429


def test_widget_and_demo_page_are_served(client):
    js = client.get("/widget.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert "textContent" in js.text and "innerHTML = text" not in js.text
    page = client.get("/")
    assert page.status_code == 200 and 'src="/widget.js"' in page.text


def test_no_api_docs_in_production(client):
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_cors_only_for_allowed_origins(assistant):
    client = TestClient(create_app(assistant, allowed_origins=["https://www.clinic.example"]))
    ok = client.options(
        "/api/chat",
        headers={"Origin": "https://www.clinic.example", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "https://www.clinic.example"
    bad = client.options(
        "/api/chat", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in bad.headers
