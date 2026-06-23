---
name: kubevirt-vms
description: >
  KubeVirt ephemeral VM lifecycle in the testing-lab: containerDisk build,
  VM provisioning, SSH wait, teardown. Use when writing provision-vm templates,
  debugging VM boot failures, or working with KubeVirt manifests.
metadata:
  context7-sources:
    - /kubevirt/kubevirt
    - /kubevirt/containerized-data-importer
---

# KubeVirt VMs — testing-lab Skill

## When to Use

- Editing `provision-bluefin-vm.yaml`, `provision-flatcar-vm.yaml`, `knuckle-qa-pipeline.yaml`
- Debugging VM boot timeouts or SSH readiness failures
- Adding a new image variant
- Enabling a new KubeVirt feature gate
- Understanding why a VM is stuck `Terminating`

## When NOT to Use

- Argo Workflows YAML syntax issues → `argo-workflows.md`
- GNOME/behave test failures → `test-authoring.md`
- ArgoCD sync problems → `gitops-argocd.md`

## Core Process

### 1. Disk placement — all VM data goes on ghost-data SSD

Ghost has two storage devices:
- `/dev/nvme0n1p3` → mounted at `/var` — OS partition (~1.9T, **do not fill**)
- `/dev/sdb` → mounted at `/var/mnt/ghost-data` — data SSD (~1.9T, use this for VM disks)

**Rule: all VM disk files and build staging MUST live under `/var/mnt/ghost-data/`.**
Putting VM disk images on `/var/tmp` (nvme) will fill the OS partition and trigger
kubelet disk-pressure, evicting all pods and crashing the cluster.

| Pipeline | Disk storage location |
|---|---|
| Bluefin containerDisk build staging | `/var/mnt/ghost-data/bluefin-cd-build/` |
| Flatcar hostDisk clones | `/var/mnt/ghost-data/flatcar-test/` |
| Knuckle hostDisk clones | `/var/mnt/ghost-data/knuckle-test/` |
| GnomeOS hostDisk clones | `/var/mnt/ghost-data/gnomeos-test/` |
| LLM model cache | `/var/mnt/ghost-data/llm-models/` |

**Never use `/var/tmp` for VM disk files.** It is on the nvme OS partition.

### 2. Bluefin VM model — containerDisk (no hostDisk files)

Bluefin test VMs use KubeVirt `containerDisk` — an OCI image containing the qcow2
disk image, stored in the local Zot registry. No reflink, no hostDisk, no golden disk.

```
build-containerdisk (build-containerdisk.yaml)
  ├─ check       — skopeo: exists in 192.168.1.102:30500/bluefin-containerdisk:<tag>?
  ├─ install-to-disk  — podman run bootc install to-disk → /mnt/ghost-data/bluefin-cd-build/<tag>/disk.raw
  ├─ configure-disk   — inject test user, SSH, GDM autologin, sudoers, selinux=0
  └─ convert-and-push — qemu-img raw→qcow2, buildah OCI wrap, push to zot:30500
         │
provision-bluefin-vm (provision-bluefin-vm.yaml)
  └─ VM boots from containerDisk: 192.168.1.102:30500/bluefin-containerdisk:<tag>
```

Check if a containerDisk exists:
```bash
# Fast check — 0 bytes = image lost, rebuild required
ssh ghost "wc -c /var/mnt/ghost-data/zot-local/bluefin-containerdisk/index.json"
# Full check
skopeo inspect --tls-verify=false docker://192.168.1.102:30500/bluefin-containerdisk:testing
```

**Zot data loss:** The `zot-writable` pod (port 30500) loses its `index.json` on every pod or
k3s restart — the manifest index goes to 0 bytes even though blobs may still exist. Always
check before running the pipeline; rebuild if the index is empty.

### 2a. Bluefin btrfs disk layout (bootc install to-disk output)

`bootc install to-disk` creates:
- `p1` = BIOS boot (1M)
- `p2` = EFI (512M)
- `p3` = btrfs root (14.5G)

**`btrfs subvolume list` returns EMPTY** — there are NO named btrfs subvolumes in a
bootc-installed Bluefin disk. Mount the toplevel with no `subvol=` option:
```bash
mount -t btrfs ${LOOP}p3 /mnt/btroot
```

