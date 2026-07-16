import importlib.util
import json
import math
import socket
import threading
import time
import http.client
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_rejects_empty_and_duplicate_agent_tokens(tmp_path):
    hub = load_module('hub_config', 'ws_hub.py')
    hub.CONFIG_PATH = tmp_path / 'config.json'

    hub.CONFIG_PATH.write_text(json.dumps({'nodes': [{'id': 'a', 'name': 'A', 'type': 'agent', 'token': ''}]}))
    with pytest.raises(ValueError, match='token'):
        hub.load_config()

    hub.CONFIG_PATH.write_text(json.dumps({'nodes': [
        {'id': 'a', 'name': 'A', 'type': 'agent', 'token': 'same'},
        {'id': 'b', 'name': 'B', 'type': 'agent', 'token': 'same'},
    ]}))
    with pytest.raises(ValueError, match='duplicate'):
        hub.load_config()


def test_report_validation_rejects_nonfinite_wrong_type_and_out_of_range():
    hub = load_module('hub_report', 'ws_hub.py')
    with pytest.raises(ValueError, match='missing required'):
        hub.clean_report({})
    with pytest.raises(ValueError):
        hub.clean_report({'cpu_usage_percent': float('inf')})
    with pytest.raises(ValueError):
        hub.clean_report({'mem_total_mb': 'lots'})
    with pytest.raises(ValueError):
        hub.clean_report({'disk_percent': 101})
    with pytest.raises(ValueError):
        hub.clean_report({'os': 'x' * 300})

    clean = hub.clean_report({
        'uptime_sec': 1,
        'cpu_usage_percent': 12.5,
        'mem_total_mb': 1024,
        'mem_used_mb': 512,
        'disk_percent': 10,
        'net_rx_bytes': 1,
        'net_tx_bytes': 2,
        'ts': 1,
        'os': 'Linux',
        'ignored': 'value',
    })
    assert clean == {
        'uptime_sec': 1,
        'cpu_usage_percent': 12.5,
        'mem_total_mb': 1024,
        'mem_used_mb': 512,
        'disk_percent': 10,
        'net_rx_bytes': 1,
        'net_tx_bytes': 2,
        'ts': 1,
        'os': 'Linux',
    }
    json.dumps(clean, allow_nan=False)


def test_state_corruption_is_not_silently_replaced(tmp_path):
    hub = load_module('hub_state', 'ws_hub.py')
    hub.STATE_PATH = tmp_path / 'state.json'
    hub.STATE_BACKUP_PATH = tmp_path / 'state.json.bak'
    hub.STATE_PATH.write_text('{broken')
    hub.STATE_BACKUP_PATH.write_text(json.dumps({'old': {'reported_at': 1}}))

    assert hub.load_state() == {'old': {'reported_at': 1}}

    hub.STATE_BACKUP_PATH.write_text('{also broken')
    with pytest.raises(RuntimeError, match='state'):
        hub.load_state()


def test_nonstandard_json_constants_are_rejected_and_backup_is_used(tmp_path):
    hub = load_module('hub_nonfinite_state', 'ws_hub.py')
    hub.STATE_PATH = tmp_path / 'state.json'
    hub.STATE_BACKUP_PATH = tmp_path / 'state.json.bak'
    hub.STATE_PATH.write_text('{"evil":{"cpu_usage_percent":Infinity}}')
    hub.STATE_BACKUP_PATH.write_text(json.dumps({'good': {'reported_at': 1}}))
    assert hub.load_state() == {'good': {'reported_at': 1}}

    panel = load_module('panel_nonfinite_state', 'panel.py')
    panel.STATE_PATH = hub.STATE_PATH
    panel.STATE_BACKUP_PATH = hub.STATE_BACKUP_PATH
    assert panel.state() == {'good': {'reported_at': 1}}


def test_agent_rejects_insecure_remote_websocket_endpoint():
    agent = load_module('agent_endpoint', 'agent/vps-probe-agent.py')
    assert agent.ws_endpoint('https://agent.example.com/foo') == 'wss://agent.example.com/ws'
    assert agent.ws_endpoint('wss://agent.example.com/ws') == 'wss://agent.example.com/ws'
    assert agent.ws_endpoint('ws://127.0.0.1:8089/ws') == 'ws://127.0.0.1:8089/ws'
    with pytest.raises(ValueError, match='wss'):
        agent.ws_endpoint('ws://agent.example.com/ws')
    with pytest.raises(ValueError, match='wss'):
        agent.ws_endpoint('http://agent.example.com')


def test_panel_html_uses_polling_not_browser_websocket():
    panel = load_module('panel_html', 'panel.py')
    assert 'new WebSocket' not in panel.HTML_PAGE
    assert 'setInterval(load,5000)' in panel.HTML_PAGE.replace(' ', '')


