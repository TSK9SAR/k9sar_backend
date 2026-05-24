mkdir -p ~/handoff_build
cat > ~/handoff_build/make_handoff_zip.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME"
OUTDIR="$HOME/handoff_out"
STAGE="$OUTDIR/k9sar_handoff"
DATE="$(date +%Y%m%d-%H%M%S)"
ZIP="$OUTDIR/k9sar_handoff_$DATE.zip"

mkdir -p "$OUTDIR"
rm -rf "$STAGE"
mkdir -p "$STAGE"

copy_dir () {
  local src="$1"
  local dst="$2"
  if [ -d "$src" ]; then
    rsync -a --delete "$src"/ "$STAGE/$dst"/
  fi
}

copy_dir "$ROOT/k9sar_backend" "k9sar_backend"
copy_dir "$ROOT/k9sar_frontend" "k9sar_frontend"
copy_dir "$ROOT/k9sar_frontend_dist" "k9sar_frontend_dist"

# Remove secrets (adjust if you have other secret filenames)
# rm -f "$STAGE/k9sar_backend/backend.env" 2>/dev/null || true
# rm -f "$STAGE/k9sar_backend/.env" 2>/dev/null || true
# rm -f "$STAGE/k9sar_frontend/.env" 2>/dev/null || true

# Create example env placeholders if they don't exist
if [ -d "$STAGE/k9sar_backend" ] && [ ! -f "$STAGE/k9sar_backend/backend.env.example" ]; then
  cat > "$STAGE/k9sar_backend/backend.env.example" <<'ENV'
# Example only — DO NOT commit real secrets
SMTP_HOST=email-smtp.us-east-2.amazonaws.com
SMTP_PORT=587
SMTP_USER=YOUR_SES_SMTP_USERNAME
SMTP_PASS=YOUR_SES_SMTP_PASSWORD
SMTP_TLS=true
SMTP_SSL=false
SMTP_FROM="SARK9S <no-reply@sark9s.org>"
# DB_* etc...
ENV
fi

# Optional: include nginx config if present (you can add this later)
# sudo cp /etc/nginx/sites-available/sark9s.org "$STAGE/infra/nginx.conf"

# Zip it
cd "$OUTDIR"
zip -r "$ZIP" "$(basename "$STAGE")" >/dev/null
echo "Created: $ZIP"
SH

chmod +x ~/handoff_build/make_handoff_zip.sh
~/handoff_build/make_handoff_zip.sh
