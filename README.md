# Jager Monitor

A lightweight VPS status monitoring panel.

The controller hosts a web dashboard. Each monitored VPS runs a small WebSocket agent that reports its status to the controller over WSS every five seconds.

## One-line Install

Run as root on either a controller or monitored VPS:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/am-tmac/jager-monitor/main/install.sh)
```
