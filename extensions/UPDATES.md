# Operations and later updates

## Included now

Two configured superadmins, personal and team workspaces, eight workspace permissions, admin activation codes, short conditional forms, independent general/raise branches, immutable source tags, assignment and status, notes and guest replies, verified group binding, personalized invitation preview/confirmation, programs and participation, tasks, archive/restore, permanent project purge, editable bot copy, native Telegram management, browser management, Excel/CSV, health, bounded autorepair, database backups and schema 1 migration.

Version 2.1 uses English only throughout the bot, forms, dashboard, errors, guides and documentation. There is no language selector. The dashboard uses left-to-right layout and English dates and numbers. Recognized legacy built-in defaults are updated at startup. Custom copy and user-entered records remain as entered.

The HTML guide explains every screen. The bot and web systemd examples run separately. `maintenance.py` makes consistent snapshots or restores only into a new destination. The source contains real-HTTP simulation tests, DOM integration tests and a separate Chromium script.

## VPS installation

Use a persistent local filesystem and one bot worker. Extract under `/srv/futarchist`, create an unprivileged `futarchist` service user and let that user write only the data directory. Create the virtual environment using the target VPS Python. Do not transfer the build machine's virtual environment.

Copy `.env.example` to `.env` and set the token. Keep owner IDs 313342234 and 5691137098. Leave APP_URL empty for native-only operation, or set the exact HTTPS origin for the panel. Set `.env` to owner-readable permissions and keep the source outside webserver document roots. Run `--check-bot` to verify the replacement username and token pair.

Install the two `.service.example` files as `.service` units only after replacing paths and checking service-account ownership. If no web panel is needed, enable only the bot unit. They do not depend on one another. Install and validate the nginx example after obtaining a certificate. Do not proxy demo mode. The HTTP server is not intended to be the public TLS endpoint.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now futarchist-bot
sudo systemctl enable --now futarchist-web
sudo nginx -t
sudo systemctl reload nginx
```

These commands are deployment instructions. They were not run on a production VPS during creation of this package.

## Daily checks

Check `/health` in Telegram or the owner health page. Healthy worker heartbeats appear after workers have run. A poller may need one full 20-second long poll after startup. Browser `/ready` checks database readiness and `/health` checks process liveness. These public endpoints omit private data. They do not replace the authenticated owner queue and incident view.

Use `extensions/health_probe.py --database PATH --mode bot` or `--mode web` from an external monitoring process. It checks database consistency and worker liveness with bounded staleness. Degraded connectivity is reported separately from liveness. The probe does not restart processes or mutate business records. systemd restarts a crashed process automatically.

Review unknown delivery outcomes in Telegram before deciding to send again. A queued invite is not proof of delivery. Closing an incident is an acknowledgement, not repair of its cause.

## Backup and restore

```bash
python3 extensions/maintenance.py backup --source data/futarchist.sqlite3 --output data/backups/snapshot-2026-10-03.sqlite3
```

Create the backups directory first. Choose a new filename on every run. Source and destination may not be the same. This uses SQLite's backup API and verifies database integrity. The owner `/health` backup button performs the same kind of local verified snapshot without exposing a database file in Telegram.

Restore while bot and web are stopped:

```bash
python3 extensions/maintenance.py restore --source data/backups/snapshot-2026-10-03.sqlite3 --output data/recovered.sqlite3
```

Point DATABASE_PATH to `data/recovered.sqlite3`, check its schema and rerun the regression checks. Inspect uncertain deliveries before restarting workers. Restore does not overwrite the original database. Store encrypted backup copies outside the VPS under your retention policy. Automated offsite upload and deletion of old backups are not configured without a chosen destination and policy.

## Upgrade from version 1

Stop old bot and web. Take a verified backup. Install this source in a separate directory. Keep the original owner ID, add the second configured superadmin, and point DATABASE_PATH at a controlled copy of the old database. The first run makes an additional `.before-v2-*.sqlite3` snapshot, adds schema 2 structures and disables public entry.

Before enabling user traffic, confirm the owners, team memberships, existing projects, source tags and inactive public route. Admins receive private codes. Guests with previous submissions need an active new code for their workspace before editing if no valid grant exists. Do not run version 1 code against a version 2 database. A rollback uses the old source and a restored version 1 backup in a different path.

## Not implemented in this version

| Later capability | Why it is separate | Migration or acceptance condition |
| --- | --- | --- |
| PostgreSQL and multiple worker hosts | SQLite is intentionally one-VPS storage | Atomic row claiming, permission regression and measured load test |
| Calendar integration and scheduled reminders | External provider and timing policy are not selected | OAuth scopes, workspace isolation and idempotent jobs |
| Website/CSV import | Existing website schema and reconciliation policy are unknown | Preview, validation, source mapping and duplicate resolution |
| Multiple fundraising rounds and document version snapshots | Current form records the latest/current raise | Explicit round entity, scoped exports and version history |
| Encrypted file attachments | This build exports files, it does not accept arbitrary uploads | Storage choice, file limits, permissions and retention policy |
| Private enterprise deployment policies | A team policy is needed | At-rest encryption, retention, access review and backup policy |
| Custom question builder | Owner can edit text today, field schema remains controlled | Versioned form definitions and migration of existing responses |

No AI feature is part of this roadmap. Features in this table are not presented as working features in the release.

## Real-client acceptance before broad rollout

With both superadmins, Start and `/manage`, add one temporary admin and one team. Give one guest a single-use personal code and another a team code. Complete general-only, raise-only and combined forms. Verify source tags, permissions, reassignment, replies, opt-in and opt-out, group bind, personal invitation preview, archive/restore, Excel/CSV and code revocation mid-draft.

Open the HTTPS panel from Telegram on iOS, Android and desktop, and in an ordinary browser with the one-use login link. Check logos, English left-to-right layout, 390px width, focus, dialogs, native file downloads, connection fallback and permissions after refresh. Run the Chromium script locally. Check real group permissions and Telegram rate-limit behavior. This package's local simulator and DOM tests do not certify official Telegram client behavior or the production network.
