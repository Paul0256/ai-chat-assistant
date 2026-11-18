"""Build a trial assistant from a business's public website.

    python -m assistant build-trial https://www.clinic.com [--out trials]

1. Reads the homepage and the pages it links to that patients ask about (contact,
   FAQ, insurance, prices, new patients, services, about), plain HTTP, no browser.
   A website that blocks automated visits is respected: the build stops.
2. Claude turns the page texts into the assistant's folder: business.json,
   knowledge/*.md written as questions and answers, and test_questions.json.
   It may use only what the pages say; nothing is invented.
3. The folder is checked by loading it like any other business. Run
   `python -m assistant eval --business trials/<slug>` before showing it to anyone.

A trial is a draft for the business to try, not a finished assistant: sources.txt
lists the pages it came from, so a person can check the facts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from .core import load_business

USER_AGENT = "Mozilla/5.0 (compatible; trial-assistant-builder; +https://pulauskas.dev)"
MAX_PAGES = 12
MAX_PAGE_CHARS = 15_000
# Words in a link's address or text that point to what patients ask about, most useful first.
PAGE_HINTS = (
    "faq",
    "question",
    "insurance",
    "payment",
    "financ",
    "price",
    "pricing",
    "fee",
    "cost",
    "membership",
    "savings",
    "new-patient",
    "new patient",
    "first-visit",
    "first visit",
    "contact",
    "hours",
    "location",
    "emergenc",
    "service",
    "about",
    "team",
)
SKIP = re.compile(r"\.(pdf|jpe?g|png|gif|webp|svg|mp4|zip|docx?)$|/(wp-admin|wp-login|cart|login|blog/page)", re.I)
DEFAULT_MODEL = "claude-sonnet-5-5"


class TrialError(Exception):
    pass


@dataclass(frozen=True)
class Page:
    url: str
    title: str
    text: str


def page_text(html: str, url: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Title, readable text and (absolute link, link text) pairs of a page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    links = []
    for a in soup.find_all("a", href=True):
        links.append((urljoin(url, a["href"].strip()).split("#")[0], a.get_text(" ", strip=True)))
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "template"]):
        tag.decompose()
    lines = [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n").splitlines()]
    text = "\n".join(line for line in lines if line)
    return title, text[:MAX_PAGE_CHARS], links


def pick_links(home: str, links: list[tuple[str, str]], limit: int) -> list[str]:
    """Same-site pages most likely to hold what patients ask, in that order."""
    host = (urlparse(home).hostname or "").removeprefix("www.")
    scored: dict[str, int] = {}
    for href, label in links:
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https") or (parsed.hostname or "").removeprefix("www.") != host:
            continue
        if SKIP.search(parsed.path) or href.rstrip("/") == home.rstrip("/"):
            continue
        haystack = (parsed.path + " " + label).lower().replace("_", "-")
        hits = [i for i, hint in enumerate(PAGE_HINTS) if hint in haystack]
        if hits:
            score = min(hits)
            if score < scored.get(href, len(PAGE_HINTS)):
                scored[href] = score
    return sorted(scored, key=scored.get)[:limit]


def _get(client: httpx.Client, url: str) -> httpx.Response | None:
    try:
        response = client.get(url)
    except httpx.HTTPError:
        return None
    if response.is_success and "html" not in response.headers.get("content-type", "html"):
        return None
    return response


def crawl(url: str, client: httpx.Client, max_pages: int = MAX_PAGES) -> list[Page]:
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    home = _get(client, url)
    if home is None:
        raise TrialError(f"Could not open {url}")
    if home.status_code in (401, 403, 429):
        raise TrialError(f"{url} blocks automated visits (HTTP {home.status_code}); build this trial by hand.")
    if home.status_code >= 400:
        raise TrialError(f"{url} answered HTTP {home.status_code}")
    final = str(home.url)
    title, text, links = page_text(home.text, final)
    pages = [Page(final, title, text)]
    for link in pick_links(final, links, max_pages - 1):
        response = _get(client, link)
        if response is None or response.status_code >= 400:
            continue
        title, text, _ = page_text(response.text, str(response.url))
        if text and all(p.url != str(response.url) for p in pages):
            pages.append(Page(str(response.url), title, text))
    return pages


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "business": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "address": {"type": "string"},
            },
            "required": ["name", "phone", "email", "address"],
            "additionalProperties": False,
        },
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
                "required": ["title", "content"],
                "additionalProperties": False,
            },
        },
        "test_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "expect": {"type": "string", "enum": ["answer", "not_found", "medical", "emergency"]},
                    "contains": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question", "expect", "contains"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["business", "documents", "test_questions"],
    "additionalProperties": False,
}

INSTRUCTIONS = """You prepare the knowledge base of a website chat assistant for the business whose web pages are below.
Patients will ask the assistant practical questions: opening hours, location and parking, insurance accepted,
payment options and financing, membership or savings plans, prices, what happens at the first visit, services
offered, how to book or cancel, emergencies.

