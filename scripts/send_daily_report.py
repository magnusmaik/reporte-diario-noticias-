#!/usr/bin/env python3
"""
Genera y envía el reporte diario de noticias.

Flujo:
  1. Lee el prompt editorial de prompt.md
  2. Lo envía a OpenRouter (modelo con búsqueda web nativa, p.ej. perplexity/sonar)
  3. Recibe JSON y lo convierte a HTML vía generar_html()
  4. Envía el email vía Resend

Variables de entorno requeridas:
  OPENROUTER_API_KEY   API key de OpenRouter
  RESEND_API_KEY       API key de Resend

Variables opcionales:
  OPENROUTER_MODEL     default: "perplexity/sonar"
  REPORT_RECIPIENT     default: "miguel.carsub@gmail.com"
  REPORT_FROM          default: "Reporte Diario <noreply@zetaperformance.com>"
  PROMPT_FILE          default: "prompt.md" (relativo al repo)

Sale con código 0 si Resend devuelve un id; 1 en cualquier otro caso.
"""

from __future__ import annotations

import html
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
REPORT_FROM = (os.environ.get("REPORT_FROM") or "Reporte Diario <noreply@zetaperformance.com>").strip()


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


def extract_json(raw: str) -> dict:
    """Extrae y parsea JSON de la respuesta del LLM."""
    s = raw.strip()

    # Caso 1: parseo directo
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            log(f"JSON directo OK ({len(str(data))} chars)")
            return data
    except json.JSONDecodeError:
        pass

    # Caso 2: remover fences markdown ```json ... ```
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        try:
            data = json.loads(fence.group(1).strip())
            if isinstance(data, dict):
                log("JSON extraído de fence markdown")
                return data
        except json.JSONDecodeError:
            pass

    # Caso 3: buscar objeto JSON en texto mixto (encontrar el outermost {...})
    start = s.find("{")
    if start != -1:
        depth = 0
        end = -1
        for idx in range(start, len(s)):
            if s[idx] == "{":
                depth += 1
            elif s[idx] == "}":
                depth -= 1
                if depth == 0:
                    end = idx
                    break
        if end != -1:
            try:
                data = json.loads(s[start:end + 1])
                if isinstance(data, dict):
                    log("JSON extraído por búsqueda de llaves")
                    return data
            except json.JSONDecodeError:
                pass

    raise RuntimeError(f"No se pudo extraer JSON válido. Inicio respuesta: {s[:300]}")