The ostree deployment structure at boot:
- `/etc` is bind-mounted from `ostree/deploy/default/deploy/<hash>.0/etc/` (btrfs)
- `/var` is the real content at `ostree/deploy/default/var/` (btrfs, NOT a subvolume)
- `/` is composefs overlay (read-only lower layer from image)

**Post-install etc/ injection caveat (ostree 3-way merge):**
Files that already exist in the image's `usr/etc/` (e.g. `sshd_config.d/10-test.conf`,
`sshd_config`) get RESET to image content at first boot by the ostree merge.
NEW files added to `deploy/.../etc/` (e.g. `etc/passwd` entries, `etc/sudoers.d/`,
`etc/gdm/custom.conf`) survive if they have no counterpart in the image's `usr/etc/`.

**Do not rely on disk injection for SSH keys.** Use KubeVirt accessCredentials instead
(see section 2b). Even `var/` writes confirmed by VERIFY may not survive the
qemu-img raw→qcow2 conversion (sparse block allocation issue).

### 2b. SSH key injection — use KubeVirt accessCredentials (canonical pattern)

**Never bake SSH keys into the disk image.** Use KubeVirt's native mechanism:

```yaml
# In the VirtualMachine spec:
spec:
  template:
    spec:
      accessCredentials:
        - sshPublicKey:
            source:
              secret:
                secretName: bluefin-test-ssh-pubkey
            propagationMethod:
              qemuGuestAgent:
                users:
                  - root
```

The secret must exist in the **same namespace as the VM** (e.g. `bluefin-test`) and
contain only the public key value:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: bluefin-test-ssh-pubkey
  namespace: bluefin-test
type: Opaque
data:
  key: <base64 of "ssh-ed25519 AAAA...">
```

KubeVirt virt-controller injects the key via QEMU guest agent after the VM boots.
The VM must have `qemu-guest-agent` running (Bluefin has it). No disk modifications needed.
The key is visible to sshd within seconds of the QEMU guest agent starting.

**Requirements:** KubeVirt v1.8+ (confirmed present), qemu-guest-agent in VM (confirmed).
**Why not disk injection:** ostree resets etc/ files that exist in usr/etc/ at first boot;
var/ writes may not survive qemu-img sparse conversion.

### 2c. Runtime user creation (more reliable than disk injection)

Even if `bluefin-test` user was added to `etc/passwd` during disk build, never assume
the home directory has correct ownership. Create the user and home directory at runtime
via root SSH immediately after root SSH is confirmed working:

```bash
# In the test runner, after root SSH is ready:
ROOT_SSH "
  # Create user if not present (uid 1001, wheel group)
  id bluefin-test &>/dev/null || \
    useradd -m -u 1001 -g 1001 -G wheel -s /bin/bash \
      -d /var/home/bluefin-test bluefin-test
  # Always fix home dir ownership — install -d creates parent dirs as root
  mkdir -p /var/home/bluefin-test
  chown 1001:1001 /var/home/bluefin-test
  chmod 750 /var/home/bluefin-test
  # Set sudoers
  echo 'bluefin-test ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/bluefin-test
  chmod 440 /etc/sudoers.d/bluefin-test
  # Set up SSH keys
  install -d -m 700 -o 1001 -g 1001 /var/home/bluefin-test/.ssh
  echo '${SSH_PUBKEY}' > /var/home/bluefin-test/.ssh/authorized_keys
  chown 1001:1001 /var/home/bluefin-test/.ssh/authorized_keys
  chmod 600 /var/home/bluefin-test/.ssh/authorized_keys
