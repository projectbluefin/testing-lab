---
name: kubevirt-vms
description: >
  KubeVirt ephemeral VM lifecycle in the testing-lab: containerDisk build,
  VM provisioning, SSH wait, teardown. Use when writing provision-vm templates,
  debugging VM boot failures, or working with KubeVirt manifests.
metadata:
  context7-sources:
    - /kubevirt/kubevirt
    - /kubevirt/user-guide
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

### 2a. Native bootc OCI boot — what is and isn't possible

**KubeVirt cannot boot a bootc OCI image directly without disk preparation.** This is a hard
constraint of the current KubeVirt architecture. Summary of what was verified:

**What the bootc OCI image contains (verified on `bluefin:testing`):**
- Kernel: `/usr/lib/modules/<version>/vmlinuz`  (e.g. `7.0.12-201.fc44.x86_64`)
- Initramfs: `/usr/lib/modules/<version>/initramfs.img`
- These paths are accessible via `KubeVirt kernelBoot.container`

**Why `kernelBoot.container` alone is not enough:**
- `kernelBoot.container` extracts kernel + initramfs from an OCI image and passes them to QEMU
  as `-kernel`/`-initrd` — it does NOT provide a root filesystem
- The bootc/ostree initramfs requires `root=UUID=<uuid>` and `ostree=/ostree/boot.1/default/<hash>/0`
  — both set by `bootc install to-disk` at disk creation time
- Without an ostree-deployed root disk the VM fails to mount `/` and panics

**Why `containerDisk` cannot use the raw bootc OCI image:**
- KubeVirt `containerDisk` expects a disk image file at `/disk/` inside the OCI image (raw or qcow2)
- A bootc OCI image contains OS filesystem layers, not a disk image — KubeVirt rejects it
- CDI `DataVolume` registry source has the same constraint

**Verified boot cmdline structure (reference for debugging):**
```
BOOT_IMAGE=(hd0,gpt3)/boot/ostree/default-<hash>/vmlinuz-7.0.12-201.fc44.x86_64
root=UUID=<disk-uuid> rw selinux=0 ostree=/ostree/boot.1/default/<hash>/0
```

**The minimum required disk prep is `bootc install to-disk`.** This can be done:
1. As a pre-built containerdisk (current: BIB pipeline → Zot → containerDisk) — schedulable on any node
2. Inline in the workflow: `bootc install to-disk /path/to/disk.raw` → `hostDisk` — ghost-local only

**Diagnosing kernel/initramfs paths in a running VM (guest-agent):**
```bash
kubectl exec -n <ns> <virt-launcher-pod> -c compute -- \
  virsh qemu-agent-command 1 \
  '{"execute":"guest-exec","arguments":{"path":"cat","arg":["/proc/cmdline"],"capture-output":true}}'
# Decode result: base64 -d <<< <out-data>
```

### 2b_btrfs. Bluefin btrfs disk layout (bootc install to-disk output)

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

KubeVirt nodes: `ghost` (control-plane, primary compute, 32 CPU, 64 GB RAM) and
`bazzite` (permanent full-time worker, 12 CPU, 30 GB RAM, k3s-agent enabled at boot).
Both have `kubevirt.io/schedulable: "true"` and virt-handler running.
No Argo global parallelism cap — Kubernetes pod scheduling (8 Gi/VM request) is the
real backpressure. ghost + bazzite fit ~11 concurrent 8 Gi VM pods before the scheduler
queues naturally.

**VM memory by image type:**
- bluefin `:testing` → 8 Gi (full GNOME + Wayland + AT-SPI + dogtail)
- bluefin-lts `:testing` → 8 Gi (same desktop stack — 4 Gi was wrong)
- LTS smoke PRs do NOT get a reduced allocation; same 8 Gi applies

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

