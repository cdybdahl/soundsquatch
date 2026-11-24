#!/bin/sh
# Soundsquatch runs as an ordinary user, not root: PUID/PGID (default 1000, the first user on most Linux machines; make
# them the owner of your music if Soundsquatch is to change its files). Started as root (the default), it gives /data to
# that user (once, when it isn't theirs already) and drops to it; started with compose's user:, it just runs.
set -e
# As a Home Assistant add-on: its connection to Home Assistant comes with it (the Supervisor's token, kept where the
# app keeps its own), and the add-on's folders (share, media) are root's, so it stays root there.
if [ -n "$SUPERVISOR_TOKEN" ]; then
  export HA_URL="${HA_URL:-http://supervisor/core}" SOUNDSQUATCH_ADDON=1
  umask 077 && printf %s "$SUPERVISOR_TOKEN" > /data/.ha_token && umask 022
  exec python3 soundsquatch.py
fi
if [ "$(id -u)" = 0 ]; then
  PUID="${PUID:-1000}"; PGID="${PGID:-1000}"
  [ "$(stat -c %u:%g /data)" = "$PUID:$PGID" ] || chown -R "$PUID:$PGID" /data
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups python3 soundsquatch.py
fi
exec python3 soundsquatch.py