"
```

**IMPORTANT:** `install -d -m 700 -o 1001 -g 1001 /var/home/bluefin-test/.ssh` creates
`.ssh` with the right mode/owner BUT creates the PARENT `/var/home/bluefin-test/` as
root:root (mode 755). This makes pip install --user fail with EACCES when trying to
create `.local`. Always explicitly `chown 1001:1001 /var/home/bluefin-test` after.

### 2. Required KubeVirt feature gates

Two feature gates must be enabled in the `kubevirt` CR. If VM creation fails with
`feature gate is not enabled in kubevirt-config`, this is cluster drift — fix via GitOps:

```bash
kubectl patch kubevirt kubevirt -n kubevirt --type=merge --patch='
{
  "spec": {
    "configuration": {
      "developerConfiguration": {
        "featureGates": ["HostDisk", "ExperimentalIgnitionSupport"]
      }
    }
  }
}'
```

Persist this in `manifests/` so ArgoCD maintains it.

### 3. VM node scheduling

**containerDisk VMs** (Bluefin test VMs) do NOT need to be pinned to ghost. They use
OCI images from the local Zot registry and have no hostPath dependency. They can run on
any KubeVirt-capable node (ghost or bazzite).

```yaml
# containerDisk VM — no nodeSelector needed; floats to ghost or bazzite
spec:
  domain:
    devices:
      disks:
        - name: containerdisk
          disk: {}
  volumes:
    - name: containerdisk
      containerDisk:
        image: 192.168.1.102:30500/bluefin-containerdisk:testing
```

**hostDisk VMs** (Flatcar, Knuckle, GnomeOS) MUST pin to ghost because hostPath files
are only accessible on ghost:

```yaml
nodeSelector:
  kubernetes.io/hostname: ghost
```

KubeVirt nodes: `ghost` (control-plane, primary compute) and `bazzite` (worker, 12 CPU, 30GB RAM).
Both have `kubevirt.io/schedulable: "true"` and virt-handler running.

### 4. hwprofile: standard vs full-hw

`provision-variant-vm` supports two hardware profiles:

```yaml
- name: hw-profile
  value: standard    # default: no TPM, no watchdog
# or
- name: hw-profile
  value: full-hw     # adds TPM 2.0, ich9 audio, i6300esb watchdog (for hardware-suite tests)
```

Use `full-hw` only when the test explicitly requires hardware attestation or watchdog behavior.

### 5. SSH readiness wait pattern

The canonical way to wait for a VM to be SSH-accessible:

```bash
# Step 1: wait for VMI Ready condition
kubectl wait vmi -n "${NS}" "${VM}" \
  --for=condition=Ready --timeout=600s

# Step 2: get pod IP (virt-launcher pod IP = VM network interface)
POD_IP=$(kubectl get pod -n "${NS}" -l "kubevirt.io/vm=${VM}" \
  -o jsonpath='{.items[0].status.podIP}')

# Step 3: wait for SSH port to be open
timeout 120 bash -c \
  "until bash -c 'echo >/dev/tcp/${POD_IP}/22' 2>/dev/null; do sleep 5; done"

