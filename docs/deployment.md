# Deployment — Docker, produzione e sicurezza

> Parte del pacchetto "Parte completa per IA cloud e locale" (vedi [`AI_CONTEXT.md`](../AI_CONTEXT.md), sezioni 5 e 13). Per la configurazione dei provider (locali e cloud) vedi [`providers.md`](providers.md); per il database vedi [`migrations.md`](migrations.md).

## 5. Docker

Preparazione:

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

Stop:

```bash
docker compose down
```

Reset ambiente:

```bash
docker compose down -v
docker compose up -d --build
```

Endpoint:

```text
http://127.0.0.1:8000
```

Health:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

Produzione:

```dotenv
ALLOW_MOCK=false
ENABLE_FILE_TOOLS=false
ENABLE_HTTP_TOOLS=false
API_HOST=0.0.0.0
DATABASE_URL=postgresql+asyncpg://agenthive:CHANGE_ME@db:5432/agenthive
```

Usare TLS, reverse proxy e autenticazione.

## 13. Sicurezza minima obbligatoria

- autenticazione API;
- API key o Bearer token;
- CORS esplicito;
- rate limit;
- payload size limit;
- timeout;
- TLS via reverse proxy;
- mock disabilitato in produzione;
- file tools disabilitati di default;
- HTTP tools disabilitati di default;
- SSRF protection;
- path traversal protection;
- validazione YAML;
- validazione provider URLs;
- allowlist domini;
- secret redaction nei log;
- health endpoint senza segreti;
- audit log;
- backup e restore;
- branch protetto;
- dipendenze aggiornate;
- scan vulnerabilità.

> Nota sullo stato attuale: alcune voci sono già implementate di base nella codebase (segnacolori via `ENABLE_FILE_TOOLS` / `ENABLE_HTTP_TOOLS`, sandbox `WORKSPACE_DIR`, secret scan nel quality gate, immagine Docker non-root, CORS e auth API opzionale — vedi `CHANGELOG.md` 1.0.1). Le voci non ancora implementate vanno trattate come requisiti per l'apertura al pubblico: verificare la presenza di ciascuna prima di esporre l'API.
