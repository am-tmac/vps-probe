#!/usr/bin/env python3
import hmac
import json
import shlex
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONFIG_PATH = Path('/opt/vps-probe/config.json')
STATE_PATH = Path('/opt/vps-probe/state.json')
STALE_SECONDS = 120

COLLECT_SH = r'''
set -e
json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
hostname=$(hostname 2>/dev/null || echo unknown)
uptime_sec=$(awk '{print int($1)}' /proc/uptime 2>/dev/null || echo 0)
load=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo '0 0 0')
load1=$(echo "$load" | awk '{print $1}')
cpu_count=$(nproc 2>/dev/null || echo 0)
cpu_line=$(awk '/^cpu /{print}' /proc/stat 2>/dev/null || echo 'cpu 0 0 0 0 0 0 0 0')
set -- $cpu_line
user=$2; nice=$3; system=$4; idle=$5; iowait=$6; irq=$7; softirq=$8; steal=$9
idle_all=$((idle+iowait)); non_idle=$((user+nice+system+irq+softirq+steal)); total=$((idle_all+non_idle))
sleep 0.25
cpu_line2=$(awk '/^cpu /{print}' /proc/stat 2>/dev/null || echo 'cpu 0 0 0 0 0 0 0 0')
set -- $cpu_line2
user2=$2; nice2=$3; system2=$4; idle2=$5; iowait2=$6; irq2=$7; softirq2=$8; steal2=$9
idle_all2=$((idle2+iowait2)); non_idle2=$((user2+nice2+system2+irq2+softirq2+steal2)); total2=$((idle_all2+non_idle2))
totald=$((total2-total)); idled=$((idle_all2-idle_all))
cpu_usage=$(awk -v t="$totald" -v i="$idled" 'BEGIN{if(t>0) printf "%.1f", (t-i)*100/t; else printf "0"}')
mem_total=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
mem_avail=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
mem_used=$((mem_total - mem_avail))
swap_total=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
swap_free=$(awk '/SwapFree/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
swap_used=$((swap_total - swap_free))
disk_line=$(df -BM / | awk 'NR==2 {print $2,$3,$4,$5}')
disk_total=$(echo "$disk_line" | awk '{print $1}' | tr -d M)
disk_used=$(echo "$disk_line" | awk '{print $2}' | tr -d M)
disk_avail=$(echo "$disk_line" | awk '{print $3}' | tr -d M)
disk_percent=$(echo "$disk_line" | awk '{print $4}' | tr -d %)
net_rx=$(awk 'BEGIN{s=0} $1 ~ /^[a-zA-Z0-9_.-]+:$/ {iface=$1; gsub(":","",iface); if(iface!="lo") s+=$2} END{print s+0}' /proc/net/dev 2>/dev/null || echo 0)
net_tx=$(awk 'BEGIN{s=0} $1 ~ /^[a-zA-Z0-9_.-]+:$/ {iface=$1; gsub(":","",iface); if(iface!="lo") s+=$10} END{print s+0}' /proc/net/dev 2>/dev/null || echo 0)
tcp_count=$(ss -tan 2>/dev/null | awk 'NR>1{c++} END{print c+0}')
udp_count=$(ss -uan 2>/dev/null | awk 'NR>1{c++} END{print c+0}')
process_count=$(ps -e --no-headers 2>/dev/null | wc -l | tr -d ' ')
os=$(awk -F= '/^PRETTY_NAME=/ {gsub(/"/,"",$2); print $2}' /etc/os-release 2>/dev/null || uname -s)
kernel=$(uname -r 2>/dev/null || echo unknown)
arch=$(uname -m 2>/dev/null || echo unknown)
now=$(date +%s)
printf '{"hostname":"%s","uptime_sec":%s,"load":"%s","load1":%s,"cpu_count":%s,"cpu_usage_percent":%s,"mem_total_mb":%s,"mem_used_mb":%s,"swap_total_mb":%s,"swap_used_mb":%s,"disk_total_mb":%s,"disk_used_mb":%s,"disk_avail_mb":%s,"disk_percent":%s,"net_rx_bytes":%s,"net_tx_bytes":%s,"tcp_count":%s,"udp_count":%s,"process_count":%s,"os":"%s","kernel":"%s","arch":"%s","ts":%s}\n' \
  "$(json_escape "$hostname")" "$uptime_sec" "$(json_escape "$load")" "$load1" "$cpu_count" "$cpu_usage" "$mem_total" "$mem_used" "$swap_total" "$swap_used" "$disk_total" "$disk_used" "$disk_avail" "$disk_percent" "$net_rx" "$net_tx" "$tcp_count" "$udp_count" "$process_count" "$(json_escape "$os")" "$(json_escape "$kernel")" "$(json_escape "$arch")" "$now"
'''

