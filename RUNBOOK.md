# Bluefin QA Pipeline — Runbook

> For future agents and human operators. Last updated: 2026-05-25.

## GitOps Policy — Read Before Doing Anything

**No SSH to nodes.** Never SSH to ghost (192.168.1.102) or exo-1 (192.168.1.239).
All node-level operations run as privileged Argo Workflow pods. If you think you need SSH,
you need a WorkflowTemplate instead.

**No `kubectl apply` for WorkflowTemplates.** Edit the YAML in `argo/workflow-templates/`,
push to `main`, and ArgoCD auto-syncs within ~3 minutes. To force immediate sync:
```bash
just argocd-sync
```

**MCP tool usage for agents:**
| Operation | Use |
|---|---|
| Submit a workflow | Argo MCP `submit_workflow` or `just <target>` |
| Watch workflow status | Argo MCP `get_workflow` / `list_workflows` |
| Get workflow logs | Argo MCP `get_workflow_logs` |
| Update a WorkflowTemplate | Edit YAML → git push → ArgoCD syncs |
| Read cluster state | kubectl MCP or `just list-vms` / `just list-workflows` |
| Patch a golden disk | `just patch-disk [tag]` (submits `patch-golden-disk` workflow) |

**Never use `argo-mcp-create_workflow_template` for template updates** — ArgoCD owns
that reconciliation loop. MCP template creation bypasses git history and will be
overwritten on the next ArgoCD sync.

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

```bash
just ensure-disk          # latest
just ensure-disk lts      # lts
```

`bib-disk-configure` reads the SSH pubkey from the `bluefin-test-ssh-key` secret automatically
via `secretKeyRef` — no pubkey parameter needed, no SSH to node required.

### Patching an Existing Golden Disk

Use when SSH auth fails on a disk that was built before 2026-05-25, or after secret rotation:

```bash
just patch-disk           # latest
just patch-disk lts       # lts
```

This submits the `patch-golden-disk` WorkflowTemplate which runs as a privileged pod on ghost.
**Do not SSH to ghost to run the patch manually.** The workflow does the same operations.

### After Secret Rotation

If `bluefin-test-ssh-key` is regenerated, all existing golden disks have the old pubkey.
Run `just patch-disk` for each variant, then verify SSH:
```bash
just patch-disk latest
just patch-disk lts
```

## SSH Key

Stored in k8s secret `bluefin-test-ssh-key` in `argo` namespace.

```bash
# Get fingerprint (to verify)
kubectl get secret bluefin-test-ssh-key -n argo \
  -o jsonpath="{.data.id_ed25519\.pub}" | base64 -d | ssh-keygen -lf -

# Current fingerprint (2026-05-25): SHA256:4iazqYR3lM2tOuniG4MOSERDz0+qaq12qoM/WqP5qLw
```

## bib-disk-configure — Fixed Bugs (2026-05-25)

All four SSH auth bugs were fixed. Golden disks built after 2026-05-25 do not need manual patching.

| Bug | Fix |
|---|---|
| Home dir 777 — sshd StrictModes rejects it | `chmod 750` added after chown |
| sshd_config.d drop-in 666 — sshd rejects it | `chmod 600` added after write |
| authorized_keys write not verified | `test -s` check; exits 1 on empty file |
| Disk not flushed before umount | `sync` added before umount |
| pubkey read via kubectl (not in image) | Replaced with `secretKeyRef` env var |

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

**All four bugs are tracked and fixed. New issues go to castrojo/testing-lab.**

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
| `patch-golden-disk` | argo | Patch SSH auth on existing disk (no SSH to node) |
| `provision-bluefin-vm` | argo | Reflink + hostDisk + KubeVirt VM |
| `provision-flatcar-vm` | argo | Prepare Flatcar disk + KubeVirt VM |
| `run-gnome-tests` | argo | SSH into VM, run behave suite via qecore-headless |

### Updating a WorkflowTemplate

Edit `argo/workflow-templates/<name>.yaml`, commit, push to `main`.
ArgoCD (`argocd/application.yaml`) auto-syncs. To check sync state:
```bash
just argocd-status
just argocd-sync   # force immediate sync
```

**Do NOT** use `argo-mcp-create_workflow_template` or `kubectl apply -f` for template updates.
These bypass git and will be overwritten by ArgoCD.

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

