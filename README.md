# Asset Manager

A personal budgeting app for Windows. It runs fully offline and keeps all data in a local SQLite file.

The monthly flow is **income → plan → spend → month-end settlement**: every won of income is assigned to an expense category, spending is tracked against that plan, and whatever is left over at month end goes to a category of your choice (e.g. savings), so that income = plan = spending.

> The UI is in Korean and amounts are whole KRW.

## Features

- **Monthly budget** — record income and expenses as line items under fixed categories, set a plan per category, and track remaining budget with a progress bar that shows a daily allowance.
- **Allocation & settlement** — cover overspending by moving plan amounts between categories, then close the month with one click (re-settle or undo any time).
- **Copy last month** — carry over income items and/or plan amounts from the previous month.
- **Dashboard** — monthly summary, income/expense trend, savings rate, spending breakdown, plan vs. actual.
- **Data safety** — manual backups, restore, reset, and automatic backups before migrations, restores, resets and deletions.
- **CSV import/export** with a dry-run preview; imports are all-or-nothing.

Asset tracking and economic-indicator features (ECOS/FRED) exist in the backend but are currently hidden from the UI.

## Quick start

Requires Python 3.11+.

```bat
setup.bat   :: create .venv and install dependencies (first time only)
run.bat     :: launch the desktop app
```

| Command | Description |
| --- | --- |
| `.venv\Scripts\python -m app.main` | Run in a desktop window (WebView2) |
| `.venv\Scripts\python -m app.main --browser` | Run in the default browser instead |
| `.venv\Scripts\python -m pytest -q` | Run tests |
| `build.bat` | Run tests, then build `dist\AssetManager\AssetManager.exe` with PyInstaller |

Data is stored in `%LOCALAPPDATA%\AssetManager` (database, `backups\`, `exports\`, `app.log`). Set `ASSET_MANAGER_DATA_DIR` to use a different folder.

## Tech stack

- **Backend**: Python, FastAPI, SQLite (versioned migrations via `PRAGMA user_version`)
- **Frontend**: Preact + htm and Chart.js, vendored (no build step, no CDN)
- **Desktop shell**: pywebview; packaged with PyInstaller

The server binds to `127.0.0.1` only and requires a custom header on state-changing requests (CSRF protection).

## Project layout

```
app/
  main.py        launcher (local server + desktop window)
  server.py      HTTP API
  db.py          schema and migrations
  services/      business logic (budget, records, categories, stats, backup, csv, ...)
  static/        frontend (index.html, css, js, vendor)
tests/           pytest suite
docs/            functional specification
```

See [docs/functional_specification.md](docs/functional_specification.md) for detailed behavior.
