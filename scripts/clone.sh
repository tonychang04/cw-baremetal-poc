#!/bin/bash
# CoW-clone the golden rootfs and boot it as a fork with its own network identity.
# Usage: clone.sh <forkid> <n>   (n in 1..254 -> subnet 172.16.<n>.0/24, mac/tap derived)
set -e
FORK=$1; N=$2
TAP=tap$N
HOSTIP=172.16.$N.1
GIP=172.16.$N.2
MAC=$(printf '06:00:AC:10:%02x:02' "$N")

echo "=== zfs CoW clone ==="
sudo zfs destroy -r cwpool/$FORK 2>/dev/null || true
T0=$(date +%s.%N)
sudo zfs clone cwpool/golden@base cwpool/$FORK
T1=$(date +%s.%N)
echo "CLONE_SECONDS=$(echo "$T1 - $T0"|bc)"
ROOTFS=/cwpool/$FORK/rootfs.ext4
sudo chown "$(id -un):$(id -gn)" "$ROOTFS"   # firecracker (ubuntu) needs RW on the drive

echo "=== net + boot fork ==="
bash /opt/cw/netsetup.sh "$TAP" "$HOSTIP/24" >/dev/null
bash /opt/cw/boot.sh "$FORK" "$TAP" "$GIP" "$MAC" "$ROOTFS"
