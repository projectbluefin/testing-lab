# Bluefin QA Pipeline — Runbook

> For future agents and human operators. Last updated: 2026-05-25.

## Cluster Topology

| Host | Role | IP | Specs |
|---|---|---|---|
| ghost | control-plane + primary compute | 192.168.1.102 | AMD Ryzen AI MAX+ 395, 16c/32t, 64GB RAM |
| exo-1 | worker node | 192.168.1.239 | — |
| Argo UI | — | http://192.168.1.102:2746 | Login: `kubectl exec -n argo deploy/argo-server -- argo auth token` |
| Loki | log aggregation | http://192.168.1.102:30100 | Scrapes pods with label `app.kubernetes.io/part-of=bluefin-test-suite` |

KubeVirt VMs are pinned to ghost (16-core host; exo-1 is for workflow pods only).

## Valid Bluefin Image Variants

| Tag | Image | Notes |
|---|---|---|
| `latest` | `ghcr.io/ublue-os/bluefin:latest` | Bleeding edge, tested every PR |
| `lts` | `ghcr.io/ublue-os/bluefin:lts` | Long-term support |

**`gts` does NOT exist. `lts-hwe` does NOT exist.** Do not use these tags.

## Golden Disk Location

Golden disks live on ghost at `/var/tmp/bluefin-golden/<variant>/disk.raw`.

| Variant | Path | Built | SSH key patched |
|---|---|---|---|
| `latest` | `/var/tmp/bluefin-golden/latest/disk.raw` | ✅ | ✅ |
| `lts` | `/var/tmp/bluefin-golden/lts/disk.raw` | ❌ needs rebuild | — |

### Building a Golden Disk (BIB)

Submit the `bib-build-and-push` WorkflowTemplate via Argo:
```bash
argo submit --from workflowtemplate/bib-build-and-push \
  -p image-tag=latest \
  -n argo
```

### Patching a Golden Disk (SSH key fix procedure)

Run on ghost as root. Required after any BIB rebuild:

```bash
sudo bash << 'PATCH'
PUBKEY=$(kubectl get secret bluefin-test-ssh-key -n argo \
  -o jsonpath="{.data.id_ed25519}" | base64 -d | ssh-keygen -y -f /dev/stdin)
DISK="/var/tmp/bluefin-golden/latest/disk.raw"

losetup -D; sleep 1
LOOP=$(losetup --find --partscan --show "$DISK"); sleep 1
mkdir -p /mnt/bfpatch
mount "${LOOP}p4" /mnt/bfpatch
DEPLOY=$(ls /mnt/bfpatch/ostree/deploy/default/deploy/ | head -1)
VAR="/mnt/bfpatch/ostree/deploy/default/var"
ROOT="/mnt/bfpatch/ostree/deploy/default/deploy/${DEPLOY}"

chmod 755 "${VAR}/home/bluefin-test"
mkdir -p "${VAR}/home/bluefin-test/.ssh"
echo "$PUBKEY" > "${VAR}/home/bluefin-test/.ssh/authorized_keys"
chmod 750 "${VAR}/home/bluefin-test"
chmod 700 "${VAR}/home/bluefin-test/.ssh"
chmod 600 "${VAR}/home/bluefin-test/.ssh/authorized_keys"
chown -R 1001:1001 "${VAR}/home/bluefin-test"

printf 'PermitRootLogin yes\nPasswordAuthentication no\nStrictModes no\n' \
  > "${ROOT}/etc/ssh/sshd_config.d/99-bluefin-test.conf"
chmod 600 "${ROOT}/etc/ssh/sshd_config.d/99-bluefin-test.conf"
sync
umount /mnt/bfpatch; losetup -d "$LOOP"
PATCH
```

**Critical:** always derive pubkey from the secret (`ssh-keygen -y -f`). Never hardcode it.

## SSH Key

Stored in k8s secret `bluefin-test-ssh-key` in `argo` namespace.

```bash
# Get fingerprint (to verify)
kubectl get secret bluefin-test-ssh-key -n argo \
  -o jsonpath="{.data.id_ed25519}" | base64 -d | ssh-keygen -lf /dev/stdin

# Current fingerprint (2026-05-25): SHA256:4iazqYR3lM2tOuniG4MOSERDz0+qaq12qoM/WqP5qLw
```

**Key mismatch bug:** `bib-disk-configure` in the BIB workflow may silently write the wrong key
or write it to a path that is not the runtime path. Always verify with the patch procedure above
after every disk rebuild.

## Known Bugs in bib-disk-configure

