#!/usr/bin/env bash
set -euo pipefail

UPLOAD="$HOME/k9sar_frontend_upload"
LIVE="/var/www/k9sar_frontend"
BACKUPS="$HOME/k9sar_frontend_backups"
OWNER="www-data:www-data"

ts="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BACKUPS/k9sar_frontend_$ts"

echo "== Redeploy frontend =="
echo "UPLOAD : $UPLOAD"
echo "LIVE   : $LIVE"
echo "BACKUP : $BACKUP_DIR"

# --- sanity checks ---
if [[ ! -d "$UPLOAD" ]]; then
  echo "ERROR: upload directory not found: $UPLOAD"
  exit 1
fi

if [[ ! -f "$UPLOAD/index.html" ]]; then
  echo "ERROR: $UPLOAD does not look like a built frontend (missing index.html)."
  echo "Tip: copy the *contents* of your local dist/ into $UPLOAD."
  exit 1
fi

mkdir -p "$BACKUPS"

# --- backup current live ---
if [[ -d "$LIVE" ]]; then
  echo "Backing up current live site..."
  sudo mkdir -p "$BACKUP_DIR"
  # preserve permissions/links/etc
  sudo rsync -a --delete "$LIVE"/ "$BACKUP_DIR"/
fi

# --- deploy (safe sync) ---
echo "Deploying upload -> live..."
# This makes LIVE match UPLOAD exactly (including deletions)
sudo rsync -a --delete "$UPLOAD"/ "$LIVE"/

echo "Fixing ownership..."
sudo chown -R "$OWNER" "$LIVE"

echo "Testing nginx config..."
sudo nginx -t

echo "Reloading nginx..."
# reload is typically enough; restart is heavier
sudo systemctl reload nginx || sudo systemctl restart nginx

echo "Done."
echo "Backup saved at: $BACKUP_DIR"

