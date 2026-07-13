# vps-probe

A lightweight, dependency-free VPS status panel with push agents.

The controller stores the latest report from each node. Remote nodes initiate outbound HTTPS reports, so the controller never needs remote SSH access or SSH credentials.

## Architecture

```text
agent node -- HTTPS POST /api/report --> controller --> browser status panel
```

- Controller: `panel.py` plus `vps-probe.service`
- Agent: `agent/vps-probe-agent.py` plus a systemd timer every 30 seconds
- Transport: HTTPS through a reverse proxy such as Caddy
- Authentication: one unique Bearer token per agent
- No Python third-party dependencies

## Data collected

- CPU usage and load
- Memory and swap
- Root disk usage
- Network counters and reporting-interval speed
- TCP/UDP socket counts and process count
- OS, kernel, architecture, uptime

## Security model

- The controller has no remote node IP, SSH port, SSH username, SSH key, or SSH password in its configuration.
- Each agent stores only its own opaque report token in `/etc/vps-probe-agent.json`, mode `0600`.
- The agent opens no listening port. It only makes outbound HTTPS requests.
- Tokens are accepted only by `POST /api/report`; the panel and `GET /api/status` can be public.
- Reports older than 120 seconds are displayed offline.
- Do not commit real tokens, controller credentials, node addresses, or `state.json`.

## Controller setup

Install on the public controller host:

```bash
apt-get update
apt-get install -y python3 caddy
install -d -m 0755 /opt/vps-probe
install -m 0700 panel.py /opt/vps-probe/panel.py
install -m 0600 config.example.json /opt/vps-probe/config.json
install -m 0644 systemd/vps-probe.service /etc/systemd/system/vps-probe.service
systemctl daemon-reload
systemctl enable --now vps-probe.service
```

Use `config.example.json` as a template. Generate a unique token for every agent, for example:

```bash
openssl rand -hex 24
```

The controller listens on `127.0.0.1:8088` by default. Expose it through Caddy:

```caddyfile
probe.example.com {
    encode gzip zstd
    reverse_proxy 127.0.0.1:8088
}
```

Validate and reload:

```bash
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy
```

If using Cloudflare, use SSL/TLS mode `Full (strict)`.

## Agent setup

On every remote node, copy the agent and systemd units:

```bash
install -m 0700 agent/vps-probe-agent.py /usr/local/sbin/vps-probe-agent.py
install -m 0644 systemd/vps-probe-agent.service /etc/systemd/system/vps-probe-agent.service
install -m 0644 systemd/vps-probe-agent.timer /etc/systemd/system/vps-probe-agent.timer
```

Create `/etc/vps-probe-agent.json` with the matching node token:

```json
{
  "endpoint": "https://probe.example.com/api/report",
  "token": "replace-with-this-node-unique-token"
}
```

Then enable it:

```bash
chmod 600 /etc/vps-probe-agent.json
systemctl daemon-reload
systemctl enable --now vps-probe-agent.timer
systemctl start vps-probe-agent.service
systemctl status vps-probe-agent.timer
```

Manual report test:

```bash
python3 /usr/local/sbin/vps-probe-agent.py
journalctl -u vps-probe-agent.service -n 30 --no-pager
```

## Controller configuration

`/opt/vps-probe/config.json`:

```json
{
  "listen": "127.0.0.1",
  "port": 8088,
  "nodes": [
    {
      "id": "controller-local",
      "name": "Controller",
      "type": "local",
      "flag": "LOCAL",
      "region": "Controller region"
    },
    {
      "id": "remote-a",
      "name": "Remote VPS",
      "type": "agent",
      "token": "replace-with-a-unique-agent-token",
      "flag": "REMOTE",
      "region": "Remote region"
    }
  ]
}
```

The `id` and token must exactly match the agent configuration. Restart the controller after changing its config:

```bash
systemctl restart vps-probe.service
```

## Endpoints

- `GET /`: status panel
- `GET /api/status`: latest public status records
- `POST /api/report`: agent ingestion endpoint, requires `Authorization: Bearer <node-token>`

Example report validation:

```bash
curl -i -X POST \
  -H 'Authorization: Bearer replace-with-a-unique-agent-token' \
  -H 'Content-Type: application/json' \
  --data '{"hostname":"test","cpu_count":1}' \
  https://probe.example.com/api/report
```

A valid request returns HTTP `204`. A missing or invalid token returns HTTP `401`.

## Token rotation

To rotate one node token:

1. Generate a new token.
2. Replace the matching controller node token in `/opt/vps-probe/config.json` and restart `vps-probe.service`.
3. Replace the agent token in `/etc/vps-probe-agent.json` and run `systemctl start vps-probe-agent.service`.
4. Verify the node becomes online within 30 seconds.
