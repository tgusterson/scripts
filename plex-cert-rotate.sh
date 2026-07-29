#!/bin/bash
# Force Plex Media Server to discard its cached plex.direct TLS certificate
# and fetch a fresh one from plex.tv. Fixes "tlsv1 alert unknown ca" handshake
# failures that only affect some clients (seen with PS5) after Plex's cert
# chain rotates to a not-yet-widely-trusted intermediate/root.
set -euo pipefail

APP_NAME="Plex Media Server"
CACHE_DIR="$HOME/Library/Caches/PlexMediaServer"
CERT_FILE="$CACHE_DIR/cert-v2.p12"
OCSP_FILE="$CACHE_DIR/OCSP/main.der"
BACKUP_DIR="$HOME/.plex-cert-backups"
LOG_FILE="$HOME/Library/Logs/Plex Media Server/Plex Media Server.log"
TIMEOUT=20

mkdir -p "$BACKUP_DIR"
ts=$(date +%Y%m%d_%H%M%S)

echo "== Plex certificate rotate =="

if [ -f "$CERT_FILE" ]; then
  cp "$CERT_FILE" "$BACKUP_DIR/cert-v2.p12.$ts.bak"
  echo "Backed up cert-v2.p12 -> $BACKUP_DIR/cert-v2.p12.$ts.bak"
else
  echo "No existing cert-v2.p12 found, nothing to back up."
fi

if [ -f "$OCSP_FILE" ]; then
  cp "$OCSP_FILE" "$BACKUP_DIR/OCSP-main.der.$ts.bak"
  echo "Backed up OCSP/main.der -> $BACKUP_DIR/OCSP-main.der.$ts.bak"
fi

echo "Quitting $APP_NAME..."
osascript -e "tell application \"$APP_NAME\" to quit" >/dev/null 2>&1 || true

waited=0
while pgrep -f "$APP_NAME" >/dev/null 2>&1; do
  sleep 1
  waited=$((waited + 1))
  if [ "$waited" -ge "$TIMEOUT" ]; then
    echo "Plex didn't quit gracefully after ${TIMEOUT}s, forcing..."
    pkill -f "$APP_NAME" || true
    sleep 2
    break
  fi
done
echo "Plex stopped."

rm -f "$CERT_FILE" "$OCSP_FILE"
echo "Deleted cached certificate (and OCSP cache if present)."

echo "Relaunching $APP_NAME..."
open -a "$APP_NAME"

waited=0
until pgrep -f "$APP_NAME" >/dev/null 2>&1; do
  sleep 1
  waited=$((waited + 1))
  if [ "$waited" -ge "$TIMEOUT" ]; then
    echo "Plex did not relaunch within ${TIMEOUT}s. Check manually."
    exit 1
  fi
done
echo "Plex relaunched."

echo "Waiting for new certificate fetch to appear in the log..."
waited=0
while [ "$waited" -lt "$TIMEOUT" ]; do
  if [ -f "$LOG_FILE" ] && tail -n 50 "$LOG_FILE" | grep -q "Downloaded new cert from plex.tv"; then
    echo "New certificate downloaded successfully:"
    tail -n 50 "$LOG_FILE" | grep "CERT:" | tail -5
    exit 0
  fi
  sleep 1
  waited=$((waited + 1))
done
echo "Timed out waiting for confirmation in the log. Check manually:"
echo "  tail -f \"$LOG_FILE\" | grep CERT:"
