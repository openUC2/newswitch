# CLAUDE.md

## Arbeitsweise — verbindlich

**Immer zuerst planen.** Auch wenn im Prompt nicht ausdrücklich danach gefragt wird: erst in
den Planungsmodus gehen und einen Umsetzungsplan vorlegen. Implementiert wird **erst nach
ausdrücklicher Freigabe** durch den Nutzer. Reine Fragen, Recherche und Lesezugriffe sind
davon nicht betroffen — die Regel gilt für Änderungen am Projekt.

**Das Arbeitsverzeichnis `newswitch` nicht verlassen.** `cd` nur innerhalb des Projekts.
Diese Einschränkung lässt sich als Berechtigungsregel nicht ausdrücken und steht deshalb hier.

**Keine Git-Schreiboperationen** (commit, push, merge, rebase, reset, cherry-pick) — das macht
der Nutzer selbst. Technisch erzwungen in **[settings.json](settings.json)** unter
`permissions.allow` / `permissions.deny`.

Den aktuellen Arbeitsstand / Übergaben zwischen Sessions führt **[STATUS.md](STATUS.md)**.

Bitte für jeden umgesetzten Plan einen neuen Eintrag am oberen Teil der Status.md genierieren.  (Überschrift, Datum, implemented?, committed?)
---

## Projekt und Aufbau

"Imswitch, aber neu": Mikroskop-Steuerung (openUC2) mit Web-Stack. Früher Alpha-Stand.

- `backend/` — Python ≥3.11, FastAPI/uvicorn, Paket `newswitch/`, Einstieg `main.py`, Tests in
  `tests/`. Abhängigkeiten über **uv**. Geräte-Konfiguration: eine Datei
  `backend/Configs/newswitch-config.yaml`, gelesen von `newswitch/config_io/` (Schema, generiert:
  `Configs/schemas/newswitch-config.schema.yaml`). Entwickler-Überblick:
  `backend/docs/DEVELOPER_OVERVIEW.md`.
- `frontend/` — React + TypeScript + Vite, Paketmanager **yarn** (v1), Tests mit vitest.
- Ports (`BACKEND_PORT` 8099, `FRONTEND_PORT` 5173) kommen aus der committeten Root-`.env`.

## Fallstricke

- **Das Frontend wird aus dem Backend generiert.** `frontend/plugins/generate-app.ts` holt bei
  `vite dev`/`vite build` die Schemas vom *laufenden* Backend und erzeugt
  `frontend/src/apps/default/**` sowie `frontend/blok.json`. Ist das Backend nicht erreichbar,
  wird **still** auf die committeten Dateien zurückgefallen → veraltete Hooks. Deshalb Backend
  zuerst starten (`just dev` sequenziert das).
- Generierte Dateien (`frontend/src/apps/**`, `frontend/blok.json`) sind **absichtlich committet**
  — nicht gitignoren, nicht von Hand formatieren oder editieren.
- `tsc --noEmit` im Root prüft nichts (Solution-Config mit `files: []`) — Typprüfung über
  `just types` (`tsconfig.app.json`).
- Commit-Messages sind **Conventional Commits** (commitlint, Scopes: backend, frontend, codegen,
  ci, docker, release, deps, repo) — daraus leitet semantic-release Version und Changelog ab.

## Konventionen

- Backend: ruff (Format + Lint, zusätzlich `ANN`, `D1`, `F401` → Typannotationen und
  Docstrings erwartet).
- Frontend: eslint + prettier.

## Build- und Testbefehle (alle über `just`, vom Projekt-Root)

```bash
just check         # fmt-check + lint + types + test — vor Abschluss einer Änderung
just test-backend  # pytest -k "not integration"
just test-frontend # vitest
just test-all      # inkl. Backend-Integrationstests
just lint | just fmt | just types
just drift-check   # generierter Code noch synchron? (Backend muss laufen)
```
