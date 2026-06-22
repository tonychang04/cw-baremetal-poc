# cw-baremetal-poc

Bare-metal **Firecracker microVM** proof-of-concept for Cloneable Worlds: boot, snapshot/resume,
and **copy-on-write fork** of microVMs on a single EC2 `a1.metal` host, fronted by a tiny
control-plane API + UI you hit over HTTP.

This is the bare-metal / microVM track — distinct from the APFS-CoW `cloneable-worlds-poc`.
Goal: find out **how hard the fork primitive (L4) really is** and get real numbers on our own metal.

## Measured results (a1.metal, aarch64, us-east-1)

| Operation | Time | Notes |
|---|---|---|
| **Cold boot** (kernel → SSH-reachable) | **~1.45–1.55 s** | full userspace + sshd; kernel→init alone ~125 ms |
| **Resume from snapshot** (load → SSH-reachable) | **~28 ms** | the L4 moat number — on par with Blaxel ~25 ms, *with* fork |
| **CoW clone** (ZFS clone of golden rootfs) | **~47–51 ms** | metadata-only, space-shared |
| Snapshot *create* (full 512 MB RAM → disk) | ~4.6 s | on EBS; optimizable (diff snapshots / smaller RAM / local NVMe) |
| CoW space per fork | **~345 KB** | each fork `REFER`s the full 87.6 MB rootfs, `USED` only the diff |

Two forks booted with independent identity (`m10-fork`/`m11-fork`, distinct IPs, independent
writable state) while sharing the golden image's blocks.

## Architecture (what we built vs leveraged)

```
L7  ingress/routing (world-x → VM)      ← deferred (reuse CW routing)
L6  control plane: POST /machines,/clone,/exec   ← control-plane/cw_api.py
L5  exec channel (ssh over tap)         ← scripts (ssh into guest)
L4  snapshot → resume                   ← scripts/snaprestore.sh   (THE moat)
L3  CoW clone (ZFS clone per fork)       ← scripts/zfssetup.sh + clone.sh
L2  lifecycle: tap/IP, rootfs, kvm       ← scripts/boot.sh + netsetup.sh
---------------------------------------------------------------
L1  Firecracker VMM                      ✓ upstream (driven via REST API)
L0  a1.metal /dev/kvm, kernel, NIC       ✓ AWS + Firecracker CI prebuilt artifacts
```

Frameworks leveraged to finish fast: **Firecracker** (VMM, driven via its own REST API over a
unix socket), **Firecracker CI prebuilt aarch64 kernel + rootfs** (skipped image-building), **ZFS**
(CoW). Heavyweight orchestrators (firecracker-containerd, Kata, Flintlock) are the *product* path —
intentionally deferred so the PoC measures L4 directly instead of hiding it.

## Layout

- `scripts/netsetup.sh`   — host tap + NAT (per-subnet, idempotent)
- `scripts/boot.sh`       — boot one microVM via Firecracker REST API; times cold boot; self-heals `/dev/kvm` ACL
- `scripts/snaprestore.sh`— pause→snapshot→kill→restore; times resume
- `scripts/zfssetup.sh`   — file-backed ZFS pool + golden rootfs dataset + `@base` snapshot
- `scripts/clone.sh`      — ZFS CoW clone + boot a fork with its own subnet/tap/MAC
- `control-plane/cw_api.py` — stdlib HTTP API + one-page UI (spawn / clone / exec / kill), port 8080

## Run it

See `PROVISION.md` for the EC2 host setup. On the host (Ubuntu 24.04, aarch64 metal):

```bash
bash scripts/zfssetup.sh                 # one-time: ZFS pool + golden image
python3 control-plane/cw_api.py          # serves UI+API on :8080
# then hit http://<host-ip>:8080
```

## Known gaps → product

- **Snapshot create is slow** (full RAM to EBS) — use diff snapshots, smaller RAM, or local NVMe.
- **Single host only.** Cross-node fork (a clone runnable on *another* box) needs JuiceFS at L3 — the
  fleet-level story; benchmark the cache-warm boot path vs this local-ZFS floor.
- **Clock/entropy on resume** not yet kicked (negligible at 28 ms gaps; matters for long-paused VMs).
- **No multi-tenant isolation** (jailer/seccomp), **no auth/quotas**, **no L7 ingress** for guest ports.
- Snapshot path stores network identity; clones get fresh identity via per-subnet tap/MAC (works,
  but ad-hoc — needs an IP/MAC allocator for scale).

## Docs (knowledge share)

- [`docs/01-bare-metal-config.md`](docs/01-bare-metal-config.md) — **how to configure a bare-metal host** for Firecracker microVMs, step by step with rationale (KVM access, VMM+images, networking, REST boot, ZFS CoW)
- [`docs/02-architecture.md`](docs/02-architecture.md) — the L0–L9 layering; what we leveraged vs deferred; request path
- [`docs/03-results.md`](docs/03-results.md) — measured benchmarks (boot / resume / clone) and how each was measured
- [`docs/04-gotchas.md`](docs/04-gotchas.md) — every wall we hit + the fix (the time-saver doc)
- [`docs/05-gaps-to-product.md`](docs/05-gaps-to-product.md) — what's missing to go from PoC to product (incl. JuiceFS cross-node)
- [`PROVISION.md`](PROVISION.md) — the exact EC2 launch + host bootstrap commands

## Web UI (Vercel)

`web/` is the static UI + a serverless proxy to the metal control plane. Deployed at
`https://web-ins-forge.vercel.app` (currently behind Vercel team auth). It goes live once the metal
API is exposed and `METAL_URL`/`CW_TOKEN` env vars are set — see [`web/README.md`](web/README.md).