# Step 2: start sshd.socket via QEMU guest agent (Fedora 41+ OpenSSH packaging workaround)
# Fedora 41+ ships sshd.service as a compatibility shim that NEVER auto-starts at boot.
# Only sshd.socket listens on TCP 22, and it requires explicit activation.
# Without this, SSH polls time out on every Bluefin VM.
VIRT_POD=$(kubectl get pod -n "${NS}" -l "kubevirt.io/vm=${VM}" \
  -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n "${NS}" "${VIRT_POD}" -c compute -- \
  virsh qemu-agent-command 1 \
  '{"execute":"guest-exec","arguments":{"path":"systemctl","arg":["start","sshd.socket"],"capture-output":false}}' \
  >&2 || echo "WARNING: guest-exec for sshd.socket failed, SSH poll will be the arbiter" >&2

# Step 3: wait for SSH key injection to complete
kubectl wait vmi -n "${NS}" "${VM}" \
  --for=condition=AccessCredentialsSynchronized --timeout=120s

# Step 4: get pod IP
POD_IP=$(kubectl get pod -n "${NS}" -l "kubevirt.io/vm=${VM}" \
  -o jsonpath='{.items[0].status.podIP}')

# Step 5: wait for SSH port to be open (300s is plenty once sshd.socket is started)
timeout 300 bash -c \
  "until bash -c 'echo >/dev/tcp/${POD_IP}/22' 2>/dev/null; do sleep 5; done"

# Emit IP to stdout (captured as output parameter)
echo "${POD_IP}"
```

**Common failure:** `outputs.result` contains debug text. Always send debug to `>&2`.

**RBAC requirement:** `kubectl exec` on `virt-launcher` pods requires `pods/exec` (verb: create)
on the `pods/exec` sub-resource in the VM namespace. If this is missing, the guest-agent exec
fails with `Error from server (Forbidden)` and SSH will time out. Add it to the kubevirt-manager
Role in every VM namespace (`bluefin-test`, `bluefin-lts-test`).

**Why not just `systemctl enable sshd.socket` in the image?** `systemctl enable` writes a symlink
into the OCI image's `/usr/lib/systemd/system/sockets.target.wants/`. The image does have this
symlink — but it does NOT appear in `multi-user.target.wants/`, so socket activation does not
fire until `sockets.target` is reached later in the boot ordering. The race is consistent: the
VM reports Ready before sockets.target fully activates. The explicit guest-exec start is the
reliable fix; it runs at a known point (after VMI Ready) with no race.

**Diagnosing sshd status via guest agent (for debugging):**
```bash
kubectl exec -n <ns> <virt-launcher-pod> -c compute -- \
  virsh qemu-agent-command 1 \
  '{"execute":"guest-exec","arguments":{"path":"systemctl","arg":["is-active","sshd.socket"],"capture-output":true}}'
# Then decode: base64 -d <<< <out-data value>
# "inactive" = not started, "active" = listening on TCP 22
```

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

### 13. LTS (RHEL10) VM boot — EFI fallback and fstab stalls

**Bluefin-LTS uses RHEL10 (el10) base images. They differ from Fedora in two critical
ways for KubeVirt VM boot:**

#### a. OVMF cannot find the bootloader (no `/EFI/BOOT/BOOTX64.EFI`)

KubeVirt uses OVMF with ephemeral NVRAM (no stored boot entries). OVMF falls back to the
well-known path `/EFI/BOOT/BOOTX64.EFI`. 

| Image base | EFI path created by bootc | Fallback created? |
|---|---|---|
| Fedora (bluefin:testing) | `/EFI/fedora/` | **Yes** — `bootc install` creates fallback |
| RHEL10 (bluefin-lts:testing) | `/EFI/redhat/` | **No** — fallback is missing |

**Symptom:** VM shows KubeVirt condition `Ready=True` but SSH never opens. CPU time
stays at ~40-50s over 12+ minutes (VM is idle at OVMF boot manager screen, not
executing any OS code). Screenshot pixel analysis shows cyan (0,170,170) / gray
background = VGA text mode = OVMF UI.

**Diagnosing with CPU time:**
```bash
# CPU time increasing = VM executing code (good: systemd starting)
# CPU time flat/stalled relative to wall clock = VM idle (bad: stuck at OVMF/GRUB)
kubectl get vmi -n bluefin-lts-test <vm-name> -o jsonpath='{.status.cpuTime}'
# 43s CPU in 12+ min wall clock → VM completely idle → OVMF issue
```

**Fix:** Copy the shim EFI binary to the OVMF fallback path during disk build:
```bash
# In build-containerdisk configure-disk step:
EFI_MOUNT=/mnt/efi   # mounted EFI partition
SHIM=$(find "\${EFI_MOUNT}/EFI/redhat/" -name "shim*.efi" | head -1)
if [ -n "\${SHIM}" ]; then
    mkdir -p "\${EFI_MOUNT}/EFI/BOOT"
    cp "\${SHIM}" "\${EFI_MOUNT}/EFI/BOOT/BOOTX64.EFI"
fi
```

This is already implemented in `argo/workflow-templates/build-containerdisk.yaml`. If
you are authoring a new LTS VM build pipeline, include this step.

#### b. fstab UUID mounts stall boot without a device timeout

RHEL10 bootc `install to-disk` generates `/etc/fstab` entries for `/boot` and `/boot/efi`
that reference partition UUIDs without `nofail`. In a KubeVirt VM, the EFI partition is
exposed via `virtio` — systemd sees it as a new block device. If the device is slow to
appear (race with virtio enumeration), systemd waits indefinitely.

**Fedora** fstab `/boot/efi` options: `defaults` — systemd hits its default device timeout.
**RHEL10** fstab `/boot/efi` options: `umask=0077,shortname=winnt` — no `nofail`, and the
sed pattern `/defaults/` doesn't match, leaving the stall in place.

**Symptoms:** VM boot takes 8-15+ minutes; `systemd-analyze blame` shows
`dev-disk-by\x2duuid-*.device` taking 8+ minutes (the full systemd unit activation timeout).

**Fix — two-part:**
1. Add `--karg=systemd.device-timeout=5` to the `bootc install to-disk` command.
2. Add `nofail,x-systemd.device-timeout=5s` to ALL `/boot/*` fstab entries using a
   field-aware sed (column 4 = mount options, regardless of content):

```bash
# Field-aware sed: match lines containing /boot in column 2 (whitespace-delimited),
# append ,nofail,x-systemd.device-timeout=5s to column 4 if not already present.
# This works for BOTH 'defaults' AND 'umask=0077,shortname=winnt' option strings.
sed -i '/[[:space:]]\/boot/{ /nofail/! s/^\([^[:space:]]*[[:space:]]\+\)\([^[:space:]]*[[:space:]]\+\)\([^[:space:]]*[[:space:]]\+\)\([^[:space:]]*\)/\1\2\3\4,nofail,x-systemd.device-timeout=5s/ }' /mnt/etc/fstab
```

3. Add a `DefaultDeviceTimeoutSec=5` systemd drop-in as belt-and-suspenders:
```bash
mkdir -p /mnt/etc/systemd/system.conf.d
printf '[Manager]\nDefaultDeviceTimeoutSec=5\n' > \
  /mnt/etc/systemd/system.conf.d/99-vm-device-timeout.conf
```

**Why not just `nofail` without the timeout?** `nofail` only suppresses boot failure, not
the wait. Systemd still waits for the default device timeout (90s) before giving up.
`x-systemd.device-timeout=5s` limits the wait to 5 seconds.

The `--karg` adds the timeout as a kernel argument that applies even before systemd reads
fstab. Belt-and-suspenders: karg + fstab + drop-in.

**Important:** All fstab sed must run INSIDE the build container where fstab lives at
`/mnt/etc/fstab` (the mounted disk), NOT at `/etc/fstab` (the container's fstab).

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

**The correct approach:** use the `build-containerdisk` WorkflowTemplate. It runs `bootc install to-disk`
inside the container image itself (the image is its own installer), then wraps the output as an OCI
containerDisk pushed to the local Zot registry. No golden disk file, no BIB, no osbuild.

```yaml
# Reference the build-containerdisk WorkflowTemplate directly:
templateRef:
  name: build-containerdisk
  template: build-containerdisk
arguments:
  parameters:
  - name: image-tag
    value: lts-testing
  - name: image
    value: ghcr.io/projectbluefin/bluefin-lts:testing
```

Staging disk is written to `/var/mnt/ghost-data/bluefin-cd-build/<tag>/disk.raw` during the build
and removed after the OCI image is pushed. See `argo/workflow-templates/build-containerdisk.yaml`
for the canonical implementation.

If you see the error:
```
setfiles: Regex version mismatch, expected: 10.46 actual: 10.44
```
That is the osbuild Fedora 38 runner PCRE2 mismatch. Switch to `bootc install to-disk`.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "SSH will come up on its own after VMI Ready — just poll longer." | Fedora 41+ `sshd.service` is a dead shim that never starts. No amount of polling helps. Start `sshd.socket` via guest-exec immediately after VMI Ready (section 5). |
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
- LTS VM goes `Stopped` immediately after creation — `bluefin-test-ssh-pubkey` secret missing from `bluefin-lts-test` namespace. The manifest must create the secret in **both** `bluefin-test` and `bluefin-lts-test`. Check with `kubectl get secret -n bluefin-lts-test bluefin-test-ssh-pubkey`.
- VM goes `Stopped` with `FailedCreate` and `metadata.labels: must be no more than 63 characters` — VM name exceeds Kubernetes label-value limit. `bluefin-lts-testing-developer-<36-char-uuid>` = 67 chars, fails. `smoke` (5 chars) just passes; `developer` (9 chars) overflows. Fix: use `{{workflow.name}}-{{item}}` instead of `{{workflow.parameters.variant}}-{{item}}-{{workflow.uid}}` — workflow names are short and unique. Fixed in `bluefin-qa-pipeline` commit `7fca070`.
- Orphaned VMs from a prior workflow consuming ghost resources — run `just list-vms` before submitting a new matrix run; delete orphans with `kubernetes-mcp-resources_delete` if present. Four concurrent VMs on ghost can cause VMI Ready timeouts.
- **SSH always times out with 1800s poll even though VMI is Ready** — Fedora 41+ OpenSSH packaging: `sshd.service` is a dead shim, never starts. `sshd.socket` is enabled but requires explicit activation via guest-exec. Check with `systemctl is-active sshd.socket` via guest agent; if inactive, the `wait-for-vm-ready` template is missing the guest-exec start step (section 5). The 1800s timeout is the smoke alarm, not the root cause.
- **`kubectl exec ... -c compute -- virsh qemu-agent-command` returns Forbidden** — `pods/exec` (verb: create) is missing from the kubevirt-manager Role in the VM namespace. Add it to `manifests/kubevirt-rbac.yaml` for every namespace (`bluefin-test`, `bluefin-lts-test`). RHEL10 `bootc install` only creates `/EFI/redhat/`; copy the shim to the fallback path in the build step. See section 13a.
- **LTS VM SSH never opens and CPU time grows but slowly (8-15 min boot)** — fstab `/boot` or `/boot/efi` entry missing `nofail`+`x-systemd.device-timeout=5s`. The field-aware sed in section 13b MUST cover both `defaults` and `umask=...` option strings. A simple `/defaults/ s/defaults/defaults,nofail/` won't match RHEL10's `/boot/efi` entry.
- **Field-aware fstab sed not patching `/boot/efi`** — the old sed pattern `/defaults/` doesn't match RHEL10 fstab where `/boot/efi` uses `umask=0077,shortname=winnt`. Use the column-4-aware sed from section 13b.

## Verification

Before merging any VM provisioning change:

- [ ] `wait-for-vm-ready` template starts `sshd.socket` via guest-exec (Fedora 41+ packaging); `AccessCredentialsSynchronized` wait added; SSH poll timeout ≤ 300s
- [ ] kubevirt-manager Role in EVERY VM namespace (`bluefin-test`, `bluefin-lts-test`) includes `pods/exec` (verb: create) — required for guest-exec
- [ ] hostDisk templates have `nodeSelector: kubernetes.io/hostname: ghost`; containerDisk templates float freely
- [ ] `onExit` teardown deletes VM object AND disk file
- [ ] Feature gates checked if adding a new VM capability
- [ ] `just list-vms` shows empty after workflow completion
- [ ] **All `hostPath` volume paths under `/var/mnt/ghost-data/`, never `/var/tmp`**
- [ ] No hardcoded IPs — pod IP derived at runtime via `kubectl get pod`
- [ ] Zot-writable index checked before running pipeline: `wc -c /var/mnt/ghost-data/zot-local/bluefin-containerdisk/index.json` > 100 bytes
- [ ] `bluefin-test-ssh-pubkey` secret exists in **both** `bluefin-test` and `bluefin-lts-test` namespaces
- [ ] Runtime user bootstrap sets home dir ownership (`chown 1001:1001 /var/home/bluefin-test`) before pip/pip3 installs
- [ ] **LTS containerDisk**: disk build includes `/EFI/BOOT/BOOTX64.EFI` fallback creation (section 13a)
- [ ] **LTS containerDisk**: fstab field-aware sed adds `nofail,x-systemd.device-timeout=5s` to ALL `/boot/*` entries (section 13b)
- [ ] **LTS containerDisk**: `bootc install to-disk` uses `--karg=systemd.device-timeout=5` (section 13b)
- [ ] If LTS VM Ready but SSH never opens: check CPU time diagnostic before assuming network or systemd issue

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
