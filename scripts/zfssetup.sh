#!/bin/bash
# One-time: create a file-backed ZFS pool + golden rootfs dataset + snapshot.
set -e
if zpool list cwpool >/dev/null 2>&1; then echo "cwpool exists"; else
  truncate -s 20G /opt/cw/zpool.img
  sudo zpool create -f cwpool /opt/cw/zpool.img
fi
if ! zfs list cwpool/golden >/dev/null 2>&1; then
  sudo zfs create cwpool/golden
  sudo cp /opt/cw/base/rootfs-base.ext4 /cwpool/golden/rootfs.ext4
  sudo zfs snapshot cwpool/golden@base
fi
echo "=== zfs state ==="
zfs list -t all -o name,used,refer,origin
