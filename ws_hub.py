#!/usr/bin/env python3
import asyncio
import hmac
import json
import time
from pathlib import Path

import websockets

CONFIG_PATH = Path('/opt/vps-probe/config.json')
STATE_PATH = Path('/opt/vps-probe/state.json')
WS_HOST = '127.0.0.1'
WS_PORT = 8089
MAX_REPORT_BYTES = 16384
MAX_BROWSER_CLIENTS = 128

clients = set()
state_lock = asyncio.Lock()


def load_config():
    return json.loads(CONFIG_PATH.read_text())


def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    tmp = STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(',', ':')))
    tmp.chmod(0o600)
    tmp.replace(STATE_PATH)


def matching_agent(token):
    for node in load_config().get('nodes', []):
        if node.get('type') == 'agent' and hmac.compare_digest(node.get('token', ''), token):
            return node
    return None


async def notify_browsers():
    if not clients:
        return
    message = json.dumps({'type': 'update', 'ts': int(time.time())})
    results = await asyncio.gather(*(client.send(message) for client in clients), return_exceptions=True)
    for client, result in zip(list(clients), results):
        if isinstance(result, Exception):
            clients.discard(client)


async def handler(websocket):
    role = None
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=15)
        if not isinstance(raw, str) or len(raw) > MAX_REPORT_BYTES:
            await websocket.close(code=1008, reason='invalid handshake')
            return
        hello = json.loads(raw)
        role = hello.get('role')
        if role == 'browser':
            if len(clients) >= MAX_BROWSER_CLIENTS:
                await websocket.close(code=1013, reason='browser capacity reached')
                return
            clients.add(websocket)
            await websocket.send(json.dumps({'type': 'connected', 'ts': int(time.time())}))
            await websocket.wait_closed()
            return
        if role != 'agent' or not matching_agent(str(hello.get('token', ''))):
            await websocket.close(code=1008, reason='unauthorized')
            return
        node = matching_agent(str(hello['token']))
        await websocket.send(json.dumps({'type': 'accepted', 'interval_seconds': 5}))
        async for raw in websocket:
            if not isinstance(raw, str) or len(raw) > MAX_REPORT_BYTES:
                continue
            report = json.loads(raw)
            if report.get('type') != 'report' or not isinstance(report.get('data'), dict):
                continue
            allowed = {'hostname', 'uptime_sec', 'load', 'load1', 'cpu_count', 'cpu_usage_percent', 'mem_total_mb', 'mem_used_mb', 'swap_total_mb', 'swap_used_mb', 'disk_total_mb', 'disk_used_mb', 'disk_avail_mb', 'disk_percent', 'net_rx_bytes', 'net_tx_bytes', 'rx_speed_bps', 'tx_speed_bps', 'tcp_count', 'udp_count', 'process_count', 'os', 'kernel', 'arch', 'ts'}
            clean = {key: report['data'][key] for key in allowed if key in report['data']}
            clean['reported_at'] = int(time.time())
            async with state_lock:
                state = load_state()
                state[node['id']] = clean
                save_state(state)
            await notify_browsers()
    except websockets.exceptions.ConnectionClosed:
        pass
    except (json.JSONDecodeError, asyncio.TimeoutError):
        await websocket.close(code=1008, reason='invalid request')
    finally:
        if role == 'browser':
            clients.discard(websocket)


async def main():
    async with websockets.serve(handler, WS_HOST, WS_PORT, ping_interval=20, ping_timeout=20, max_size=MAX_REPORT_BYTES):
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
