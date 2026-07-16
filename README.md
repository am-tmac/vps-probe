# Jager Monitor

A lightweight VPS status monitoring panel.

The controller hosts a web dashboard. Each monitored VPS runs a small WebSocket agent that reports its status to the controller over WSS every five seconds.

## Security model

- Agent reports are accepted only over authenticated WebSocket connections.
- Public agents must use `wss://`; insecure `ws://` is permitted only on loopback for local testing.
- The dashboard refreshes `/api/status` every five seconds and doesn't open an anonymous browser WebSocket.
- Agent tokens must be non-empty and unique. Invalid controller configuration prevents the hub from starting.
- Reports are schema-validated before they are written to disk, and JSON serialization rejects `NaN` and `Infinity`.
- Controller and agent WebSocket dependencies run in isolated virtual environments pinned to `websockets==10.4`.

Running the installer again performs an update and restarts the affected services after validation.

## One-line Install

Run as root on either a controller or monitored VPS:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/am-tmac/jager-monitor/main/install.sh)
```

## Tests

```bash
python3 -m venv .venv
.venv/bin/pip install pytest websockets==10.4
.venv/bin/pytest -q
.venv/bin/python tests/integration_smoke.py
```
