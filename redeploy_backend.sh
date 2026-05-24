#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$HOME/k9sar_backend"
CONTAINER_NAME="k9sar_api"
IMAGE_NAME="k9sar_backend:latest"
ENV_FILE="$APP_DIR/backend.env"

UPLOADS_HOST_DIR="/var/k9sar/uploads"
SIGNATURES_HOST_DIR="/var/www/k9sar_signatures"

PORT_HOST="8000"
PORT_CONTAINER="8000"

echo "==> K9SAR backend redeploy starting..."
echo "    App dir:        $APP_DIR"
echo "    Container:      $CONTAINER_NAME"
echo "    Image:          $IMAGE_NAME"
echo "    Env file:       $ENV_FILE"
echo "    Uploads mount:  $UPLOADS_HOST_DIR -> /app/uploads"
echo "    Signatures:     $SIGNATURES_HOST_DIR -> /var/www/k9sar_signatures"
echo ""

# ---- Preconditions ----
if [[ ! -d "$APP_DIR" ]]; then
  echo "ERROR: App directory not found: $APP_DIR"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Env file not found: $ENV_FILE"
  exit 1
fi

# Ensure host mount dirs exist
sudo mkdir -p "$UPLOADS_HOST_DIR" "$SIGNATURES_HOST_DIR"

cd "$APP_DIR"

# ---- Stop/remove old container ----
echo "==> Stopping old container (if exists)..."
sudo docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true

echo "==> Removing old container (if exists)..."
sudo docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true

# ---- Build new image ----
echo "==> Building Docker image..."
sudo docker build -t "$IMAGE_NAME" .

# ---- Run new container ----
echo "==> Starting new container..."
sudo docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --env-file "$ENV_FILE" \
  -p "${PORT_HOST}:${PORT_CONTAINER}" \
  -v "${UPLOADS_HOST_DIR}:/app/uploads" \
  -v "${SIGNATURES_HOST_DIR}:/var/www/k9sar_signatures" \
  "$IMAGE_NAME"

# ---- Verify ----
echo ""
echo "==> Container status:"
sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | sed -n '1p;/'"$CONTAINER_NAME"'/p'

echo ""
echo "==> Recent logs:"
sudo docker logs --tail 60 "$CONTAINER_NAME"

echo ""
echo "==> Done."