# Emit IP to stdout (captured as output parameter)
echo "${POD_IP}"
```

**Common failure:** `outputs.result` contains debug text. Always send debug to `>&2`.

### 6. Teardown — always via onExit, never skip

Every pipeline must include an `onExit` teardown that:
1. Deletes the KubeVirt VM object: `kubectl delete vm "${VM}" -n "${NS}"`
2. Deletes the reflinked disk file: `rm -f "${DISK_PATH}"`

The teardown template must also be pinned to ghost (it deletes a hostPath file).

Orphaned VMs (from force-deleted workflows) are cleaned by the `orphan-vm-cleanup`
CronWorkflow every 2 hours.

### 7. VM namespaces

| Variant | Namespace |
|---|---|
| `latest` | `bluefin-test` |
| `lts` | `bluefin-lts-test` |
| Flatcar | `flatcar-test` |
| Knuckle installer | `knuckle-test` |

Never create VMs in `argo` or `argocd` namespaces.

### 8. Checking for stuck VMs

```bash
just list-vms
# Expected output when idle: empty (no VMs)
```

If VMs are stuck `Terminating`:
```bash
# Delete the virt-launcher pod and let reconciliation finish
kubectl delete pod -n <namespace> -l kubevirt.io/vm=<vm-name> --force
```

### 9. Golden disk management

Bluefin VMs no longer use golden disk hostPath files. They use `containerDisk` (OCI image).
The disk build pipeline is `build-containerdisk` — see section 2 above.

For Flatcar/Knuckle/GnomeOS variants that still use hostDisk, disk files live under
`/var/mnt/ghost-data/<variant>/` on ghost. Never `/var/tmp`.

`gts` and `lts-hwe` tags do NOT exist. Never use them.

### 10. Node inotify limits — required for KubeVirt

KubeVirt virt-handler, containerd, and podman together consume thousands of inotify
watches. When exhausted, VM boot fails silently (SSH never becomes ready) and container
errors appear. The `inotify-tuning` DaemonSet in `manifests/` raises limits on all nodes:

```
fs.inotify.max_user_watches=1048576
fs.inotify.max_user_instances=512
```

If you see VM boot timeouts that aren't explained by disk or network issues, check:
```bash
cat /proc/sys/fs/inotify/max_user_watches   # should be >= 1048576
```

The DaemonSet applies this on every node restart. Do not remove it.

### 12. Cross-policy LTS containerDisk builds — fsetxattr EINVAL

When building the LTS containerDisk on a bluefin (non-LTS) ghost host, `bootc install to-disk`
fails with:
```
fsetxattr(security.selinux): Invalid argument
```

**Root cause:** The LTS image contains SELinux file labels (types like `container_t`, etc.) not
present in the host's in-memory SELinux policy. The kernel's `selinux_inode_setxattr` returns
`EINVAL` for unknown types. This is only absorbed if `has_cap_mac_admin()` returns true, which
requires both CAP_MAC_ADMIN (satisfied by `--privileged`) AND an SELinux AVC check for
`capability2 { mac_admin }` in the process's SELinux type.

**Why `seLinuxOptions.type=spc_t` does not fix it:** k3s/containerd assigns
`unconfined_service_t` to ALL containers regardless of `seLinuxOptions`. Confirmed via
`/proc/self/attr/current` diagnostic.

**Why `--security-opt label=type:spc_t` does not fix it:** Same — k3s/containerd overrides
the SELinux type to `unconfined_service_t` for privileged containers.

**Actual fix — LD_PRELOAD wrapper:**
Compile a tiny `fsetxattr` interceptor in the outer container (before running podman). Mount it
into the inner container via a dedicated bind mount. The wrapper converts `EINVAL` → `0` for
`security.*` xattrs, silently dropping unknown labels. The installed VM boots with `selinux=0`
so missing xattrs are irrelevant.

```bash
# In the outer script (quay.io/podman/stable which has dnf):
dnf install -y gcc glibc-devel 2>&1 | tail -2
mkdir -p /tmp/bluefin-cd-preload
printf '%s\n' \
  '#define _GNU_SOURCE' '#include <dlfcn.h>' '#include <string.h>' \
  '#include <errno.h>' '#include <stddef.h>' \
  'typedef int (*fn_t)(int,const char*,const void*,size_t,int);' \
  'int fsetxattr(int fd,const char*n,const void*v,size_t s,int f){' \
  '  static fn_t real;' \
  '  if(!real)real=(fn_t)dlsym(RTLD_NEXT,"fsetxattr");' \
  '  int r=real(fd,n,v,s,f);' \
  '  if(r==-1&&errno==EINVAL&&n&&strncmp(n,"security.",9)==0){errno=0;return 0;}' \
  '  return r;}' > /tmp/fsetxattr_wrap.c
gcc -shared -fPIC -o /tmp/bluefin-cd-preload/fsetxattr_wrapper.so /tmp/fsetxattr_wrap.c -ldl
chcon -t lib_t /tmp/bluefin-cd-preload/fsetxattr_wrapper.so 2>/dev/null || true

# In the podman run command:
podman run --rm --privileged ... \
  -e LD_PRELOAD=/preload/fsetxattr_wrapper.so \
  -v /tmp/bluefin-cd-preload:/preload \
  ... ${IMAGE} bash -c "bootc install to-disk ..."
