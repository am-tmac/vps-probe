# Tmac VPS Probe

A tiny no-dependency VPS status panel built with Python standard library.

Features:

- Basic Auth
- Local node collection
- Remote node collection over `sshpass + ssh`
- CPU, memory, swap, disk, load, uptime, network traffic/speed, TCP/UDP count, process count
- Region flags and compact Akile-style cards
- Optional Caddy HTTPS reverse proxy

## Quick Install

```bash
apt-get update
apt-get install -y python3 sshpass caddy
mkdir -p /opt/vps-probe
cp panel.py /opt/vps-probe/panel.py
cp config.example.json /opt/vps-probe/config.json
chmod 700 /opt/vps-probe/panel.py
chmod 600 /opt/vps-probe/config.json
cp systemd/vps-probe.service /etc/systemd/system/vps-probe.service
systemctl daemon-reload
systemctl enable --now vps-probe.service
```

Edit `/opt/vps-probe/config.json` and set your nodes/passwords.

## Caddy HTTPS

```bash
cp caddy/Caddyfile.example /etc/caddy/Caddyfile
# edit domain
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

## API

```bash
curl -u admin:change-me http://127.0.0.1:8088/api/status
```

## Security Notes

- Do not commit real server passwords.
- Prefer SSH key auth for production.
- Keep the panel listening on `127.0.0.1` and expose it through Caddy HTTPS.
