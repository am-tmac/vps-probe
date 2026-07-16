#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/vps-probe"
CONTROLLER_VENV="/opt/vps-probe-controller-venv"
CONTROLLER_SERVICE="/etc/systemd/system/vps-probe.service"
AGENT_SCRIPT="/usr/local/sbin/vps-probe-agent.py"
AGENT_VENV="/opt/vps-probe-agent-venv"
AGENT_CONFIG="/etc/vps-probe-agent.json"
AGENT_SERVICE="/etc/systemd/system/vps-probe-agent.service"
HUB_SERVICE="/etc/systemd/system/vps-probe-hub.service"
REPO_RAW="https://raw.githubusercontent.com/am-tmac/jager-monitor/main"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LANG=""
umask 077

need_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "Please run as root / 请使用 root 运行" >&2
    exit 1
  fi
}

tr() {
  if [ "$LANG" = "zh" ]; then
    case "$1" in
      choose_language) echo "选择语言";;
      chinese) echo "中文";;
      english) echo "English";;
      invalid_choice) echo "无效选项，请重试。";;
      choose_action) echo "选择操作";;
      controller) echo "安装/更新主控端";;
      agent) echo "安装/更新被控端探针";;
      uninstall) echo "卸载";;
      exit) echo "退出";;
      install_controller) echo "正在安装主控端...";;
      install_agent) echo "正在安装被控端探针...";;
      uninstalling) echo "正在卸载 Jager Monitor...";;
      endpoint) echo "主控端上报地址";;
      token) echo "此被控端的 Bearer Token";;
      node_id) echo "节点 ID（仅用于显示提示，不会发送）";;
      public_panel) echo "面板地址";;
      agent_ready) echo "被控端探针已安装并保持 WSS 长连接。";;
      controller_ready) echo "主控端已安装。请编辑配置添加被控端 Token。";;
      caddy_question) echo "配置域名与自动 HTTPS 证书？";;
      caddy_domain) echo "面板域名（仅网页和 API）";;
      agent_domain) echo "Agent WSS 域名（仅 /ws）";;
      caddy_note) echo "脚本将安装 Caddy、创建独立站点配置，并自动申请 Let's Encrypt 证书。两个域名的 A/AAAA 记录必须已指向当前服务器，且 80/443 端口可访问。";;
      dns_missing) echo "未检测到此域名的 DNS 记录。请先确认 DNS 已解析到本机。";;
      domain_exists) echo "Jager Monitor 的 Caddy 站点配置已存在，脚本不会覆盖它。";;
      https_ready) echo "面板 HTTPS 与 Agent WSS 验证成功。";;
      config_path) echo "主控端配置文件";;
      removed) echo "已移除 Jager Monitor 文件和 systemd 服务。未卸载 Python 或 Caddy。";;
      confirm_uninstall) echo "确认卸载？此操作会删除本组件配置与缓存";;
      yes_no) echo "[y/N]";;
      cancelled) echo "已取消。";;
      fetch_failed) echo "无法下载所需文件。请检查网络或从仓库目录运行。";;
      controller_help) echo "为每个被控端创建唯一 Token，并在 nodes 中添加 type=agent 的节点。";;
      agent_help) echo "Token 必须与主控端 config.json 中相应 agent 节点的 token 完全一致。";;
      service_active) echo "服务状态";;
      *) echo "$1";;
    esac
  else
    case "$1" in
      choose_language) echo "Choose language";;
      chinese) echo "Chinese";;
      english) echo "English";;
      invalid_choice) echo "Invalid choice. Please try again.";;
      choose_action) echo "Choose an action";;
      controller) echo "Install/update controller";;
      agent) echo "Install/update agent";;
      uninstall) echo "Uninstall";;
      exit) echo "Exit";;
      install_controller) echo "Installing controller...";;
      install_agent) echo "Installing agent...";;
      uninstalling) echo "Uninstalling Jager Monitor...";;
      endpoint) echo "Controller report endpoint";;
      token) echo "This agent's Bearer token";;
      node_id) echo "Node ID (display hint only; not transmitted)";;
      public_panel) echo "Panel URL";;
      agent_ready) echo "Agent installed and keeping a persistent WSS connection.";;
      controller_ready) echo "Controller installed. Edit its config to add agent tokens.";;
      caddy_question) echo "Configure domain and automatic HTTPS certificate?";;
      caddy_domain) echo "Panel domain (web and API only)";;
      agent_domain) echo "Agent WSS domain (/ws only)";;
      caddy_note) echo "The script installs Caddy, creates isolated site configs, and automatically obtains Let's Encrypt certificates. Both domain A/AAAA records must already point to this server and ports 80/443 must be reachable.";;
      dns_missing) echo "No DNS record was detected for this domain. Confirm it points to this server first.";;
      domain_exists) echo "A Jager Monitor Caddy site configuration already exists. The script will not overwrite it.";;
      https_ready) echo "Panel HTTPS and Agent WSS verification succeeded.";;
      config_path) echo "Controller config";;
      removed) echo "Removed Jager Monitor files and systemd units. Python and Caddy were not removed.";;
      confirm_uninstall) echo "Confirm uninstall? This deletes this component's config and state";;
      yes_no) echo "[y/N]";;
      cancelled) echo "Cancelled.";;
      fetch_failed) echo "Could not fetch required files. Check network access or run from the repository directory.";;
      controller_help) echo "Generate a unique token for each agent and add a type=agent node to nodes.";;
      agent_help) echo "The token must exactly match the corresponding agent node token in the controller config.json.";;
      service_active) echo "Service status";;
      *) echo "$1";;
    esac
  fi
}