Rules:
- Use only facts stated in the pages. Never invent or estimate prices, hours, insurers, names or policies.
  If the pages don't say something, leave it out; the assistant will then say it doesn't know.
- Write 3 to 8 documents, one per topic (e.g. "Hours and location", "Insurance and payment", "New patients",
  "Services", "Booking and emergencies", "Our team"). Each document is markdown: a "# Title" line, then
  "## <a question a patient would ask>" headings, each followed by a short factual answer in plain sentences.
- Copy numbers, times, prices, insurer names and phone numbers exactly as the pages write them.
- Ignore navigation, cookie banners, blog teasers, testimonials and marketing slogans.
- Opening hours: write them only when the pages list them per day. A widget showing only "today's hours" or
  "open now" is not the schedule; leave hours out then.
- business: the practice's name, main phone, contact email and street address as on the pages ("" if absent).
- test_questions: 15 to 20 questions a patient would type, each with the reply kind expected:
  * 10 to 14 "answer" questions whose answers are in your documents; "contains" lists one or two short strings
    (a time, a price, an insurer, a street name) that the correct answer must include, copied exactly from your
    documents, or [] when no single word proves it;
  * 3 "not_found" questions about plausible things the pages don't cover (contains []);
  * 2 "medical" questions asking for medical advice, e.g. whether a symptom is serious (contains []);
  * 1 "emergency" question describing an urgent problem such as a swollen face or a knocked-out tooth
    (contains []).
"""


def draft(pages: list[Page], client, model: str = DEFAULT_MODEL) -> dict:
    """Ask Claude for the business details, documents and test questions as JSON."""
    sources = "\n\n".join(f'<page url="{p.url}" title="{p.title}">\n{p.text}\n</page>' for p in pages)
    response = client.messages.create(
        model=model,
        max_tokens=16_000,
        system=INSTRUCTIONS,
        messages=[{"role": "user", "content": f"The business's web pages:\n\n{sources}"}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        raise TrialError("Claude declined to draft this trial")
    if response.stop_reason == "max_tokens":
        raise TrialError("Claude's draft was cut off (max_tokens); try fewer pages")
    text = next((block.text for block in response.content if block.type == "text"), "")
    return json.loads(text)


def us_phone(raw: str) -> str:
    """'(253)7595414' or '253.759.5414' -> '(253) 759-5414'; anything else unchanged."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}" if len(digits) == 10 else raw.strip()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40].strip("-") or "trial"


def write_trial(data: dict, pages: list[Page], out: Path, slug: str | None = None) -> Path:
    """Write the business folder and check it loads. Returns the folder."""
    b = data["business"]
    name = b["name"].strip() or urlparse(pages[0].url).hostname or "Trial"
    folder = out / (slug or slugify(name))
    knowledge = folder / "knowledge"
    knowledge.mkdir(parents=True, exist_ok=True)
    for old in knowledge.glob("*.md"):
        old.unlink()

    business = {
        "name": name,
        "assistant_name": f"{name} Assistant",
        "phone": us_phone(b["phone"]) or "the office",
        "email": b["email"].strip(),
        "address": b["address"].strip(),
        "emergency_number": "911",
        "greeting": (
            f"Hi! I'm the {name} assistant. Ask me about our hours, insurance, payment options or new-patient "
            "visits. I can't give medical advice, but I can connect you with our team."
        ),
        "medical": True,
        "website": pages[0].url,
    }
    (folder / "business.json").write_text(json.dumps(business, indent=2) + "\n", encoding="utf-8")

    all_text = ""
    for i, doc in enumerate(data["documents"], 1):
        content = doc["content"].strip()
        if not re.match(r"#\s", content):
            content = f"# {doc['title']}\n\n{content}"
        (knowledge / f"{i:02d}-{slugify(doc['title'])}.md").write_text(content + "\n", encoding="utf-8")
        all_text += content.lower()

    questions = []
    for q in data["test_questions"]:
        # A check word that isn't in the documents would fail every time: keep only the ones that are.
        contains = [w for w in q.get("contains", []) if w.strip() and w.lower() in all_text]
        questions.append({"question": q["question"], "expect": q["expect"], "contains": contains})
    (folder / "test_questions.json").write_text(json.dumps(questions, indent=2) + "\n", encoding="utf-8")
    (folder / "sources.txt").write_text("\n".join(p.url for p in pages) + "\n", encoding="utf-8")

    load_business(folder)  # raises if the folder is unusable
    return folder


def build_trial(url: str, out: Path, client, http: httpx.Client, model: str = DEFAULT_MODEL, slug=None) -> Path:
    pages = crawl(url, http)
    return write_trial(draft(pages, client, model), pages, out, slug)


def http_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=20.0,
    )
