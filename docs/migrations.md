# Database — PostgreSQL e migrazioni

> Parte del pacchetto "Parte completa per IA cloud e locale" (vedi [`AI_CONTEXT.md`](../AI_CONTEXT.md), sezione 14). Stato attuale: lo schema è creato automaticamente con `create_all` all'avvio (nessuna migrazione formale); SQLite è il database di default (`sqlite+aiosqlite:///./data/agent_hive.db`), PostgreSQL è supportato tramite `DATABASE_URL` con driver `asyncpg`.

## 14. Database

Per PostgreSQL:

```dotenv
DATABASE_URL=postgresql+asyncpg://agenthive:CHANGE_ME@localhost:5432/agenthive
```

Aggiungere:

- Alembic;
- migrazione iniziale;
- rollback;
- backup;
- restore test;
- indici;
- constraint;
- soft delete dove necessario;
- isolamento tenant;
- cancellazione dati;
- retention.

## Piano di adozione di Alembic (proposta operativa)

1. Aggiungere `alembic` a `requirements-dev.txt` e configurare `alembic.ini` + `alembic/env.py` puntando allo stesso `DATABASE_URL` usato dall'app.
2. Collegare i metadata SQLAlchemy esistenti (`agent_hive.db`) all'autogenerate di Alembic e generare la migrazione iniziale (`alembic revision --autogenerate -m "initial schema"`).
3. Sostituire gradualmente `create_all` con `alembic upgrade head` negli script di avvio (`agent-hive init-db`, Docker entrypoint), mantenendo `create_all` solo per i test su SQLite.
4. Ogni nuova tabella o colonna deve avere una migrazione con relativo `downgrade()` testato (rollback).
5. Aggiungere in CI un job per i test PostgreSQL (service container `postgres:16-alpine`) prima di rendere PostgreSQL il default di produzione.
6. Documentare le procedure di backup/restore in `docs/operations.md` quando implementate.
