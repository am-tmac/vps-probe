#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/vps-probe"
SERVICE_FILE="/etc/systemd/system/vps-probe.service"
CADDYFILE="/etc/caddy/Caddyfile"
REPO_RAW="https://raw.githubusercontent.com/am-tmac/vps-probe/main"

need_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "Please run as root: sudo bash install.sh" >&2
    exit 1
  fi
}

prompt() {
  local name="$1" default="$2" value
  read -r -p "$name [$default]: " value || true
  printf '%s' "${value:-$default}"
}

install_packages() {
  apt-get update
  apt-get install -y python3 sshpass curl
}

install_files() {
  mkdir -p "$APP_DIR"
  if [ -f ./panel.py ] && [ -f ./config.example.json ]; then
    cp ./panel.py "$APP_DIR/panel.py"
    if [ ! -f "$APP_DIR/config.json" ]; then
      cp ./config.example.json "$APP_DIR/config.json"
    fi
  else
    curl -fsSL "$REPO_RAW/panel.py" -o "$APP_DIR/panel.py"
    if [ ! -f "$APP_DIR/config.json" ]; then
      curl -fsSL "$REPO_RAW/config.example.json" -o "$APP_DIR/config.json"
    fi
  fi
  chmod 700 "$APP_DIR/panel.py"
  chmod 600 "$APP_DIR/config.json"
}

install_service() {
  cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=vps-probe status panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/vps-probe
ExecStart=/usr/bin/python3 /opt/vps-probe/panel.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now vps-probe.service
}

configure_basic() {
  local user pass listen port
  user=$(prompt "Panel username" "admin")
  pass=$(prompt "Panel password" "change-me")
  listen=$(prompt "Listen address" "127.0.0.1")
  port=$(prompt "Listen port" "8088")
  python3 - "$APP_DIR/config.json" "$user" "$pass" "$listen" "$port" <<'PY'
import json, sys
path, user, password, listen, port = sys.argv[1:]
with open(path) as f:
    data = json.load(f)
data['auth_user'] = user
data['auth_pass'] = password
data['listen'] = listen
data['port'] = int(port)
with open(path, 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
PY
}

configure_caddy() {
  local answer domain port
  read -r -p "Install/configure Caddy HTTPS reverse proxy? [y/N]: " answer || true
  case "${answer:-}" in
    y|Y|yes|YES)
      apt-get install -y caddy
      domain=$(prompt "Domain" "probe.example.com")
      port=$(python3 - <<'PY'
import json
print(json.load(open('/opt/vps-probe/config.json')).get('port', 8088))
PY
)
      cat > "$CADDYFILE" <<EOF
$domain {
    encode gzip zstd
    reverse_proxy 127.0.0.1:$port
}
EOF
      caddy validate --config "$CADDYFILE"
      systemctl enable --now caddy
      systemctl reload caddy || systemctl restart caddy
      echo "HTTPS enabled: https://$domain/"
      ;;
    *)
      echo "Skipping Caddy. Panel will listen according to $APP_DIR/config.json"
      ;;
  esac
}

main() {
  need_root
  install_packages
  install_files
  configure_basic
  install_service
  configure_caddy
  systemctl status vps-probe.service --no-pager | sed -n '1,12p'
  echo
  echo "Installed. Edit nodes in: $APP_DIR/config.json"
  echo "Restart after edits: systemctl restart vps-probe"
}

main "$@"
