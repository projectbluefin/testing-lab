---
name: flatcar-node-onboarding
description: >
  Add a Flatcar Linux node to the k3s cluster and connect it to the Nebraska
  kernel update pipeline. Use when onboarding a new Flatcar node (e.g. exo-0,
  exo-2), joining it to k3s, or pointing update_engine at the local Nebraska
  server. Covers k3s sysext install, DaemonSet auto-configuration, and
  validating the update pipeline end-to-end.
metadata:
  context7-sources:
    - /websites/flatcar
    - /argoproj/argo-workflows
    - /kubernetes/website
---

# Flatcar Node Onboarding — testing-lab Skill

## When to Use

- Adding a new Flatcar Linux node to the k3s homelab cluster
- Flatcar node not appearing in `kubectl get nodes`
- update_engine on a Flatcar node not checking in to Nebraska
- Validating a new node's kernel update pipeline end-to-end

## When NOT to Use

- Non-Flatcar nodes (Bluefin, Bazzite, Ubuntu) → `k3s-cluster-ops.md`
- KubeVirt VM provisioning → `kubevirt-vms.md`
- Kernel build pipeline authoring → `argo-workflows.md`

---

## Core Process

### 1. Join the Flatcar node to k3s

Flatcar uses immutable `/usr` — install k3s via the official sysext approach:

```bash
# On the Flatcar node (SSH in as core):
# 1. Download the k3s sysext installer
curl -fsSL https://raw.githubusercontent.com/flatcar/sysext-bakery/main/create_sysext.sh \
  -o /tmp/create_sysext.sh

# 2. Or use the k3s installer with INSTALL_K3S_SKIP_START=true first, then:
# The canonical approach for Flatcar is the k3s-sysext image
# See: https://github.com/flatcar/sysext-bakery

# Simplest path — k3s provides a sysext-aware installer:
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_TYPE="agent" \
  INSTALL_K3S_EXEC="agent --server https://192.168.1.102:6443 --token <TOKEN>" \
  sh -
```

**Get the join token from ghost:**
```bash
kubectl get secret k3s-token -n kube-system \
  -o jsonpath='{.data.token}' | base64 -d
# Or read from ghost directly:
# cat /var/lib/rancher/k3s/server/node-token
```

**Verify join:**
```bash
kubectl get nodes -o wide | grep -i flatcar
```

### 2. update_engine auto-configures via DaemonSet

Once the node is in the cluster, the `flatcar-update-configurator` DaemonSet
automatically writes `/etc/flatcar/update.conf` pointing at Nebraska:

```
GROUP=stable
SERVER=http://192.168.1.102:30802/v1/update/
```

**Check it worked:**
```bash
# Find the configurator pod on the new node
kubectl get pods -n flatcar-update -l app=flatcar-update-configurator \
  -o wide | grep <node-name>

# Verify update.conf was written
kubectl exec -n flatcar-update <pod-name> -- \
  nsenter --target 1 --mount -- cat /etc/flatcar/update.conf
```

**Expected output:**
```
GROUP=stable
SERVER=http://192.168.1.102:30802/v1/update/
```

### 3. Verify Nebraska receives first check-in

Within 5-10 minutes of `update.conf` being written, update_engine polls Nebraska.
Check Nebraska logs for the node's first contact:

```bash
kubectl logs -n flatcar-update -l app=nebraska --tail=20 | grep "processEvent\|RegisterEvent"
```

**Expected:** `processEvent` log with appID `e96281a6-d1af-4bde-9a0a-97b76e56dc57`.
`RegisterEvent - could not get instance, maybe it is a first contact` is normal on first ping.

### 4. Wait for kernel build to register a package

Once `flatcar-kernel-build` workflow completes and registers a package with Nebraska,
update_engine will receive it on the next poll cycle (default 1h, or trigger manually).

**Check Nebraska packages:**
```bash
curl -s "http://192.168.1.102:30802/api/v1/apps/e96281a6-d1af-4bde-9a0a-97b76e56dc57/packages" \
  | python3 -m json.tool
```

### 4a. Kernel run status and failure triage (June 2026)

Current state: no successful `flatcar-kernel-build` completion over the recent 4-day window.
Most runs fail in `build-kernel` (timeout/termination) or are manually terminated while stuck.

Fast operator checks:
```bash
argo list -n argo | rg "flatcar-kernel-build" | head -n 20
argo get -n argo <latest-flatcar-kernel-build-name>
argo logs -n argo <latest-flatcar-kernel-build-name> -c main | tail -n 120
```

Known high-signal failure modes seen in this streak:
- `Pod was active on the node longer than the specified deadline` during `build-kernel`:
  workflow timeout was too short for full SDK compile+image.
