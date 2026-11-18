"""Website adapter: a small JSON API plus the embeddable chat window.

    GET  /widget.js       the chat window; a website adds one <script> tag
    GET  /api/greeting    first message shown when the window opens
    POST /api/chat        {"conversation_id": "...", "message": "..."}
    POST /api/handoff     {"conversation_id": "..."}  ("Talk to a person")
    GET  /api/messages    ?conversation_id=...&after=N  staff replies since message N (polled)
    GET  /                demo page of the fictional clinic with the widget on it
    /t/<slug>/...         the same for each trial assistant (one per business folder in TRIALS_FOLDER)

No business rules here: everything is decided by `Assistant`. The adapter only
validates input, applies a per-IP limit (a visitor can always start a new
conversation, so per-conversation limits alone are not enough) and serves files.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from ...core import Assistant, Reply

STATIC = Path(__file__).parent / "static"
CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
CHANNEL = "web"


class ChatIn(BaseModel):
    conversation_id: str = Field(max_length=64)
    # The core enforces the business's own limit; this only stops huge bodies early.
    message: str = Field(max_length=4000)


class HandoffIn(BaseModel):
    conversation_id: str = Field(max_length=64)


class ReplyOut(BaseModel):
    kind: str
    text: str
    offer_handoff: bool

    @classmethod
    def of(cls, reply: Reply) -> ReplyOut:
        return cls(kind=reply.kind.value, text=reply.text, offer_handoff=reply.offer_handoff)


class StaffMessageOut(BaseModel):
    seq: int
    text: str


class MessagesOut(BaseModel):
    messages: list[StaffMessageOut]


class IpLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        hits = self.hits[ip]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= self.per_minute:
            return False
        hits.append(now)
        return True


def create_app(
    assistant: Assistant,
    allowed_origins: list[str] | None = None,
    per_ip_per_minute: int = 20,
    page_html: str | None = None,
    trials: dict[str, tuple[Assistant, str]] | None = None,
) -> FastAPI:
    """`page_html` replaces the demo page; `trials` maps a slug to (assistant, its page) served under /t/<slug>/."""
    app = FastAPI(title="AI chat assistant", docs_url=None, redoc_url=None, openapi_url=None)
    if allowed_origins:
        # Websites allowed to embed the widget, e.g. ["https://www.clinic.com"].
        app.add_middleware(
            CORSMiddleware, allow_origins=allowed_origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"]
        )
    limiter = IpLimiter(per_ip_per_minute)

    def check(request: Request, conversation_id: str) -> None:
        if not CONVERSATION_ID.match(conversation_id):
            raise HTTPException(400, "Invalid conversation id")
        ip = request.client.host if request.client else "unknown"
        if not limiter.allow(ip):
            raise HTTPException(429, "Too many messages. Please wait a minute.")

    @app.get("/api/greeting")
    async def greeting() -> ReplyOut:
        return ReplyOut.of(assistant.greeting())

    @app.post("/api/chat")
    async def chat(body: ChatIn, request: Request) -> ReplyOut:
        check(request, body.conversation_id)
        reply = await asyncio.to_thread(assistant.ask, body.conversation_id, body.message, CHANNEL)
        return ReplyOut.of(reply)

    @app.post("/api/handoff")
    async def handoff(body: HandoffIn, request: Request) -> ReplyOut:
        check(request, body.conversation_id)
        reply = await asyncio.to_thread(
            assistant.request_handoff, body.conversation_id, "Customer pressed the button", CHANNEL
        )
        return ReplyOut.of(reply)

    @app.get("/api/messages")
    async def messages(conversation_id: str = Query(max_length=64), after: int = Query(0, ge=0)) -> MessagesOut:
        # Polled every few seconds after a handoff; a cheap in-memory read, so no per-IP limit.
        if not CONVERSATION_ID.match(conversation_id):
            raise HTTPException(400, "Invalid conversation id")
        found = assistant.messages_since(conversation_id, after)
        return MessagesOut(messages=[StaffMessageOut(seq=m.seq, text=m.text) for m in found])

    @app.get("/widget.js")
    async def widget() -> FileResponse:
        return FileResponse(STATIC / "widget.js", media_type="text/javascript")

    @app.get("/", response_model=None)
    async def demo_page() -> FileResponse | HTMLResponse:
        if page_html is not None:
            return HTMLResponse(page_html)
        return FileResponse(STATIC / "demo.html", media_type="text/html")

    for slug, (trial, html) in (trials or {}).items():
        app.add_api_route(f"/t/{slug}", _redirect(f"/t/{slug}/"), include_in_schema=False)
        app.mount(f"/t/{slug}", create_app(trial, per_ip_per_minute=per_ip_per_minute, page_html=html))

    return app


def _redirect(target: str):
    async def redirect() -> RedirectResponse:
        return RedirectResponse(target)

    return redirect
