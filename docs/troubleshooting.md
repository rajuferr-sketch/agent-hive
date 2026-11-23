# Troubleshooting

> Guida rapida ai problemi più comuni, basata sul comportamento documentato della codebase (vedi [`providers.md`](providers.md), [`operations.md`](operations.md), [`windows.md`](windows.md), [`deployment.md`](deployment.md)).

## L'output contiene il tag `[MOCK]`

- **Causa:** nessun provider reale configurato, oppure tutti i provider della catena dell'agente hanno fallito con `ALLOW_MOCK=true`: il mock deterministico risponde al posto loro. È un comportamento voluto, non un bug.
- **Soluzione:** configurare un provider reale (`OPENAI_API_KEY` oppure `OLLAMA_BASE_URL`, vedi [`providers.md`](providers.md)) oppure continuare in mock mode, utile per test e CI.

## `ProviderError` durante una missione

- Con `ALLOW_MOCK=false` l'esaurimento della catena di provider solleva `ProviderError`: nessuna risposta finta, nessun silenzio (policy di onestà del mock, vedi [`providers.md`](providers.md)).
- **Verifica:** `python scripts/diagnose.py` oppure `agent-hive diagnose` (health probe dei provider, timeout 10 s, exit code 1 su failure core).

## Un provider locale non risponde

- **Circuit breaker:** dopo 2 fallimenti consecutivi il provider viene saltato per 60 secondi, poi ritentato; un backend giù non blocca il resto della catena.
- **Ollama:** un 404 da Ollama quasi sempre significa "modello non scaricato": `ollama pull <modello>`.
- **LM Studio / vLLM / LiteLLM:** verificare la porta (1234, 8001, 4000 negli esempi di [`providers.md`](providers.md)), che il server sia avviato e che il nome del modello nel YAML corrisponda a quello servito.
- Dopo una modifica alle configurazioni, non fidarsi dei contatori del circuit breaker di una sessione già avviata: riavviare il processo (invalidazione cache/circuit breaker, regola universale in [`AI_CONTEXT.md`](../AI_CONTEXT.md)).

## Quality gate: deliverable respinto o score basso

- Il gate valuta completezza, copertura dei requisiti, controllo AST del Python incluso, segreti e marker residui; score minimo 0.7, fino a 2 round di revisione automatica.
- **Soluzione:** riformulare la missione con requisiti espliciti e completi; verificare che il deliverable non contenga segreti o marker tipo TODO/XXX.

## Problemi database

- **SQLite:** `./data/agent_hive.db` viene creato automaticamente; per il percorso server usare `agent-hive init-db`.
- **Task orfani dopo crash/restart:** `python -m agent_hive.cli recover` oppure `agent-hive recover`.
- **PostgreSQL:** vedi [`migrations.md`](migrations.md) e la variabile `DATABASE_URL` in `.env`.

## Porta 8000 occupata o API non raggiungibile

- `agent-hive start --port 8001`, oppure `API_PORT=8001` in `.env`; bind di default `127.0.0.1`.
- **Docker:** `docker compose ps` e `docker compose logs -f app` (vedi [`deployment.md`](deployment.md)).

## Windows: attivazione del venv fallita

- `.venv\Scripts\Activate.ps1` richiede una ExecutionPolicy che consenta gli script: `Set-ExecutionPolicy -Scope Process RemoteSigned`. Dettagli in [`windows.md`](windows.md).

## Diagnostica completa

- `python scripts/diagnose.py` (exit code 1 su failure core) — procedure complete in [`operations.md`](operations.md).

## Universal AI Platform (MCP / gateway / connettori / memoria condivisa)

### `/mcp` risponde `404 "session expired or missing: re-initialize first"`

- **Causa:** richiesta senza l'header `Mcp-Session-Id` di una sessione inizializzata (o sessione scaduta/evictata).
- **Soluzione:** rifare `initialize` su `POST /mcp`, riprendere il `Mcp-Session-Id` dalla risposta e riverberarlo su ogni chiamata. Nota: dopo `initialize` serve anche la notifica `notifications/initialized` (risponde `202`).

### `tools/call` restituisce `isError: true` con `permission_denied`

- **Causa:** il token della sessione MCP/REST non possiede lo scope richiesto dal tool (es. `memory:write` per `agent_save_memory`).
- **Soluzione:** emettere un token con il ruolo corretto (`agent-hive token --role operator`), e usarlo come `Authorization: Bearer`; oppure, in modalità enforced, verificare la tabella `api_tokens` (`GET /api/security/tokens`). In local-trust mode l'identità è admin: se vedete `permission_denied` in locale, esiste almeno un token attivo → siete in enforced mode.

### `429 Too Many Requests` / `rate_limited`

- **Causa:** sliding-window rate limiter (default 120 richieste/60 s per identità/IP).
- **Soluzione:** attendere `Retry-After`, oppure alzare `RATE_LIMIT_REQUESTS`/`RATE_LIMIT_WINDOW` in `.env`.

### `injection_blocked` su una missione

- **Causa:** l'istruzione ha matchato le euristiche anti prompt-injection ("ignore all previous instructions", "reveal your system prompt", pattern distruttivi…). È difesa voluta.
- **Soluzione:** riformulare l'istruzione. L'evento è registrato nell'audit (`GET /api/security/audit`).

### Il deliverable è vuoto / la missione via gateway fallisce con `gateway_error`

- **Verificare:** `POST /api/selfheal/run` → ciclo di diagnostica (database, scheduler, agenti, memoria). Se `healthy: false`, correggere la causa indicata dai check.
- Se il master resta senza agenti: `CONFIG_DIR` punta a `configs/`? `agent-hive agents` elenca il roster caricato.

### `session_not_found` su resume

- **Causa:** nessun record in memoria universale per quel `session_id` (sessione mai usata o records scaduti per TTL).
- **Soluzione:** verificare `GET /api/universal/session/{id}/context`; ricordare che `ttl_seconds` cancella i record scaduti (`purge_expired` gira nel gateway e nel self-heal).

### Il token non funziona subito dopo `rotate`

- **Comportamento corretto:** `rotate` revoca immediatamente il vecchio token e restituisce il nuovo **una sola volta**. Se il nuovo token viene rifiutato con `Token revoked`, state passando il vecchio. Salvare il nuovo al primo utilizzo.

### STDIO MCP: nessuna risposta dal processo

- **Causa tipica:** log/warning inviati su stdout (corrompono il protocollo JSON-RPC) oppure DB inaccessibile.
- **Verifica:** lo STDIO scrive i log solo su stderr; provare `DATABASE_URL=sqlite+aiosqlite:///./data/agent_hive.db agent-hive mcp` e controllare stderr. Ogni riga di risposta è un oggetto JSON-RPC 2.0.

### L'audit non registra

- L'audit è best-effort: un fallimento di scrittura non blocca la richiesta ma viene loggato. Verificare che la tabella `audit_log` esista (`agent-hive init-db`) e il livello di log (`LOG_LEVEL=INFO` mostra i warning).

### GitHub `403` da parte del client interno

- **Lettura corretta:** il messaggio distingue *token limitation* (scope mancanti riportati dall'API, visibili in `GET /api/github/status` → `reported_scopes`) da *mode limitation* (`read_only` rifiuta le scritture by design). Aggiustare il mode (`AGENT_HIVE_GITHUB_MODE`) oppure il token; le operazioni distruttive richiedono sempre `confirm: true`.
