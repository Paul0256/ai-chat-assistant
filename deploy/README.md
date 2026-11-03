# Public demo on a server that already runs Caddy

The demo (`python -m assistant web`) runs in one container next to an existing
Docker Compose stack whose Caddy owns ports 80 and 443. Caddy gets a separate
site block for the demo's domain and forwards it to the container over the
stack's Docker network. No port of the demo is published.

## One-time setup

1. **DNS:** an `A` record `demo` → the server's IPv4, **DNS only** (grey cloud
   in Cloudflare), so Caddy can obtain the certificate itself.
2. **Caddy imports extra sites:** the main Caddyfile has
   `import /etc/caddy/sites/*.caddy`, and the Caddy container mounts a host
   directory there (for example `/opt/caddy-sites:/etc/caddy/sites:ro`).
3. **Code and settings:**

   ```bash
   cd /opt
   git clone https://github.com/Paul0256/ai-chat-assistant.git
   cd ai-chat-assistant
   cp .env.example .env
   nano .env
   ```

   For the public demo:

   ```
   MODEL=claude
   ANTHROPIC_API_KEY=sk-ant-...      # a key only for this server
   DAILY_MESSAGE_CAP=300             # whole demo per day; ~0.13 cents per answer
   PROXY_NETWORK=mysite_default      # Caddy's Docker network: docker network ls
   ```

   Leave the Google Sheets and handoff settings empty: the demo keeps
   conversations in memory, and "Talk to a person" reaches nobody.
   Then `chmod 600 .env`.

4. **Start:**

   ```bash
   docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
   cp deploy/demo.caddy /opt/caddy-sites/
   docker exec <caddy container> caddy reload --config /etc/caddy/Caddyfile
   ```

   `docker ps` shows the Caddy container's name.

5. **Check:** `https://demo.pulauskas.dev` shows the demo clinic. Ask a
   question in the chat window.

## Update

```bash
cd /opt/ai-chat-assistant
git pull
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
```

## Costs and limits

- `DAILY_MESSAGE_CAP` stops the whole demo for the day; visitors then get the
  clinic's phone number. Each visitor is also limited per minute (the real
  address comes from Caddy's `X-Forwarded-For`).
- Set a monthly spend limit for the key's workspace in the Claude Console.
- Request logs are discarded (`demo.caddy`), and the container keeps no
  conversation after a restart.

`docker compose --env-file .env -f deploy/docker-compose.yml logs --tail 50` shows errors,
for example a rejected API key.
