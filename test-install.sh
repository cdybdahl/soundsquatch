#!/usr/bin/env bash
# A test Soundsquatch on sasquatch-server, beside the house's: a branch (default: the one checked out) built as
# soundsquatch-test on port 8098 with fresh data, so a first scan runs from nothing. Then how far it has got, every
# five minutes, to ~/soundsquatch-test/settling.log there.  FRESH=0 keeps the test's data from last time.
#   ./test-install.sh [branch]        HOST=sasquatch by default
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOST="${HOST:-sasquatch}"
REF="${1:-$(git -C "$HERE" branch --show-current)}"
FRESH="${FRESH:-1}"

python3 "$HERE/check.py"
echo "== $REF to $HOST:soundsquatch-test-src"
ssh "$HOST" 'rm -rf ~/soundsquatch-test-src && mkdir -p ~/soundsquatch-test-src ~/soundsquatch-test'
git -C "$HERE" archive "$REF" | ssh "$HOST" 'tar -x -C ~/soundsquatch-test-src'
ssh "$HOST" "FRESH=$FRESH bash -s" <<'REMOTE'
set -e
cd ~/soundsquatch-test-src
docker compose -f compose.test.yaml down 2>/dev/null || true
pkill -f "soundsquatch-test/settling.log" 2>/dev/null || true
if [ "$FRESH" = 1 ]; then
  docker run --rm -v ~/soundsquatch-test:/d alpine sh -c 'rm -rf /d/* /d/.[!.]*' 2>/dev/null || rm -rf ~/soundsquatch-test/*
fi
docker compose -f compose.test.yaml up -d --build --quiet-pull 2>&1 | grep -v "^ *[✔#]" || true
start=$(date +%s)
nohup bash -c 'while sleep 300; do
  s=$(curl -s --max-time 10 http://192.168.1.6:8098/api/settling) || s="(no answer)"
  echo "$(date "+%F %H:%M") +$(( ($(date +%s) - '"$start"') / 60 ))min $s" >> ~/soundsquatch-test/settling.log
  case "$s" in *"\"settled\": true"*|*"\"settled\":true"*) break;; esac
done' </dev/null >/dev/null 2>&1 &
echo "   watching: ~/soundsquatch-test/settling.log (every 5 minutes, until settled)"
REMOTE
echo "== http://192.168.1.6:8098/   (the house's is untouched at :8097)"
echo "   ssh $HOST tail -f soundsquatch-test/settling.log"
