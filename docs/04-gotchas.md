# Gotchas & debugging log

Every real wall we hit during the PoC, the symptom, and the fix. This is the time-saver doc.

### 1. `/dev/kvm` Permission denied at InstanceStart
**Symptom:** all config PUTs succeed (204), then `InstanceStart` → `400 … Error creating KVM
object: Permission denied (os error 13)`.
**Cause:** `ubuntu` not on `/dev/kvm`'s ACL/group. `usermod -aG kvm` needs a fresh login; manual
`setfacl` gets reset by udev/logind.
**Fix:** add to `kvm` group **and** re-apply `setfacl -m u:ubuntu:rw /dev/kvm` on every launch
(baked into `boot.sh`/`snaprestore.sh`).

### 2. Pause rejected — `Invalid request method and/or path: PUT vm`
**Cause:** Firecracker pauses with **`PATCH /vm`**, not `PUT`.
**Fix:** use PATCH for VM-state changes; PUT is only for resource config.

### 3. Restored/cloned guest panics: `Cannot open root device "(null)"`
**Symptom:** kernel boots ~0.38 s then `Kernel panic … Unable to mount root fs`, VM reboots/exits.
**Cause:** the `drives/rootfs` PUT silently failed — the golden rootfs was created with `sudo`
(root-owned, mode 644), the ZFS clone inherits that, and Firecracker (running as `ubuntu`) can't
open it **read-write**, so no root device is attached.
**Fix:** `chown ubuntu: /cwpool/<fork>/rootfs.ext4` right after `zfs clone` (in `clone.sh`).

### 4. `pkill -f <name>` kills its own SSH session (exit 255)
**Symptom:** a remote command that calls `pkill -f firecracker` (or `…cw_api`, `…snaprestore.sh`)
returns 255 with no output, and the thing you meant to kill is still running.
**Cause:** `pkill -f` matches the **full command line**, and the SSH shell's own command line
contains that string → it kills itself.
**Fix:** use `pkill -x <exactname>` (process-name match) or kill by PID / by port
(`fuser -k 8080/tcp`). Bit us three times — never use `-f` with a pattern present in your command.

### 5. v1.12+ CI artifacts ship only a read-only squashfs
**Cause:** newer Firecracker CI dropped the writable `.ext4`; only `ubuntu-24.04.squashfs` remains.
**Fix:** pull the writable `ubuntu-22.04.ext4` (+ `id_rsa`) from the **v1.10** CI prefix, or convert
the squashfs to ext4 yourself.

### 6. Metal boots slowly + SSH flaps during init
**Symptom:** instance `running` but SSH refused for several minutes; status checks `initializing`.
**Fix:** poll — port 22 opens before status checks finish; just retry with a connect timeout.

### 7. Could not expose the control plane publicly (by design)
Opening EC2 `:8080` to `0.0.0.0/0` **and** an outbound `cloudflared` tunnel were both blocked by
the safety guardrail, because the control plane can spawn/exec in microVMs. Token auth is in place,
but public exposure requires explicit human authorization. See `web/README.md`.
