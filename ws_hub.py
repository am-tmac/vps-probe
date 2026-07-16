#!/usr/bin/env python3
import asyncio
import hmac
import json
import math
import os
import time
from pathlib import Path

import websockets

CONFIG_PATH = Path('/opt/vps-probe/config.json')
STATE_PATH = Path('/opt/vps-probe/state.json')
STATE_BACKUP_PATH = Path('/opt/vps-probe/state.json.bak')
WS_HOST = '127.0.0.1'
WS_PORT = 8089
MAX_REPORT_BYTES = 16384
MAX_AGENT_CONNECTIONS = 64
MIN_REPORT_INTERVAL = 1.0
MAX_STRING_LENGTH = 256

active_agents = {}
state_lock = asyncio.Lock()
agent_lock = asyncio.Lock()

STRING_FIELDS = {'hostname', 'load', 'os', 'kernel', 'arch'}
PERCENT_FIELDS = {'cpu_usage_percent', 'disk_percent'}
INTEGER_FIELDS = {
    'uptime_sec', 'cpu_count', 'mem_total_mb', 'mem_used_mb',
    'swap_total_mb', 'swap_used_mb', 'disk_total_mb', 'disk_used_mb',
    'disk_avail_mb', 'net_rx_bytes', 'net_tx_bytes', 'rx_speed_bps',
    'tx_speed_bps', 'tcp_count', 'udp_count', 'process_count', 'ts',
}
FLOAT_FIELDS = {'load1'}
REQUIRED_REPORT_FIELDS = {
    'uptime_sec', 'cpu_usage_percent', 'mem_total_mb', 'mem_used_mb',
    'disk_percent', 'net_rx_bytes', 'net_tx_bytes', 'ts',
}
MAX_INTEGER = 2 ** 63 - 1


def strict_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def reject_json_constant(value):
    raise ValueError(f'invalid JSON constant: {value}')


def validate_config(data):
    if not isinstance(data, dict) or not isinstance(data.get('nodes', []), list):
        raise ValueError('config nodes must be a list')
    ids = set()
    tokens = set()
    for index, node in enumerate(data.get('nodes', [])):
        if not isinstance(node, dict):
            raise ValueError(f'node {index} must be an object')
        for field in ('id', 'name', 'type'):
            if not isinstance(node.get(field), str) or not node[field].strip():
                raise ValueError(f'node {index} has invalid {field}')
        if node['id'] in ids:
            raise ValueError(f'duplicate node id: {node["id"]}')
        ids.add(node['id'])
        if node['type'] not in ('local', 'agent'):
            raise ValueError(f'node {node["id"]} has invalid type')
        if node['type'] == 'agent':
            token = node.get('token')
            if not isinstance(token, str) or not token.strip():
                raise ValueError(f'node {node["id"]} has invalid token')
            if token in tokens:
                raise ValueError('duplicate agent token')
            tokens.add(token)
    return data


def load_config():
    return validate_config(json.loads(CONFIG_PATH.read_text()))


def _read_state(path):
    data = json.loads(path.read_text(), parse_constant=reject_json_constant)
    if not isinstance(data, dict):
        raise ValueError('state must be an object')
    return data


def load_state():
    if not STATE_PATH.exists() and not STATE_BACKUP_PATH.exists():
        return {}
    try:
        return _read_state(STATE_PATH)
    except (OSError, json.JSONDecodeError, ValueError) as primary_error:
        try:
            return _read_state(STATE_BACKUP_PATH)
        except (OSError, json.JSONDecodeError, ValueError) as backup_error:
            raise RuntimeError(f'state file and backup are invalid: {primary_error}; {backup_error}')


def _durable_write(path, content):
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    with tmp.open('w') as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.chmod(0o600)
    tmp.replace(path)
    directory_fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def save_state(state):
    payload = strict_json(state)
    if STATE_PATH.exists():
        try:
            current = _read_state(STATE_PATH)
            _durable_write(STATE_BACKUP_PATH, strict_json(current))
        except (OSError, json.JSONDecodeError, ValueError):
            # Never overwrite a known-good backup with a corrupt primary.
            pass
    _durable_write(STATE_PATH, payload)


