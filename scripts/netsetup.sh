#!/bin/bash
# One-time host networking for microVM taps (idempotent). Usage: netsetup.sh <tapname> <host_cidr>
set -e
TAP=${1:-tap0}
HOST_CIDR=${2:-172.16.0.1/24}
HOST_IF=$(ip route get 8.8.8.8 | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
sudo ip link del "$TAP" 2>/dev/null || true
sudo ip tuntap add "$TAP" mode tap
sudo ip addr add "$HOST_CIDR" dev "$TAP"
sudo ip link set "$TAP" up
sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null
# NAT (idempotent: delete-then-add)
sudo iptables -t nat -D POSTROUTING -o "$HOST_IF" -j MASQUERADE 2>/dev/null || true
sudo iptables -t nat -A POSTROUTING -o "$HOST_IF" -j MASQUERADE
sudo iptables -D FORWARD -i "$TAP" -o "$HOST_IF" -j ACCEPT 2>/dev/null || true
sudo iptables -A FORWARD -i "$TAP" -o "$HOST_IF" -j ACCEPT
sudo iptables -D FORWARD -i "$HOST_IF" -o "$TAP" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
sudo iptables -A FORWARD -i "$HOST_IF" -o "$TAP" -m state --state RELATED,ESTABLISHED -j ACCEPT
echo "net ready: $TAP ($HOST_CIDR) -> $HOST_IF"