1. **Home directory permissions 777**: `mkdir -p` inside container creates home dir with 0777.
   sshd `StrictModes yes` refuses `authorized_keys` from world-writable home dirs.
   Fix: `chmod 750 "${VAR}/home/bluefin-test"` in configure script.

2. **`sshd_config.d` file permissions 666**: Written without explicit chmod.
   sshd on Fedora/RHEL rejects world-writable config drop-ins.
   Fix: `chmod 600 "${ROOT}/etc/ssh/sshd_config.d/99-bluefin-test.conf"` after writing.

3. **Authorized_keys may not be written**: Silent failure if the target path doesn't exist
   or there's a mount flush issue. Fix: add `test -f ... || exit 1` verification + `sync`.

4. **Key mismatch**: If the secret is regenerated, golden disks still have the old public key.
   No automated reconciliation exists. Always re-patch after secret rotation.

**All four bugs are tracked in castrojo/copilot-config with label `homelab`.**

## Disk Layout (BIB --type raw --rootfs ext4)

| Partition | Size | Content |
|---|---|---|
| p1 | 1MB | BIOS boot |
| p2 | 100MB | EFI |
| p3 | 1GB | /boot (ext4, BLS boot entries) |
| p4 | ~13GB | root (ext4, OSTree) |

At runtime:
- `/home` → symlink to `/var/home`
- bluefin-test user: UID 1001, GID 1001
- Authorized keys path: `/var/home/bluefin-test/.ssh/authorized_keys`

## Workflow Templates

| Template | Namespace | Purpose |
|---|---|---|
| `bib-build-and-push` | argo | Build golden disk with BIB |
| `provision-bluefin-vm` | argo | Reflink + hostDisk + KubeVirt VM |
| `provision-flatcar-vm` | argo | Prepare Flatcar disk + KubeVirt VM |
| `run-tmt-tests` | argo | SSH into VM, run tmt plan |

### Updating a WorkflowTemplate

Use the Argo MCP tool `argo-mcp-create_workflow_template`. Do NOT use
`kubernetes-mcp-resources_create_or_update` (missing `resource` arg — broken).

### Argo `outputs.result` stdout pollution

Any text printed to stdout in a `script:` template becomes the step output parameter.
ALL debug output MUST go to `>&2` or `>/dev/null`. The last line of stdout only should
be the actual output value. Pattern:
```bash
echo "debug info" >&2
printf '%s' "${RESULT_VALUE}"   # last line = output parameter
```

## Test Structure

```
tests/
  smoke/          # Phase 1: GNOME shell boot, top bar, Activities (every PR)
  developer/      # Phase 2: Ptyxis, brew, podman, micro editor
  software/       # Phase 3: Flatpak UI via gnome-software
  flatcar/        # Flatcar: systemd health, containerd, networking
```

Tests use **pytest + dogtail** (AT-SPI). NOT behave. NOT qecore.

Fixtures in `tests/developer/conftest.py` use `root.application("ptyxis")` —
this is the correct AT-SPI app name for Ptyxis on Bluefin.

## Dogtail / Wayland Setup

`gnome-ponytail-daemon` is required for AT-SPI coordinate injection on Wayland.
The `plan.fmf` `enable-ponytail` step starts it via `systemctl --user`.

**TODO (not yet implemented):** gnome-ponytail-daemon may require GNOME Shell unsafe mode:
```bash
gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
  --method org.gnome.Shell.Eval 'global.context.unsafe_mode = true'
```
This needs to be added to the `enable-ponytail` prepare step in `plan.fmf`.

## VM Cleanup

Orphaned VMs (workflow deleted but VM not cleaned up) must be deleted manually:
```bash
kubectl get vms --all-namespaces
kubectl delete vm <name> -n <namespace> --wait=false
```

Namespaces in use:
- `bluefin-test` — Bluefin VMs
- `bluefin-lts-test` — LTS VMs
- `flatcar-test` — Flatcar VMs
- `knuckle-test` — knuckle QA VMs (DO NOT DELETE — managed by knuckle-qa skill)

## Argo UI Login

```bash
# On ghost or from kubectl
kubectl exec -n argo -it deploy/argo-server -- argo auth token
# URL: http://192.168.1.102:2746
```

## Running Tests Manually

```bash
# Submit a smoke test run against latest
argo submit argo/bluefin-smoke-test.yaml \
  -p image-tag=latest \
  -p vm-name="manual-smoke-$(date +%s)" \
  -n argo

# Submit full matrix
argo submit argo/bluefin-test-matrix.yaml -n argo
```

## Iteration 2 Lessons (2026-05-25)

### dogtail 4.16 API changes

