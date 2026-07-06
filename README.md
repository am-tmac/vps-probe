# vps-probe

A tiny no-dependency VPS status panel built with the Python standard library.

Repository: https://github.com/am-tmac/vps-probe

## Features

- Basic Auth
- Local node collection
- Remote node collection over `sshpass + ssh`
- CPU, memory, swap, disk, load, uptime, network traffic/speed, TCP/UDP count, process count
- Region flags and compact Akile-style cards
- Optional Caddy HTTPS reverse proxy
- No Python third-party dependencies

## One-Line Install

Run as `root` on Ubuntu/Debian:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/am-tmac/vps-probe/main/install.sh)
```

The installer will:

- Install `python3`, `sshpass`, `curl`
- Install the panel to `/opt/vps-probe`
- Create `/opt/vps-probe/config.json`
- Create and start `vps-probe.service`
- Optionally install/configure Caddy for HTTPS reverse proxy

After installation, edit your nodes:

```bash
nano /opt/vps-probe/config.json
systemctl restart vps-probe
```

## Manual Install

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

## Configuration

Example `/opt/vps-probe/config.json`:

```json
{
  "listen": "127.0.0.1",
  "port": 8088,
  "auth_user": "admin",
  "auth_pass": "change-me",
  "refresh_seconds": 20,
  "nodes": [
    {
      "name": "Local VPS",
      "type": "local",
      "flag": "🇺🇸",
      "region": "Los Angeles, US"
    },
    {
      "name": "Remote VPS",
      "type": "ssh",
      "host": "1.2.3.4",
      "port": 22,
      "user": "root",
      "password": "change-me",
      "flag": "🇯🇵",
      "region": "Tokyo, JP"
    }
  ]
}
```

## Caddy HTTPS

Keep the panel listening on `127.0.0.1:8088`, then expose it via Caddy:

```caddyfile
probe.example.com {
    encode gzip zstd
    reverse_proxy 127.0.0.1:8088
}
```

Apply:

```bash
cp caddy/Caddyfile.example /etc/caddy/Caddyfile
# edit domain
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy
```

## API

```bash
curl -u admin:change-me http://127.0.0.1:8088/api/status
```

## Security Notes

- Do not commit real server passwords.
- Prefer SSH key auth for production.
- Keep the panel listening on `127.0.0.1` and expose it through Caddy HTTPS.
- Use Cloudflare proxy with SSL/TLS mode `Full (strict)` when serving through Cloudflare.
