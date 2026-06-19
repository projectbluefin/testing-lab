---
name: kubevirt-vms
description: >
  KubeVirt ephemeral VM lifecycle in the testing-lab: golden disk, btrfs
  reflink clone, VM provisioning, SSH wait, teardown. Use when writing
  provision-vm templates, debugging VM boot failures, or working with
  KubeVirt manifests.
metadata:
  context7-sources:
    - /argoproj/argo-workflows
---

# KubeVirt VMs — testing-lab Skill

## When to Use

- Editing `provision-vm.yaml`, `provision-variant-vm.yaml`, `provision-flatcar-vm.yaml`
- Debugging VM boot timeouts or SSH readiness failures
- Adding a new image variant (new golden disk path, new namespace)
- Enabling a new KubeVirt feature gate
- Understanding why a VM is stuck `Terminating`

## When NOT to Use

- Argo Workflows YAML syntax issues → `argo-workflows.md`
- GNOME/behave test failures → `test-authoring.md`
- ArgoCD sync problems → `gitops-argocd.md`

## Core Process

### 1. The golden disk + reflink model

```
/var/tmp/bluefin-golden/<tag>/disk.raw        ← built once by bib-build-and-push
        │
        │  btrfs reflink (~24ms, CoW, ~0 extra disk)
        ▼
/var/tmp/bluefin-test/<vm-name>.raw           ← per-run ephemeral clone
        │
        │  KubeVirt HostDisk hostPath mount
        ▼
KubeVirt VM (VirtualMachineInstance)          ← boots in ~60-90s, torn down on exit
```

**Critical:** both paths must be on the same btrfs volume for reflink to work:
```bash
stat --file-system --format=%T /var/tmp   # must output: btrfs
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

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll keep the VM up between runs to save time." | No persistent test VMs. The `orphan-vm-cleanup` CronWorkflow will delete it. |
| "The teardown step can be optional." | A missing `onExit` handler leaks VMs and disk clones on failure. Always required. |
| "I can skip the `nodeSelector`." | KubeVirt VMs can only schedule on ghost. Without the selector, the pod will stay Pending. |
| "HostDisk feature gate is probably already on." | Verify with `kubectl get kubevirt kubevirt -n kubevirt -o jsonpath='{.spec.configuration}'`. Don't assume. |

## Red Flags

- A provision template without `nodeSelector: kubernetes.io/hostname: ghost`
- An `onExit` handler that doesn't delete both the VM object AND the disk file
- Using `gts` or `lts-hwe` as image tags (they don't exist)
- VMs in namespaces other than the four test namespaces
- Hardcoded IPs in VM templates (use pod IP from `kubectl get pod -l kubevirt.io/vm=...`)
- A `wait-for-vm` step that writes debug text to stdout (breaks output parameter capture)

## Verification

Before merging any VM provisioning change:

- [ ] `nodeSelector: kubernetes.io/hostname: ghost` present on all VM-touching steps
- [ ] `onExit` teardown deletes VM object AND disk file
- [ ] Feature gates checked if adding a new VM capability
- [ ] `just list-vms` shows empty after workflow completion
- [ ] Golden disk path matches the `AGENTS.md` image variants table
- [ ] No hardcoded IPs — pod IP derived at runtime via `kubectl get pod`
