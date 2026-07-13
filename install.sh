#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/vps-probe"
SERVICE_FILE="/etc/systemd/system/vps-probe.service"
REPO_RAW="https://raw.githubusercontent.com/am-tmac/vps-probe/main"

need_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "Please run as root: sudo bash install.sh" >&2
    exit 1
  fi
}

install_packages() {
  apt-get update
  apt-get install -y python3 curl
}

install_files() {
  install -d -m 0755 "$APP_DIR"
  if [ -f ./panel.py ] && [ -f ./config.example.json ]; then
    install -m 0700 ./panel.py "$APP_DIR/panel.py"
    if [ ! -f "$APP_DIR/config.json" ]; then
      install -m 0600 ./config.example.json "$APP_DIR/config.json"
    fi
  else
    curl -fsSL "$REPO_RAW/panel.py" -o "$APP_DIR/panel.py"
    chmod 700 "$APP_DIR/panel.py"
    if [ ! -f "$APP_DIR/config.json" ]; then
      curl -fsSL "$REPO_RAW/config.example.json" -o "$APP_DIR/config.json"
      chmod 600 "$APP_DIR/config.json"
    fi
  fi
  chmod 700 "$APP_DIR/panel.py"
  chmod 600 "$APP_DIR/config.json"
}

install_service() {
  if [ -f ./systemd/vps-probe.service ]; then
    install -m 0644 ./systemd/vps-probe.service "$SERVICE_FILE"
  else
    curl -fsSL "$REPO_RAW/systemd/vps-probe.service" -o "$SERVICE_FILE"
  fi
  systemctl daemon-reload
  systemctl enable --now vps-probe.service
}

main() {
  need_root
  install_packages
  install_files
  install_service
  systemctl status vps-probe.service --no-pager | sed -n '1,12p'
  echo
  echo "Controller installed. Configure agent nodes in: $APP_DIR/config.json"
  echo "Do not add remote SSH passwords or SSH node definitions."
  echo "Restart after config edits: systemctl restart vps-probe.service"
}

main "$@"
