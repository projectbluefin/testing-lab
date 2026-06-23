---
name: kubevirt-vms
description: >
  KubeVirt ephemeral VM lifecycle in the testing-lab: containerDisk build,
  VM provisioning, SSH wait, teardown. Use when writing provision-vm templates,
  debugging VM boot failures, or working with KubeVirt manifests.
metadata:
  context7-sources:
    - /argoproj/argo-workflows
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
skopeo inspect --tls-verify=false docker://192.168.1.102:30500/bluefin-containerdisk:testing
```

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

### 3. All test VMs pinned to ghost

Every VM and every workflow pod that touches VMs must use:

```yaml
nodeSelector:
  kubernetes.io/hostname: ghost
```

KubeVirt VMs only run on `ghost` (the node with the bare-metal disk and hardware access).
Flatcar and Knuckle workflows also pin to ghost for the same reason.

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

Golden disks live at `/var/tmp/bluefin-golden/<tag>/disk.raw` on ghost.

| Tag | Image | Disk path |
|---|---|---|
| `testing` | `ghcr.io/projectbluefin/bluefin:testing` | `/var/tmp/bluefin-golden/testing/disk.raw` |
| `lts-testing` | `ghcr.io/projectbluefin/bluefin-lts:testing` | `/var/tmp/bluefin-golden/lts-testing/disk.raw` |

`gts` and `lts-hwe` tags do NOT exist. Never use them.

The `golden-disk-gc` CronWorkflow keeps the newest disk per tag and any disk modified
in the last 14 days. GC runs weekly.

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

### 11. Golden disk build — use `bootc install to-disk`, not BIB

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
| "I can skip the `nodeSelector`." | KubeVirt VMs can only schedule on ghost. Without the selector, the pod will stay Pending. |
| "HostDisk feature gate is probably already on." | Verify with `kubectl get kubevirt kubevirt -n kubevirt -o jsonpath='{.spec.configuration}'`. Don't assume. |
| "The PCRE2 mismatch means the host needs upgrading." | BIB is fully containerized — stale cached image layer, not the host. Force-pull the image. |
| "inotify limits are a kernel concern, not a k8s concern." | KubeVirt virt-handler + containerd exhaust defaults at scale. The `inotify-tuning` DaemonSet is required. |

## Red Flags

- A provision template without `nodeSelector: kubernetes.io/hostname: ghost`
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

## Verification

Before merging any VM provisioning change:

- [ ] `nodeSelector: kubernetes.io/hostname: ghost` present on all VM-touching steps
- [ ] `onExit` teardown deletes VM object AND disk file
- [ ] Feature gates checked if adding a new VM capability
- [ ] `just list-vms` shows empty after workflow completion
- [ ] **All `hostPath` volume paths under `/var/mnt/ghost-data/`, never `/var/tmp`**
- [ ] No hardcoded IPs — pod IP derived at runtime via `kubectl get pod`
