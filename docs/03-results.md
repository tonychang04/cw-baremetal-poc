# Measured results

Host: EC2 `a1.metal` (Graviton1, aarch64, 16 vCPU / 31 GB), us-east-1, Ubuntu 24.04.
Guest: Firecracker v1.16.0, kernel 6.1.102, Ubuntu 22.04 rootfs, 2 vCPU / 512 MB.

| Operation | Time | How measured |
|---|---|---|
| Cold boot (kernel → SSH-reachable) | **~1.45–1.55 s** | `InstanceStart` → guest `:22` open |
| Kernel → init (boot alone) | ~125 ms | Firecracker serial log |
| **Resume from snapshot** (load → SSH-reachable) | **~28 ms** | `snapshot/load` → guest `:22` open |
| **CoW clone** (ZFS clone of golden) | **~47–51 ms** | around `zfs clone` |
| Snapshot *create* (512 MB RAM → disk) | ~4.6 s | around `snapshot/create` |
| Disk per fork (CoW diff) | **~345 KB** | `zfs list` USED |

## Reading the numbers
- **28 ms resume** is the headline — restoring a fully-booted microVM to usable in 28 ms. For
  comparison, Blaxel resumes ~25 ms but has **no fork primitive**; we have both.
- **Snapshot create is slow (4.6 s)** because it writes the full 512 MB RAM to an EBS-backed file.
  Not on the hot path for resume. Optimizable: diff snapshots, smaller RAM, local NVMe instance store.
- **CoW is cheap**: two forks of an 87.6 MB image cost ~700 KB total extra; each `REFER`s the full
  image but only `USED` its own writes.

## Proof of fork independence
Two forks `m10`/`m11`: distinct hostnames, IPs (172.16.10.2 / .11.2), and independent writable
state (different `/root/who.txt`); neither sees the other's writes; the golden image is untouched.
