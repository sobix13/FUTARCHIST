# Deploy FUTARCHIST on a VPS

These instructions target Linux with systemd and Python 3.12 or later. Production installation was not performed in the build environment. Run the real-client acceptance checks after installation. The HTML guide explains all app sections.

## 1. Directory and service account

Extract the main ZIP and place the contents of its `futarchist` folder under `/srv/futarchist`. Root owns the source. The service account writes only to the data directory. Create the account once, if it does not already exist:

```bash
sudo useradd --system --home /srv/futarchist --shell /usr/sbin/nologin futarchist
cd /srv/futarchist
sudo python3 -m venv .venv
sudo install -d -o futarchist -g futarchist -m 700 data data/backups
sudo cp .env.example .env
sudo chown futarchist:futarchist .env
sudo chmod 600 .env
sudoedit .env
```

Create the virtual environment on the target VPS. No third-party Python runtime packages are required. Node and npm dependencies are for interface tests only.

| Setting | Value |
| --- | --- |
| `BOT_TOKEN` | Your bot token. No real token is included in the package. |
| `BOT_USERNAME` | `FutarchistBot` for the current test bot, or your replacement username |
| `OWNER_TG_ID` | `313342234` |
| `SUPER_ADMIN_IDS` | `313342234,5691137098` |
| `DATABASE_PATH` | `data/futarchist.sqlite3` on persistent local storage |
| `APP_URL` | Empty for native Telegram use, or an exact HTTPS origin with no path |

Keep configuration and the database outside public web roots. The nginx example proxies requests to the internal HTTP service.

## 2. Bot identity and command menus

```bash
sudo -u futarchist .venv/bin/python -m futarchist --env .env --check-bot
sudo -u futarchist .venv/bin/python -m futarchist --env .env --configure-bot
```

This version uses polling. If a webhook exists, resolve the connection method first. The app does not remove it automatically. Run only one polling worker for this database.

Both superadmins start the bot. Rerun configure after their first Start to install scoped command menus for recognized chats. `/manage` and numeric-ID permissions work independently of those menus. All configured command descriptions are English.

## 3. Independent services and HTTPS

The service examples assume `/srv/futarchist` and the `futarchist` account. Edit paths before installing if your setup differs.

```bash
sudo cp extensions/futarchist-bot.service.example /etc/systemd/system/futarchist-bot.service
sudo cp extensions/futarchist-web.service.example /etc/systemd/system/futarchist-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now futarchist-bot
sudo systemctl status futarchist-bot --no-pager
sudo journalctl -u futarchist-bot -n 60 --no-pager
```

For browser access, set HTTPS and `APP_URL`, then enable the web unit:

```bash
sudo systemctl enable --now futarchist-web
sudo systemctl status futarchist-web --no-pager
```

The units do not depend on each other. Writable service paths are restricted to `data/`. HTTP listens on `127.0.0.1:8765`. Obtain a TLS certificate, replace the domain and certificate paths in `nginx.conf.example`, and install it using your VPS's nginx configuration structure.

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Demo login and `/emulator` are unavailable in live mode. Native Telegram management works without the web unit. If enabling a BotFather menu button or Main Mini App, use the same real HTTPS origin.

## 4. Health and troubleshooting

Open `/health` and `/manage`. Heartbeats appear after a polling cycle. For independent monitoring:

```bash
sudo -u futarchist .venv/bin/python extensions/health_probe.py --database data/futarchist.sqlite3 --mode bot
sudo -u futarchist .venv/bin/python extensions/health_probe.py --database data/futarchist.sqlite3 --mode web
```

The probe reports health without changing business records. systemd restarts crashed processes within a bounded restart policy. Telegram connection failures use internal backoff. Persistent failures require log and incident review.

`/repair` performs bounded safe recovery. Check an `uncertain` delivery at its Telegram destination before sending again. Acknowledging an incident records review, not resolution of its cause.

## 5. Backup and restore

Choose a fresh filename for each snapshot:

```bash
sudo -u futarchist .venv/bin/python extensions/maintenance.py backup --source data/futarchist.sqlite3 --output data/backups/snapshot-2026-10-03.sqlite3
```

The command takes a consistent snapshot and verifies integrity. Backups contain private information. Choose your own offsite destination, encryption and retention policy.

Stop both services before restoring into a new file:

```bash
sudo systemctl stop futarchist-bot futarchist-web
sudo -u futarchist .venv/bin/python extensions/maintenance.py restore --source data/backups/snapshot-2026-10-03.sqlite3 --output data/recovered.sqlite3
sudoedit .env
```

Set `DATABASE_PATH` to `data/recovered.sqlite3`. The original database is not overwritten. Review delivery state and `uncertain` entries before restarting. An old backup might predate a message that was delivered successfully. Start only the units you use.

## 6. Acceptance before broad use

With both superadmins and a temporary admin, create personal and team workspaces. Test single-use and team codes, general-only, raise-only and combined forms, code revocation mid-draft, read-only membership, reassignment, questions and replies, a real group, invitation preview, opt-out, Excel/CSV, archive and restore.

Open the HTTPS dashboard in Telegram on mobile and desktop and through a browser login link. Check the English left-to-right layout, mobile width, focus, dialogs and downloads. DOM and local simulator tests do not verify official Telegram client rendering. The separate test report identifies completed and pending checks.

## 7. Upgrade

Stop services and take a verified backup before replacing source. Schema 1 upgrades create a separate pre-migration snapshot. Do not run older code against the upgraded database.

The English-only update uses schema 2. On startup it updates recognized legacy built-in copy and generated workspace/code labels, removes old language preferences and converts cached admin form titles. It preserves custom copy, names, project records, answers, permissions, source tags and delivered message history. Reopen `/manage` to use the current buttons.

See `UPDATES.md` for implemented features and later work. Multiple servers and larger loads require a separate PostgreSQL and queue migration.
