# Bluefin Test Lab — Implementation Plan

## Timing: how long does provisioning take?

| Scenario | Time |
|---|---|
| BIB build (cold, image not cached) | ~100s |
| BIB build (warm, image in containerd cache) | ~60s |
| hostDisk reflink clone from golden disk | ~24ms |
| VM boot to GNOME Shell ready | ~3-4 min |
| **Total cold (new image tag)** | **~8-10 min** |
| **Total warm (golden disk already present)** | **~4-5 min** |

No `bootc install to-disk` at test time. BIB runs once per image tag and writes
a golden disk to `/var/tmp/bluefin-golden/<tag>/disk.raw`. Each test run
reflinks that golden disk into a per-run `hostDisk`, then boots the VM from it.

## Architecture

```
Argo Workflow / bluefin-qa-pipeline
  ├── ensure-disk (bib-build-and-push)
  │     ├── check-golden-disk   → test -f /var/tmp/bluefin-golden/<tag>/disk.raw
  │     └── bib-build           → BIB privileged pod writes golden disk on hostPath
  │                               (skipped if exists)
  │
  ├── provision-vm (provision-bluefin-vm)
  │     ├── reflink-golden-disk → cp --reflink=auto to per-run hostDisk
  │     ├── relabel-hostdisk    → chcon -t svirt_sandbox_file_t
  │     ├── create-vm           → KubeVirt VM with hostDisk root disk + cloud-init
  │     └── wait-for-vm-ready   → polls pod Ready, emits pod IP
  │
  ├── run-tests (run-gnome-tests)
  │     └── Fedora runner pod   → SSHes to VM IP
  │                               behave + qecore-headless + dogtail
  │                               gnome-ponytail-daemon bridges AT-SPI → Wayland
  │
  └── cleanup (onExit, always)
        ├── delete VM
        └── delete hostDisk clone
```

## Iteration 1 Fixes (2026-05-25)

Three root causes fixed after 20 failed matrix runs:

| Bug | Fix | Template |
|---|---|---|
| tmt runner SIGTERM (exit 143) — SSH wait 180s < VM boot time 3-4min | SSH wait 180s→600s; activeDeadlineSeconds:3600 added | run-gnome-tests |
| LTS hostDisk Permission Denied — SVirt SELinux label missing | Added `chcon -t svirt_sandbox_file_t` after reflink | provision-bluefin-vm |
| reflink-disk exit 1 — `cp --reflink=always` transient failure | Changed to `cp --reflink=auto` | provision-bluefin-vm |

Also applied: `bluefin-qa-pipeline` WorkflowTemplate (was missing from cluster).
Issues filed: castrojo/copilot-config #329–332.

## Prerequisites: what's on the cluster vs what's needed

| Item | Status |
|---|---|
| Argo Workflows | ✅ running |
| KubeVirt | ✅ running |
| RBAC: argo-kubevirt-manager ClusterRole + Binding | ✅ applied |
| WorkflowTemplate: bib-build-and-push | ✅ live |
| WorkflowTemplate: provision-bluefin-vm | ✅ live (updated) |
| WorkflowTemplate: run-gnome-tests | ✅ live |
| WorkflowTemplate: teardown-bluefin-vm | ✅ live (updated, cleans hostDisk) |
| WorkflowTemplate: bluefin-qa-pipeline | ✅ live |
| CDI | ✅ not used — hostDisk + reflink replaced CDI |
| CDI insecure registry config | ✅ not applicable — no CDI/PVC path |
| SSH secret `bluefin-test-ssh-key` | ✅ exists |
| tmt runner image | ✅ not used — runner is now behave+qecore in run-gnome-tests (Fedora container) |
| First golden disk | ✅ at `/var/tmp/bluefin-golden/{latest,lts}/disk.raw` |

## Execution order (first run)

```bash
# 1. Bootstrap SSH secret (idempotent — skip if already exists)
just setup-ssh-secret

# 2. Deploy ArgoCD Application (syncs WorkflowTemplates automatically)
just setup-argocd

# 3. Pre-build golden disk for latest tag (~100s BIB if missing)
just ensure-disk

# 4. Run smoke tests
just run-tests
```

## Subsequent runs (warm)

```bash
just run-tests          # ~4-5 min total, golden disk already present
```

## Open questions for iteration

- **Dependency install time** *(open — plan needed)*: `run-gnome-tests` installs
  `gnome-ponytail-daemon`, `qecore`, `behave`, `dogtail`, and `python-uinput` on
  every run via `dnf` + `pip` inside the live VM. Measured impact unknown but
  estimated at 5–10 min per run based on package counts. This eats the "warm run
  4–5 min" target from the timing table above.

  Options (in order of effort):
  1. **Cache in golden disk** *(best)*: Install all deps during `bib-disk-configure`
     so they are baked into `disk.raw`. Requires `ostree admin unlock` equivalent
     in BIB or a custom image layer. No per-run install cost.
  2. **Pip wheel cache on hostPath** *(medium)*: Pre-download wheels to
     `/var/tmp/pip-cache` on ghost; mount as `hostPath` in `run-gnome-tests`
     and pass `--find-links`. Halves pip time but dnf still runs.
  3. **Accept current cost** *(pragmatic)*: Measure actual wall-clock time on a
     full warm run first. If total is under 15 min, iteration velocity is
     acceptable and caching can wait.

  **Decision needed**: measure a real run before investing in caching. File an
  issue once the baseline is known.

- **gnome-ponytail-daemon COPR** *(resolved)*: Package exists in official Fedora
  repos (`dnf install -y gnome-ponytail-daemon`). No COPR or build-from-source
  needed.

- **Session timing** *(resolved)*: SSH wait is 600s in `run-gnome-tests`, covers
  3–4 min VM boot.

- **CDI pullMethod** *(resolved)*: Not applicable. CDI is no longer used;
  provisioning now uses golden disks + per-run `hostDisk` reflinks.

- **local-path + WaitForFirstConsumer** *(resolved)*: Not applicable. There is
  no CDI/PVC provisioning path in the current architecture.
