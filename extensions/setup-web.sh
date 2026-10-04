#!/usr/bin/env bash
# Configure HTTPS for the installed VPS app. Existing sites stay in place.
set +x
set -Eeuo pipefail
umask 022
app_dir=/srv/futarchist
site=/etc/nginx/conf.d/futarchist.conf
hook=/etc/letsencrypt/renewal-hooks/deploy/futarchist-nginx.sh
[[ $EUID -eq 0 ]] || { echo 'Run web setup as root.' >&2; exit 1; }
[[ -x "$app_dir/.venv/bin/python" && -f "$app_dir/.env" ]] || { echo 'Install the FUTARCHIST app first.' >&2; exit 1; }
command -v apt-get >/dev/null
command -v systemctl >/dev/null
command -v ss >/dev/null
cd "$app_dir"

for owned_file in "$site" "$hook"; do
    if [[ -e "$owned_file" ]] && ! head -n 2 "$owned_file" | grep -q '^# FUTARCHIST managed'; then
        echo "Existing $owned_file is not owned by this installer. Nothing replaced." >&2
        exit 1
    fi
done
listeners=$(ss -H -ltnp '( sport = :80 or sport = :443 )')
if [[ -n "$listeners" ]] && printf '%s\n' "$listeners" | grep -v '"nginx"' >/dev/null; then
    echo 'Port 80 or 443 belongs to another service. Web setup stopped before changing it.' >&2
    echo 'Use that existing reverse proxy with extensions/nginx.conf.example.' >&2
    exit 1
fi
if command -v nginx >/dev/null; then nginx -t; fi

host=$(.venv/bin/python -B extensions/web_setup.py host \
    --hostname "${FUTARCHIST_WEB_HOST:-}" --ip "${FUTARCHIST_PUBLIC_IPV4:-}")
echo "Preparing dashboard HTTPS: $host"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y nginx certbot ca-certificates curl
install -d -m 755 /var/lib/futarchist-acme /etc/nginx/conf.d
setup_dir=$(mktemp -d "$app_dir/data/web-setup.XXXXXX")
chmod 700 "$setup_dir"
cp -p .env "$setup_dir/env.before"
had_site=0
if [[ -f "$site" ]]; then cp -p "$site" "$setup_dir/nginx.before"; had_site=1; fi
env_changed=0

rollback() {
    status=$?
    trap - ERR
    if [[ "$had_site" == 1 ]]; then cp -p "$setup_dir/nginx.before" "$site";
    elif [[ -f "$site" ]] && head -n 1 "$site" | grep -q '^# FUTARCHIST managed'; then rm -f "$site"; fi
    if [[ "$env_changed" == 1 ]]; then
        cp -p "$setup_dir/env.before" .env
        systemctl try-restart futarchist-web.service futarchist-bot.service || true
    fi
    if nginx -t; then systemctl reload nginx || true; fi
    echo "Web setup stopped. Existing app configuration was restored. Details: $setup_dir" >&2
    exit "$status"
}
trap rollback ERR

cat >"$setup_dir/http.conf" <<NGINX
# FUTARCHIST managed
server {
    listen 80;
    server_name $host;
    access_log off;
    location /.well-known/acme-challenge/ { root /var/lib/futarchist-acme; }
    location / { return 404; }
}
NGINX
install -m 644 "$setup_dir/http.conf" "$site"
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo 'Requesting the HTTPS certificate. Public ports 80 and 443 must reach this VPS.'
certbot certonly --webroot -w /var/lib/futarchist-acme -d "$host" \
    --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring

cat >"$setup_dir/https.conf" <<NGINX
# FUTARCHIST managed
server {
    listen 80;
    server_name $host;
    access_log off;
    location /.well-known/acme-challenge/ { root /var/lib/futarchist-acme; }
    location / { return 301 https://$host\$request_uri; }
}
server {
    listen 443 ssl;
    server_name $host;
    ssl_certificate /etc/letsencrypt/live/$host/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$host/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 64k;
    access_log off;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_http_version 1.1;
        proxy_read_timeout 35s;
    }
}
NGINX
install -m 644 "$setup_dir/https.conf" "$site"
nginx -t
systemctl reload nginx
install -m 644 extensions/futarchist-web.service.example /etc/systemd/system/futarchist-web.service
systemctl daemon-reload
systemctl enable --now futarchist-web.service

echo 'Verifying the public HTTPS endpoint...'
curl --fail --silent --show-error --retry 5 --retry-connrefused --retry-delay 1 --connect-timeout 8 --max-time 20 \
    "https://$host/api/config" >"$setup_dir/public-config.json"
.venv/bin/python -B - "$setup_dir/public-config.json" <<'PY'
import json,sys,os
from ownership.__main__ import load_env
load_env('.env')
with open(sys.argv[1]) as stream: config=json.load(stream)
if config.get('demo') is not False or config.get('bot_name')!=os.environ.get('BOT_USERNAME','FutarchistBot'):
    raise SystemExit('The HTTPS endpoint did not return the live FUTARCHIST app.')
PY
env_changed=1
.venv/bin/python -B extensions/web_setup.py origin --env .env --hostname "$host"
systemctl restart futarchist-web.service futarchist-bot.service
curl --fail --silent --show-error --retry 5 --retry-connrefused --retry-delay 1 \
    --connect-timeout 5 --max-time 15 "https://$host/api/config" >"$setup_dir/public-config.json"
systemctl is-active --quiet futarchist-web.service
systemctl is-active --quiet futarchist-bot.service

install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat >"$setup_dir/renew.sh" <<'RENEW'
#!/bin/sh
# FUTARCHIST managed
set -e
nginx -t
systemctl reload nginx
RENEW
install -m 755 "$setup_dir/renew.sh" "$hook"
systemctl enable --now certbot.timer
if ! timeout 75s runuser -u futarchist -- .venv/bin/python -B -m futarchist --env .env --configure-bot; then
    echo 'Dashboard is active. Command menu registration remains pending. /guide and /manage work directly.'
fi
trap - ERR
echo "Dashboard ready: https://$host"
echo 'Open the bot, send /start, then choose Open dashboard. Ordinary browser login uses /panel.'
echo "Local configuration rollback files: $setup_dir"
