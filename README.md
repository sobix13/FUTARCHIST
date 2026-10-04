# FUTARCHIST 2.1.1

An English-only Telegram management app for project information, fundraising reviews, teams, agencies, hosts and programs in the MetaDAO and Futardio ecosystem. Native Telegram management and a browser dashboard, private access codes, case history, programs, tasks and Excel/CSV exports. No AI services or emoji controls. Built by Ownership.

## Repository contents and downloads

This repository contains the complete English 2.1.1 release. The ZIP filenames retain `v2`; the application version inside is `2.1.1`.

| Resource | Contents |
| --- | --- |
| [Requirements](requirements.txt) | Python runtime requirements, with no third-party runtime dependencies |
| [Command help](docs/HELP.md) | Guest, admin and superadmin commands and common workflows |
| [Architecture](docs/ARCHITECTURE.md) | Data model, permissions, queues, exports and failure boundaries |
| [VPS installation](extensions/DEPLOY.md) | Configuration, independent services, HTTPS, backups and acceptance |
| [Operations and updates](extensions/UPDATES.md) | Implemented operations, known limits and future work |
| [Release notes](docs/RELEASE.md) | English-only changes and verified release evidence |
| [Complete source ZIP](https://github.com/sobix13/FUTARCHIST/blob/main/downloads/FUTARCHIST_v2.zip) | Source, assets, requirements, documentation and tests |
| [Standalone user guide](docs/USER_GUIDE.html) | The full English guide with embedded styles and logos |
| [Standalone test report](reports/test-report.html) | Recorded tests, results and pending acceptance checks |
| [Operations ZIP](https://github.com/sobix13/FUTARCHIST/blob/main/downloads/FUTARCHIST_Operations_v2.zip) | Installation and maintenance documents and scripts |
| [Download checksums](https://github.com/sobix13/FUTARCHIST/blob/main/downloads/FUTARCHIST_Checksums.json) | SHA-256 checksums of the four download files |

Publication in GitHub makes the source and downloads available. Continuous bot operation requires a configured host following the VPS installation guide.

## Quick local start

Requires Python 3.12 or later on Linux or macOS, with a persistent local filesystem. Runtime dependencies are Python's standard library. Node is needed only for interface tests.

```bash
git clone https://github.com/sobix13/FUTARCHIST.git
cd FUTARCHIST
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m futarchist --demo
```

Open `http://127.0.0.1:8765`. The dashboard is at `/`, the Telegram-shaped simulator at `/emulator`, and the complete guide at `/guide`. Demo mode never connects to Telegram. It uses sample superadmins 1 and 4, admin 2, read-only member 3 and project representatives 101 and 102. Keep demo mode local. Demo and live databases are separate.

## Test bot and superadmins

Current test username: `FutarchistBot`. Bot ID: `8911627546`. Product name: FUTARCHIST. Account authority uses numeric Telegram IDs, never usernames.

| Account | Telegram ID | Role |
| --- | --- | --- |
| @sobix13 | 313342234 | Superadmin and support |
| @SrMessiSOL | 5691137098 | Superadmin and support |

The real token is excluded from the package. Copy `.env.example` to `.env` and set `BOT_TOKEN`. For a replacement bot, also update `BOT_USERNAME`. Removing a previously configured superadmin fails safely and requires a controlled migration.

```bash
.venv/bin/python -m futarchist --env .env --check-bot
.venv/bin/python -m futarchist --env .env --configure-bot
.venv/bin/python -m futarchist --env .env --mode bot
```

Each superadmin starts the bot and opens `/manage`. If Telegram has not seen a superadmin's chat yet, run `--configure-bot` again after their first Start to install the scoped command menu. App permissions are independent of that menu.

With `APP_URL` empty, management remains available entirely within Telegram. To use the browser dashboard or Mini App, set `APP_URL` to your HTTPS origin and run the web process separately:

```bash
.venv/bin/python -m futarchist --env .env --mode web --port 8765
```

For the installed Ubuntu/Debian VPS, `bash extensions/setup-web.sh` completes HTTPS and enables the web service. No purchased domain is required: it uses an IP-based `sslip.io` hostname, or your `FUTARCHIST_WEB_HOST`. The installer checks for conflicting proxies, preserves credentials and owner IDs, and keeps the bot and web in separate units. See the HTTPS section of [deployment](extensions/DEPLOY.md) for reachability requirements and rollback.

`--mode all` runs both processes together for local use. On a VPS, the two supplied systemd units isolate bot and web failures. Both use the same database on a local persistent disk. Run one polling worker only. An existing Telegram webhook is not removed automatically.

## Workspaces and access codes

Superadmins add admins using numeric Telegram IDs. Each admin receives a personal workspace and a private intake code. Internal teams use separate shared workspaces with explicit member permissions. An internal admin team is different from the project team submitting information.

The admin shares a code or intake link with a project representative. `/activate CODE` or `?start=intake_CODE` opens its assigned route. A guest code never grants an admin role. Codes support activation limits, expiry, restriction to one Telegram ID, suspension, rotation and individual access revocation. The public code is disabled in live mode.

General review and raise review use separate case branches. Each records its source admin ID and name, current assignee, status and history. Reassignment preserves the original source. Submissions in different workspaces are not merged automatically.

## English-only interface

Open **Guide** on the Telegram home screen or any native management screen, or send `/guide`. It explains submissions, replies, workspaces, codes, cases, filters, programs, tasks, invitations, exports, admin permissions, bot text, health and browser access. Sections follow the user's role. Opening the guide preserves saved guest forms and the active admin step. `/help` and `/guide` are registered in the command menu by `--configure-bot`. The native guide works without HTTPS or a running browser service.

The web Overview maps four steps: select a workspace, collect information, review cases and plan the next action. Navigation groups follow that workflow. Every section includes **How to use**, numbered steps, the next action and a link to the matching full-guide section. Access codes uses the same label in Telegram and the dashboard. Once HTTPS is configured, **Open dashboard** is the primary admin home action. Telegram management remains the fallback.

Bot messages, guest forms, inline buttons, native admin screens, web dashboards, validation errors, demo content, guides and documentation use English. There is no language selector. Dashboard text flows left to right, with English date and number formatting.

Custom questions, the welcome message, help and invitation template remain editable by superadmins. Previously stored built-in defaults are converted during startup. User-entered records, names and custom copy are preserved as entered. Form drafts retain their answers. The update does not translate private records or rewrite previously delivered messages.

The complete guide is `ownership/static/guide.html`. Technical architecture is in `docs/ARCHITECTURE.md`. VPS installation is in `extensions/DEPLOY.md`. Operations and future work are described in `extensions/UPDATES.md`.

## Tests and evidence

```bash
.venv/bin/python -m unittest discover -s tests -t . -q
npm ci
.venv/bin/python tools/check.py
npm run test:dom
npx playwright install chromium
npm run test:ui
```

Python tests use temporary SQLite databases and a simulated Telegram API over real local HTTP. DOM integration runs the interface scripts against the real app HTTP server. It does not verify browser rendering. The Playwright script requires Chromium and checks a desktop dashboard, mobile width and Telegram-shaped chat. Actual results are recorded in `reports/`.

```bash
.venv/bin/python tools/live_check.py --env .env
```

This reads the real Bot API identity and commands. `--worker-smoke` runs the real worker briefly, only when no webhook or pending updates exist. It does not send synthetic test messages to other people. A person who independently starts the bot during that window receives its normal response.

To produce and verify deliverables after backend and DOM checks:

```bash
.venv/bin/python tools/package.py
.venv/bin/python tools/release_check.py
.venv/bin/python tools/package.py
```

The release check extracts the distributable into an empty directory and runs all Python tests from that copy. The final packaging step includes the verification report. Runtime data, private configuration, the real token and the virtual environment are excluded.

## Source layout

| File | Responsibility |
| --- | --- |
| `futarchist/__main__.py` | Public product entry point |
| `ownership/core.py`, `schema.sql` | Permissions, transactions, storage and schema migration |
| `ownership/english.py` | Conversion of legacy built-in defaults without changing user records |
| `ownership/forms.py`, `bot.py` | English guest forms, editing, replies and group connections |
| `ownership/native.py` | Native Telegram management using inline buttons and short forms |
| `ownership/management.py` | Shared operations for web and Telegram |
| `ownership/exports.py` | Permission-aware XLSX, CSV and multi-dataset ZIP |
| `ownership/telegram.py` | Bot API transport, inbox, outbox, retries and isolated workers |
| `ownership/health.py` | Health, incidents, bounded recovery and consistent backups |
| `ownership/server.py`, `static/` | Login, HTTP API, browser dashboard and local simulator |
| `tests/`, `tools/` | Regression, language checks, reports and safe packaging |

The internal package name `ownership` remains for compatibility. The public product and command are FUTARCHIST. The supplied logos are used without image modifications.

## Operating limits

Automatic recovery covers expired state cleanup, connection backoff, worker restart and safe retry. Code defects and database corruption are not rewritten automatically. A delivery with an unknown outcome is not retried automatically.

SQLite targets one VPS. WAL and busy timeouts handle concurrent local access. PostgreSQL and an independent queue are later work for larger loads or multiple hosts, not features of this release. Database and backup files contain private information. This version uses infrastructure-level encryption at rest.

Permanent deletion requires an archived case and superadmin confirmation. It removes the active database records. Old backups and previously delivered Telegram messages remain outside that operation. The app does not guarantee continuous internet access, Telegram availability or disk integrity. See the test report for checks not completed in a real client or production VPS.
