# AI workflow — GitHub, PR e ordine corretto per le modifiche

> Parte del pacchetto "Parte completa per IA cloud e locale" (vedi [`AI_CONTEXT.md`](../AI_CONTEXT.md), sezioni 6 e 16). Integra il protocollo di bootstrap in [`AGENTS.md`](../AGENTS.md) e la coda dei compiti in [`TASKS.md`](../TASKS.md). I template per PR e issue (bug, feature, AI task) sono in `.github/`.

## 6. GitHub

Metodologia:

```bash
git switch -c feature/my-change
git add -A
git commit -m "feat: add provider support"
git push -u origin feature/my-change
```

Creazione PR con GitHub CLI:

```bash
gh pr create \
  --title "Add provider support" \
  --body "Tested locally and in CI"
```

Permessi ideali:

- repository selezionato;
- Contents: Read and write;
- Pull requests: Read and write;
- Workflows: Read and write solo se modificati `.github/workflows`;
- branch `main` protetto;
- merge solo tramite PR;
- almeno una review;
- CI obbligatoria.

Mai usare PAT nei comandi remoti visibili:

```bash
# Sconsigliato
git remote set-url origin https://TOKEN@github.com/...
```

Preferire:

- credenziali del credential manager;
- GitHub CLI;
- SSH;
- GitHub App.

## 16. Ordine corretto per modifiche

Per ogni modifica:

1. leggere `AGENTS.md`;
2. leggere `README.md`;
3. leggere le documentazioni pertinenti;
4. cercare test esistenti;
5. creare un branch;
6. eseguire diagnosi;
7. preparare test che riproducano il problema;
8. modificare solo i file necessari;
9. eseguire test;
10. eseguire lint;
11. eseguire typecheck;
12. verificare i diff;
13. verificare che nessun segreto sia stato aggiunto;
14. eseguire smoke test;
15. fare commit;
16. aprire pull request;
17. attendere CI;
18. richiedere review;
19. eseguire merge.

## Legami con gli altri file

- Il template di pull request (`.github/PULL_REQUEST_TEMPLATE.md`) implementa come checklist i punti 9-13 e 17 di questa pagina.
- Le issue assegnate alle IA usano il template `.github/ISSUE_TEMPLATE/ai-task.md`.
- Le regole di sicurezza applicabili durante il workflow sono in [`deployment.md`](deployment.md) (sezione 13).
