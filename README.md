# 📰 Reporte Diario de Noticias

Automatización que envía cada día a las **12:00 PM (hora local UTC-3)** un email bilingüe con las 15 noticias más relevantes del mundo, tecnología y ciencia (5 por categoría), curadas por un LLM con búsqueda web nativa.

```
[GitHub Actions cron 15:03 UTC = 12:03 PM local]
        │
        ▼
[scripts/send_daily_report.py]
        │
        ├─ Lee prompt.md (instrucciones editoriales)
        ├─ Llama OpenRouter → modelo perplexity/sonar (search + síntesis nativa)
        ├─ Extrae HTML del response
        │
        ▼
[Resend API] ──→ miguel.carsub@gmail.com
```

## Componentes

| Archivo | Rol |
|---------|-----|
| `prompt.md` | Prompt editorial puro: qué buscar, formato HTML, restricciones. Editable sin tocar código. |
| `scripts/send_daily_report.py` | Orquestador: lee prompt, llama OpenRouter, envía vía Resend. Sin dependencias externas (solo stdlib). |
| `.github/workflows/daily-report.yml` | Workflow cron de GitHub Actions. |
| `.env.example` | Plantilla de credenciales para correr localmente. |
| `CLAUDE.md` | Notas para Claude Code: arquitectura y convenciones. |

## Setup (una sola vez)

### 1. Resend — ya tienes la API key

Si todavía no creaste la cuenta:
1. Registrate en <https://resend.com/signup> con `miguel.carsub@gmail.com` (sin dominio verificado, Resend solo permite enviar a esa dirección).
2. Verifica el correo → **API Keys → Create API Key** → permission `Sending access`.
3. Copia la key (`re_...`).

### 2. Crear el repo en GitHub

```bash
cd "/Users/miguel/Reporte Diario de noticias"
git init -b main
git add -A
git commit -m "Initial: reporte diario de noticias automation"

# Crea el repo en GitHub (privado, recomendado) y conecta:
gh repo create reporte-diario-noticias- --private --source=. --remote=origin --push
```

> Si no tenés `gh` CLI: crea el repo en <https://github.com/new> (privado), luego:
> ```bash
> git remote add origin git@github.com:magnusmaik/reporte-diario-noticias-.git
> git push -u origin main
> ```

### 3. Configurar secrets de GitHub Actions

En el repo de GitHub: **Settings → Secrets and variables → Actions → New repository secret**.

| Nombre | Valor |
|--------|-------|
| `OPENROUTER_API_KEY` | Tu key de OpenRouter (la que está en `settings.local.json`, formato `sk-or-v1-...`) |
| `RESEND_API_KEY` | Tu key de Resend (`re_...`) |

Opcional — en **Variables** (no secrets) podés sobreescribir:
- `OPENROUTER_MODEL` (default `perplexity/sonar`)
- `REPORT_RECIPIENT` (default `miguel.carsub@gmail.com`)

### 4. Probar manualmente

En GitHub: **Actions → Reporte Diario de Noticias → Run workflow**.

Verifica:
- Logs del workflow (sin errores rojos).
- Inbox de `miguel.carsub@gmail.com` (incluye spam la primera vez).

### 5. Listo

El workflow correrá automáticamente cada día a las 15:03 UTC (12:03 PM hora local).

## Probar localmente (opcional)

```bash
cp .env.example .env
# Edita .env con tus keys reales

set -a; source .env; set +a
python3 scripts/send_daily_report.py
```

## Mantenimiento

| Tarea | Cómo |
|-------|------|
| Cambiar la hora | Edita el cron en `.github/workflows/daily-report.yml` (recordá: en UTC) |
| Cambiar contenido/categorías/cantidad | Edita `prompt.md` y commitea |
| Probar sin esperar al cron | GitHub UI → Actions → Run workflow |
| Cambiar modelo de OpenRouter | Edita variable `OPENROUTER_MODEL` en GitHub Settings |
| Pausar | Comentá el bloque `schedule:` del workflow |
| Rotar API key | Generá nueva en Resend/OpenRouter, actualizá secret de GitHub, revocá la vieja |

## Costos estimados

| Servicio | Costo |
|----------|-------|
| GitHub Actions | $0 (repo privado: 2000 min/mes gratis; este job tarda ~1 min/día = 30 min/mes) |
| Resend | $0 (free: 100 emails/día, 3000/mes) |
| OpenRouter (perplexity/sonar) | ~$0.01-0.05 por reporte → ~$1.50/mes según uso |

## Seguridad

- ⚠️ Tu `settings.local.json` actual contiene la API key de OpenRouter en texto plano. **No commitees ese archivo** — `.gitignore` ya lo excluye. Considera rotarla en <https://openrouter.ai/keys> y guardarla solo en GitHub Secrets.
- Nunca pongas keys reales en `prompt.md`, `README.md` ni en commits.
- GitHub Secrets están cifrados en reposo y solo se exponen al runner durante la ejecución del workflow.

## Troubleshooting

| Síntoma | Diagnóstico |
|---------|-------------|
| El email no llega | Revisa spam. Confirma que el dueño de la cuenta Resend coincide con `REPORT_RECIPIENT`. Mira los logs del workflow. |
| `HTTP 401` de OpenRouter | Secret `OPENROUTER_API_KEY` mal configurado o expirado. |
| `HTTP 403` de Resend | Estás intentando enviar a un email que no es el de tu cuenta Resend (sin dominio verificado, solo podés enviar a esa dirección). |
| El reporte tiene noticias viejas/irrelevantes | Endurece criterios en `prompt.md` o probá otro modelo (ej. `perplexity/sonar-pro`). |
| El HTML llega malformado | El modelo envolvió la respuesta en markdown — el script ya intenta extraerlo, pero si falla revisa los logs del workflow. |

## Variantes de modelo recomendadas

Modelos en OpenRouter con búsqueda web nativa (orden de costo creciente):

- `perplexity/sonar` — equilibrio costo/calidad (default).
- `perplexity/sonar-pro` — mejor curación, ~3x precio.
- `openai/gpt-4o-search-preview` — alternativa de OpenAI con web search.
- Cualquier modelo con sufijo `:online` (ej. `anthropic/claude-3.5-sonnet:online`) — añade un wrapper de búsqueda; menos preciso para news.
