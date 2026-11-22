# Coda dei compiti affidati — TASKS.md

**Come funziona.** Questo file è il canale ufficiale con cui l'utente affida compiti alle chat IA che lavorano su questa repository. Ogni chat IA o agente che apre questa repo DEVE:

1. leggere prima [`AGENTS.md`](AGENTS.md) (protocollo di bootstrap, comandi, convenzioni, regole di sicurezza);
2. leggere questo file e prendere il primo compito aperto (priorità più alta);
3. eseguire il compito seguendo le regole in `AGENTS.md`;
4. a fine lavoro, spostare il compito in "Compiti completati" con un breve resoconto.

**Per assegnare un compito:** copia il template qui sotto nella sezione "Compiti aperti", compilando tutti i campi. In alternativa puoi aprire una issue con il template "AI task" (`.github/ISSUE_TEMPLATE/ai-task.md`): le chat IA con accesso a GitHub la vedranno allo stesso modo.

---

## Stato attuale

**1 compito aperto:** T-002 — applicare la matrice CI OS x Python a `.github/workflows/ci.yml`. Richiede il permesso `workflows` (che l'integrazione GitHub in uso non ha) oppure l'intervento manuale dell'owner: la specifica completa pronta da incollare è in [`AI_CONTEXT.md`](AI_CONTEXT.md), sezione 12 ("Migliorie CI").

---

## Compiti aperti

### T-002 — Applicare la matrice CI OS x Python a `.github/workflows/ci.yml`
- **Stato:** todo
- **Priorità:** alta
- **Assegnato a:** owner (applicazione manuale) oppure una chat IA con permesso `workflows`
- **Descrizione:** sostituire il job `test` in `.github/workflows/ci.yml` con la matrice completa `ubuntu-latest` / `windows-latest` / `macos-latest` x Python `3.10` / `3.11` / `3.12` (fail-fast: false) e aggiungere il job `typecheck` (`mypy src`). La specifica completa pronta da incollare è in `AI_CONTEXT.md`, sezione 12 ("Migliorie CI"); il job `lint` resta invariato.
- **Criteri di accettazione:** `.github/workflows/ci.yml` contiene la matrice e il job `typecheck`; la run CI su `main` è verde su tutte le celle della matrice.
- **Vincoli:** non toccare altro; il job `lint` non cambia; nessuna modifica al codice sorgente.
- **Esito / note:** da compilare a fine lavoro.

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

### T-001 — Integrare il pacchetto "Parte completa per IA cloud e locale"
- **Stato:** done
- **Priorità:** alta
- **Assegnato a:** Z.AI (chat utente, sessione 2026-11-22/23)
- **Descrizione:** aggiungere alla repo tutte le 18 sezioni del pacchetto fornito dall'utente e i file essenziali di community/CI indicati nella sezione 12 del pacchetto.
- **Criteri di accettazione:** tutte le sezioni presenti nei file previsti e collegate dagli indici; indici aggiornati; CHANGELOG aggiornato; TASKS.md aggiornato.
- **Vincoli:** solo documentazione e file di configurazione CI/community; nessuna modifica al codice sorgente; nessun segreto.
- **Esito / note:** completato il 2026-11-23. Contenuto distribuito in: `AI_CONTEXT.md` (sez. 1, 2, 7, 10, 11, 12, 17, 18 + specifica CI pronta), `docs/providers.md` (esteso con sez. 3, 4, 15), `docs/deployment.md` (sez. 5, 13), `docs/migrations.md` (sez. 14), `docs/compatibility.md` (sez. 9), `docs/windows.md`, `docs/troubleshooting.md`, `docs/ai-workflow.md` (sez. 6, 16), `llms-full.txt`, `llms.txt` (aggiornato), `SUPPORT.md`, `.github/CODEOWNERS`, `.github/CODE_OF_CONDUCT.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/bug_report.yml`, `.github/ISSUE_TEMPLATE/feature_request.yml`, `AGENTS.md` (indice documentazione aggiornato), `CHANGELOG.md` (voce [Unreleased]). **Residuo:** la matrice CI non è applicabile da questa integrazione (permesso `workflows` mancante) — tracciata come T-002.

<!-- Sposta qui i compiti terminati, con data ed esito. -->
