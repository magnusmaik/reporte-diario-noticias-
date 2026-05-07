#!/usr/bin/env python3
"""
Genera y envía el reporte diario de noticias.

Flujo:
  1. Lee el prompt editorial de prompt.md
  2. Lo envía a OpenRouter (modelo con búsqueda web nativa, p.ej. perplexity/sonar)
  3. Recibe HTML y lo manda como email vía Resend

Variables de entorno requeridas:
  OPENROUTER_API_KEY   API key de OpenRouter
  RESEND_API_KEY       API key de Resend

Variables opcionales:
  OPENROUTER_MODEL     default: "perplexity/sonar"
  REPORT_RECIPIENT     default: "miguel.carsub@gmail.com"
  REPORT_FROM          default: "Reporte Diario <onboarding@resend.dev>"
  PROMPT_FILE          default: "prompt.md" (relativo al repo)

Sale con código 0 si Resend devuelve un id; 1 en cualquier otro caso.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_FILE = REPO_ROOT / os.environ.get("PROMPT_FILE", "prompt.md")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
RESEND_URL = "https://api.resend.com/emails"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "perplexity/sonar")
REPORT_RECIPIENT = os.environ.get("REPORT_RECIPIENT", "miguel.carsub@gmail.com")
REPORT_FROM = os.environ.get("REPORT_FROM", "Reporte Diario <onboarding@resend.dev>")


def log(msg: str) -> None:
    """Log a stderr con timestamp UTC, visible en GitHub Actions."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}Z] {msg}", file=sys.stderr, flush=True)


def post_json(url: str, headers: dict, payload: dict, timeout: int = 300) -> dict:
    req = Request(
        url,
        method="POST",
        headers={**headers, "Content-Type": "application/json"},
        data=json.dumps(payload).encode("utf-8"),
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} de {url}: {body}") from e
    except URLError as e:
        raise RuntimeError(f"Error de red contactando {url}: {e}") from e


def call_openrouter(prompt: str) -> str:
    log(f"Llamando OpenRouter modelo={OPENROUTER_MODEL}")
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/magnusmaik/reporte-diario-noticias-",
        "X-Title": "Reporte Diario de Noticias",
    }

    last_err: Exception | None = None
    for attempt in (1, 2, 3):
        try:
            resp = post_json(OPENROUTER_URL, headers, payload, timeout=300)
            content = resp["choices"][0]["message"]["content"]
            log(f"OpenRouter OK ({len(content)} chars)")
            return content
        except Exception as e:
            last_err = e
            log(f"Intento {attempt}/3 falló: {e}")
            if attempt < 3:
                time.sleep(5 * attempt)
    raise RuntimeError(f"OpenRouter falló tras 3 intentos: {last_err}")


def extract_html(raw: str) -> str:
    """Extrae HTML del output del LLM, removiendo fences ``` o texto extra."""
    s = raw.strip()
    # Caso 1: el modelo envolvió en ```html ... ```
    fence = re.search(r"```(?:html)?\s*\n(.*?)\n```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()
    # Caso 2: hay texto antes de <!DOCTYPE o <html>
    m = re.search(r"<!DOCTYPE html.*?</html>", s, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(0)
    m = re.search(r"<html.*?</html>", s, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(0)
    return s


def send_via_resend(html: str, subject: str) -> dict:
    log(f"Enviando email a {REPORT_RECIPIENT} (asunto: {subject})")
    payload = {
        "from": REPORT_FROM,
        "to": [REPORT_RECIPIENT],
        "subject": subject,
        "html": html,
    }
    headers = {"Authorization": f"Bearer {RESEND_API_KEY}"}
    return post_json(RESEND_URL, headers, payload, timeout=60)


def main() -> int:
    if not OPENROUTER_API_KEY:
        log("ERROR: falta OPENROUTER_API_KEY en el entorno")
        return 1
    if not RESEND_API_KEY:
        log("ERROR: falta RESEND_API_KEY en el entorno")
        return 1
    if not PROMPT_FILE.exists():
        log(f"ERROR: prompt no encontrado en {PROMPT_FILE}")
        return 1

    prompt = PROMPT_FILE.read_text(encoding="utf-8")
    log(f"Prompt cargado de {PROMPT_FILE.name} ({len(prompt)} chars)")

    raw = call_openrouter(prompt)
    html = extract_html(raw)
    if not html.lower().startswith(("<!doctype", "<html")):
        log("ADVERTENCIA: el output no empieza con <!DOCTYPE/<html>; envío tal cual")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"📰 Reporte Diario — {today}"
    result = send_via_resend(html, subject)

    if "id" not in result:
        log(f"ERROR de Resend: {json.dumps(result, ensure_ascii=False)}")
        return 1

    log(f"✅ Email enviado · resend_id={result['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
