#!/usr/bin/env bash
set -euo pipefail

UPLOAD="$HOME/k9sar_frontend_upload"
DIST="$HOME/k9sar_frontend_dist"
BACKUPS="$HOME/k9sar_frontend_backups"

# Optional: set to your public URL for a quick post-deploy check
HEALTH_URL="${HEALTH_URL:-https://tsk9sar.org/}"

echo "== Redeploy Frontend =="
echo "UPLOAD : $UPLOAD"
echo "DIST   : $DIST"
echo "BACKUPS: $BACKUPS"
echo "CHECK  : $HEALTH_URL"

mkdir -p "$BACKUPS"

# --- Sanity checks ---
if [[ ! -d "$UPLOAD" ]]; then
  echo "ERROR: upload dir missing: $UPLOAD"
  exit 1
fi

# A Vite/React build should have index.html
if [[ ! -f "$UPLOAD/index.html" ]]; then
  echo "ERROR: $UPLOAD does not look like a built frontend (missing index.html)."
  echo "Tip: copy the *contents* of your local dist/ into $UPLOAD."
  exit 1
fi

# Prevent accidental deploy of empty build
file_count="$(find "$UPLOAD" -maxdepth 2 -type f | wc -l | tr -d ' ')"
if [[ "${file_count}" -lt 5 ]]; then
  echo "ERROR: upload dir seems too small (${file_count} files). Aborting."
  exit 1
fi

ts="$(date +%Y%m%d-%H%M%S)"

# --- Backup current dist ---
if [[ -d "$DIST" ]]; then
  echo "Backing up current dist -> $BACKUPS/dist-$ts"
  mv "$DIST" "$BACKUPS/dist-$ts"
fi

# --- Promote upload -> dist ---
echo "Promoting upload -> dist"
mv "$UPLOAD" "$DIST"

# Recreate empty upload dir for next time
mkdir -p "$UPLOAD"

# --- Optional: quick health check ---
echo "Health check..."
if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 10 "$HEALTH_URL" >/dev/null; then
    echo "OK: $HEALTH_URL"
  else
    echo "WARNING: health check failed: $HEALTH_URL"
    echo "Rollback available in: $BACKUPS/dist-$ts (if there was a previous dist)"
  fi
else
  echo "curl not found; skipping health check."
fi

echo "Done."
