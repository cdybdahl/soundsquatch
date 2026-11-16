#!/bin/sh
# The turntable's listener: the amplifier's record-out, as it comes from the USB audio interface (a Behringer UCA202/222
# or any USB sound card), sent raw to Soundsquatch (CD quality: 44.1 kHz, 16-bit, stereo) over one TCP connection, which
# names the songs, keeps them, feeds the visualisers and the live stream. Nothing is done here, so a Pi 3 is plenty.
# Soundsquatch's address and port come from /etc/default/turntable-listener (SOUNDSQUATCH=host, PORT=8095).
. /etc/default/turntable-listener
PORT=${PORT:-8095}
while true; do
  # the first USB sound card that can record, as ALSA names it (the UCA202 is "CODEC")
  CARD=${CARD:-$(arecord -l 2>/dev/null | sed -n 's/^card [0-9]*: \([^ ]*\) \[.*USB.*/\1/p' | head -n1)}
  if [ -z "$CARD" ]; then
    echo "no USB sound card found; trying again" >&2
    sleep 10
    continue
  fi
  # a tenth of a second of buffer: the sound reaches Soundsquatch (and the visualisers) almost as it plays
  arecord -q -D "plughw:CARD=$CARD" -f S16_LE -r 44100 -c 2 -t raw --buffer-time=100000 --period-time=20000 | nc -N "$SOUNDSQUATCH" "$PORT"
  sleep 2 # Soundsquatch restarting, or the network gone a moment: connect again
done
