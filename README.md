# VPS Probe

轻量 VPS 状态监控面板。

主控端提供网页面板；每台被控 VPS 运行轻量探针，每 30 秒主动通过 HTTPS 上报数据。主控端不需要保存或使用远程 VPS 的 SSH 信息。

## 可查看的数据

- 在线状态与最近上报时间
- CPU 使用率、CPU 核心数、系统负载
- 内存与 Swap 使用情况
- 根目录磁盘使用率
- 上下行流量与实时速率
- TCP / UDP 连接数、进程数
- 系统版本、内核、架构、运行时间

## 一键安装

在主控端或被控端使用 root 运行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/am-tmac/vps-probe/main/install.sh)
```

脚本会先选择 **中文 / English**，再选择：

```text
1. 安装/更新主控端
2. 安装/更新被控端探针
3. 卸载
```

被控端安装时填写主控端上报地址和该节点专属 Token 即可。