HTML_PAGE = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tmac VPS Probe</title><style>:root{color-scheme:dark;--bg:#070b10;--panel:#101822;--panel2:#0d141d;--line:#243345;--text:#eaf2fb;--muted:#8ba1b7;--ok:#27d17f;--bad:#ff5269;--warn:#f5bb42;--blue:#4aa8ff;--cyan:#19d3ff;--purple:#9b7cff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#111d29 0,#070b10 42%);color:var(--text);font:13px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:1320px;margin:0 auto;padding:22px}header{display:flex;justify-content:space-between;gap:14px;align-items:flex-end;margin-bottom:14px}h1{font-size:24px;margin:0}.sub,.refresh{color:var(--muted)}.summary{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:10px;margin-bottom:14px}.sum{background:linear-gradient(180deg,#142031,#0d141d);border:1px solid var(--line);border-radius:8px;padding:12px}.sum .k{color:var(--muted);font-size:12px}.sum .v{font-size:20px;font-weight:800;margin-top:4px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px}.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:8px;padding:14px;box-shadow:0 12px 30px rgba(0,0,0,.18)}.top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;border-bottom:1px solid var(--line);padding-bottom:10px}.name{font-size:17px;font-weight:800}.host{color:var(--muted);font-size:12px;margin-top:2px}.badge{border:1px solid var(--line);border-radius:999px;padding:3px 9px;font-size:12px;font-weight:700}.on{color:var(--ok);border-color:#1f6b45;background:#0b2418}.off{color:var(--bad);border-color:#78313a;background:#2a0f14}.kv{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}.mini{background:#09111a;border:1px solid #1f2b39;border-radius:7px;padding:8px}.mini .k{color:var(--muted);font-size:11px}.mini .v{font-weight:700;font-variant-numeric:tabular-nums;margin-top:3px}.bars{display:grid;gap:9px}.row{display:grid;grid-template-columns:58px 1fr 94px;gap:9px;align-items:center}.label{color:var(--muted);font-size:12px}.bar{height:8px;background:#071018;border-radius:999px;overflow:hidden}.fill{height:8px;background:linear-gradient(90deg,var(--blue),var(--cyan));border-radius:999px}.fill.mem{background:linear-gradient(90deg,var(--purple),var(--blue))}.fill.disk{background:linear-gradient(90deg,var(--cyan),var(--ok))}.fill.warn{background:var(--warn)}.fill.bad{background:var(--bad)}.value{text-align:right;font-variant-numeric:tabular-nums;color:#dbe8f5}.foot{display:grid;grid-template-columns:1fr auto;gap:10px;color:var(--muted);font-size:12px;margin-top:12px;border-top:1px solid var(--line);padding-top:10px}.err{color:var(--bad);white-space:pre-wrap;margin-top:12px}@media(max-width:760px){.summary{grid-template-columns:repeat(2,1fr)}header{display:block}.grid{grid-template-columns:1fr}.row{grid-template-columns:52px 1fr 82px}}</style></head><body><div class="wrap"><header><div><h1>Tmac VPS Probe</h1><div class="sub">Push-agent status panel</div></div><div class="refresh" id="refresh">loading...</div></header><section class="summary" id="summary"></section><main class="grid" id="grid"></main></div><script>const refreshMs=10000;function pct(u,t){return t?Math.round(Number(u||0)*100/Number(t)):0}function uptime(s){s=Number(s||0);const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return d?`${d}d ${h}h`:`${h}h ${m}m`}function bytes(v){v=Number(v||0);const u=['B','KB','MB','GB','TB'];let i=0;while(v>=1024&&i<u.length-1){v/=1024;i++}return `${v.toFixed(i?1:0)}${u[i]}`}function mb(v){v=Number(v||0);return v>=1024?`${(v/1024).toFixed(1)}G`:`${v}M`}function cls(p){return p>=90?'bad':p>=75?'warn':''}function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}function kernel(k){return String(k||'').split('-')[0]}function osShort(o){return String(o||'').replace('GNU/Linux','').replace(' LTS','')}function speedVal(v){v=Number(v||0);return v<=0?'0B/s':bytes(v)+'/s'}function sumBox(k,v){return `<div class="sum"><div class="k">${k}</div><div class="v">${v}</div></div>`}function renderSummary(nodes){const on=nodes.filter(n=>n.online),total=nodes.length;const avg=x=>on.length?Math.round(on.reduce((s,n)=>s+Number(x(n)||0),0)/on.length):0;const abnormal=on.filter(n=>Number(n.cpu_usage_percent)>=85||pct(n.mem_used_mb,n.mem_total_mb)>=85||Number(n.disk_percent)>=85).length;document.getElementById('summary').innerHTML=[sumBox('在线节点',`${on.length}/${total}`),sumBox('异常节点',abnormal),sumBox('平均CPU',avg(n=>n.cpu_usage_percent)+'%'),sumBox('平均内存',avg(n=>pct(n.mem_used_mb,n.mem_total_mb))+'%'),sumBox('平均磁盘',avg(n=>Number(n.disk_percent))+'%'),sumBox('总流量',bytes(on.reduce((s,n)=>s+Number(n.net_rx_bytes||0)+Number(n.net_tx_bytes||0),0)))].join('')}function card(n){const online=n.online,mem=pct(n.mem_used_mb,n.mem_total_mb),disk=Number(n.disk_percent)||pct(n.disk_used_mb,n.disk_total_mb),cpu=Number(n.cpu_usage_percent||0),loadRatio=n.cpu_count?Number(n.load1||0)/Number(n.cpu_count):0;return `<section class="card"><div class="top"><div><div class="name">${esc(n.flag||'🖥️')} ${esc(n.name)}</div><div class="host">${esc(n.region||'')} · ${esc(osShort(n.os))} · ${esc(kernel(n.kernel))}</div></div><span class="badge ${online?'on':'off'}">${online?'ONLINE':'OFFLINE'}</span></div>${online?`<div class="kv"><div class="mini"><div class="k">运行时间</div><div class="v">${uptime(n.uptime_sec)}</div></div><div class="mini"><div class="k">进程</div><div class="v">${esc(n.process_count)}</div></div><div class="mini"><div class="k">TCP/UDP</div><div class="v">${esc(n.tcp_count)}/${esc(n.udp_count)}</div></div><div class="mini"><div class="k">负载</div><div class="v">${esc(n.load)} / ${esc(n.cpu_count)}C</div></div><div class="mini"><div class="k">下行速率</div><div class="v">${speedVal(n.rx_speed_bps)}</div></div><div class="mini"><div class="k">上行速率</div><div class="v">${speedVal(n.tx_speed_bps)}</div></div></div><div class="bars"><div class="row"><div class="label">CPU</div><div class="bar"><div class="fill ${cls(cpu)}" style="width:${Math.min(100,cpu)}%"></div></div><div class="value">${cpu.toFixed(1)}%</div></div><div class="row"><div class="label">MEM</div><div class="bar"><div class="fill mem ${cls(mem)}" style="width:${mem}%"></div></div><div class="value">${mb(n.mem_used_mb)} / ${mb(n.mem_total_mb)}</div></div><div class="row"><div class="label">DISK</div><div class="bar"><div class="fill disk ${cls(disk)}" style="width:${disk}%"></div></div><div class="value">${mb(n.disk_used_mb)} / ${mb(n.disk_total_mb)}</div></div></div><div class="foot"><div>${esc(n.arch)} · load ratio ${loadRatio.toFixed(2)}</div><div>${new Date((n.reported_at||0)*1000).toLocaleTimeString()}</div></div>`:`<div class="err">${esc(n.error||'No recent agent report')}</div>`}</section>`}async function load(){try{const r=await fetch('/api/status',{cache:'no-store'});const d=await r.json();const nodes=d.nodes.sort((a,b)=>(a.online===b.online?0:a.online?1:-1));renderSummary(nodes);document.getElementById('grid').innerHTML=nodes.map(card).join('');document.getElementById('refresh').textContent='更新：'+new Date().toLocaleString()}catch(e){document.getElementById('refresh').textContent='加载失败：'+e.message}}load();setInterval(load,refreshMs);</script></body></html>'''


def load_config():
    with CONFIG_PATH.open() as f:
        return json.load(f)


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


def collect_local():
    import subprocess
    proc = subprocess.run('bash -lc ' + shlex.quote(COLLECT_SH), shell=True, text=True, capture_output=True, timeout=7)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or 'local collection failed').strip()[-300:])
    return json.loads(proc.stdout.strip().splitlines()[-1])


