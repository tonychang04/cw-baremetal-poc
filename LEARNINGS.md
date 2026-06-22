# LEARNINGS — bare-metal Firecracker microVM PoC

Everything learned building this in one day, beyond the per-doc detail. Read alongside `docs/`.

## What we proved (measured, on EC2 a1.metal, aarch64, 16 vCPU / 31 GB)
- **Cold boot** (kernel → SSH-reachable): **~1.5 s**.
- **Resume from snapshot**: **~28 ms** — the moat. On par with Blaxel's ~25 ms, but *with* a fork primitive Blaxel lacks.
- **CoW clone** (ZFS): **~50 ms**, **~345 KB/clone** (blocks shared with golden).
- **Density**: **120 microVMs concurrently** on one box using only **~10 GB RAM** (21 GB free, load 4.6/16). Limited by our safety cap, not the hardware.

## Architecture insights
- **Only two things come for free:** the bare-metal host (`/dev/kvm`) and Firecracker (the VMM). **Everything that makes it a product (L2–L9) is yours to build** — and the only genuinely hard parts are **L4 snapshot/resume** and **per-clone identity**. No framework gives you those (they all do cold-create, not fork-a-running-machine).
- **Drive Firecracker directly via its REST API** for a PoC. Frameworks (firecracker-containerd, Kata, Flintlock) are the *product* path — adopting them first *hides* the L4 layer you're trying to measure. Sequence: DIY to learn L4 → snap frameworks underneath for L1–L3/L5/L7.
- **The control plane must run on the host** (needs /dev/kvm, Firecracker, taps, ZFS). The **UI can run anywhere**. In production you split them: a public authenticated **API-gateway/UI tier** commands a fleet of bare-metal hosts that each run a small **agent + the VMs**. The hosts aren't directly public.

## Technical gotchas (the time-savers)
1. **`/dev/kvm` permission denied** at InstanceStart → user must be in the `kvm` group (needs fresh login) *and* device ACLs get reset by udev/logind, so re-apply `setfacl` on each launch.
2. **Pause is `PATCH /vm`**, not PUT.
3. **Cloned rootfs panics** `Cannot open root device "(null)"` → the golden image was root-owned, the ZFS clone inherits that, Firecracker (as `ubuntu`) can't open it RW, drive PUT fails silently. Fix: `chown` the clone.
4. **`pkill -f <pattern>` kills its own shell** when the pattern appears in the command line. Bit us 3–4 times (firecracker, cw_api, snaprestore, kill handler). Use `pkill -x <name>`, kill by PID, or `fuser -k <port>`.
5. **Firecracker CI v1.12+ ships only a read-only squashfs** — pull the writable `ubuntu-22.04.ext4` from the v1.10 prefix.

## Networking & exposure (the part we spent the most time on)
- **VMs are private** (`172.16.N.2`), NAT egress out. Only the **host** has a public IP. To expose a VM you front it through the host — same pattern as **EC2 itself** (an instance's "public IP" is really a NAT to its private IP).
- **This is normal everywhere**: containers/k8s, VMs on bare metal, Fly/Lambda — all "public edge → private backends." The *only* alternative (bridged + real routable IPs per VM) needs an IP block you don't get on EC2.
- **Exposing the box, options:** open SG port (simplest, but exposes an RCE control plane), **tunnel** (cloudflared/ngrok — outbound, no inbound port, free HTTPS), **load balancer/API gateway** (production: TLS + stable + scaling), **VPN/Tailscale** (keep it private — correct for an admin/control plane).
- **Vercel SSO breaks in-browser `fetch`**: Deployment Protection issues a short-lived (`~1h`) JWT; top-level navigation re-auths but `fetch('/api/...')` can't follow the SSO redirect → 401s once the JWT goes stale. Don't gate an SPA's API with Vercel SSO; gate at the app layer (an access key) instead.
- **A frontend (Next.js or static) is never the hard part** — the hard part is connecting browser → the control plane on the host. The framework is irrelevant to that.

## VM lifecycle & memory
- States: **running** (~80 MB RAM, instant), **paused** (~80 MB — frees CPU only, *not* RAM), **snapshot→disk+kill** (**0 RAM**, 28 ms wake), **destroyed**.
- **Pause keeps RAM** because the guest's live state must stay in physical memory for instant resume. To free RAM the memory must *leave* RAM → that's what snapshot-to-disk does.
- **VMs don't cost money — the box does.** Flat ~$0.41/hr whether 0 or 350 VMs run. Keeping idle VMs on is free; it only consumes the box's RAM (~80 MB each → ~350 ceiling). To save money you stop the *box*, not the VMs.

## Density & economics (verified AWS pricing)
- `t4g.nano` (0.5 GB, the ~equivalent of a 512 MB VM) = **$0.0042/hr = $3.07/mo**. `a1.metal` = **$0.408/hr = $298/mo**.
- **Conservative (reserve full 512 MB):** ~55 VMs/box → **~$5.4/VM/mo — *more expensive than a nano*.** On AWS, metal density does NOT beat nanos unless you overcommit. (c6g/c7g.metal are worse per-VM conservatively.)
- **Aggressive levers (stack-able):**
  1. **Overcommit** (idle ≈ 80 MB): ~350/box → ~$0.85/VM/mo (3.6× cheaper than a nano).
  2. **KSM** (all VMs share the same golden image's pages): ~40 MB → ~700/box → ~$0.43/VM (7×).
  3. **Smaller VMs** (128 MB): denser still.
  4. **Snapshot dormant to disk** (28 ms wake): RAM holds only *active* VMs; disk holds thousands. Total fleet becomes **disk-bound, not RAM-bound** — the scale-to-zero model (Lambda/Fly).
- **VMs running *real* workloads** (not idle): CPU-bound ≈ **15–30** concurrent (16 cores is the wall); bursty agent/web ≈ **80–150** active, **thousands registered**. Most agent sandboxes are I/O-bound (waiting on LLM/user), so few are *hot* at once.
- **The real cost lever is the hardware, not AWS.** Hetzner-class bare metal is ~**10–15× cheaper per GB of RAM** → even conservative density ≈ **$0.45/VM/mo**, ~6× cheaper than a nano; aggressive → cents/VM.
- **The point isn't per-VM price** — it's what nanos *can't* do: **ms fork/resume + density for bursty per-agent sandboxes.**

## Gaps to product (priority order)
1. Snapshot *create* is slow (~4.6 s — full RAM → EBS); use diff snapshots / smaller RAM / local NVMe. (Resume is already 28 ms.)
2. **Single host only.** ZFS clones are host-local → a fork can't run on another box. Cross-node needs `zfs send/recv` or moving the rootfs to object storage via **JuiceFS** (and benchmarking the cache-warm boot vs this local-ZFS floor).
3. Clock/entropy kick on resume (negligible at 28 ms gaps; matters after long pauses).
4. Multi-tenant isolation (jailer/seccomp), auth/quotas, L7 ingress (`world-x → VM:port`), IP/MAC allocator.
5. Evaluate Cloud Hypervisor (better snapshot/restore + virtio-fs for JuiceFS-into-guest + live migration) for the product VMM.
