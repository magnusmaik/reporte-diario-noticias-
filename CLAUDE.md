# Reporte Diario de Noticias

Automatización que corre en **GitHub Actions** y envía cada día a las 12:03 PM (hora local UTC-3, equivale a 15:03 UTC) un email bilingüe con 5 noticias de Mundo + 5 de Tecnología + 5 de Ciencia, vía **Resend**, a `miguel.carsub@gmail.com`. La curación corre en **OpenRouter** con `perplexity/sonar` (LLM con búsqueda web nativa).

## Arquitectura

```
GitHub Actions cron (15:03 UTC daily)
  → scripts/send_daily_report.py
    → lee prompt.md
    → POST OpenRouter chat/completions (perplexity/sonar)
    → extract_html() limpia fences y texto extra
    → POST Resend /emails
  → Resend → Inbox
```

- **Prompt editorial**: `prompt.md`. Fuente de verdad de qué busca y cómo formatea el reporte. El script lo lee en runtime, no está embebido en código.
- **Script**: `scripts/send_daily_report.py`. Stdlib only (urllib, json, re). Reintentos con backoff para OpenRouter. Sale con código no-cero si falla — eso marca el run como rojo en GitHub.
- **Workflow**: `.github/workflows/daily-report.yml`. Cron + dispatch manual. Concurrencia con `cancel-in-progress: false` para que dos runs solapados no manden dos emails.
- **Secrets** viven en GitHub Actions secrets, NO en el repo: `OPENROUTER_API_KEY`, `RESEND_API_KEY`.

## Convenciones para edición

- **Cambios de contenido/categorías/cantidad de noticias** → editar `prompt.md`. El script lo recoge en el siguiente run sin tocar código.
- **Cambio de horario** → editar el `cron` en `.github/workflows/daily-report.yml` (siempre en UTC).
- **Cambio de modelo LLM** → opción A: editar la variable `OPENROUTER_MODEL` en GitHub Settings; opción B: cambiar el default en `scripts/send_daily_report.py`.
- **No commitear**: `settings.local.json`, `.env`, ni keys reales. `.gitignore` ya los excluye.
- **No incluir** lógica de envío en `prompt.md` — eso vive en el script. `prompt.md` es solo guía editorial.

## Decisiones de diseño

- **GitHub Actions** sobre `/schedule` de Claude Code porque el usuario está en OpenRouter y `/schedule` requiere cuenta claude.ai.
- **OpenRouter perplexity/sonar** en lugar de WebSearch+LLM separado porque hace search+síntesis en una sola llamada → simpler.
- **Stdlib-only Python** sin `requirements.txt` para evitar `pip install` en el workflow → más rápido y menos puntos de falla.
- **HTML inline-styled** porque clientes de email no soportan `<style>` externo bien, y queremos que se vea decente en Gmail.
- **Resend** sobre Gmail SMTP/OAuth: una sola llamada HTTP, sin OAuth flow. Dominio verificado: `zetaperformance.com`, `from` configurado como `Reporte Diario <noreply@zetaperformance.com>`.
- **Prompt en archivo separado** (no embedded en script) para iterar sobre el editorial sin tocar Python.

## Verificación end-to-end

1. **Setup local** (una vez): `cp .env.example .env`, llenar keys, `set -a; source .env; set +a; python3 scripts/send_daily_report.py`.
2. **GitHub manual**: tab Actions → Reporte Diario de Noticias → Run workflow.
3. **Inbox**: revisar `miguel.carsub@gmail.com` (incluido spam el primer envío).
4. **Logs**: si falla, los logs del workflow muestran qué endpoint falló y el body del error.

## Riesgos conocidos / TODOs

- Si `perplexity/sonar` empieza a devolver noticias de baja calidad, considerar bumping a `sonar-pro` o cambiar a `gpt-4o-search-preview`.
- Sin retención de historial: cada reporte es independiente. Si se quisiera dedup ("ya cubrimos esa noticia ayer"), habría que persistir últimos N titulares en el repo y pasarlos en el prompt.
- Resend sin dominio verificado limita el `from` a `onboarding@resend.dev` y el `to` al email del titular de la cuenta. Para enviar a más destinatarios o tener un `from` propio, configurar dominio en Resend.