**`findChild(requireResult=...)` is GONE.** The `requireResult` kwarg was removed in dogtail 4.16.
Migrate all callers:
```python
# OLD (broken on dogtail 4.16)
node = root.findChild(pred, requireResult=True)

# NEW
results = root.findChildren(pred)
assert len(results) > 0, f"No node found matching {pred}"
node = results[0]
```

### qecore `run_and_save` — 5-second timeout rule

- **Output attribute:** `context.command_stdout` (NOT `context.last_command_output`)
- **Timeout:** 5 seconds hard limit on the subprocess. Any command that may produce large output
  MUST be bounded. Pattern for journalctl:
  ```bash
  journalctl --lines=50 -p err..emerg
  ```
  Do NOT use bare `journalctl -b` — it times out and returns empty output.

### GNOME 50.1 AT-SPI gaps

On Bluefin 44 (GNOME Shell 50.1), the top-bar panel exposes **no toggle buttons** for the clock
or system status area at any AT-SPI depth. Only `Activities` and `Show Apps` exist.

Implications:
- `@quick_settings` and `@calendar` scenarios cannot use AT-SPI to open these menus
- Fix requires one of: GNOME Shell `unsafe_mode` eval, coordinate-based click, or
  checking whether `org.gnome.desktop.interface toolkit-accessibility` is enabled
- Enable unsafe mode before AT-SPI interaction:
  ```bash
  gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
    --method org.gnome.Shell.Eval 'global.context.unsafe_mode = true'
  ```
- Tracked in castrojo/copilot-config #351, #353

### ConfigMap sync pattern (SSH-free test file updates)

To update test files on ghost's `/var/tmp/bluefin-tests` **without SSH**:
1. Encode files as base64 and create a ConfigMap with `binaryData`
2. Create a Job with a `hostPath` volume pointing to `/var/tmp/bluefin-tests`
3. Init container: `cp /etc/config/<file> /host/<file>` (ConfigMap mount → hostPath)

```yaml
# Skeleton
apiVersion: batch/v1
kind: Job
metadata:
  name: sync-test-files
  namespace: argo
spec:
  template:
    spec:
      initContainers:
        - name: sync
          image: busybox
          command: ["sh", "-c", "cp /etc/config/* /host/"]
          volumeMounts:
            - name: config
              mountPath: /etc/config
            - name: host
              mountPath: /host
      containers:
        - name: done
          image: busybox
          command: ["true"]
      restartPolicy: Never
      volumes:
        - name: config
          configMap:
            name: test-files-configmap
        - name: host
          hostPath:
            path: /var/tmp/bluefin-tests
            type: DirectoryOrCreate
```

### Artifact reading via probe pods

No persistent artifact repository is configured. Artifacts in Argo pod `/tmp/` disappear when
pods are deleted. **Titan VMs are persistent** and retain `/tmp/results/` between runs.

To read artifacts after a test run:
1. Create a probe pod with the SSH key secret mounted
2. `kubectl exec` into the probe pod
3. SSH from probe pod into titan VM (10.42.0.75 or 10.42.0.76) and `cat /tmp/results/`

```yaml
# Probe pod skeleton
apiVersion: v1
kind: Pod
metadata:
  name: probe
  namespace: argo
spec:
  containers:
    - name: probe
      image: fedora:latest
      command: ["sleep", "3600"]
      volumeMounts:
        - name: ssh-key
          mountPath: /root/.ssh
  volumes:
    - name: ssh-key
      secret:
        secretName: bluefin-test-ssh-key
        defaultMode: 0600
```

Then: `kubectl exec -n argo probe -- ssh -o StrictHostKeyChecking=no bluefin-test@10.42.0.75 cat /tmp/results/results.json`

**Note:** `podGC: OnWorkflowCompletion` keeps pods alive on FAILURE — but completed pods
reject `kubectl exec`. Use probe pod + SSH to titan instead.

---

## Common Failure Modes

| Symptom | Root cause | Fix |
|---|---|---|
| `Permission denied (publickey)` | Key mismatch or home dir 777 | Re-patch golden disk (see above) |
| `outputs.result` gets "Waiting…" string | stdout pollution in script template | All debug to `>&2` |
| Workflow times out at SSH wait | sshd_config.d has 666 permissions | chmod 600 in configure script |
| `qemu-img: command not found` | Wrong container image for Flatcar prep | Use `quay.io/fedora/fedora:latest` |
| VM stuck Terminating | KubeVirt controller race | `kubectl delete pod virt-launcher-... -n ns --force` |
| tmt-run pod Error immediately | `volumes:` inside `container:` block | Move `volumes:` to template level |

