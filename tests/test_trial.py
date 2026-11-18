from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant.adapters.web import create_app
from assistant.core import MockModel
from assistant.trial import Page, TrialError, crawl, draft, pick_links, write_trial
from assistant.wiring import build_trials

HOME = """<html><head><title>Bright Smile Dental | Tacoma</title><script>var x=1</script></head><body>
<nav><a href="/about-us/">About</a> <a href="/insurance">Insurance &amp; Payment</a> <a href="/faq">FAQ</a>
<a href="/blog/whitening-tips">Blog</a> <a href="https://facebook.com/brightsmile">Facebook</a>
<a href="/forms/new-patient.pdf">Form</a> <a href="/contact#map">Contact us</a></nav>
<h1>Bright Smile Dental</h1><p>Call (253) 555-0142. Open Mon-Thu 7:30-5:00.</p></body></html>"""


def site(blocked: bool = False) -> httpx.Client:
    pages = {
        "/": HOME,
        "/faq": "<html><title>FAQ</title><body><h2>Do you take Delta Dental?</h2><p>Yes.</p></body></html>",
        "/insurance": "<html><body><p>We accept Delta Dental and MetLife.</p></body></html>",
        "/contact": "<html><body><p>2520 N Alder St, Tacoma</p></body></html>",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if blocked:
            return httpx.Response(403, text="Forbidden")
        html = pages.get(request.url.path)
        if html is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_pick_links_prefers_patient_pages_on_the_same_site():
    links = [
        ("https://brightsmile.example/about-us/", "About"),
        ("https://brightsmile.example/insurance", "Insurance & Payment"),
        ("https://www.brightsmile.example/faq", "FAQ"),
        ("https://brightsmile.example/blog/whitening-tips", "Blog"),
        ("https://facebook.com/brightsmile", "Facebook"),
        ("https://brightsmile.example/forms/new-patient.pdf", "Form"),
    ]
    picked = pick_links("https://brightsmile.example/", links, 5)
    assert picked == [
        "https://www.brightsmile.example/faq",
        "https://brightsmile.example/insurance",
        "https://brightsmile.example/about-us/",
    ]


def test_crawl_reads_home_and_key_pages_as_text():
    pages = crawl("https://brightsmile.example", site())
    urls = [p.url for p in pages]
    assert urls[0] == "https://brightsmile.example"
    assert "https://brightsmile.example/faq" in urls and "https://brightsmile.example/insurance" in urls
    assert "https://brightsmile.example/contact" in urls  # "#map" dropped
    assert pages[0].title == "Bright Smile Dental | Tacoma"
    assert "Call (253) 555-0142" in pages[0].text and "var x" not in pages[0].text


def test_blocked_site_stops_the_build():
    with pytest.raises(TrialError, match="blocks automated visits"):
        crawl("https://brightsmile.example", site(blocked=True))


DRAFT = {
    "business": {
        "name": "Bright Smile Dental",
        "phone": "(253)5550142",
        "email": "",
        "address": "2520 N Alder St, Tacoma",
    },
    "documents": [
        {
            "title": "Insurance and payment",
            "content": "# Insurance and payment\n\n## Do you take Delta Dental?\n"
            "Yes, we accept Delta Dental and MetLife.",
        },
        {"title": "Hours", "content": "## When are you open?\nMonday to Thursday 7:30-5:00."},
    ],
    "test_questions": [
        {"question": "Do you take MetLife?", "expect": "answer", "contains": ["MetLife", "Cigna"]},
        {"question": "Do you sell gift cards?", "expect": "not_found", "contains": []},
    ],
}


def test_draft_sends_pages_and_parses_json():
    calls = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            block = SimpleNamespace(type="text", text=json.dumps(DRAFT))
            return SimpleNamespace(stop_reason="end_turn", content=[block])

    data = draft(
        [Page("https://brightsmile.example/faq", "FAQ", "Delta Dental: yes")], SimpleNamespace(messages=FakeMessages())
    )
    assert data == DRAFT
    sent = calls[0]
    assert "Delta Dental: yes" in sent["messages"][0]["content"]
    assert sent["output_config"]["format"]["type"] == "json_schema"


def test_write_trial_makes_a_loadable_folder(tmp_path):
    pages = [Page("https://brightsmile.example/", "Home", "x")]
    folder = write_trial(DRAFT, pages, tmp_path)
    assert folder.name == "bright-smile-dental"
    business = json.loads((folder / "business.json").read_text())
    assert business["medical"] is True and business["emergency_number"] == "911"
    assert business["website"] == "https://brightsmile.example/"
    assert business["phone"] == "(253) 555-0142"
    docs = sorted(p.name for p in (folder / "knowledge").iterdir())
    assert docs == ["01-insurance-and-payment.md", "02-hours.md"]
    assert (folder / "knowledge" / "02-hours.md").read_text().startswith("# Hours\n")
    questions = json.loads((folder / "test_questions.json").read_text())
    assert questions[0]["contains"] == ["MetLife"]  # "Cigna" is not in the documents
    assert (folder / "sources.txt").read_text().strip() == "https://brightsmile.example/"


def test_trials_are_served_under_their_own_path(tmp_path, make_assistant):
    write_trial(DRAFT, [Page("https://brightsmile.example/", "Home", "x")], tmp_path)
    trials = build_trials(str(tmp_path), MockModel())
    assert list(trials) == ["bright-smile-dental"]
    client = TestClient(create_app(make_assistant(), trials=trials))

    page = client.get("/t/bright-smile-dental/")
    assert page.status_code == 200
    assert "Test version for Bright Smile Dental" in page.text
    assert 'data-api="/t/bright-smile-dental"' in page.text
    assert "<li>Do you take MetLife?</li>" in page.text

    assert client.get("/t/bright-smile-dental", follow_redirects=False).status_code in (307, 308)
    assert client.get("/t/bright-smile-dental/widget.js").status_code == 200
    greeting = client.get("/t/bright-smile-dental/api/greeting").json()["text"]
    assert "Bright Smile Dental" in greeting
    reply = client.post(
        "/t/bright-smile-dental/api/chat",
        json={"conversation_id": "trial-conversation-1", "message": "Do you take Delta Dental?"},
    ).json()
    assert reply["kind"] == "answer" and "Delta Dental" in reply["text"]
    # The main demo is untouched.
    assert "Riverside Dental Studio" in client.get("/api/greeting").json()["text"]


def test_a_broken_trial_folder_is_skipped(tmp_path):
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "business.json").write_text("{}")
    assert build_trials(str(tmp_path), MockModel()) == {}


def test_build_trial_command_parses_and_asks_for_a_key(monkeypatch):
    import sys

    from assistant.__main__ import main

    for name in ("ANTHROPIC_API_KEY", "ASSISTANT_ANTHROPIC_API_KEY"):
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(sys, "argv", ["assistant", "build-trial", "https://brightsmile.example"])
    with pytest.raises(SystemExit, match="needs ANTHROPIC_API_KEY"):
        main()
