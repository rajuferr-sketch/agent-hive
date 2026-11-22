# Pull Request

## Descrizione

<!-- Cosa cambia e perché. Riferirsi al compito in TASKS.md o alla issue se esiste. -->

## Checklist

- [ ] Modifico solo i file necessari al compito
- [ ] Test aggiunti/aggiornati: `pytest -q` verde
- [ ] Lint pulito: `python -m ruff check src tests`
- [ ] Typecheck pulito: `python -m mypy src`
- [ ] Diagnosi eseguita: `python scripts/diagnose.py`
- [ ] Nessun segreto o API key nel diff (`.env` mai committato)
- [ ] Documentazione aggiornata insieme al codice (README/docs)
- [ ] `TASKS.md` aggiornato se il lavoro nasce da un compito affidato
- [ ] Compatibilità Python >= 3.10 su Linux, Windows, macOS
- [ ] Provider mock nei test; nessun provider reale senza configurazione esplicita

## Verifica eseguita

<!-- Comandi lanciati e risultato (diagnosi, test, smoke test, diff finale). -->

## CI

- [ ] Tutti i check verdi prima del merge
- [ ] Merge solo dopo review approvata (branch `main` protetto)
