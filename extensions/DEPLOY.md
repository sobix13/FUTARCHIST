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

### Complete HTTPS setup without buying a domain

After updating the installed source, run the supplied installer as root:

```bash
cd /srv/futarchist
bash extensions/setup-web.sh
```

It derives a public IPv4 address from the SSH connection, falling back to the HTTPS ipify API. It creates a hostname such as `futarchist-8-8-8-8.sslip.io`, verifies its DNS, installs nginx and Certbot, obtains a certificate, starts the independent web service and verifies its public HTTPS response. It then updates only `APP_URL`, preserving the bot token, owner IDs, file mode and ownership. It restarts the two app services and registers the command menus. Open the bot, send `/start`, then choose **Open dashboard**. `/panel` provides the personal browser login link.

The installer retains local rollback copies, restores existing app configuration on failure, and leaves other nginx sites in place. A different process using port 80 or 443 stops setup before changes. It never disables another proxy or opens/reset firewall rules. Public TCP ports 80 and 443 must already reach the VPS. The hostname remains usable while this IP and the public DNS service remain available. A custom domain replaces that dependency later.

Use explicit inputs when the server is behind NAT or a different public address is needed:

```bash
FUTARCHIST_PUBLIC_IPV4=YOUR_PUBLIC_IPV4 bash extensions/setup-web.sh
FUTARCHIST_WEB_HOST=panel.example.com bash extensions/setup-web.sh
```

Do not use both alternatives at once. For a custom domain, its DNS must point to this server. Existing non-nginx proxies need their own configuration using the loopback upstream described below.

Primary references: [sslip.io DNS and TLS](https://sslip.io/), [Certbot webroot authentication](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot), [HTTP-01 reachability](https://letsencrypt.org/docs/challenge-types/#http-01-challenge), and [ipify](https://www.ipify.org/).

### Manual proxy setup

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
