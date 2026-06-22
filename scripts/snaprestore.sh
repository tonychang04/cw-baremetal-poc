#!/bin/bash
# Snapshot a running microVM, kill it, restore into a fresh process, measure resume.
# Usage: snaprestore.sh <id> <guest_ip>
set -e
ID=$1; GIP=$2
SOCK=/opt/cw/run/$ID.sock
RSOCK=/opt/cw/run/${ID}r.sock
SNAP=/opt/cw/run/$ID.snap
MEM=/opt/cw/run/$ID.mem
api(){ curl -s --unix-socket "$1" -X PUT "http://localhost/$2" -H 'Content-Type: application/json' -d "$3"; }
apatch(){ curl -s --unix-socket "$1" -X PATCH "http://localhost/$2" -H 'Content-Type: application/json' -d "$3"; }

echo "=== pause + snapshot ==="
apatch "$SOCK" "vm" '{"state":"Paused"}'
T0=$(date +%s.%N)
api "$SOCK" "snapshot/create" "{\"snapshot_type\":\"Full\",\"snapshot_path\":\"$SNAP\",\"mem_file_path\":\"$MEM\"}"
T1=$(date +%s.%N)
echo "SNAPSHOT_SECONDS=$(echo "$T1-$T0"|bc)"
ls -la "$SNAP" "$MEM" | awk '{print $5, $9}'

echo "=== kill original (free tap0) ==="
sudo pkill -x firecracker
for i in $(seq 1 20); do pgrep -x firecracker >/dev/null || break; done

echo "=== restore + resume ==="
sudo setfacl -m u:"$(id -un)":rw /dev/kvm 2>/dev/null || true
rm -f "$RSOCK"
firecracker --api-sock "$RSOCK" >/opt/cw/run/${ID}r.log 2>&1 &
for i in $(seq 1 50); do [ -S "$RSOCK" ] && break; done
TR0=$(date +%s.%N)
api "$RSOCK" "snapshot/load" "{\"snapshot_path\":\"$SNAP\",\"mem_backend\":{\"backend_type\":\"File\",\"backend_path\":\"$MEM\"},\"resume_vm\":true}" >/dev/null
for i in $(seq 1 600); do
  if nc -z -w1 "$GIP" 22 2>/dev/null; then
    TR1=$(date +%s.%N)
    echo "RESUME_SECONDS=$(echo "$TR1 - $TR0"|bc)"
    exit 0
  fi
done
echo "RESUME TIMEOUT"; tail -15 /opt/cw/run/${ID}r.log; exit 1
