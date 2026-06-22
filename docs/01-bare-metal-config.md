# Configuring bare metal for Firecracker microVMs

The core knowledge transfer: how to turn a fresh bare-metal box into a host that boots,
snapshots, and CoW-forks microVMs. Validated on EC2 `a1.metal` (Graviton1, aarch64), but the
steps are host-agnostic (Hetzner/Latitude x86 works the same, swap `aarch64`→`x86_64`).

## Why bare metal at all

Firecracker needs `/dev/kvm` — hardware virtualization. Normal cloud instances don't expose it;
only **bare-metal** instances do. On EC2 that means the `.metal` types. On Hetzner/Latitude, any
dedicated box. This is the entire reason for the cost/complexity — there is no shortcut.

Verify on a new host:
```bash
ls -l /dev/kvm        # must exist
uname -m              # aarch64 or x86_64 — your kernel/rootfs/firecracker must match
nproc; free -h        # capacity
```

## The five things you must configure

### 1. KVM access for the non-root user  ← the #1 gotcha
Firecracker runs as your user (`ubuntu`), but `/dev/kvm` is `root:kvm`. Two layers, use both:
```bash
sudo usermod -aG kvm ubuntu          # group membership — needs a FRESH login to take effect
sudo setfacl -m u:ubuntu:rw /dev/kvm # immediate; but udev/logind RESET this periodically
```
Because the ACL gets reset, our `boot.sh`/`snaprestore.sh` re-apply it on every launch. Without
this you get `Error creating KVM object: Permission denied (os error 13)` at `InstanceStart`.

### 2. The VMM + guest images
```bash
# Firecracker binary (match arch)
REL=$(curl -s https://api.github.com/repos/firecracker-microvm/firecracker/releases/latest | jq -r .tag_name)
curl -sSL .../firecracker-$REL-aarch64.tgz | tar -xz && sudo install …/firecracker-$REL-aarch64 /usr/local/bin/firecracker

# Prebuilt kernel + rootfs from Firecracker CI — skips building your own image
B=https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.10/aarch64
curl -sSL $B/vmlinux-6.1.102     -o vmlinux
curl -sSL $B/ubuntu-22.04.ext4   -o rootfs-base.ext4   # writable ext4 (v1.12+ ships read-only squashfs only)
curl -sSL $B/ubuntu-22.04.id_rsa -o guest_key          # SSH key baked into that rootfs
```

### 3. Networking (per-VM tap + NAT)
Each microVM gets a host-side `tap` device and an IP; the host NATs guest egress. We put each VM
on its own `/24` (`172.16.<n>.0/24`, host = `.1`, guest = `.2`) so many VMs don't collide:
```bash
ip tuntap add tap<n> mode tap
ip addr add 172.16.<n>.1/24 dev tap<n>; ip link set tap<n> up
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -A POSTROUTING -o <uplink> -j MASQUERADE
iptables -A FORWARD -i tap<n> -o <uplink> -j ACCEPT
iptables -A FORWARD -i <uplink> -o tap<n> -m state --state RELATED,ESTABLISHED -j ACCEPT
```
The guest gets its IP via the kernel boot arg `ip=<guest>::<gw>:255.255.255.0::eth0:off` — no DHCP.

### 4. Booting via the Firecracker REST API
Firecracker listens on a unix socket; you `PUT` config then start. Order: `boot-source` →
`drives/rootfs` → `network-interfaces/eth0` → `machine-config` → `actions{InstanceStart}`.
Setting a drive `is_root_device:true` makes Firecracker pass `root=` to the kernel automatically.
**Pause is `PATCH /vm {"state":"Paused"}` — not PUT.**

### 5. CoW storage (ZFS) for forks
No spare disk on `a1.metal`, so we back a ZFS pool with a file (fine for PoC; use real NVMe/zvol
in prod):
```bash
truncate -s 20G zpool.img && zpool create cwpool zpool.img
zfs create cwpool/golden && cp rootfs-base.ext4 /cwpool/golden/rootfs.ext4
zfs snapshot cwpool/golden@base
# fork = instant CoW clone:
zfs clone cwpool/golden@base cwpool/<fork>
chown ubuntu: /cwpool/<fork>/rootfs.ext4   # ← clone inherits root ownership; FC needs RW or guest panics
```

## The two fork primitives (and when to use each)
- **Snapshot → resume** (`snaprestore.sh`): freeze a *running* VM's full state (RAM+devices) and
  restore it. ~28 ms resume. Use to fork a *live, warmed* machine.
- **CoW disk clone** (`clone.sh`): clone the rootfs and cold-boot. ~50 ms clone + ~1.5 s boot.
  Use to spawn many independent machines from a golden image cheaply (~345 KB each).

The full product fork = snapshot the RAM **and** CoW-clone the disk **and** give each fork its own
identity. This PoC proves the pieces; combining them is the next step.
