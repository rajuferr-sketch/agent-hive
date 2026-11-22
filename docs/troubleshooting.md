# Troubleshooting

> Guida rapida ai problemi più comuni, basata sul comportamento documentato della codebase (vedi [`providers.md`](providers.md), [`operations.md`](operations.md), [`windows.md`](windows.md), [`deployment.md`](deployment.md)).

## L'output contiene il tag `[MOCK]`

- **Causa:** nessun provider reale configurato, oppure tutti i provider della catena dell'agente hanno fallito con `ALLOW_MOCK=true`: il mock deterministico risponde al posto loro. E un comportamento voluto, non un bug.
- **Soluzione:** configurare un provider reale (`OPENAI_API_KEY` oppure `OLLAMA_BASE_URL`, vedi [`providers.md`](providers.md)) oppure continuare in mock mode, utile per test e CI.

## `ProviderError` durante una missione

- Con `ALLOW_MOCK=false` l'esaurimento della catena di provider solleva `ProviderError`: nessuna risposta finta, nessun silenzio (policy di onestà del mock, vedi [`providers.md`](providers.md)).
- **Verifica:** `python scripts/diagnose.py` oppure `agent-hive diagnose` (health probe dei provider, timeout 10 s, exit code 1 su failure core).

## Un provider locale non risponde

- **Circuit breaker:** dopo 2 fallimenti consecutivi il provider viene saltato per 60 secondi, poi ritentato; un backend giu non blocca il resto della catena.
- **Ollama:** un 404 da Ollama quasi sempre significa "modello non scaricato": `ollama pull <modello>`.
- **LM Studio / vLLM / LiteLLM:** verificare la porta (1234, 8001, 4000 negli esempi di [`providers.md`](providers.md)), che il server sia avviato e che il nome del modello nel YAML corrisponda a quello servito.
- Dopo una modifica alle configurazioni, non fidarsi dei contatori del circuit breaker di una sessione gia avviata: riavviare il processo (invalidazione cache/circuit breaker, regola universale in [`AI_CONTEXT.md`](../AI_CONTEXT.md)).

## Quality gate: deliverable respinto o score basso

- Il gate valuta completezza, copertura dei requisiti, controllo AST del Python incluso, segreti e marker residui; score minimo 0.7, fino a 2 round di revisione automatica.
- **Soluzione:** riformulare la missione con requisiti espliciti e completi; verificare che il deliverable non contenga segreti o marker tipo TODO/XXX.

## Problemi database
n
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
