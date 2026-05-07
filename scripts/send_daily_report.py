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

import email as email_module
import http.client
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_FILE = REPO_ROOT / os.environ.get("PROMPT_FILE", "prompt.md")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
RESEND_HOST = "api.resend.com"
RESEND_PATH = "/emails"

OPENROUTER_API_KEY = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
RESEND_API_KEY = (os.environ.get("RESEND_API_KEY") or "").strip()
OPENROUTER_MODEL = (os.environ.get("OPENROUTER_MODEL") or "perplexity/sonar").strip()
# Sin dominio verificado en Resend, el destinatario debe ser el email de la cuenta Resend
RESEND_ACCOUNT_EMAIL = (os.environ.get("RESEND_ACCOUNT_EMAIL") or "").strip()
REPORT_RECIPIENT = (os.environ.get("REPORT_RECIPIENT") or "").strip()
if not REPORT_RECIPIENT and RESEND_ACCOUNT_EMAIL:
    REPORT_RECIPIENT = RESEND_ACCOUNT_EMAIL
elif not REPORT_RECIPIENT:
    REPORT_RECIPIENT = "miguel.carsub@gmail.com"
REPORT_FROM = (os.environ.get("REPORT_FROM") or "Reporte Diario <onboarding@resend.dev>").strip()


def log(msg: str) -> None:
    """Log a stderr con timestamp UTC, visible en GitHub Actions."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}Z] {msg}", file=sys.stderr, flush=True)


def http_post(host: str, path: str, headers: dict, body: str, timeout: int = 300) -> tuple[int, str]:
    """POST usando http.client con control total sobre headers."""
    conn = http.client.HTTPSConnection(host, timeout=timeout)
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        response_body = resp.read().decode("utf-8", errors="replace")
        return resp.status, response_body
    finally:
        conn.close()


def call_openrouter(prompt: str) -> str:
    log(f"Llamando OpenRouter modelo={OPENROUTER_MODEL}")
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/magnusmaik/reporte-diario-noticias",
        "X-Title": "Reporte Diario de Noticias",
        "Content-Type": "application/json",
    }

    last_err: Exception | None = None
    for attempt in (1, 2, 3):
        try:
            status, body = http_post(
                "openrouter.ai", "/api/v1/chat/completions", headers,
                json.dumps(payload), timeout=300
            )
            if status != 200:
                raise RuntimeError(f"HTTP {status}: {body[:500]}")
            resp = json.loads(body)
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
    fence = re.search(r"```(?:html)?\s*\n(.*?)\n```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()
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
    body = json.dumps(payload)
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "ReporteDiario/1.0",
    }

    log(f"Resend request: host={RESEND_HOST} path={RESEND_PATH}")
    log(f"Resend auth header presente: {bool(RESEND_API_KEY)}")
    log(f"Resend payload size: {len(body)} bytes")

    status, response_body = http_post(RESEND_HOST, RESEND_PATH, headers, body, timeout=60)
    log(f"Resend response: status={status} body={response_body[:300]}")

    if status != 200:
        # Error conocido: sin dominio verificado en Resend
        if "send testing emails to your own email" in response_body:
            msg = json.loads(response_body).get("message", response_body)
            log(f"ERROR de Resend: {msg}")
            log("SOLUCIÓN: Ve a https://resend.com/domains y verifica un dominio,")
            log("o cambia REPORT_RECIPIENT al email de tu cuenta Resend.")
            if RESEND_ACCOUNT_EMAIL:
                log(f"Tip: configura REPORT_RECIPIENT={RESEND_ACCOUNT_EMAIL} en GitHub Variables")
        raise RuntimeError(f"Resend HTTP {status}: {response_body[:500]}")

    return json.loads(response_body)


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

    log(f"RESEND_API_KEY configurada (len={len(RESEND_API_KEY)})")
    log(f"OPENROUTER_API_KEY configurada (len={len(OPENROUTER_API_KEY)})")
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