ask() {
  local label="$1" default="$2" value
  read -r -p "$label [$default]: " value || true
  printf '%s' "${value:-$default}"
}

ask_secret() {
  local label="$1" generated="$2" value
  read -r -s -p "$label [press Enter to generate]: " value || true
  echo >&2
  printf '%s' "${value:-$generated}"
}

confirm() {
  local answer
  read -r -p "$(tr "$1") $(tr yes_no) " answer || true
  [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]
}

source_file() {
  local relative="$1" destination="$2" mode="$3" temp
  temp=$(mktemp "${destination}.XXXXXX")
  if [ -f "$SCRIPT_DIR/$relative" ]; then
    install -m "$mode" "$SCRIPT_DIR/$relative" "$temp"
  else
    if ! curl -fsSL "$REPO_RAW/$relative" -o "$temp"; then
      rm -f "$temp"
      echo "$(tr fetch_failed)" >&2
      exit 1
    fi
    chmod "$mode" "$temp"
  fi
  case "$relative" in
    *.py) python3 -m py_compile "$temp" ;;
    *.json) python3 -m json.tool "$temp" >/dev/null ;;
    *.sh) bash -n "$temp" ;;
  esac
  mv -f "$temp" "$destination"
}

backup_file() {
  local source="$1" backup_dir="$2" key="$3"
  if [ -e "$source" ]; then
    cp -a "$source" "$backup_dir/$key"
    : > "$backup_dir/$key.present"
  fi
}

restore_file() {
  local destination="$1" backup_dir="$2" key="$3"
  if [ -f "$backup_dir/$key.present" ]; then
    cp -a "$backup_dir/$key" "$destination"
  else
    rm -f "$destination"
  fi
}

install_prerequisites() {
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-websockets curl ca-certificates
}

generate_token() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    python3 -c 'import secrets; print(secrets.token_hex(24))'
  fi
}

