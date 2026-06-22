#!/bin/bash
# Boot one Firecracker microVM via its REST API and measure cold boot.
# Usage: boot.sh <id> <tap> <guest_ip> <mac> <rootfs_path>
set -e
ID=$1; TAP=$2; GIP=$3; MAC=$4; ROOTFS=$5
SOCK=/opt/cw/run/$ID.sock
LOG=/opt/cw/run/$ID.log
KERNEL=/opt/cw/base/vmlinux
# self-heal /dev/kvm access (ACLs get reset by udev/logind)
sudo setfacl -m u:"$(id -un)":rw /dev/kvm 2>/dev/null || true
rm -f "$SOCK"
api() { curl -s --unix-socket "$SOCK" -X PUT "http://localhost/$1" -H 'Content-Type: application/json' -d "$2"; }

# launch firecracker process
firecracker --api-sock "$SOCK" >"$LOG" 2>&1 &
FCPID=$!
# wait for socket
for i in $(seq 1 50); do [ -S "$SOCK" ] && break; done

GW=$(echo "$GIP" | sed 's/\.[0-9]*$/.1/')
BOOTARGS="console=ttyS0 reboot=k panic=1 pci=off ip=${GIP}::${GW}:255.255.255.0::eth0:off"
api "boot-source" "{\"kernel_image_path\":\"$KERNEL\",\"boot_args\":\"$BOOTARGS\"}" >/dev/null
api "drives/rootfs" "{\"drive_id\":\"rootfs\",\"path_on_host\":\"$ROOTFS\",\"is_root_device\":true,\"is_read_only\":false}" >/dev/null
api "network-interfaces/eth0" "{\"iface_id\":\"eth0\",\"guest_mac\":\"$MAC\",\"host_dev_name\":\"$TAP\"}" >/dev/null
api "machine-config" "{\"vcpu_count\":2,\"mem_size_mib\":512}" >/dev/null

T0=$(date +%s.%N)
api "actions" '{"action_type":"InstanceStart"}' >/dev/null
# poll guest ssh port
for i in $(seq 1 600); do
  if nc -z -w1 "$GIP" 22 2>/dev/null; then
    T1=$(date +%s.%N)
    echo "FCPID=$FCPID"
    echo "COLD_BOOT_SECONDS=$(echo "$T1 - $T0" | bc)"
    exit 0
  fi
done
echo "TIMEOUT waiting for guest $GIP:22"
echo "--- log tail ---"; tail -15 "$LOG"
exit 1