```

**Important notes:**
- Compile to `/tmp/bluefin-cd-preload/` (outer container tmpfs), NOT to the staging hostPath.
  Files on the hostPath (`/mnt/staging/`) get a SELinux file label (`svirt_sandbox_file_t`)
  that blocks ld.so in the inner container.
- Use `chcon -t lib_t` to ensure the .so has a loadable label.
- The `ld.so: cannot be preloaded` error at container startup is a red herring — it fires
  before mounts are set up for the bash entrypoint, but the wrapper IS loaded correctly when
  `bootc` exec's later.
- `ENOTSUP` (not `EINVAL`) means the wrapper loaded but the LTS ostree version doesn't skip
  ENOTSUP in all paths. Solution: return `0` (noop success) instead of `ENOTSUP`.

See `argo/workflow-templates/build-containerdisk.yaml` for the canonical implementation.



**Do not use `bootc-image-builder` (BIB) for bluefin/bluefin-lts golden disk builds.**

BIB invokes osbuild internally, which spawns a Fedora 38 runner chroot to execute
build stages (`org.osbuild.selinux`). That runner's `setfiles` is linked against
PCRE2 10.44, but bluefin images ship SELinux `.bin` policy files compiled for PCRE2 10.46+.
This mismatch breaks every time the Fedora base advances. BIB has no way to override
the internal runner version.

**The correct approach:** the bootc image IS the installer.

```yaml
container:
  image: "ghcr.io/projectbluefin/bluefin-lts:testing"  # the real image
  securityContext:
    privileged: true
    runAsUser: 0
  nodeSelector:
    kubernetes.io/hostname: ghost
  command: [bash, -c]
  args:
  - |
    mkdir -p /var/tmp/bluefin-golden/lts-testing
    truncate -s 40G /var/tmp/bluefin-golden/lts-testing/disk.raw
    bootc install to-disk \
      --generic-image \
      --skip-fetch-check \
      /var/tmp/bluefin-golden/lts-testing/disk.raw
    chown 107:107 /var/tmp/bluefin-golden/lts-testing/disk.raw
    chcon -t svirt_sandbox_file_t /var/tmp/bluefin-golden/lts-testing/disk.raw 2>/dev/null || true
