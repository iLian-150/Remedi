#!/usr/bin/env bash
# 仅修复 Remedi bridge 的转发；不改默认策略、NAT 或 /etc 下的配置。
set -euo pipefail

network="${1:-remedi_default}"
if [[ "$EUID" -ne 0 ]]; then
  echo "请以 root 运行本项目网络检查脚本。" >&2
  exit 1
fi
network_id="$(docker network inspect --format '{{.Id}}' "$network")"
bridge="$(docker network inspect --format '{{index .Options "com.docker.network.bridge.name"}}' "$network")"
if [[ -z "$bridge" || "$bridge" == '<no value>' ]]; then
  bridge="br-${network_id:0:12}"
fi
subnet="$(docker network inspect --format '{{range .IPAM.Config}}{{println .Subnet}}{{end}}' "$network" | awk '/^[0-9]+\./ {print; exit}')"
if [[ -z "$subnet" || ! -d "/sys/class/net/$bridge" ]]; then
  echo "无法确认项目 bridge 和 IPv4 网段，停止修改。" >&2
  exit 1
fi

ensure_rule() {
  if ! iptables -w 5 -C FORWARD "$@" 2>/dev/null; then
    iptables -w 5 -I FORWARD 1 "$@"
  fi
}

ensure_rule -i "$bridge" -o "$bridge" -s "$subnet" -d "$subnet" \
  -m comment --comment 'remedi: internal' -j ACCEPT
ensure_rule -i "$bridge" '!' -o "$bridge" -s "$subnet" \
  -m comment --comment 'remedi: outbound' -j ACCEPT
ensure_rule '!' -i "$bridge" -o "$bridge" -d "$subnet" \
  -m conntrack --ctstate ESTABLISHED,RELATED \
  -m comment --comment 'remedi: return' -j ACCEPT
ensure_rule '!' -i "$bridge" -o "$bridge" -d "$subnet" -p tcp \
  -m multiport --dports 80,8000 -m conntrack --ctstate DNAT \
  -m comment --comment 'remedi: published http' -j ACCEPT

printf 'Remedi 项目转发已检查：%s %s；全局默认策略未更改。\n' "$bridge" "$subnet"
