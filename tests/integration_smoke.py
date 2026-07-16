#!/usr/bin/env python3
import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(cpu=12.5, ts=1):
    return {
        'uptime_sec': 1,
        'cpu_usage_percent': cpu,
        'mem_total_mb': 1024,
        'mem_used_mb': 512,
        'disk_percent': 10,
        'net_rx_bytes': 1,
        'net_tx_bytes': 2,
        'ts': ts,
        'os': 'Linux',
    }


async def main():
    hub = load('smoke_hub', 'ws_hub.py')
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        hub.CONFIG_PATH = tmp / 'config.json'
        hub.STATE_PATH = tmp / 'state.json'
        hub.STATE_BACKUP_PATH = tmp / 'state.json.bak'
        hub.WS_PORT = 18091
        hub.CONFIG_PATH.write_text(json.dumps({'nodes': [
            {'id': 'n1', 'name': 'Node', 'type': 'agent', 'token': 'secret'},
        ]}))

        server = await websockets.serve(hub.handler, '127.0.0.1', hub.WS_PORT, max_size=hub.MAX_REPORT_BYTES)
        try:
            async with websockets.connect('ws://127.0.0.1:18091') as ws:
                await ws.send(json.dumps({'role': 'browser'}))
                try:
                    await ws.recv()
                except websockets.exceptions.ConnectionClosed as exc:
                    assert exc.code == 1008

            async with websockets.connect('ws://127.0.0.1:18091') as ws:
                await ws.send(json.dumps({'role': 'agent', 'token': 'secret'}))
                accepted = json.loads(await ws.recv())
                assert accepted['type'] == 'accepted'
                await ws.send(json.dumps({'type': 'report', 'data': report()}))
                await asyncio.sleep(0.1)
                state = json.loads(hub.STATE_PATH.read_text())
                assert state['n1']['cpu_usage_percent'] == 12.5

                hub.CONFIG_PATH.write_text(json.dumps({'nodes': []}))
                await asyncio.sleep(hub.MIN_REPORT_INTERVAL)
                await ws.send(json.dumps({'type': 'report', 'data': report(cpu=1, ts=2)}))
                try:
                    await ws.recv()
                except websockets.exceptions.ConnectionClosed as exc:
                    assert exc.code == 1008

            hub.CONFIG_PATH.write_text(json.dumps({'nodes': [
                {'id': 'n1', 'name': 'Node', 'type': 'agent', 'token': 'secret'},
            ]}))
            async with websockets.connect('ws://127.0.0.1:18091') as ws:
                await ws.send(json.dumps({'role': 'agent', 'token': 'secret'}))
                await ws.recv()
                bad = report()
                bad['cpu_usage_percent'] = float('inf')
                await ws.send(json.dumps({'type': 'report', 'data': bad}))
                try:
                    await ws.recv()
                except websockets.exceptions.ConnectionClosed as exc:
                    assert exc.code == 1008
            state = json.loads(hub.STATE_PATH.read_text())
            assert state['n1']['cpu_usage_percent'] == 12.5
        finally:
            server.close()
            await server.wait_closed()
    print('integration_smoke=ok')


if __name__ == '__main__':
    asyncio.run(main())