- Manual `Terminated` runs while `build-kernel` was still progressing.

Current baseline for workflow timeout:
- `argo/workflow-templates/flatcar-kernel-build.yaml` uses `activeDeadlineSeconds: 21600` (6h).
- Avoid adding tighter per-step `activeDeadlineSeconds` unless measured compile time supports it.

---

## Known Flatcar Constraints

### `/etc` is overlayfs — direct writes fail

Flatcar mounts `/etc` as overlayfs over a read-only base. `hostPath` mounts of
`/etc` appear writable but writes fail:

```
/bin/sh: can't create /host/etc/flatcar/update.conf: Permission denied
```

**Fix:** Enter the host mount namespace via `nsenter`:
```bash
nsenter --target 1 --mount -- sh -c "mkdir -p /etc/flatcar && cat > /etc/flatcar/update.conf << EOF
GROUP=stable
SERVER=http://192.168.1.102:30802/v1/update/
EOF"
```

**Requirements for nsenter to work in a pod:**
- `hostPID: true` on the pod spec
- `privileged: true` in the container securityContext
- `seccompProfile: { type: Unconfined }` — Chainguard wolfi-base's default seccomp blocks `nsenter`

### Correct DaemonSet image: `cgr.dev/chainguard/wolfi-base:latest`

- `cgr.dev/chainguard/wolfi-base:latest` — has `util-linux` (nsenter), `apk`, full tooling ✅
- `cgr.dev/chainguard/wolfi-base:latest-dev` — **DOES NOT EXIST** (tag not published) ❌
- `cgr.dev/chainguard/busybox` — no nsenter, restricted seccomp blocks namespace entry ❌

### update_engine does NOT need restart after update.conf change

Send `SIGHUP` to reload config without restart:
```bash
UPDATE_ENGINE_PID=$(nsenter --target 1 --mount -- pgrep update_engine)
kill -HUP "$UPDATE_ENGINE_PID"
```

The DaemonSet does this automatically.

### Flatcar Docker is built-in — no sysext needed for SDK builds

Flatcar 4593.2.3+ ships Docker 28.0.4 natively. The Flatcar SDK's
`run_sdk_container` auto-detects and uses it. No sysext installation needed.

---

## Flatcar Image Download

**Current domain (2026):** `stable.release.flatcar-linux.net`
**Old domain (NXDOMAIN):** `stable.release.flatcar-container.net` — do not use

Images ship as **bzip2-compressed qcow2** (`.img.bz2`), not bare `.img`:

```bash
VERSION=4593.2.3
URL="https://stable.release.flatcar-linux.net/amd64-usr/${VERSION}/flatcar_production_qemu_image.img.bz2"
curl -L --fail --retry 3 -o flatcar.img.bz2 "${URL}"
bzip2 -d flatcar.img.bz2
qemu-img convert -f qcow2 -O raw flatcar.img flatcar.raw
```

---

## Nebraska Quick Reference

| Item | Value |
|---|---|
| NodePort | 30802 |
| Flatcar app UUID | `e96281a6-d1af-4bde-9a0a-97b76e56dc57` |
| Update URL (in update.conf) | `http://192.168.1.102:30802/v1/update/` |
| Auth mode | `noop` |
| Binary path in image | `/nebraska/nebraska` (no default ENTRYPOINT — must set `command:`) |
| Package version scheme | `9999.MAJOR.MINOR` (always > any stock Flatcar for semver precedence) |

**Nebraska package registration shape:**
```json
{
  "filename": "flatcar_production_update-kernel7.1.1.gz",
  "url": "http://192.168.1.102:30802/flatcar/",
  "version": "9999.7.1",
  "hash": "<SHA1 as base64>",
  "hash256": "<SHA256 hex>",
  "size": "<bytes as string>",
  "type": 1,
  "arch": 1,
  "flatcar_action": { "sha256": "<SHA256 hex>" }
}
```

**Critical:** `url` is the BASE PATH only. Nebraska constructs the full download URL
as `url + filename`. `flatcar_action.sha256` is required — update_engine rejects Omaha
responses without it.

---

## Kernel Lifecycle (3-node simple mode)

Use one update group (`GROUP=stable`) for all Flatcar nodes. Keep canary behavior as
an operational gate: **exo-0 must validate first for 24h** before the same package is
considered promoted for the rest of the cluster.

This keeps config simple while preserving staged rollout discipline.