def matching_agent(token, config_data=None):
    if not isinstance(token, str) or not token:
        return None
    for node in (config_data or load_config()).get('nodes', []):
        configured = node.get('token')
        if node.get('type') == 'agent' and isinstance(configured, str) and configured and hmac.compare_digest(configured, token):
            return node
    return None


def is_agent_hello(hello):
    return isinstance(hello, dict) and hello.get('role') == 'agent' and isinstance(hello.get('token'), str) and bool(hello['token'])


def _number(value, field, *, integer=False, minimum=0, maximum=MAX_INTEGER):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{field} must be a finite number')
    if integer and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValueError(f'{field} must be an integer')
    if value < minimum or value > maximum:
        raise ValueError(f'{field} is out of range')
    return value


def clean_report(data):
    if not isinstance(data, dict):
        raise ValueError('report data must be an object')
    missing = sorted(REQUIRED_REPORT_FIELDS - data.keys())
    if missing:
        raise ValueError(f'missing required report fields: {", ".join(missing)}')
    clean = {}
    for field in STRING_FIELDS:
        if field in data:
            value = data[field]
            if not isinstance(value, str) or len(value) > MAX_STRING_LENGTH:
                raise ValueError(f'{field} must be a short string')
            clean[field] = value
    for field in PERCENT_FIELDS:
        if field in data:
            clean[field] = _number(data[field], field, minimum=0, maximum=100)
    for field in INTEGER_FIELDS:
        if field in data:
            clean[field] = _number(data[field], field, integer=True)
    for field in FLOAT_FIELDS:
        if field in data:
            clean[field] = _number(data[field], field, minimum=0, maximum=1_000_000)
    return clean


async def handler(websocket):
    token = None
    node_id = None
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=15)
        if not isinstance(raw, str) or len(raw) > MAX_REPORT_BYTES:
            await websocket.close(code=1008, reason='invalid handshake')
            return
        hello = json.loads(raw)
        if not is_agent_hello(hello):
            await websocket.close(code=1008, reason='agent authentication required')
            return
        token = hello['token']
        config_data = load_config()
        node = matching_agent(token, config_data)
        if node is None:
            await websocket.close(code=1008, reason='unauthorized')
            return
        node_id = node['id']
        async with agent_lock:
            if len(active_agents) >= MAX_AGENT_CONNECTIONS or token in active_agents:
                await websocket.close(code=1013, reason='agent connection already active')
                return
            active_agents[token] = websocket
        await websocket.send(strict_json({'type': 'accepted', 'interval_seconds': 5}))
        last_report = 0.0
        async for raw in websocket:
            if not isinstance(raw, str) or len(raw) > MAX_REPORT_BYTES:
                await websocket.close(code=1008, reason='invalid report')
                return
            now_monotonic = time.monotonic()
            if now_monotonic - last_report < MIN_REPORT_INTERVAL:
                await websocket.close(code=1008, reason='report rate exceeded')
                return
            last_report = now_monotonic
            report = json.loads(raw)
            if report.get('type') != 'report':
                continue
            current_node = matching_agent(token)
            if current_node is None or current_node['id'] != node_id:
                await websocket.close(code=1008, reason='agent authorization revoked')
                return
            clean = clean_report(report.get('data'))
            clean['reported_at'] = int(time.time())
            async with state_lock:
                state = load_state()
                state[node_id] = clean
                save_state(state)
    except websockets.exceptions.ConnectionClosed:
        pass
    except (json.JSONDecodeError, asyncio.TimeoutError, ValueError, RuntimeError, OSError) as exc:
        try:
            await websocket.close(code=1008, reason=str(exc)[:120])
        except websockets.exceptions.ConnectionClosed:
            pass
    finally:
        if token is not None:
            async with agent_lock:
                if active_agents.get(token) is websocket:
                    active_agents.pop(token, None)


async def main():
    load_config()
    async with websockets.serve(
        handler,
        WS_HOST,
        WS_PORT,
        ping_interval=20,
        ping_timeout=20,
        max_size=MAX_REPORT_BYTES,
        max_queue=8,
    ):
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
