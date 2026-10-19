# AI Chat Assistant for Small Businesses

An AI assistant that answers customers from a business's own documents (FAQ,
prices, policies, opening hours) and hands the conversation to a person when it
doesn't know. Every exchange is logged, including the questions it couldn't
answer, so the business sees what to add to its FAQ.

**Status:** core, website chat window, offline mock model, console and tests
are done. The Claude adapter, handoff by email/Telegram and the Google Sheets
log are next.

## What it does

- **Answers only from the documents.** If the answer isn't there, it says so
  and offers a person instead of guessing.
- **Healthcare-safe.** For clinics it never gives medical advice, and urgent
  messages ("my face is swollen", "it won't stop bleeding") get the clinic's
  phone and the emergency number right away, before any model is asked.
- **Talk to a person.** A button or a typed request passes the conversation,
  with its transcript, to the team.
- **Protects the bill.** Message length limit, messages per minute per visitor
  and a daily cap for the whole business.
- **Provider-independent.** The core never imports an AI SDK; Claude, OpenAI
  or the offline mock plug in through one small interface.

## Try it in 1 minute (no API key)

Requires Python 3.10+.

```bash
pip install -r requirements-dev.txt
python -m assistant demo      # scripted conversation with the demo dental clinic
python -m assistant console   # chat yourself; :human, :log, :new, :quit
python -m assistant web       # demo clinic website with the chat window: http://127.0.0.1:8000
pytest
```

The demo business lives in `demo/clinic/`: `business.json` (name, phone,
emergency number) and `knowledge/*.md`. To try your own business, copy the
folder, edit it, and run `python -m assistant console --business path/to/folder`.

## Add it to a website

One line before `</body>`:

```html
<script src="https://YOUR-SERVER/widget.js" data-title="Riverside Dental Studio" data-color="#0f766e" defer></script>
```

Start the server with the sites allowed to embed it:
`python -m assistant web --business path/to/folder --origins https://www.clinic.com`.
The window lives in a shadow root, so the site's CSS can't break it, and it
never renders replies as HTML.

## How it works

```
assistant/
  core/                 platform- and provider-independent
    service.py          Assistant.ask(): limits -> safety -> model -> reply -> log
    safety.py           emergency and "talk to a person" checks
    knowledge.py        loads .md/.txt documents, size check, sections
    business.py         business.json
    llm/base.py         LanguageModel interface (one method: answer)
    llm/mock.py         offline keyword-matching model for demos and tests
    storage.py          ConversationLog and HandoffNotifier interfaces + in-memory versions
  adapters/
    console.py          terminal chat and scripted demo
    web/app.py          JSON API (/api/chat, /api/handoff, /api/greeting), per-IP limit, CORS
    web/static/         widget.js (the chat window) and the demo clinic page
demo/clinic/            fictional "Riverside Dental Studio"
tests/
```

The whole knowledge base goes into the model's context (with prompt caching),
so there is no vector database. That covers up to roughly 150k tokens of
documents, enough for almost any small business.

## License

MIT