configure_https() {
  local panel_domain agent_domain main_file panel_file agent_file main_backup agent_status
  echo "$(tr caddy_note)"
  if ! confirm caddy_question; then
    return
  fi

  panel_domain=$(ask "$(tr caddy_domain)" "panel.example.com")
  agent_domain=$(ask "$(tr agent_domain)" "agent.example.com")
  for domain in "$panel_domain" "$agent_domain"; do
    if [[ ! "$domain" =~ ^[A-Za-z0-9.-]+$ ]] || [[ "$domain" != *.* ]]; then
      echo "Invalid domain: $domain" >&2
      return 1
    fi
    if ! getent ahosts "$domain" >/dev/null 2>&1; then
      echo "$(tr dns_missing): $domain" >&2
      return 1
    fi
  done
  if [ "$panel_domain" = "$agent_domain" ]; then
    echo "Panel and Agent domains must be different." >&2
    return 1
  fi

  DEBIAN_FRONTEND=noninteractive apt-get install -y caddy
  main_file="/etc/caddy/Caddyfile"
  panel_file="/etc/caddy/jager-monitor-panel.caddy"
  agent_file="/etc/caddy/jager-monitor-agent.caddy"
  install -d -m 0755 /etc/caddy
  touch "$main_file"
  if [ -e "$panel_file" ] || [ -e "$agent_file" ]; then
    echo "$(tr domain_exists)" >&2
    return 1
  fi
  main_backup=$(mktemp)
  cp -a "$main_file" "$main_backup"
  rollback_https() {
    cp -a "$main_backup" "$main_file"
    rm -f "$panel_file" "$agent_file" "$main_backup"
    caddy validate --config "$main_file" --adapter caddyfile >/dev/null 2>&1 && (systemctl reload caddy || true)
  }

  if ! grep -Fqx 'import /etc/caddy/*.caddy' "$main_file"; then
    printf '\nimport /etc/caddy/*.caddy\n' >> "$main_file"
  fi
  cat > "$panel_file" <<EOF
$panel_domain {
    encode gzip zstd
    reverse_proxy 127.0.0.1:8088
}
EOF
  cat > "$agent_file" <<EOF
$agent_domain {
    encode gzip zstd
    handle /ws {
        reverse_proxy 127.0.0.1:8089
    }
    handle {
        respond "Not Found" 404
    }
}
EOF
  chmod 644 "$panel_file" "$agent_file"
  caddy fmt --overwrite "$main_file"
  caddy fmt --overwrite "$panel_file"
  caddy fmt --overwrite "$agent_file"
  if ! caddy validate --config "$main_file" --adapter caddyfile; then
    rollback_https
    return 1
  fi
  systemctl enable --now caddy
  if ! systemctl reload caddy && ! systemctl restart caddy; then
    rollback_https
    return 1
  fi
  agent_status=$(curl -sS --connect-timeout 15 --max-time 30 -o /dev/null -w '%{http_code}' "https://$agent_domain/")
  if curl -fsS --connect-timeout 15 --max-time 30 "https://$panel_domain/api/status" -o /dev/null && [ "$agent_status" = "404" ]; then
    rm -f "$main_backup"
    echo "$(tr https_ready): https://$panel_domain and wss://$agent_domain/ws"
  else
    rollback_https
    echo "HTTPS verification failed; Caddy configuration was restored. Check DNS propagation, ports 80/443, and: journalctl -u caddy -n 100 --no-pager" >&2
    return 1
  fi
}

install_controller() {
  local controller_stage controller_backup release old_venv old_release
  echo "$(tr install_controller)"
  install_prerequisites
  install -d -m 0755 "$APP_DIR"
  controller_stage=$(mktemp -d)
  controller_backup=$(mktemp -d)
  release="${CONTROLLER_VENV}.release.$(date +%s).$$"
  old_venv="${CONTROLLER_VENV}.rollback.$$"

  source_file "panel.py" "$controller_stage/panel.py" 0700
  source_file "ws_hub.py" "$controller_stage/ws_hub.py" 0700
  source_file "validate_config.py" "$controller_stage/validate_config.py" 0700
  source_file "systemd/vps-probe.service" "$controller_stage/vps-probe.service" 0644
  source_file "systemd/vps-probe-hub.service" "$controller_stage/vps-probe-hub.service" 0644
  if [ -f "$APP_DIR/config.json" ]; then
    python3 "$controller_stage/validate_config.py" "$APP_DIR/config.json"
  else
    source_file "config.example.json" "$controller_stage/config.json" 0600
    python3 "$controller_stage/validate_config.py" "$controller_stage/config.json"
  fi
  python3 -m venv "$release"
  "$release/bin/pip" install --no-cache-dir "websockets==10.4"
  "$release/bin/python" -c 'import websockets; assert websockets.__version__ == "10.4"'

  backup_file "$APP_DIR/panel.py" "$controller_backup" panel.py
  backup_file "$APP_DIR/ws_hub.py" "$controller_backup" ws_hub.py
  backup_file "$APP_DIR/validate_config.py" "$controller_backup" validate_config.py
  backup_file "$CONTROLLER_SERVICE" "$controller_backup" vps-probe.service
  backup_file "$HUB_SERVICE" "$controller_backup" vps-probe-hub.service
  if [ -e "$CONTROLLER_VENV" ] || [ -L "$CONTROLLER_VENV" ]; then
    old_release=$(readlink -f "$CONTROLLER_VENV" 2>/dev/null || true)
    mv "$CONTROLLER_VENV" "$old_venv"
  fi

  rollback_controller() {
    restore_file "$APP_DIR/panel.py" "$controller_backup" panel.py
    restore_file "$APP_DIR/ws_hub.py" "$controller_backup" ws_hub.py
    restore_file "$APP_DIR/validate_config.py" "$controller_backup" validate_config.py
    restore_file "$CONTROLLER_SERVICE" "$controller_backup" vps-probe.service
    restore_file "$HUB_SERVICE" "$controller_backup" vps-probe-hub.service
    rm -rf "$CONTROLLER_VENV"
    if [ -e "$old_venv" ] || [ -L "$old_venv" ]; then mv "$old_venv" "$CONTROLLER_VENV"; fi
    systemctl daemon-reload
    systemctl restart vps-probe.service vps-probe-hub.service || true
  }

  install -m 0700 "$controller_stage/panel.py" "$APP_DIR/panel.py"
  install -m 0700 "$controller_stage/ws_hub.py" "$APP_DIR/ws_hub.py"
  install -m 0700 "$controller_stage/validate_config.py" "$APP_DIR/validate_config.py"
  install -m 0644 "$controller_stage/vps-probe.service" "$CONTROLLER_SERVICE"
  install -m 0644 "$controller_stage/vps-probe-hub.service" "$HUB_SERVICE"
  if [ ! -f "$APP_DIR/config.json" ]; then install -m 0600 "$controller_stage/config.json" "$APP_DIR/config.json"; fi
  ln -s "$release" "$CONTROLLER_VENV"

  systemctl daemon-reload
  systemctl enable vps-probe.service vps-probe-hub.service
  if ! systemctl restart vps-probe.service vps-probe-hub.service; then
    rollback_controller
    rm -rf "$controller_stage" "$controller_backup" "$release"
    return 1
  fi
  sleep 3
  if ! systemctl is-active --quiet vps-probe.service vps-probe-hub.service || ! curl -fsS --connect-timeout 3 --max-time 10 http://127.0.0.1:8088/api/status -o /dev/null; then
    rollback_controller
    rm -rf "$controller_stage" "$controller_backup" "$release"
    return 1
  fi
  rm -rf "$controller_stage" "$controller_backup" "$old_venv"
  case "${old_release:-}" in "$CONTROLLER_VENV.release."*) rm -rf "$old_release" ;; esac
  echo "$(tr controller_ready)"
  echo "$(tr config_path): $APP_DIR/config.json"
  echo "$(tr controller_help)"
  echo
  echo "$(tr service_active): $(systemctl is-active vps-probe.service)"
  configure_https
}

