# Architecture & layering

What AWS + Firecracker give for free vs what we build, and where frameworks slot in.

```
┌──────────────────────────────────────────────────────────────┐
│  L9  UI / dashboard                          ← web/ (Vercel)   │
│  L8  auth, quotas, multi-tenant isolation    ← TODO (product)  │
│  L7  ingress/routing (world-x → VM:port)     ← TODO (reuse CW) │
│  L6  control plane: POST /machines /clone /exec ← control-plane/cw_api.py │
│  L5  exec channel (ssh over tap)             ← scripts (ssh into guest)   │
│  L4  snapshot → resume  (THE moat)           ← scripts/snaprestore.sh     │
│  L3  CoW clone (ZFS clone per fork)          ← scripts/zfssetup.sh + clone.sh │
│  L2  lifecycle: tap/IP, rootfs, kvm          ← scripts/boot.sh + netsetup.sh  │
├──────────────────────────────────────────────────────────────┤
│  L1  Firecracker VMM (boot + snapshot API)   ✓ upstream         │
│  L0  bare-metal /dev/kvm, kernel, NIC        ✓ AWS a1.metal     │
└──────────────────────────────────────────────────────────────┘
```

## Frameworks: what we leveraged vs deferred

**Leveraged (to finish in a day):**
- **Firecracker** — the VMM, driven directly via its REST API over a unix socket (its own
  reference method). Gives boot + snapshot/restore primitives.
- **Firecracker CI prebuilt kernel + rootfs** — skipped building our own guest image.
- **ZFS** — copy-on-write clones for L3.

**Deferred to the product phase (on purpose):**
- **firecracker-containerd** — OCI images as microVMs + devmapper CoW; the natural L2+L3 base.
- **Kata Containers** — k8s/OCI runtime running containers as microVMs.
- **Flintlock** — gRPC control plane for Firecracker (maintenance uncertain post-Weaveworks).
- **Nomad + firecracker-task-driver** — multi-host scheduling (L8).

Rationale: the moat is **L4 (snapshot/resume) + per-clone identity**, which *no* framework hands
you — they all do cold-create, not fork-a-running-machine. Adopting a framework first would hide
the exact layer we needed to measure. Sequence: **DIY to learn L4 → snap frameworks underneath for
L1–L3/L5/L7–L8.**

## Request path (once backend is exposed)
```
browser ──HTTPS──> Vercel static UI ──/api/*──> Vercel serverless proxy
        ──(token, server-side)──> metal control plane (cw_api.py :8080)
        ──shell──> firecracker REST API + zfs + ssh ──> microVM (172.16.n.2)
```
