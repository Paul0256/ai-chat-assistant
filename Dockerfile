# The website chat window and the demo page (python -m assistant web).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistant ./assistant
COPY demo ./demo

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
# Only reachable through the reverse proxy, so its X-Forwarded-For can be trusted.
CMD ["python", "-m", "assistant", "web", "--host", "0.0.0.0", "--port", "8000", "--behind-proxy"]