install_agent() {
  local endpoint token node_id agent_stage agent_backup release old_venv old_release preserve_agent_config
  echo "$(tr install_agent)"
  install_prerequisites
  agent_stage=$(mktemp -d)
  agent_backup=$(mktemp -d)
  release="${AGENT_VENV}.release.$(date +%s).$$"
  old_venv="${AGENT_VENV}.rollback.$$"
  preserve_agent_config=false

  if [ -f "$AGENT_CONFIG" ]; then
    preserve_agent_config=true
    cp -a "$AGENT_CONFIG" "$agent_stage/config.json"
    python3 -m json.tool "$agent_stage/config.json" >/dev/null
    endpoint=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["endpoint"])' "$agent_stage/config.json")
    node_id="existing-node"
  else
    endpoint=$(ask "$(tr endpoint)" "wss://agent.example.com/ws")
    node_id=$(ask "$(tr node_id)" "remote-node")
    token=$(ask_secret "$(tr token)" "$(generate_token)")
    cat > "$agent_stage/config.json" <<EOF
{
  "endpoint": "$endpoint",
  "token": "$token"
}
EOF
    python3 -m json.tool "$agent_stage/config.json" >/dev/null
    chmod 600 "$agent_stage/config.json"
  fi

  source_file "agent/vps-probe-agent.py" "$agent_stage/vps-probe-agent.py" 0700
  source_file "systemd/vps-probe-agent.service" "$agent_stage/vps-probe-agent.service" 0644
  sed -i 's|^ExecStart=/usr/bin/python3 |ExecStart=/opt/vps-probe-agent-venv/bin/python |' "$agent_stage/vps-probe-agent.service"
  python3 -m venv "$release"
  "$release/bin/pip" install --no-cache-dir "websockets==10.4"
  "$release/bin/python" -c 'import websockets; assert websockets.__version__ == "10.4"'

  backup_file "$AGENT_SCRIPT" "$agent_backup" vps-probe-agent.py
  backup_file "$AGENT_SERVICE" "$agent_backup" vps-probe-agent.service
  backup_file "$AGENT_CONFIG" "$agent_backup" config.json
  if [ -e "$AGENT_VENV" ] || [ -L "$AGENT_VENV" ]; then
    old_release=$(readlink -f "$AGENT_VENV" 2>/dev/null || true)
    mv "$AGENT_VENV" "$old_venv"
  fi

  rollback_agent() {
    restore_file "$AGENT_SCRIPT" "$agent_backup" vps-probe-agent.py
    restore_file "$AGENT_SERVICE" "$agent_backup" vps-probe-agent.service
    restore_file "$AGENT_CONFIG" "$agent_backup" config.json
    rm -rf "$AGENT_VENV"
    if [ -e "$old_venv" ] || [ -L "$old_venv" ]; then mv "$old_venv" "$AGENT_VENV"; fi
    systemctl daemon-reload
    systemctl restart vps-probe-agent.service || true
  }

  install -m 0700 "$agent_stage/vps-probe-agent.py" "$AGENT_SCRIPT"
  install -m 0644 "$agent_stage/vps-probe-agent.service" "$AGENT_SERVICE"
  install -m 0600 "$agent_stage/config.json" "$AGENT_CONFIG"
  ln -s "$release" "$AGENT_VENV"
  rm -f /etc/systemd/system/vps-probe-agent.timer

  systemctl daemon-reload
  systemctl disable --now vps-probe-agent.timer 2>/dev/null || true
  systemctl enable vps-probe-agent.service
  if ! systemctl restart vps-probe-agent.service; then
    rollback_agent
    rm -rf "$agent_stage" "$agent_backup" "$release"
    return 1
  fi
  sleep 3
  if ! systemctl is-active --quiet vps-probe-agent.service; then
    rollback_agent
    rm -rf "$agent_stage" "$agent_backup" "$release"
    return 1
  fi
  rm -rf "$agent_stage" "$agent_backup" "$old_venv"
  case "${old_release:-}" in "$AGENT_VENV.release."*) rm -rf "$old_release" ;; esac

  echo "$(tr agent_ready)"
  echo "$(tr agent_help)"
  echo "Node ID: $node_id"
  echo "$(tr service_active): $(systemctl is-active vps-probe-agent.service)"
  systemctl status vps-probe-agent.service --no-pager | sed -n '1,10p' || true
}

