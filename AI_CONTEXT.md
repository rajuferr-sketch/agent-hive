# AI_CONTEXT.md — contesto operativo completo per IA cloud e locale

> Questo file è il riferimento operativo completo per qualsiasi IA (chat cloud o runtime locale) che lavora su AgentHive. Fa parte del pacchetto "Parte completa per IA cloud e locale" integrato nella repository il 2026-11-23. Per il protocollo d'ingresso (cosa leggere, in quale ordine) vedi [`AGENTS.md`](AGENTS.md); per la coda dei compiti affidati vedi [`TASKS.md`](TASKS.md).

**Dove si trova ogni parte del pacchetto:**

| Sezione del pacchetto | Posizione |
|---|---|
| 1. Quick Start universale | qui sotto |
| 2. Configurazione locale minima | qui sotto |
| 3. Provider locali (Ollama, LM Studio, vLLM, LiteLLM) | [docs/providers.md](docs/providers.md) |
| 4. Provider cloud (OpenAI, Z.AI/GLM, Azure, Anthropic, Google) | [docs/providers.md](docs/providers.md) |
| 5. Docker | [docs/deployment.md](docs/deployment.md) |
| 6. GitHub (metodologia, permessi, PR) | [docs/ai-workflow.md](docs/ai-workflow.md) |
| 7. Comandi CLI | qui sotto |
| 8. API principali | [README.md](README.md) e [docs/api.md](docs/api.md) |
| 9. Compatibilità tra modelli IA | [docs/compatibility.md](docs/compatibility.md) |
| 10. Regole universali per tutte le IA | qui sotto |
| 11. Struttura da preservare | qui sotto |
| 12. Cosa aggiungere al repository | qui sotto (con stato di applicazione) |
| 13. Sicurezza minima obbligatoria | [docs/deployment.md](docs/deployment.md) |
| 14. Database | [docs/migrations.md](docs/migrations.md) |
| 15. Aggiunta provider completo | [docs/providers.md](docs/providers.md) |
| 16. Ordine corretto per modifiche | [docs/ai-workflow.md](docs/ai-workflow.md) |
| 17. Prompt pronto da dare a qualunque IA | qui sotto |
| 18. Stato finale previsto | qui sotto |

## 1. Quick Start universale

```bash
git clone https://github.com/rajuferr-sketch/agent-hive.git
cd agent-hive
python -m venv .venv
```

Linux/macOS/WSL:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Verifica:

```bash
python scripts/diagnose.py
python run.py "Diagnose this repository"
pytest -q
python -m ruff check src tests
python -m mypy src
```

## 2. Configurazione locale minima

Copia il template:

```bash
cp .env.example .env
```

Windows:

```powershell
Copy-Item .env.example .env
```

