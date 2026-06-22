# Gaps to product

What this PoC does NOT yet do, in rough priority order.

### 1. Snapshot-create is slow (full RAM → EBS, ~4.6 s)
Use **diff snapshots** (only dirty pages), smaller guest RAM, and **local NVMe** instance store
instead of EBS. Resume (28 ms) is already fast; this only affects how quickly you can *capture* a
warm template.

### 2. Single host only — no cross-node fork
Today a fork runs on the same box as its golden image (ZFS clone is local). The fleet story needs a
clone runnable on **any** node → this is where **JuiceFS** comes in at L3: the rootfs lives in
object storage, any node mounts/clones it. Plan: store the rootfs image on JuiceFS, clone via its
CoW, boot Firecracker from the clone. **Benchmark the cache-warm boot path against this local-ZFS
floor** — cold object-store reads on the boot path are the risk; needs a warm local cache per node.
(Firecracker has no virtio-fs, so JuiceFS hosts the image *file*; Cloud Hypervisor + virtio-fs would
let you mount JuiceFS into the guest directly.)

### 3. Clock & entropy on resume
Not kicked yet. Negligible at 28 ms resume gaps; matters for VMs paused for minutes/hours — resync
time (chrony/`hwclock`) and re-seed entropy on restore.

### 4. Multi-tenant isolation
No `jailer`/seccomp/cgroups yet. Required before running untrusted code from different tenants on
one box.

### 5. Identity allocation
IP/MAC/subnet are assigned ad-hoc per index. Needs a real allocator (and an IPAM/CNI) at scale.

### 6. Control-plane hardening
Token auth only; no quotas, rate limits, persistence (state is in-memory), or graceful host reboot
recovery. No L7 ingress to expose a *guest's* own service port to the internet
(`world-x.you.dev → 172.16.n.2:port`) — reuse the Cloneable Worlds routing layer.

### 7. Production VMM choice
Evaluate **Cloud Hypervisor** vs Firecracker: CH has better snapshot/restore, virtio-fs (helps
JuiceFS-into-guest), and live migration — relevant once cross-node + data volumes matter.