uninstall_probe() {
  if ! confirm confirm_uninstall; then
    echo "$(tr cancelled)"
    return
  fi
  echo "$(tr uninstalling)"
  systemctl disable --now vps-probe.service vps-probe-hub.service 2>/dev/null || true
  systemctl disable --now vps-probe-agent.timer 2>/dev/null || true
  systemctl stop vps-probe-agent.service 2>/dev/null || true
  rm -f "$CONTROLLER_SERVICE" "$HUB_SERVICE" "$AGENT_SERVICE" /etc/systemd/system/vps-probe-agent.timer "$AGENT_SCRIPT" "$AGENT_CONFIG"
  rm -rf "$AGENT_VENV" "$AGENT_VENV".release.* "$CONTROLLER_VENV" "$CONTROLLER_VENV".release.*
  rm -f /etc/caddy/jager-monitor.caddy /etc/caddy/jager-monitor-panel.caddy /etc/caddy/jager-monitor-agent.caddy
  if [ -f /etc/caddy/Caddyfile ] && grep -Fqx 'import /etc/caddy/*.caddy' /etc/caddy/Caddyfile; then
    sed -i '\|^import /etc/caddy/\\\*\\.caddy$|d' /etc/caddy/Caddyfile
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 && systemctl reload caddy || true
  fi
  rm -rf "$APP_DIR"
  systemctl daemon-reload
  echo "$(tr removed)"
}

choose_language() {
  while :; do
    echo "1) 中文"
    echo "2) English"
    read -r -p "Choose language / 选择语言 [1]: " choice || true
    case "${choice:-1}" in
      1) LANG="zh"; return ;;
      2) LANG="en"; return ;;
      *) echo "Invalid choice / 无效选项" ;;
    esac
  done
}

main_menu() {
  while :; do
    echo
    echo "$(tr choose_action)"
    echo "1) $(tr controller)"
    echo "2) $(tr agent)"
    echo "3) $(tr uninstall)"
    echo "0) $(tr exit)"
    read -r -p "> " choice || true
    case "$choice" in
      1) install_controller; return ;;
      2) install_agent; return ;;
      3) uninstall_probe; return ;;
      0) return ;;
      *) echo "$(tr invalid_choice)" ;;
    esac
  done
}

need_root
choose_language
main_menu