def generar_html(datos: dict) -> str:
    """Construye el HTML del email a partir del JSON del LLM."""
    fecha_larga = datos.get("fecha_larga_es", datetime.now(timezone.utc).strftime("%d de %B de %Y"))
    fecha_iso = datos.get("fecha_iso", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    noticias = datos.get("noticias", [])

    # Agrupar por categoría
    categorias: dict[str, list[dict]] = {}
    for n in noticias:
        cat = n.get("categoria", "Otros")
        categorias.setdefault(cat, []).append(n)

    # Configuración visual por categoría
    cat_config = {
        "Mundo":       {"icon": "☁️", "color": "#0066cc", "label": "Mundo"},
        "Tecnología":  {"icon": "\U0001F4BB", "color": "#009966", "label": "Tecnología"},
        "Ciencia":     {"icon": "\U0001F52C", "color": "#cc6600", "label": "Ciencia"},
    }

    # Orden de renderizado
    orden_cats = ["Mundo", "Tecnología", "Ciencia"]

    # Estilos base responsivos
    parts = []
    parts.append('<!DOCTYPE html>')
    parts.append('<html>')
    parts.append('<head>')
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append('</head>')
    parts.append('<body style="margin:0;padding:0;background-color:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,\'Helvetica Neue\',Arial,sans-serif;">')
    # Wrapper
    parts.append('<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f0f2f5;">')
    parts.append('<tr><td align="center" style="padding:20px 10px;">')
    # Card container
    parts.append('<table width="680" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:680px;background-color:#ffffff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,0.08);overflow:hidden;">')

    # Header ejecutivo
    parts.append('<tr><td style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);padding:36px 28px;text-align:center;">')
    parts.append(f'<h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:700;letter-spacing:-0.5px;">\U0001F4F0 Reporte Diario</h1>')
    parts.append(f'<p style="margin:8px 0 0;color:#b0b0b0;font-size:14px;">{html.escape(fecha_larga)}</p>')
    parts.append('</td></tr>')

    # Subtitle
    parts.append('<tr><td style="padding:14px 28px;background-color:#fafbfc;border-bottom:1px solid #e8e8e8;text-align:center;">')
    parts.append('<p style="margin:0;color:#555;font-size:13px;">Análisis ejecutivo &middot; Noticias &middot; Tecnología &middot; Ciencia</p>')
    parts.append('</td></tr>')

    # Content
    parts.append('<tr><td style="padding:24px 28px;">')

    # Renderizar cada categoría
    for idx_cat, cat_nombre in enumerate(orden_cats):
        noticias_cat = categorias.get(cat_nombre, [])
        if not noticias_cat:
            continue  # No generar nada si la categoría viene vacía

        cfg = cat_config.get(cat_nombre, {"icon": "\U0001F4D6", "color": "#666", "label": cat_nombre})

        # Separador entre categorías (excepto la primera)
        if idx_cat > 0:
            parts.append('<hr style="border:none;border-top:1px solid #eee;margin:32px 0;">')

        # Título de categoría
        parts.append(f'<h2 style="color:{cfg["color"]};margin:0 0 20px;font-size:20px;font-weight:600;border-bottom:2px solid {cfg["color"]};padding-bottom:10px;">{cfg["icon"]}  {cfg["label"]}</h2>')

        # Noticias de la categoría
        for idx, n in enumerate(noticias_cat):
            titular = html.escape(n.get("titular", "Sin título"))
            resumen = html.escape(n.get("resumen", ""))
            raw_url = n.get("url", "#")
            url = html.escape(raw_url, quote=True)
            fuente = html.escape(n.get("fuente", "Desconocido"))
            impacto = n.get("impacto_score", 0)
            try:
                impacto = int(impacto)
            except (ValueError, TypeError):
                impacto = 0
            confiabilidad = html.escape(n.get("confiabilidad_fuente", "Media"))
            por_que = html.escape(n.get("por_que_importa", ""))

            # Color de badge de impacto
            if impacto >= 8:
                badge_color = "#dc2626"
                badge_bg = "#fef2f2"
            elif impacto >= 5:
                badge_color = "#d97706"
                badge_bg = "#fffbeb"
            else:
                badge_color = "#059669"
                badge_bg = "#ecfdf5"

            # Divider entre noticias (no antes de la primera)
            if idx > 0:
                parts.append('<hr style="border:none;border-top:1px solid #f0f0f0;margin:20px 0;">')

            # Tarjeta de noticia
            parts.append('<div style="margin-bottom:4px;">')
            # Titular (enlace clickeable, azul, sin subrayado)
            parts.append(f'<h3 style="margin:0 0 8px;font-size:16px;line-height:1.4;"><a href="{url}" style="color:#1a3d6a;text-decoration:none;font-weight:600;">{titular}</a></h3>')
            # Resumen
            parts.append(f'<p style="margin:0 0 10px;font-size:14px;line-height:1.6;color:#444;">{resumen}</p>')
            # Meta: fuente, impacto, confiabilidad
            parts.append('<div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-top:8px;">')
            parts.append(f'<span style="font-size:12px;color:#777;">\U0001F4CE {fuente}</span>')
            parts.append(f'<span style="background:{badge_bg};color:{badge_color};padding:2px 10px;border-radius:12px;font-size:11px;font-weight:600;">Impacto: {impacto}/10</span>')
            parts.append(f'<span style="font-size:11px;color:#666;border:1px solid #ddd;padding:2px 10px;border-radius:12px;">{confiabilidad}</span>')
            # Enlace a artículo completo
            parts.append(f'<a href="{url}" style="font-size:11px;color:#1a3d6a;text-decoration:none;background:#e8f0fe;padding:3px 10px;border-radius:12px;display:inline-block;">\U0001F517 Leer artículo completo en {fuente}</a>')
            parts.append('</div>')

            # Por qué importa - diseño destacado con borde izquierdo grueso según impacto
            if por_que:
                if impacto >= 8:
                    pq_border = "#dc2626"
                    pq_bg = "#fef2f2"
                elif impacto >= 5:
                    pq_border = "#d97706"
                    pq_bg = "#fffbeb"
                else:
                    pq_border = "#059669"
                    pq_bg = "#ecfdf5"
                parts.append(f'<div style="margin-top:10px;padding:12px 16px;background-color:{pq_bg};border-left:4px solid {pq_border};font-size:13px;color:#444;line-height:1.6;border-radius:0 6px 6px 0;"><strong style="color:#333;font-weight:600;display:block;margin-bottom:4px;">\U0001F4A1 ¿Por qué importa?</strong><span style="font-style:italic;">{por_que}</span></div>')

            parts.append('</div>')

    parts.append('</td></tr>')

    # Footer
    parts.append('<tr><td style="padding:18px 28px;background-color:#fafbfc;border-top:1px solid #e8e8e8;text-align:center;">')
    parts.append(f'<p style="margin:0;font-size:12px;color:#999;">Generado automáticamente &middot; {fecha_iso}</p>')
    parts.append('<p style="margin:4px 0 0;font-size:11px;color:#ccc;">Reporte Diario de Noticias &middot; Powered by OpenRouter + Resend</p>')
    parts.append('</td></tr>')

    # Cierre
    parts.append('</table>')
    parts.append('</td></tr>')
    parts.append('</table>')
    parts.append('</body>')
    parts.append('</html>')

    return "\n".join(parts)


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
    datos = extract_json(raw)
    log(f"JSON parseado: {len(datos.get('noticias', []))} noticias encontradas")

    html = generar_html(datos)

    today = datos.get("fecha_iso") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subject = f"\U0001F4F0 Reporte Diario — {today}"
    result = send_via_resend(html, subject)

    if "id" not in result:
        log(f"ERROR de Resend: {json.dumps(result, ensure_ascii=False)}")
        return 1

    log(f"✅ Email enviado · resend_id={result['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
