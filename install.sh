#!/usr/bin/env bash
# Deploys this house's Soundsquatch on sasquatch-server as the released container: the source to ~/soundsquatch-src,
# built and started with compose.sasquatch.yaml (its data stays in ~/soundsquatch). Checks the app's script first.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOST="${HOST:-sasquatch}"

python3 "$HERE/check.py"
rsync -a --delete --exclude .git --exclude data --exclude __pycache__ "$HERE/" "$HOST:soundsquatch-src/"
ssh "$HOST" 'if systemctl is-enabled soundsquatch >/dev/null 2>&1; then  # the old systemd service, retired once
  sudo -n systemctl disable --now soundsquatch && sudo -n rm -f /etc/systemd/system/soundsquatch.service && sudo -n systemctl daemon-reload
  echo "   (the systemd service is retired: Soundsquatch runs in Docker now)"
fi
docker compose -f ~/soundsquatch-src/compose.sasquatch.yaml up -d --build --quiet-pull 2>&1 | grep -v "^ *[✔#]" || true'
echo "== http://$HOST:8097/"