Configurazione offline:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./data/agent_hive.db
ALLOW_MOCK=true
LOG_LEVEL=INFO
CONFIG_DIR=./configs
WORKSPACE_DIR=./workspace
MAX_CONCURRENCY=8
DEFAULT_TASK_TIMEOUT=120
DEFAULT_MAX_RETRIES=2
API_HOST=127.0.0.1
API_PORT=8000
ENABLE_FILE_TOOLS=false
ENABLE_HTTP_TOOLS=false
```

## 7. Comandi CLI

```bash
python run.py "Write a haiku"
python run.py --mode A "Write a Python hello world"
python run.py --mode C "Build a REST API"
python run.py --mode B "Create a complete SaaS architecture"
python run.py --format json "Analyze the repository"
python run.py --chat "Answer using the host AI"
python run.py demo logistica
python run.py demo codice
```

Con pacchetto installato:

```bash
agent-hive diagnose
agent-hive init-db
agent-hive run "Create a REST API" --mode C --json
agent-hive agents
agent-hive status
agent-hive recover
agent-hive start --host 127.0.0.1 --port 8000
```

## 10. Regole universali per tutte le IA

- Non modificare segreti.
- Non modificare `.env`.
- Non modificare database SQLite.
- Non modificare workspace.
- Non modificare configurazioni fondamentali senza approvazione.
- Non aggiungere dipendenze senza motivo.
- Non assumere un sistema Unix su Windows.
- Non usare comandi Bash nei file Python.
- Non usare URL hardcoded nei provider.
- Non usare API key nei file versionati.
- Non usare network negli unit test.
- Non fare commit direttamente su `main`.
- Non fare merge di una PR senza test.
- Aggiornare test e documentazione insieme al codice.
- Usare type hints moderni compatibili con Python 3.10.
- Usare `pathlib` anziché concatenazioni manuali di percorsi.
- Usare logging anziché print nelle librerie.
- Usare eccezioni specifiche.
- Validare input API.
- Validare YAML.
- Validare JSON restituito dai modelli.
- Invalidare cache/circuit breaker dopo configurazioni nuove.
- Gestire cancellazione e timeout.
- Rendere tutte le operazioni ripetibili.
- Rendere gli script idempotenti.
- Registrare tutte le modifiche nello changelog.

> Nota operativa: la regola "Non fare commit direttamente su `main`" è vincolante per le IA e per i contributi esterni. L'owner può decidere quando applicarla a se stesso.

## 11. Struttura da preservare

```text
agent-hive/
├── .github/
├── configs/
│   ├── system.yaml
│   ├── master.yaml
│   └── agents/
├── docs/
├── scripts/
├── src/agent_hive/
│   ├── api/
│   ├── agents/
│   ├── communication/
│   ├── config/
│   ├── core/
│   ├── db/
│   ├── memory/
│   ├── orchestrator/
│   ├── providers/
│   ├── tasks/
│   └── tools/
├── tests/
├── workspace/
├── data/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── AGENTS.md
└── README.md
```

## 12. Cosa aggiungere al repository

**Stato di applicazione del pacchetto (aggiornato al 2026-11-23):** tutte le parti documentali e di community sono state applicate. Le voci già presenti nella repository restano quelle ufficiali; le altre sono state create. La matrice CI è specificata ma non ancora applicata: l'integrazione GitHub in uso non possiede il permesso di modificare i file in `.github/workflows/` — vedi "Migliorie CI" qui sotto e il compito T-002 in [`TASKS.md`](TASKS.md).

### File essenziali

| File | Stato |
|---|---|
| `AI_CONTEXT.md` | creato (questo file) |
| `llms.txt` | già presente, aggiornato con i link del pacchetto |
| `llms-full.txt` | creato |
| `CODEOWNERS` | creato in `.github/CODEOWNERS` |
| `.github/CODE_OF_CONDUCT.md` | creato |
| `.github/PULL_REQUEST_TEMPLATE.md` | creato |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | creato |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | creato |
| `SECURITY.md` | già presente |
| `SUPPORT.md` | creato |
| `CHANGELOG.md` | già presente, aggiornato con la voce del pacchetto |
| `CONTRIBUTING.md` | già presente |
| `docs/providers.md` | già presente, esteso con provider locali/cloud (sez. 3 e 4) e contratto provider (sez. 15) |
| `docs/compatibility.md` | creato |
| `docs/windows.md` | creato |
| `docs/troubleshooting.md` | creato |
| `docs/deployment.md` | creato |
| `docs/ai-workflow.md` | creato |
| `docs/migrations.md` | creato |

### Migliorie CI

- **Matrice OS x Python (specifica pronta, da applicare manualmente):** sostituire `.github/workflows/ci.yml` con la configurazione qui sotto — job `lint` invariato, nuovo job `typecheck` (mypy), job `test` in matrice `ubuntu-latest` / `windows-latest` / `macos-latest` x Python `3.10` / `3.11` / `3.12` con fail-fast disattivato. Applicazione richiede un token con permesso `workflows` oppure l'intervento manuale dell'owner (tracciato come T-002 in [`TASKS.md`](TASKS.md)).

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    name: Lint (ruff)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements-dev.txt

      - name: Ruff check
        run: ruff check src tests

  typecheck:
    name: Typecheck (mypy)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: |
          pip install -r requirements-dev.txt
          pip install -e ".[dev]"

      - name: MyPy
        run: mypy src

  test:
    name: Tests (${{ matrix.os }}, Python ${{ matrix.python-version }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt
          pip install -e ".[dev]"

      - name: Run test suite
        run: pytest -q
```

- Pianificate per una fase successiva (da applicare singolarmente e verificare in CI prima del merge): CodeQL, coverage, SBOM, secret scan, dependency review, Docker build, smoke test, test packaging, test PostgreSQL.

## 17. Prompt pronto da dare a qualunque IA

```text
Stai lavorando sul repository rajuferr-sketch/agent-hive.

Leggi AGENTS.md, README.md e pyproject.toml.
Non modificare segreti, .env, data/, workspace/ o configurazioni
fondamentali senza istruzioni esplicite.
Lavora su un nuovo branch.
Mantieni Python >=3.10 compatibile.
Mantieni compatibilità Linux, Windows, macOS e Docker.
Usa provider mock nei test.
Esegui prima i test esistenti.
Aggiungi test per ogni modifica.
Esegui python scripts/diagnose.py, pytest -q,
python -m ruff check src tests e python -m mypy src.
Mostrami il piano prima delle modifiche.
Crea il diff finale.
Non creare, modificare o esporre chiavi API.
Apri una pull request solo dopo che tutti i controlli passano.
```

## 18. Stato finale previsto

Una volta applicato questo pacchetto:

- compatibilità reale con modelli cloud e locali;
- GitHub Actions multipiattaforma;
- Docker e PostgreSQL verificati;
- provider IA configurabili;
- API protetta;
- database migrabile;
- installazione locale ripetibile;
- istruzioni leggibili da ogni IA;
- codice testato prima del merge;
- release e SBOM;
- branch protetto;
- segreti fuori dal repository;
- documentazione completa;
- supporto Claude, ChatGPT, Z.AI/GLM, Ollama, LM Studio, vLLM e LiteLLM;
- contributi sicuri tramite PR;
- operazioni locali e cloud documentate;
- progetto pronto per uso personale, comunitario e commerciale.
