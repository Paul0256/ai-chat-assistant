/*
 * AI chat window. Add to any website with one line:
 *
 *   <script src="https://YOUR-SERVER/widget.js" data-title="Riverside Dental" data-color="#0f766e" defer></script>
 *
 * Optional attributes: data-title, data-color, data-api (defaults to the server the script came from).
 * Everything lives in a shadow root, so the website's CSS can't break it and it can't break the website.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script || window.__aiChatWidgetLoaded) return;
  window.__aiChatWidgetLoaded = true;

  var api = (script.getAttribute("data-api") || new URL(script.src).origin).replace(/\/$/, "");
  var title = script.getAttribute("data-title") || "Chat with us";
  var color = script.getAttribute("data-color") || "#2f8cf0";

  function conversationId() {
    var key = "ai-chat-conversation";
    try {
      var id = sessionStorage.getItem(key);
      if (id) return id;
      id = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)).replace(/[^A-Za-z0-9_-]/g, "");
      sessionStorage.setItem(key, id);
      return id;
    } catch (e) {
      return "anon" + Date.now();
    }
  }
  var cid = conversationId();

  var host = document.createElement("div");
  host.style.position = "fixed";
  host.style.zIndex = "2147483000";
  host.style.right = "0";
  host.style.bottom = "0";
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });

  root.innerHTML =
    "<style>" +
    ":host{all:initial}" +
    "*{box-sizing:border-box;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}" +
    ".launcher{position:fixed;right:20px;bottom:20px;width:60px;height:60px;border-radius:50%;border:0;cursor:pointer;" +
    "background:var(--c);color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.25);display:grid;place-items:center}" +
    ".launcher svg{width:28px;height:28px}" +
    ".panel{position:fixed;right:20px;bottom:92px;width:370px;max-width:calc(100vw - 24px);height:560px;max-height:calc(100vh - 120px);" +
    "background:#fff;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.25);display:none;flex-direction:column;overflow:hidden}" +
    ".panel.open{display:flex}" +
    ".head{background:var(--c);color:#fff;padding:14px 16px;display:flex;align-items:center;justify-content:space-between}" +
    ".head b{font-size:16px}.head small{display:block;opacity:.85;font-size:12px;margin-top:2px}" +
    ".close{background:none;border:0;color:#fff;font-size:24px;line-height:1;cursor:pointer;padding:4px 8px}" +
    ".msgs{flex:1;overflow-y:auto;padding:16px;background:#f5f7fa;display:flex;flex-direction:column;gap:10px}" +
    ".msg{max-width:85%;padding:10px 13px;border-radius:14px;font-size:14.5px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}" +
    ".bot{background:#fff;color:#16202e;border:1px solid #e3e8ef;align-self:flex-start;border-bottom-left-radius:4px}" +
    ".me{background:var(--c);color:#fff;align-self:flex-end;border-bottom-right-radius:4px}" +
    ".warn{border-color:#f0b4b4;background:#fff5f5}" +
    ".staff{background:#eef8f2;border-color:#b7e1c8}" +
    ".who{display:block;font-size:11.5px;font-weight:600;color:#3a7d57;margin-bottom:3px}" +
    ".human{align-self:flex-start;background:#fff;border:1px solid var(--c);color:var(--c);border-radius:99px;padding:7px 14px;" +
    "font-size:13.5px;cursor:pointer}" +
    ".typing{align-self:flex-start;color:#7b8794;font-size:13px}" +
    "form{display:flex;gap:8px;padding:12px;border-top:1px solid #e3e8ef;background:#fff}" +
    "textarea{flex:1;resize:none;border:1px solid #d5dce5;border-radius:10px;padding:10px;font-size:14.5px;height:44px;max-height:120px;outline:none}" +
    "textarea:focus{border-color:var(--c)}" +
    ".send{border:0;border-radius:10px;background:var(--c);color:#fff;padding:0 16px;font-weight:600;cursor:pointer}" +
    ".send:disabled{opacity:.5;cursor:default}" +
    ".foot{font-size:11px;color:#9aa5b1;text-align:center;padding:0 0 8px;background:#fff}" +
    "@media (max-width:480px){.panel{right:0;bottom:0;width:100vw;max-width:100vw;height:100%;max-height:100%;border-radius:0}}" +
    "</style>" +
    '<button class="launcher" aria-label="Open chat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></button>' +
    '<section class="panel" role="dialog" aria-label="Chat">' +
    '<div class="head"><div><b></b><small>AI assistant · answers from our own information</small></div>' +
    '<button class="close" aria-label="Close chat">&times;</button></div>' +
    '<div class="msgs" aria-live="polite"></div>' +
    '<form><textarea placeholder="Type your question…" aria-label="Your message" maxlength="1000"></textarea>' +
    '<button class="send" type="submit">Send</button></form>' +
    '<div class="foot">Please don\'t share medical or payment details here.</div>' +
    "</section>";

  host.style.setProperty("--c", color);
  var panel = root.querySelector(".panel");
  var msgs = root.querySelector(".msgs");
  var form = root.querySelector("form");
  var input = root.querySelector("textarea");
  var send = root.querySelector(".send");
  root.querySelector(".head b").textContent = title;

  function add(text, who, extraClass) {
    var el = document.createElement("div");
    el.className = "msg " + who + (extraClass ? " " + extraClass : "");
    el.textContent = text; // never innerHTML: replies and user text are plain text
    msgs.appendChild(el);
    msgs.scrollTop = msgs.scrollHeight;
    return el;
  }

  function addHumanButton() {
    var b = document.createElement("button");
    b.className = "human";
    b.type = "button";
    b.textContent = "Talk to a person";
    b.addEventListener("click", function () {
      root.querySelectorAll(".human").forEach(function (x) { x.remove(); });
      call("/api/handoff", { conversation_id: cid });
    });
    msgs.appendChild(b);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function show(reply) {
    var warn = reply.kind === "emergency" || reply.kind === "error";
    add(reply.text, "bot", warn ? "warn" : "");
    if (reply.offer_handoff) addHumanButton();
    if (reply.kind === "handoff") startPolling();
  }

  // After a handoff, staff replies arrive here (the team answers from Telegram).
  var seqKey = "ai-chat-staff-seq";
  var lastSeq = 0;
  var polling = null;
  try { lastSeq = parseInt(sessionStorage.getItem(seqKey) || "0", 10) || 0; } catch (e) {}

  function addStaff(text) {
    var el = add("", "bot", "staff");
    var who = document.createElement("span");
    who.className = "who";
    who.textContent = "Team";
    el.appendChild(who);
    el.appendChild(document.createTextNode(text));
    msgs.scrollTop = msgs.scrollHeight;
  }

  function poll() {
    fetch(api + "/api/messages?conversation_id=" + encodeURIComponent(cid) + "&after=" + lastSeq)
      .then(function (r) { return r.ok ? r.json() : { messages: [] }; })
      .then(function (data) {
        data.messages.forEach(function (m) {
          if (m.seq <= lastSeq) return;
          lastSeq = m.seq;
          addStaff(m.text);
          if (!panel.classList.contains("open")) open();
        });
        try { sessionStorage.setItem(seqKey, String(lastSeq)); sessionStorage.setItem("ai-chat-handoff", "1"); } catch (e) {}
      })
      .catch(function () {});
  }

  function startPolling() {
    if (polling) return;
    poll();
    polling = setInterval(poll, 5000);
  }

  function call(path, body) {
    send.disabled = true;
    var typing = document.createElement("div");
    typing.className = "typing";
    typing.textContent = "Typing…";
    msgs.appendChild(typing);
    msgs.scrollTop = msgs.scrollHeight;
    return fetch(api + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        if (r.status === 429) return { kind: "limited", text: "You're sending messages very quickly. Please wait a minute.", offer_handoff: false };
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then(show)
      .catch(function () {
        show({ kind: "error", text: "Sorry, I can't connect right now. Please try again in a minute.", offer_handoff: false });
      })
      .finally(function () {
        typing.remove();
        send.disabled = false;
        input.focus();
      });
  }

  var greeted = false;
  function open() {
    panel.classList.add("open");
    input.focus();
    if (!greeted) {
      greeted = true;
      fetch(api + "/api/greeting")
        .then(function (r) { return r.json(); })
        .then(show)
        .catch(function () { add("Hi! How can I help?", "bot"); });
    }
  }

  try { if (sessionStorage.getItem("ai-chat-handoff") === "1") startPolling(); } catch (e) {}

  root.querySelector(".launcher").addEventListener("click", function () {
    panel.classList.contains("open") ? panel.classList.remove("open") : open();
  });
  root.querySelector(".close").addEventListener("click", function () { panel.classList.remove("open"); });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || send.disabled) return;
    add(text, "me");
    input.value = "";
    call("/api/chat", { conversation_id: cid, message: text });
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event("submit"));
    }
  });
})();
