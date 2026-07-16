#!/usr/bin/env python3
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'install.sh'


def function(text, name, next_name):
    start = text.index(f'{name}() {{')
    end = text.index(f'{next_name}() {{', start)
    return text[start:end]


def run_harness(body, setup, extra=''):
    root = Path(tempfile.mkdtemp())
    bin_dir = root / 'bin'
    bin_dir.mkdir()
    script = root / 'run.sh'
    script.write_text(f'''#!/usr/bin/env bash
set -euo pipefail
ROOT={root!s}
APP_DIR="$ROOT/app"
CONTROLLER_VENV="$ROOT/controller-venv"
CONTROLLER_SERVICE="$ROOT/vps-probe.service"
HUB_SERVICE="$ROOT/vps-probe-hub.service"
AGENT_SCRIPT="$ROOT/vps-probe-agent.py"
AGENT_VENV="$ROOT/agent-venv"
AGENT_CONFIG="$ROOT/agent.json"
AGENT_SERVICE="$ROOT/vps-probe-agent.service"
LANG=en
mkdir -p "$APP_DIR"
tr() {{ echo "$1"; }}
install_prerequisites() {{ :; }}
configure_https() {{ :; }}
backup_file() {{ local s="$1" d="$2" k="$3"; if [ -e "$s" ]; then cp -a "$s" "$d/$k"; : > "$d/$k.present"; fi; }}
restore_file() {{ local dst="$1" d="$2" k="$3"; if [ -f "$d/$k.present" ]; then cp -a "$d/$k" "$dst"; else rm -f "$dst"; fi; }}
source_file() {{ install -m "$3" "{ROOT}/$1" "$2"; }}
ask() {{ echo new-endpoint; }}
ask_secret() {{ echo new-token; }}
generate_token() {{ echo generated; }}
{body}
{extra}
''')
    script.chmod(0o700)
    setup(root)
    env = os.environ.copy()
    env['PATH'] = f'{bin_dir}:{env["PATH"]}'
    return root, script, env


def write_mock(root, name, content):
    path = root / 'bin' / name
    path.write_text('#!/usr/bin/env bash\n' + content + '\n')
    path.chmod(0o700)


def common_sources(root):
    for relative in ['panel.py', 'ws_hub.py', 'validate_config.py', 'systemd/vps-probe.service', 'systemd/vps-probe-hub.service', 'agent/vps-probe-agent.py', 'systemd/vps-probe-agent.service']:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / relative
        target.write_bytes(source.read_bytes())


def test_controller_rolls_back_files_and_venv_on_failed_health_check():
    text = INSTALLER.read_text()
    body = function(text, 'install_controller', 'install_agent')

    def setup(root):
        common_sources(root)
        (root / 'app').mkdir(exist_ok=True)
        for name in ['panel.py', 'ws_hub.py', 'validate_config.py']:
            (root / 'app' / name).write_text('old-' + name)
        (root / 'vps-probe.service').write_text('old-panel-unit')
        (root / 'vps-probe-hub.service').write_text('old-hub-unit')
        (root / 'controller-venv').mkdir()
        (root / 'controller-venv' / 'marker').write_text('old-venv')
        (root / 'app' / 'config.json').write_text('{"nodes":[]}')
        write_mock(root, 'systemctl', 'case "$1" in is-active) exit 1;; *) exit 0;; esac')
        write_mock(root, 'curl', 'exit 1')

    root, script, env = run_harness(body, setup, 'install_controller || true')
    result = subprocess.run([script], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (root / 'app' / 'panel.py').read_text() == 'old-panel.py'
    assert (root / 'vps-probe.service').read_text() == 'old-panel-unit'
    assert (root / 'controller-venv' / 'marker').read_text() == 'old-venv'


def test_agent_update_preserves_existing_credentials():
    text = INSTALLER.read_text()
    body = function(text, 'install_agent', 'uninstall_probe')

    def setup(root):
        common_sources(root)
        (root / 'agent.json').write_text('{"endpoint":"wss://old/ws","token":"old-token"}')
        (root / 'agent-venv').mkdir()
        (root / 'agent-venv' / 'marker').write_text('old')
        write_mock(root, 'systemctl', 'exit 0')

    root, script, env = run_harness(body, setup, 'install_agent')
    result = subprocess.run([script], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (root / 'agent.json').read_text() == '{"endpoint":"wss://old/ws","token":"old-token"}'


if __name__ == '__main__':
    test_controller_rolls_back_files_and_venv_on_failed_health_check()
    test_agent_update_preserves_existing_credentials()
    print('installer_transaction=ok')