def status_nodes():
    cfg = load_config()
    state = load_state()
    now = int(time.time())
    nodes = []
    for node in cfg.get('nodes', []):
        result = {'name': node['name'], 'type': node['type'], 'flag': node.get('flag', ''), 'region': node.get('region', ''), 'online': False}
        try:
            if node['type'] == 'local':
                result.update(collect_local())
                result['reported_at'] = now
                result['online'] = True
            else:
                report = state.get(node['id'])
                if not report:
                    result['error'] = 'No agent report received'
                elif now - int(report.get('reported_at', 0)) > STALE_SECONDS:
                    result['error'] = f"Agent report stale ({now - int(report['reported_at'])}s ago)"
                else:
                    result.update(report)
                    result['online'] = True
        except Exception as exc:
            result['error'] = str(exc)
        result.pop('hostname', None)
        nodes.append(result)
    return nodes


def bearer_token(headers):
    value = headers.get('Authorization', '')
    prefix = 'Bearer '
    return value[len(prefix):] if value.startswith(prefix) else ''


class Handler(BaseHTTPRequestHandler):
    server_version = 'VPSProbe/2.0'

    def log_message(self, fmt, *args):
        return

    def send_bytes(self, code, body, ctype='application/json; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/' or self.path.startswith('/?'):
            self.send_bytes(200, HTML_PAGE.encode(), 'text/html; charset=utf-8')
        elif self.path.startswith('/api/status'):
            body = json.dumps({'nodes': status_nodes(), 'ts': int(time.time())}, ensure_ascii=False).encode()
            self.send_bytes(200, body)
        else:
            self.send_bytes(404, b'not found', 'text/plain')

    def do_POST(self):
        if self.path != '/api/report':
            self.send_bytes(404, b'not found', 'text/plain')
            return
        cfg = load_config()
        token = bearer_token(self.headers)
        node = next((n for n in cfg.get('nodes', []) if n.get('type') == 'agent' and hmac.compare_digest(n.get('token', ''), token)), None)
        if not node:
            self.send_bytes(401, b'unauthorized', 'text/plain')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 2 or length > 16384:
                raise ValueError('invalid body length')
            report = json.loads(self.rfile.read(length))
            allowed = {'hostname', 'uptime_sec', 'load', 'load1', 'cpu_count', 'cpu_usage_percent', 'mem_total_mb', 'mem_used_mb', 'swap_total_mb', 'swap_used_mb', 'disk_total_mb', 'disk_used_mb', 'disk_avail_mb', 'disk_percent', 'net_rx_bytes', 'net_tx_bytes', 'tcp_count', 'udp_count', 'process_count', 'os', 'kernel', 'arch', 'ts'}
            clean = {key: report[key] for key in allowed if key in report}
            clean['reported_at'] = int(time.time())
            state = load_state()
            state[node['id']] = clean
            save_state(state)
            self.send_bytes(204, b'', 'text/plain')
        except (ValueError, json.JSONDecodeError):
            self.send_bytes(400, b'invalid report', 'text/plain')


def main():
    cfg = load_config()
    server = ThreadingHTTPServer((cfg.get('listen', '127.0.0.1'), int(cfg.get('port', 8088))), Handler)
    print(f"VPS probe listening on {cfg.get('listen')}:{cfg.get('port')}", flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