Tests use **behave + qecore-headless + dogtail** (AT-SPI). NOT pytest. NOT tmt.

- `qecore-headless` starts the GNOME Wayland session and hands off to behave
- `dogtail` does AT-SPI tree traversal inside the VM
- `gnome-ponytail-daemon` bridges AT-SPI coordinates to Wayland surface coordinates
- Steps live in `tests/<suite>/features/steps/steps.py`

## Dogtail / Wayland Setup

`gnome-ponytail-daemon` is required for AT-SPI coordinate injection on Wayland.
The `run-gnome-tests` runner starts it via `qecore-headless` before handing off to behave.

**unsafe_mode is required** for GNOME Shell 50+ AT-SPI access to top-bar elements.
Add this to `environment.py` `before_all` as `subprocess.run()` AFTER qecore-headless starts:
```bash
gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
  --method org.gnome.Shell.Eval 'global.context.unsafe_mode = true'
```
**Confirmed on Bluefin 44 (GNOME Shell 50.1):** `toolkit-accessibility=true` IS set correctly;
AT-SPI gaps in the top-bar are a GNOME Shell issue, not a config issue. `unsafe_mode` is
required to expose clock/system-status nodes.

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

### dogtail 4.16 API changes — root cause + migration

**Root cause of `requireResult` TypeError:**
`findChild(self, predicate, retry=True)` declares NO `**kwargs`. The `@logging_class`
decorator in `logging.py` does strict `sig.bind(*args, **kwargs)` before the function
body runs. Any kwarg not in the signature (e.g. `requireResult`) raises `TypeError` at
the decorator level, before reaching `find_descendant`. `find_descendant(**kwargs)` does
accept `requireResult` in its allowed kwargs, but `findChild` never passes unknown kwargs
through.

**`retry=True` causes 20-second waits:** Default `findChild(pred)` uses `retry=True`
which retries ~20 times with 1s sleep when the node is not found. Use `retry=False`
for all presence-check calls to avoid 20s hangs in tests.

**Migration table:**
```python
# OLD (broken on dogtail 4.16 — TypeError at logging decorator)
node = root.findChild(pred, requireResult=True)   # TypeError
node = root.findChild(pred, requireResult=False)  # TypeError
node = root.findChild(pred)                       # works but 20s wait if missing

# NEW (correct)
# 1. Require node exists (raises SearchError if missing):
node = root.findChild(pred, retry=True)   # same as default — raises if not found

# 2. Fast fail (raises SearchError after 1 attempt, no 20s wait):
node = root.findChild(pred, retry=False)

# 3. No-raise / check-if-present (replaces requireResult=False):
nodes = root.findChildren(pred)
node = nodes[0] if nodes else None

# 4. Boolean presence check:
if root.findChildren(pred):
    ...
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
- Tracked in castrojo/testing-lab #5

### Test file delivery (git-sync, not ConfigMap)

Test files are delivered to the runner pod via the `git-sync` initContainer in
`run-gnome-tests`. It clones `castrojo/testing-lab` (depth 1) into `/workspace`
at the start of every run. No ConfigMap sync, no hostPath for test files.

To update tests: edit `tests/<suite>/`, commit, push to `main`.

### Artifact reading

`run-gnome-tests` prints `results.json` to stderr at run end (captured by Loki
and retrievable via Argo MCP `get_workflow_logs`). Titan VMs retain
`/tmp/results/` between runs — access via a future workflow step or Loki query.

**Note:** `podGC: OnWorkflowCompletion` deletes pods on success. On failure,
pods linger until TTL. Use Argo MCP `get_workflow_logs` to read results without
exec-ing into pods.

---

## Common Failure Modes

| Symptom | Root cause | Fix |
|---|---|---|
| `Permission denied (publickey)` | Key mismatch or home dir 777 | Re-patch golden disk (see above) |
| `outputs.result` gets "Waiting…" string | stdout pollution in script template | All debug to `>&2` |
| Workflow times out at SSH wait | sshd_config.d has 666 permissions | chmod 600 in configure script |
| `qemu-img: command not found` | Wrong container image for Flatcar prep | Use `quay.io/fedora/fedora:latest` |
| VM stuck Terminating | KubeVirt controller race | `kubectl delete pod virt-launcher-... -n ns --force` |
| run-gnome-tests pod Error immediately | `volumes:` inside `container:` block | Move `volumes:` to template level |