| Key | Meaning |
|---|---|
| `candidate-version` | Kernel version currently under exo-0 canary gate |
| `candidate-package` | Nebraska package filename for the current candidate |
| `candidate-created-at` | RFC3339 timestamp when the current candidate entered the gate |
| `gate-status` | `pending`, `pass`, or `fail` for the current candidate |
| `stable-version` | Last promoted known-good kernel version |
| `stable-package` | Nebraska package filename for the last promoted stable kernel |
| `validation-marker-node` | Manual/runtime validation marker node name (`exo-0` for the canary gate fallback path) |
| `validation-marker-status` | Manual/runtime validation marker status (`pass` when no labeled workflow marker exists) |
| `validation-marker-version` | Candidate version validated by the manual/runtime marker |
| `validation-marker-created-at` | RFC3339 timestamp for the manual/runtime validation marker |

### Promotion policy

1. Build and register a new candidate package via `flatcar-kernel-build`.
2. Validate on exo-0 for 24h:
   - exo-0 remains `Ready`
   - `flatcar-update` pods remain healthy
   - one successful update/reboot validation completes on exo-0, recorded either as a labeled successful workflow or as the explicit `validation-marker-*` ConfigMap keys
3. Promote by keeping the new package as the active stable target.
4. On failure, roll back by re-pointing to the last-known-good package/version.

### Operator checks

```bash
kubectl get configmap flatcar-kernel-lifecycle-state -n argo -o yaml
argo cron list -n argo | grep flatcar-kernel-gate
argo submit -n argo --from workflowtemplate/flatcar-kernel-gate
```

### Exo-0 7.1 verification (ponytail path)

```bash
# Node kernel (cluster truth)
kubectl get node exo-0 -o jsonpath='{.status.nodeInfo.kernelVersion}{"\n"}'

# Nebraska package list (latest entries)
curl -s "http://192.168.1.102:30802/api/v1/apps/e96281a6-d1af-4bde-9a0a-97b76e56dc57/packages" | jq '.[-5:]'

# Confirm update.conf on exo-0
POD=$(kubectl get pods -n flatcar-update -l app=flatcar-update-configurator -o wide \
  | awk '/exo-0/ {print $1; exit}')
kubectl exec -n flatcar-update "$POD" -- nsenter --target 1 --mount -- cat /etc/flatcar/update.conf
```

---

## Node Addition Checklist (copy-paste for each new node)

```
[ ] Node has Flatcar Container Linux installed (any supported version)
[ ] k3s agent joined (kubectl get nodes shows new node as Ready)
[ ] flatcar-update-configurator DaemonSet pod Running on new node
[ ] kubectl exec nsenter confirms /etc/flatcar/update.conf is correct
[ ] Nebraska logs show first processEvent for this machineId
[ ] (Optional) flatcar-kernel-build workflow run to register new kernel package
[ ] exo-0 canary gate passes 24h (Ready, healthy flatcar-update pods, reboot validation)
[ ] kubectl get nodes -o wide confirms node is Running with expected kernel
```

---

## Bare-Metal Custom Kernel Builds

When the KubeVirt / Argo VM pipeline (`flatcar-kernel-build.yaml`) is blocked by resource constraints, TTY errors, or Portage overlay mapping bugs, build the custom kernel directly on a bare-metal Flatcar host (such as `exo-0`).

### Core Process

1. **Stop k3s to free resources**:
   ```bash
   sudo systemctl disable --now k3s-agent
   ```

2. **Setup workspace and clone build tools**:
   ```bash
   mkdir -p ~/work && cd ~/work
   git clone --filter=blob:none https://github.com/flatcar/scripts.git
   git clone https://github.com/projectbluefin/testing-lab.git
   cd scripts
   git checkout flatcar-4593  # Match the running Stable branch
   ```

3. **Vendor the local overlay**:
   ```bash
   OVERLAY_DST=sdk_container/src/third_party/coreos-overlay/sys-kernel
   OVERLAY_SRC=~/work/testing-lab/flatcar/kernel-overlay/sys-kernel
   rsync -av "$OVERLAY_SRC"/ "$OVERLAY_DST"/
   ```

4. **Prepare the overlay and kernel defconfig**:
   - Upstream Linux 7.1.1 compiles cleanly with an empty `UNIPATCH_LIST` inside `sys-kernel/coreos-sources-7.1.1.ebuild`. Do not include stale 6.12 patches in 7.1.1.
   - Seed a 7.1 defconfig:
     `cp sdk_container/src/third_party/coreos-overlay/sys-kernel/coreos-modules/files/amd64_defconfig-6.12 sdk_container/src/third_party/coreos-overlay/sys-kernel/coreos-modules/files/amd64_defconfig-7.1`

