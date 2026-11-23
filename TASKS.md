# Coda dei compiti affidati — TASKS.md

**Come funziona.** Questo file è il canale ufficiale con cui l'utente affida compiti alle chat IA che lavorano su questa repository. Ogni chat IA o agente che apre questa repo DEVE:

1. leggere prima [`AGENTS.md`](AGENTS.md) (protocollo di bootstrap, comandi, convenzioni, regole di sicurezza);
2. leggere questo file e prendere il primo compito aperto (priorità più alta);
3. eseguire il compito seguendo le regole in `AGENTS.md`;
4. a fine lavoro, spostare il compito in "Compiti completati" con un breve resoconto.

**Per assegnare un compito:** copia il template qui sotto nella sezione "Compiti aperti", compilando tutti i campi. In alternativa puoi aprire una issue con il template "AI task" (`.github/ISSUE_TEMPLATE/ai-task.md`): le chat IA con accesso a GitHub la vedranno allo stesso modo.

---

## Stato attuale

**1 compito aperto:** T-002 — applicare la matrice CI OS x Python a `.github/workflows/ci.yml`. Richiede il permesso `workflows` (che l'integrazione GitHub in uso non ha) oppure l'intervento manuale dell'owner: la specifica completa pronta da incollare è in [`AI_CONTEXT.md`](AI_CONTEXT.md), sezione 12 ("Migliorie CI"). La specifica è stata **validata in locale** il 2026-11-23 (YAML corretto, 9 celle, lint invariato — vedi T-003) e le celle ubuntu della matrice sono verdi dopo il fix di compatibilità Python 3.10 (T-003, PR #1); resta solo l'applicazione del file.

---

## Compiti aperti

### T-002 — Applicare la matrice CI OS x Python a `.github/workflows/ci.yml`
- **Stato:** todo
- **Priorità:** alta
- **Assegnato a:** owner (applicazione manuale) oppure una chat IA con permesso `workflows`
- **Descrizione:** sostituire il job `test` in `.github/workflows/ci.yml` con la matrice completa `ubuntu-latest` / `windows-latest` / `macos-latest` x Python `3.10` / `3.11` / `3.12` (fail-fast: false) e aggiungere il job `typecheck` (`mypy src`). La specifica completa pronta da incollare è in `AI_CONTEXT.md`, sezione 12 ("Migliorie CI"); il job `lint` resta invariato.
- **Criteri di accettazione:** `.github/workflows/ci.yml` contiene la matrice e il job `typecheck`; la run CI su `main` è verde su tutte le celle della matrice.
- **Vincoli:** non toccare altro; il job `lint` non cambia; nessuna modifica al codice sorgente.
- **Esito / note:** da compilare a fine lavoro. Nota 2026-11-23 (T-003): specifica validata in locale; push di `.github/workflows/ci.yml` rifiutato dall'integrazione (403, permesso `workflows` mancante).

<!-- Incolla qui i nuovi compiti, il più importante in cima. Rimuovi il commento e usa il template. -->

## Template compito

```markdown
### T-XXX — <titolo breve del compito>
- **Stato:** todo | in_progress | done
- **Priorità:** alta | media | bassa
- **Assegnato a:** <nome della chat/agente, oppure "qualsiasi">
- **Descrizione:** <cosa fare, con tutti i dettagli necessari>
- **Criteri di accettazione:** <come si verifica che il compito è fatto>
- **Vincoli:** <limiti, es. "non toccare configs/system.yaml">
- **Esito / note:** <da compilare a fine lavoro>
```

## Compiti completati

### T-004 — AgentHive Universal AI Platform (MCP + gateway + memoria condivisa + connettori + sicurezza + GitHub + self-heal)
- **Stato:** done
- **Priorità:** alta
- **Assegnato a:** Z.AI (chat utente, sessione 2026-11-23)
- **Descrizione:** trasformare AgentHive in una piattaforma AI universale: MCP server (18 tool, Streamable HTTP + STDIO), Universal AI Gateway, memoria condivisa persistente cross-client, connettori client (OpenAI-compatible, Ollama, WS, generic tool-calling), sicurezza by design (token/scopes/RBAC/rate-limit/audit/anti-injection), integrazione GitHub a 4 modalità, auto-diagnostica self-heal con limiti, Docker + documentazione completa, test obbligatori inclusi i due test nominati.
- **Criteri di accettazione:** 18 tool MCP realmente implementati e verificati; memoria condivisa con persistenza reale tra client diversi (test dedicato); gateway con concorrenza/timeout/cancel/resume; 6+ connettori lato server; token lifecycle completo; GitHub client con mode gates; self-heal con retry cap/budget/safe-stop; suite verde su 3.10/3.11/3.12; ruff + mypy puliti; Docker/.env aggiornati; 14+ documenti nuovi/aggiornati.
- **Vincoli:** nessun nuovo pip dependency; nessun segreto nel repo; niente claim non verificati (VERIFIED/PARTIALLY VERIFIED/IMPLEMENTED/DOCUMENTED/BLOCKED nel report finale).
- **Esito / note:** completato il 2026-11-23. Nuovi moduli: `mcp/` (schema, tools, server, http, stdio), `gateway/`, `universal_memory/`, `security/` (tokens, rbac, ratelimit, sanitize, audit, middleware), `connectors/` (openai_api, ollama_api, ws, generic), `github_integration/`, `selfheal/`, `providers/anthropic.py`, `providers/gemini.py`, `providers/presets.py`, `src/agent_hive/__main__.py`. Modificati: `hive.py`, `api/app.py`, `db/models.py` (3 nuove tabelle), `config/settings.py`, `cli.py`, `docker-compose.yml`, `.env.example`. Test: 224/224 su 3.10/3.11/3.12 (da 109), inclusi `test_UNIVERSAL_CROSS_CLIENT_MEMORY_TEST` e `test_UNIVERSAL_MCP_TOOL_EXECUTION_TEST` + STDIO end-to-end con subprocess reale. Ruff pulito, mypy pulito (107 file). Residuo: T-002 (CI matrix, permesso owner); verifica con API key reali dei provider cloud (contract-tested, non live).



### T-001 — Integrare il pacchetto "Parte completa per IA cloud e locale"
- **Stato:** done
- **Priorità:** alta
- **Assegnato a:** Z.AI (chat utente, sessione 2026-11-22/23)
- **Descrizione:** aggiungere alla repo tutte le 18 sezioni del pacchetto fornito dall'utente e i file essenziali di community/CI indicati nella sezione 12 del pacchetto.
- **Criteri di accettazione:** tutte le sezioni presenti nei file previsti e collegate dagli indici; indici aggiornati; CHANGELOG aggiornato; TASKS.md aggiornato.
- **Vincoli:** solo documentazione e file di configurazione CI/community; nessuna modifica al codice sorgente; nessun segreto.
- **Esito / note:** completato il 2026-11-23. Contenuto distribuito in: `AI_CONTEXT.md` (sez. 1, 2, 7, 10, 11, 12, 17, 18 + specifica CI pronta), `docs/providers.md` (esteso con sez. 3, 4, 15), `docs/deployment.md` (sez. 5, 13), `docs/migrations.md` (sez. 14), `docs/compatibility.md` (sez. 9), `docs/windows.md`, `docs/troubleshooting.md`, `docs/ai-workflow.md` (sez. 6, 16), `llms-full.txt`, `llms.txt` (aggiornato), `SUPPORT.md`, `.github/CODEOWNERS`, `.github/CODE_OF_CONDUCT.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/feature_request.yml`, `AGENTS.md` (indice documentazione aggiornato), `CHANGELOG.md` (voce [Unreleased]). **Residuo:** la matrice CI non è applicabile da questa integrazione (permesso `workflows` mancante) — tracciata come T-002.

### T-003 — Simulazione CI locale su repo clonata (matrice OS x Python) e correzione dei bug rilevati
- **Stato:** done
- **Priorità:** alta
- **Assegnato a:** Z.AI (chat utente, sessione 2026-11-23)
- **Descrizione:** richiesta in chat dall'utente ("Fai simulazione dopo averlo scaricato"): clonare la repo nel sandbox, simulare i job CI in locale su Python 3.10/3.11/3.12 (ruff, mypy, pytest) e validare la specifica CI della T-002 prima dell'applicazione.
- **Criteri di accettazione:** tutti i job simulati eseguiti; eventuali anomalie documentate e corrette; esito riportato.
- **Vincoli:** nessun segreto; nessuna modifica a `configs/system.yaml`; fix minimi e mirati.
- **Esito / note:** completato il 2026-11-23. Simulazione su `main`: (1) job lint rosso — W292 newline mancante in `tests/test_router.py`; (2) su Python 3.10, 2 failed + 2 teardown errors in `tests/test_missions_e2e.py` con run di ~183 s — causa: su 3.10 `asyncio.wait_for` solleva `asyncio.TimeoutError`, che coincide con il builtin `TimeoutError` solo da 3.11+, quindi i tre `except TimeoutError` in `src/agent_hive/tasks/scheduler.py` non matchavano e il loop/stop dello scheduler si rompeva; (3) mypy verde (77 file) e pytest verde su 3.11/3.12 (109 test). Correzioni: `asyncio.TimeoutError` nei tre handler (nessun cambio di comportamento su 3.11+) e newline in `tests/test_router.py`. Verifica post-fix: ruff pulito, mypy pulito, 109/109 passati su 3.10, 3.11 e 3.12 (run 3.10 da ~183 s a ~4 s); missione end-to-end in mock mode OK. Specifica T-002 validata in locale (YAML, 9 celle, fail-fast false, lint invariato); push di `ci.yml` bloccato dal permesso `workflows` mancante (403) — resta l'applicazione manuale dell'owner. Fix inviati con PR #1.

<!-- Sposta qui i compiti terminati, con data ed esito. -->
