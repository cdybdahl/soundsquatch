#!/bin/sh
# Sets up a Raspberry Pi (Raspberry Pi OS Lite) as the turntable's listener: run as
#   curl -fsSL https://raw.githubusercontent.com/cdybdahl/soundsquatch/main/turntable/install.sh | sudo sh -s SOUNDSQUATCH_HOST
# Installs ALSA's recorder and netcat, the listener, and a service that starts it at boot and restarts it if it stops.
set -e
HOST=${1:?usage: install.sh SOUNDSQUATCH_HOST [PORT]}
PORT=${2:-8095}
apt-get update -qq
apt-get install -y -qq alsa-utils netcat-openbsd >/dev/null
curl -fsSL https://raw.githubusercontent.com/cdybdahl/soundsquatch/main/turntable/listener.sh -o /usr/local/bin/turntable-listener
chmod 755 /usr/local/bin/turntable-listener
printf 'SOUNDSQUATCH=%s\nPORT=%s\n' "$HOST" "$PORT" > /etc/default/turntable-listener
cat > /etc/systemd/system/turntable-listener.service <<UNIT
[Unit]
Description=The turntable's listener: the record-out, sent to Soundsquatch
After=network-online.target sound.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/turntable-listener
Restart=always
RestartSec=3
Nice=-5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now turntable-listener
sleep 3
arecord -l | grep -i usb || echo "No USB sound card found yet: plug in the interface (the service will find it)."
echo "Listening: sending to $HOST:$PORT. Soundsquatch's Settings, Your records, says when it hears it."