5. **Generate the SDK command script inside `sdk_container/tmp`**:
   The host's `sdk_container/` directory is mapped to `/mnt/host/source/` inside the container. Command files must be written under `${PWD}/sdk_container/tmp/` on the host to be visible inside the container at `/mnt/host/source/tmp/`.
   ```bash
   mkdir -p sdk_container/tmp
   cat > sdk_container/tmp/inside-sdk.sh <<'EOF'
   #!/usr/bin/env bash
   set -euo pipefail
   KVER=7.1.1
   # Patch kernel-2.eclass to accept EAPI 7/8
   ECLASS=/mnt/host/source/src/third_party/portage-stable/eclass/kernel-2.eclass
   if [ -f "$ECLASS" ] && grep -q '2|3|4|5|6)$' "$ECLASS"; then
     sudo sed -i 's/2|3|4|5|6)$/2|3|4|5|6|7|8)/' "$ECLASS"
   fi
   # Ebuild manifest and emerge
   cd /mnt/host/source/src/third_party/coreos-overlay/sys-kernel/coreos-sources
   ebuild "coreos-sources-${KVER}.ebuild" manifest
   setup_board --board=amd64-usr --default --force
   emerge-amd64-usr -v sys-kernel/coreos-sources sys-kernel/coreos-modules sys-kernel/coreos-kernel
   # Build image update payload
   /mnt/host/source/src/scripts/build_packages --board=amd64-usr
   /mnt/host/source/src/scripts/build_image --board=amd64-usr prod
   EOF
   chmod +x sdk_container/tmp/inside-sdk.sh
   ```

6. **Run the container without `-t` in background**:
   Do **not** use the TTY `-t` flag when running via `nohup` or background tasks, or docker will crash with `the input device is not a TTY` (exit code 137).
   ```bash
   ./run_sdk_container -- /mnt/host/source/tmp/inside-sdk.sh
   ```

7. **Stage and apply update**:
   The build outputs `flatcar_production_update.gz` to `../build/images/amd64-usr/developer-latest/`. Mount this to a local nginx container, append `SERVER=http://127.0.0.1:8080/` to `/etc/flatcar/update.conf`, trigger `sudo update_engine_client -update`, and reboot.

### Red Flags

- `mkdir: cannot create directory /var/home`: On Flatcar, the home directory is `/home/jorge/`, not `/var/home/jorge/`.
- `/mnt/host/source/tmp/inside-sdk.sh: No such file or directory`: Script was written to `/tmp/` on the host instead of `sdk_container/tmp/`.
- `docker run exits with status 137` on background start: Remove the `-t` TTY flag from `run_sdk_container` invocation.
- `Unable to dry-run patch unipatch failure`: Stale 6.12 patch files are missing or do not apply to 7.1. Set `UNIPATCH_LIST=""` in `coreos-sources-7.1.1.ebuild`.


---

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I can write update.conf directly via hostPath mount." | Flatcar /etc is overlayfs — writes fail silently or with Permission denied. Always use nsenter. |
| "wolfi-base:latest-dev has more tools." | That tag does not exist. wolfi-base:latest already has apk and util-linux. |
| "cgr.dev/chainguard/busybox can run nsenter." | It cannot — restricted seccomp blocks namespace entry even with privileged: true. |
| "Flatcar images are at stable.release.flatcar-container.net." | That domain is NXDOMAIN. Use stable.release.flatcar-linux.net. |
| "The image URL ends in .img." | Images are now .img.bz2. You must decompress before qemu-img convert. |

## Red Flags

- `flatcar-update-configurator` pod in `ErrImagePull` — likely wrong wolfi-base tag
- `nsenter: can't open /proc/1/ns/ipc` — pod is missing `seccompProfile: Unconfined`; use `--mount` only, not `--ipc`
- `nsenter: can't open /proc/1/ns/mnt: Permission denied` — pod predates a DaemonSet rollout with seccompProfile fix; delete the pod to respawn
- Nebraska logs show no `processEvent` after 15 min — check update.conf was actually written
- Flatcar image download returning `curl: (6) Could not resolve host` — domain changed, use flatcar-linux.net
- `bzip2: (stdin) is not a bzip2 file` — file was uncompressed qcow2 from old URL pattern

## Verification

- [ ] `kubectl get pods -n flatcar-update -o wide` shows 1 Running pod per node
- [ ] `kubectl exec <pod> -- nsenter --target 1 --mount -- cat /etc/flatcar/update.conf` shows Nebraska URL
- [ ] Nebraska logs contain `processEvent` with `appID=e96281a6-d1af-4bde-9a0a-97b76e56dc57` for the new node
- [ ] `kubectl get node exo-0 -o jsonpath='{.status.nodeInfo.kernelVersion}'` reports `7.1.x` after promotion
- [ ] `kubectl get nodes` shows node as Ready
- [ ] No pods in ErrImagePull, CrashLoopBackOff in `flatcar-update` namespace
