# Windows

> Parte del pacchetto "Parte completa per IA cloud e locale" (vedi [`AI_CONTEXT.md`](../AI_CONTEXT.md)). Raccolta delle istruzioni specifiche Windows: attivazione ambiente virtuale (sezione 1 del pacchetto), copia della configurazione (sezione 2), regole cross-platform (sezione 10).

## Attivazione ambiente virtuale

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Se PowerShell blocca l'attivazione dello script, usare `Set-ExecutionPolicy -Scope Process RemoteSigned` per la sola sessione corrente.

## Copia della configurazione

```powershell
Copy-Item .env.example .env
```

## Verifica (comandi cross-platform, identici su Windows)

```powershell
python scripts/diagnose.py
python run.py "Diagnose this repository"
pytest -q
python -m ruff check src tests
python -m mypy src
```

Installazione one-shot alternativa con script dedicato:

```powershell
.\scripts\install.ps1
```

## Regole Windows (estratto dalla sezione 10 del pacchetto)

- Non assumere un sistema Unix su Windows.
- Non usare comandi Bash nei file Python.
- Usare `python -m ...` per invocare gli strumenti (pip, ruff, mypy): funziona su tutte le piattaforme.
- Usare `pathlib` anziché concatenazioni manuali di percorsi.
- Nei workflow GitHub Actions la matrice CI include `windows-latest`, quindi ogni modifica deve passare i test anche su Windows (vedi `.github/workflows/ci.yml`).
