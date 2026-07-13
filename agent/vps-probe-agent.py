#!/usr/bin/env python3
import json
import time
import urllib.request
from pathlib import Path

CONFIG_PATH = Path('/etc/vps-probe-agent.json')
LAST_NET = {}


def read_text(path, default=''):
    try:
        return Path(path).read_text()
    except OSError:
        return default


def first_line(path, default=''):
    return read_text(path, default).splitlines()[0] if read_text(path, default) else default


def cpu_usage():
    def sample():
        fields = first_line('/proc/stat').split()[1:]
        values = [int(value) for value in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle
    total1, idle1 = sample()
    time.sleep(0.25)
    total2, idle2 = sample()
    return round((total2 - total1 - (idle2 - idle1)) * 100 / max(1, total2 - total1), 1)


def meminfo():
    values = {}
    for line in read_text('/proc/meminfo').splitlines():
        parts = line.split()
        if len(parts) >= 2:
            values[parts[0].rstrip(':')] = int(parts[1]) // 1024
    return values


def net_bytes():
    rx = tx = 0
    for line in read_text('/proc/net/dev').splitlines()[2:]:
        iface, raw = line.split(':', 1)
        if iface.strip() == 'lo':
            continue
        values = raw.split()
        rx += int(values[0])
        tx += int(values[8])
    return rx, tx


def count_socket(prefix):
    try:
        return max(0, len(Path(prefix).read_text().splitlines()) - 1)
    except OSError:
        return 0


def os_name():
    for line in read_text('/etc/os-release').splitlines():
        if line.startswith('PRETTY_NAME='):
            return line.split('=', 1)[1].strip('"')
    return 'Linux'


def collect():
    cfg = json.loads(CONFIG_PATH.read_text())
    now = int(time.time())
    mem = meminfo()
    disk = __import__('shutil').disk_usage('/')
    rx, tx = net_bytes()
    previous = LAST_NET.get('net')
    rx_speed = tx_speed = 0
    if previous:
        elapsed = max(0.001, now - previous[0])
        rx_speed = max(0, int((rx - previous[1]) / elapsed))
        tx_speed = max(0, int((tx - previous[2]) / elapsed))
    LAST_NET['net'] = (now, rx, tx)
    load = read_text('/proc/loadavg').split()[:3]
    return cfg, {
        'hostname': __import__('socket').gethostname(),
        'uptime_sec': int(float(first_line('/proc/uptime', '0').split()[0])),
        'load': ' '.join(load) if load else '0 0 0',
        'load1': float(load[0]) if load else 0,
        'cpu_count': __import__('os').cpu_count() or 0,
        'cpu_usage_percent': cpu_usage(),
        'mem_total_mb': mem.get('MemTotal', 0),
        'mem_used_mb': max(0, mem.get('MemTotal', 0) - mem.get('MemAvailable', 0)),
        'swap_total_mb': mem.get('SwapTotal', 0),
        'swap_used_mb': max(0, mem.get('SwapTotal', 0) - mem.get('SwapFree', 0)),
        'disk_total_mb': disk.total // 1048576,
        'disk_used_mb': disk.used // 1048576,
        'disk_avail_mb': disk.free // 1048576,
        'disk_percent': round(disk.used * 100 / max(1, disk.total)),
        'net_rx_bytes': rx,
        'net_tx_bytes': tx,
        'rx_speed_bps': rx_speed,
        'tx_speed_bps': tx_speed,
        'tcp_count': count_socket('/proc/net/tcp') + count_socket('/proc/net/tcp6'),
        'udp_count': count_socket('/proc/net/udp') + count_socket('/proc/net/udp6'),
        'process_count': len([entry for entry in Path('/proc').iterdir() if entry.name.isdigit()]),
        'os': os_name(),
        'kernel': __import__('os').uname().release,
        'arch': __import__('os').uname().machine,
        'ts': now,
    }


def main():
    cfg, report = collect()
    body = json.dumps(report, separators=(',', ':')).encode()
    request = urllib.request.Request(
        cfg['endpoint'], data=body, method='POST',
        headers={'Authorization': 'Bearer ' + cfg['token'], 'Content-Type': 'application/json', 'User-Agent': 'VPSProbe-Agent/1.0'},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 204:
            raise RuntimeError(f'Unexpected HTTP status: {response.status}')


if __name__ == '__main__':
    main()
