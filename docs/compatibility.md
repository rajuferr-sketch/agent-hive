# Compatibilità tra modelli IA

> Parte del pacchetto "Parte completa per IA cloud e locale" (vedi [`AI_CONTEXT.md`](../AI_CONTEXT.md), sezione 9). Istruzioni operative da dare alle diverse IA quando lavorano su questa repository. Per il protocollo d'ingresso comune vedi [`AGENTS.md`](../AGENTS.md); per la coda dei compiti vedi [`TASKS.md`](../TASKS.md).

## 9. Compatibilità tra modelli IA

### Claude

Istruzioni consigliate:

```text
Leggi AGENTS.md e README.md.
Non modificare .env, data/, workspace/ o segreti.
Crea prima una diagnosi.
Usa pip, pytest, Ruff e MyPy.
Esegui modifiche limitate e ben descritte.
Non usare provider reali nei test salvo configurazione esplicita.
Esegui test prima del commit.
Mostra un elenco dei file modificati e un diff finale.
```

### ChatGPT/Codex

```text
Ispeziona il repository.
Individua l'errore o la feature.
Mostra un piano corto.
Modifica solo i file necessari.
Mantieni compatibilità Python 3.10+.
Aggiorna test e documentazione.
Esegui:
python scripts/diagnose.py
pytest -q
python -m ruff check src tests
python -m mypy src
Crea un branch e una PR.
```

### Z.AI/GLM

```text
Usa il repository come workspace locale o remoto.
Rispetta AGENTS.md e pyproject.toml.
Usa esclusivamente comandi Python cross-platform.
Non usare provider reali nei test senza una chiave esplicita.
Configura il provider tramite variabili ambiente.
Usa SQLite nei test.
Dopo le modifiche:
1. diagnostica;
2. pytest;
3. lint;
4. typecheck;
5. diff;
6. commit su branch;
7. pull request.
```

> Queste istruzioni integrano e non sostituiscono le regole universali in [`AI_CONTEXT.md`](../AI_CONTEXT.md) (sezione 10) e le guardie in [`AGENTS.md`](../AGENTS.md) (sezione 8).