def test_panel_config_validation_rejects_missing_required_fields(tmp_path):
    panel = load_module('panel_config', 'panel.py')
    panel.CONFIG_PATH = tmp_path / 'config.json'
    panel.CONFIG_PATH.write_text(json.dumps({'nodes': [{'id': 'a', 'type': 'agent'}]}))
    with pytest.raises(ValueError, match='name'):
        panel.config()


def test_panel_reads_state_backup_and_fails_closed(tmp_path):
    panel = load_module('panel_state', 'panel.py')
    panel.STATE_PATH = tmp_path / 'state.json'
    panel.STATE_BACKUP_PATH = tmp_path / 'state.json.bak'
    panel.STATE_PATH.write_text('{broken')
    panel.STATE_BACKUP_PATH.write_text(json.dumps({'n': {'reported_at': 1}}))
    assert panel.state() == {'n': {'reported_at': 1}}
    panel.STATE_BACKUP_PATH.write_text('{broken too')
    with pytest.raises(RuntimeError, match='state'):
        panel.state()


def test_threaded_http_server_sets_connection_timeout():
    panel = load_module('panel_timeout', 'panel.py')
    server = panel.BoundedThreadingHTTPServer(('127.0.0.1', 0), panel.Handler)
    try:
        left, right = socket.socketpair()
        try:
            server.process_request(left, ('local', 0))
            time.sleep(0.05)
            assert left.gettimeout() == panel.HTTP_CONNECTION_TIMEOUT
        finally:
            right.close()
    finally:
        server.server_close()


def test_panel_supports_head_health_checks():
    panel = load_module('panel_head', 'panel.py')
    server = panel.BoundedThreadingHTTPServer(('127.0.0.1', 0), panel.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=2)
        connection.request('HEAD', '/api/status')
        response = connection.getresponse()
        assert response.status == 200
        assert response.read() == b''
        connection.close()
    finally:
        server.shutdown()
        server.server_close()


def test_installer_has_atomic_download_restart_and_controller_venv():
    text = (ROOT / 'install.sh').read_text()
    assert 'mktemp' in text
    assert 'python3 -m py_compile' in text
    assert 'systemctl restart vps-probe.service vps-probe-hub.service' in text
    assert 'systemctl restart vps-probe-agent.service' in text
    assert 'websockets==10.4' in text
    assert 'vps-probe-controller-venv' in text
    assert 'umask 077' in text
    assert 'read -r -s' in text
    assert 'validate_config.py' in text
    assert 'controller_stage' in text
    assert 'controller_backup' in text
    assert 'rollback_controller' in text
    assert 'agent_stage' in text
    assert 'agent_backup' in text
    assert 'rollback_agent' in text
    assert 'preserve_agent_config' in text


def test_installer_validates_before_controller_replacement():
    text = (ROOT / 'install.sh').read_text()
    function = text[text.index('install_controller()'):text.index('install_agent()')]
    validate_at = function.index('validate_config.py')
    replace_at = function.index('install -m 0700 "$controller_stage/panel.py"')
    assert validate_at < replace_at


def test_installer_preserves_existing_agent_credentials():
    text = (ROOT / 'install.sh').read_text()
    function = text[text.index('install_agent()'):text.index('uninstall_probe()')]
    assert 'if [ -f "$AGENT_CONFIG" ]' in function
    assert 'preserve_agent_config' in function
    assert 'cp -a "$AGENT_CONFIG" "$agent_stage/config.json"' in function


def test_caddy_keeps_panel_http_and_agent_websocket_separate():
    installer = (ROOT / 'install.sh').read_text()
    example = (ROOT / 'caddy/Caddyfile.example').read_text()
    for text in (installer, example):
        assert '127.0.0.1:8088' in text
        assert '127.0.0.1:8089' in text
        assert 'handle /ws' in text
    panel_block = example.split('# Agent domain:', 1)[0]
    assert '127.0.0.1:8089' not in panel_block


def test_systemd_controller_uses_dedicated_venv():
    hub_unit = (ROOT / 'systemd/vps-probe-hub.service').read_text()
    assert '/opt/vps-probe-controller-venv/bin/python' in hub_unit


def test_strict_json_serializer_rejects_nonfinite():
    hub = load_module('hub_json', 'ws_hub.py')
    with pytest.raises(ValueError):
        hub.strict_json({'x': math.inf})
    assert hub.strict_json({'x': 1}) == '{"x":1}'


def test_browser_role_is_not_accepted_by_agent_hub():
    hub = load_module('hub_role', 'ws_hub.py')
    assert hub.is_agent_hello({'role': 'browser', 'token': 'x'}) is False
    assert hub.is_agent_hello({'role': 'agent', 'token': 'x'}) is True