```

- No osbuild, no runner chroot, no PCRE2 version mismatch — ever
- The image installs itself; all binaries are internally consistent
- Build time: ~12 min (vs ~5 min BIB, but BIB was broken)
- Cache hit: unchanged — reflink still ~1 sec

If you see the error:
```
setfiles: Regex version mismatch, expected: 10.46 actual: 10.44
```
That is the osbuild Fedora 38 runner PCRE2 mismatch. Switch to `bootc install to-disk`.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll keep the VM up between runs to save time." | No persistent test VMs. The `orphan-vm-cleanup` CronWorkflow will delete it. |
| "The teardown step can be optional." | A missing `onExit` handler leaks VMs and disk clones on failure. Always required. |
| "containerDisk VMs must pin to ghost." | Only hostDisk VMs need ghost. ContainerDisk VMs can schedule on bazzite too. |
| "The zot image from yesterday is still there." | Zot-writable loses its index.json on pod restart. Always check before running the pipeline. |
| "HostDisk feature gate is probably already on." | Verify with `kubectl get kubevirt kubevirt -n kubevirt -o jsonpath='{.spec.configuration}'`. Don't assume. |
| "The PCRE2 mismatch means the host needs upgrading." | BIB is fully containerized — stale cached image layer, not the host. Force-pull the image. |
| "inotify limits are a kernel concern, not a k8s concern." | KubeVirt virt-handler + containerd exhaust defaults at scale. The `inotify-tuning` DaemonSet is required. |
| "Writing to /mnt/btroot/var/ injects SSH keys into the live system." | `btrfs subvolume list` returns EMPTY for bootc disks — there are no named subvolumes. But disk injection is still unreliable: use KubeVirt accessCredentials instead. |
| "Baking SSH keys into the disk is reliable." | ostree resets etc/ files that exist in image's usr/etc/ at first boot. var/ writes may not survive qemu-img sparse conversion. Use accessCredentials. |
| "The home directory is writable after install -d creates .ssh." | `install -d` creates parent dirs as root:root. Must explicitly chown/chmod the home dir after, or pip install --user fails with EACCES. |

## Red Flags

- A hostDisk provision template without `nodeSelector: kubernetes.io/hostname: ghost`
- An `onExit` handler that doesn't delete both the VM object AND the disk file
- Using `gts` or `lts-hwe` as image tags (they don't exist)
- VMs in namespaces other than the four test namespaces
- Hardcoded IPs in VM templates (use pod IP from `kubectl get pod -l kubevirt.io/vm=...`)
- **Any `hostPath` pointing to `/var/tmp` for VM disks** — use `/var/mnt/ghost-data/` instead
- A `wait-for-vm` step that writes debug text to stdout (breaks output parameter capture)
- `registry.k8s.io/kubectl` used as image for a step that needs bash — it is distroless, use `cgr.dev/chainguard/kubectl:latest-dev`
- SSH wait using `nc -z` — `nc` is not available in distroless or minimal images; use `bash -c 'echo >/dev/tcp/${IP}/22'`
- VM boot timeout with no disk or network explanation — check `cat /proc/sys/fs/inotify/max_user_watches` (should be >= 1048576)
- Using BIB (`bib-build-and-push`) for bluefin/bluefin-lts builds — BIB's osbuild Fedora 38 runner has a PCRE2 mismatch with current bluefin images. Use `bootc install to-disk` instead.
- `fsetxattr(security.selinux): Invalid argument` during LTS containerDisk build — `unconfined_service_t` lacks `capability2 mac_admin`; neither `seLinuxOptions` nor `--security-opt` can override the k3s-assigned type. Use the LD_PRELOAD fsetxattr wrapper (section 12).
- `fsetxattr(security.selinux): Operation not supported` during LTS build — wrapper loaded but returning ENOTSUP; change wrapper to return 0 (noop) instead so ostree version mismatch doesn't matter.
- SSH `Permission denied (publickey)` after configure-disk — **do not debug disk injection further**; switch to KubeVirt accessCredentials with qemuGuestAgent (section 2b).
- Using disk injection for SSH keys when accessCredentials is available — disk injection is fragile; accessCredentials is the canonical KubeVirt pattern.
- `pip install --user` failing with EACCES inside VM — home directory owned by root; always chown after `install -d .ssh` (section 2c).

## Verification

Before merging any VM provisioning change:

- [ ] hostDisk templates have `nodeSelector: kubernetes.io/hostname: ghost`; containerDisk templates float freely
- [ ] `onExit` teardown deletes VM object AND disk file
- [ ] Feature gates checked if adding a new VM capability
- [ ] `just list-vms` shows empty after workflow completion
- [ ] **All `hostPath` volume paths under `/var/mnt/ghost-data/`, never `/var/tmp`**
- [ ] No hardcoded IPs — pod IP derived at runtime via `kubectl get pod`
- [ ] Zot-writable index checked before running pipeline: `wc -c /var/mnt/ghost-data/zot-local/bluefin-containerdisk/index.json` > 100 bytes
- [ ] SSH injection uses KubeVirt accessCredentials (not disk injection) — `bluefin-test-ssh-pubkey` secret exists in VM namespace
- [ ] Runtime user bootstrap sets home dir ownership (`chown 1001:1001 /var/home/bluefin-test`) before pip/pip3 installs

### Bluefin containerDisk SSH injection checklist (DO NOT USE DISK INJECTION)

**The correct approach is KubeVirt accessCredentials (section 2b), not disk injection.**
The checklist below is for diagnosing legacy disk injection failures only.

When debugging `Permission denied (publickey)`:
1. Confirm accessCredentials is in the VM spec: `kubectl get vm -n bluefin-test <name> -o yaml | grep -A15 accessCredentials`
2. Confirm the secret exists: `kubectl get secret -n bluefin-test bluefin-test-ssh-pubkey`
3. Check virt-controller logs for key injection: `kubectl logs -n kubevirt -l kubevirt.io=virt-controller | grep -i 'access\|credential\|authorized'`
4. Confirm qemu-guest-agent is running in VM (required for injection to work)

**Known disk injection failure modes (do not try to fix these — use accessCredentials):**
- `sshd_config.d/` files reset at boot: ostree restores files that exist in image's `usr/etc/`
- `var/` writes missing from running VM: qemu-img sparse conversion may drop newly-written btrfs blocks
- `authorized_keys` baked into disk missing from VM: same cause as above
