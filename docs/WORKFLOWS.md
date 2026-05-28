# Workflow Reference

## Table of Contents
- [Pipelines](#pipelines)
  - [bluefin-qa-pipeline](#bluefin-qa-pipeline)
  - [dakota-qa-pipeline](#dakota-qa-pipeline)
  - [knuckle-qa-pipeline](#knuckle-qa-pipeline)
- [Homelab Lanes](#homelab-lanes)
- [Ghost Maintenance](#ghost-maintenance)
- [Supporting Templates](#supporting-templates)
- [Nightly Schedule](#nightly-schedule)
- [Ghost-Heavy-Compute Mutex](#ghost-heavy-compute-mutex)
- [Disk Paths](#disk-paths)
- [Resource Profiles](#resource-profiles)

## Pipelines

### bluefin-qa-pipeline
- **Purpose:** End-to-end Bluefin validation from golden disk check/build through ephemeral VM boot and GNOME test suites.
- **Parameters:** `image`, `image-tag`, `namespace`, `suites`, `variant`, `ssh-key-secret`, `branch`.
- **DAG:** `ensure-disk` → `provision` → `run-smoke` → `run-developer` → `run-software`; `onExit: teardown`.
- **Resource profile:** BIB build/configure (`bib-img-build`, `bib-disk-configure`), VM clone/boot (`reflink-disk`, `wait-for-vm-ready`), and `run-gnome-tests`.
- **Just recipe:** `run-tests`, `run-tests-tag`, `run-tests-matrix`.

### dakota-qa-pipeline
- **Purpose:** Validate Dakota BuildStream output, export/push an OCI image, convert it into a golden disk, boot an ephemeral VM, and run smoke tests.
- **Parameters:** `branch`, `variant`, `namespace`, `suites`, `ssh-key-secret`, `tests-branch`.
- **DAG:** `bst-validate` → `bst-build-export-push` → `ensure-disk` → `provision` → `run-smoke`; `onExit: teardown`.
- **Resource profile:** Dakota BST validate/build on ghost, then the same BIB + provision + `run-gnome-tests` building blocks as Bluefin.
- **Just recipe:** `run-dakota-qa` (with `run-dakota-validate` and `run-dakota-build` for subpaths).

### knuckle-qa-pipeline
- **Purpose:** Build the Knuckle installer ISO/binary, provision a blank VM, run the headless installer in-cluster, boot the installed system, rediscover SSH reachability, and run smoke tests.
- **Parameters:** `branch`, `namespace`, `suite`, `ssh-key-secret`, `tests-branch`.
- **DAG:** `clone-source` → `build-installer` → `provision-target-vm` → `boot-installer` → `wait-install-complete` → `transition-to-installed` → `discover-ip` → `run-smoke-tests`; `onExit: teardown` (`teardown-vm` → `cleanup-installer-artifacts`).
- **Resource profile:** Installer build on ghost, several small control pods for ignition/install orchestration, then `run-gnome-tests` against the installed VM.
- **Just recipe:** None currently; submit the WorkflowTemplate directly or use the nightly CronWorkflow.

## Supporting Templates

| Template | Role |
| --- | --- |
| `bib-build-and-push` | Shared golden-disk builder. `ensure-disk` runs `bib-disk-check` and, when needed, `bib-img-pull` → `bib-img-build` → `bib-disk-configure`. Default golden root is `/var/tmp/bluefin-golden`, overridden by Dakota. |
| `provision-bluefin-vm` | Shared Bluefin/Dakota VM bring-up. `reflink-disk` clones `disk.raw`, `create-vm` defines a 4 vCPU / 8 GiB KubeVirt VM, and `wait-for-vm-ready` returns the pod IP once SSH is reachable. |
| `teardown-bluefin-vm` | Shared Bluefin/Dakota/Knuckle VM cleanup. Deletes the KubeVirt VM and removes the matching hostDisk from the pipeline test root. |
| `run-gnome-tests` | Shared test runner. Clones `testing-lab`, waits for SSH, installs test dependencies in the VM, copies `tests/<suite>`, and runs `behave` (GUI suites via `qecore-headless`). |
| `run-incluster-tests` | Shared in-cluster pytest runner. Git-syncs `testing-lab`, runs a pytest module against a live k8s workload, emits JUnit XML. Used by homelab lanes. |
| `dakota-bst` | Dakota-specific build path. `bst-validate` performs a fast graph check; `bst-build-export-push` builds on ghost, pushes `192.168.1.102:5000/dakota:<tag>`, and returns `image-ref` to `dakota-qa-pipeline`. |

## Homelab Lanes

In-cluster workload validation that proves the k3s substrate, local-path
storage, and service-access model. These lanes do not require a KubeVirt VM;
they spin up ephemeral namespaced deployments on the cluster itself.

See [docs/homelab-contracts.md](homelab-contracts.md) for the full workload
matrix, RWX blocker details, storage artifact reference, and fleet-client
contract.

| Lane WorkflowTemplate | Test module | What it proves | Just recipe |
|---|---|---|---|
| `homelab-substrate` | `tests/homelab_substrate/` | k3s scheduling, in-cluster HTTP reachability, pod lifecycle | `just run-homelab-substrate` |
| `homelab-storage` | `tests/homelab_storage/` | `local-path` PVC lifecycle, data persists across restart, storage observability artifacts | `just run-homelab-storage` |
| `homelab-access-probe` | `tests/homelab_access/` | Cluster-DNS resolution, TLS handshake, SNI-based routing | `just run-homelab-access` |
| `homelab-restore-drill` | `tests/homelab_backup/` | Full backup→wipe→restore→verify cycle on a `local-path` PVC; checksum-verified sentinel recovery | `just run-homelab-restore` |

### Storage observability artifacts

`homelab-storage` emits the following artifacts to `/tmp/results/` on every run:

| Artifact | Content |
|---|---|
| `storage-pvc.json` | PVC phase, capacity, access modes, storage class |
| `storage-disk-usage.txt` | `df -h` output for the mount path |
| `storage-ownership.txt` | `stat` output for the mount directory |
| `storage-findmnt.txt` | `findmnt` output — filesystem type and mount options |
| `storage-statfs.txt` | `stat -f` output — block-level capacity |
| `storage-lsblk.txt` | `lsblk -f` — all block devices and filesystems |
| `storage-zpool.txt` | `zpool status -x` (ZFS nodes only; empty otherwise) |
| `storage-zfs.txt` | `zfs list` (ZFS nodes only; empty otherwise) |
| `storage-pods-before.json` | Pod snapshot before rollout restart |
| `storage-pods-after.json` | Pod snapshot after rollout restart |

## Ghost Maintenance

| WorkflowTemplate | Purpose | Just recipe |
|---|---|---|
| `ghost-otel-patch` | Patch ghost OTel collector config to remove noisy `process:` scraper; restarts `otelcol-agent.service` via DBUS; idempotent | `just run-otel-patch` |


## Nightly Schedule

| CronWorkflow | Time (UTC) | Pipeline | Parameters |
| --- | --- | --- | --- |
| `nightly-smoke` | 02:00 | `bluefin-qa-pipeline` | `image=ghcr.io/ublue-os/bluefin:latest`, `image-tag=latest`, `namespace=bluefin-test`, `suites=smoke,developer` |
| `nightly-smoke-lts` | 02:30 | `bluefin-qa-pipeline` | `image=ghcr.io/ublue-os/bluefin:lts`, `image-tag=lts`, `namespace=bluefin-lts-test`, `suites=smoke,developer` |
| `nightly-dakota` | 03:00 | `dakota-qa-pipeline` | `variant=default`, `branch=main`, `namespace=bluefin-test`, `suites=smoke` |
| `nightly-knuckle` | 03:30 | `knuckle-qa-pipeline` | `branch=main`, `namespace=knuckle-test`, `suite=smoke`, `tests-branch=main` |

## Ghost-Heavy-Compute Mutex

`ghost-heavy-compute` serialises the host-local heavy work that would otherwise contend on ghost CPU, memory, loop-device I/O, and shared storage.

Templates that hold it:
- `bib-build-and-push/bib-img-build`
- `bib-build-and-push/bib-disk-configure`
- `dakota-bst/bst-build-export-push`
- `knuckle-qa-pipeline/build-installer`

In practice this means Bluefin/Dakota BIB work, Dakota BST builds, and Knuckle installer builds queue instead of racing each other.

## Disk Paths

| Pipeline | Golden root | Test root | Notes |
| --- | --- | --- | --- |
| Bluefin | `/var/tmp/bluefin-golden` | `/var/tmp/bluefin-test` | Golden disk at `<golden-root>/<image-tag>/disk.raw`; reflinked VM disks at `<test-root>/<vm-name>.raw`. |
| Dakota | `/var/tmp/dakota-golden` | `/var/tmp/dakota-test` | Dakota overrides both BIB/provision paths so its OCI-derived disks stay separate from Bluefin. |
| Knuckle | N/A | `/var/tmp/knuckle-test` | Stores installer ISO, ignition, QA config, helper binary, and installed target disk under the same root. |

## Resource Profiles

Pod resource requests/limits used by workflow steps:

| Template | CPU req/limit | Memory req/limit |
| --- | --- | --- |
| `bib-disk-check` | 100m / 500m | 128Mi / 512Mi |
| `bib-img-pull` | 2 / 4 | 2Gi / 4Gi |
| `bib-img-build` | 4 / 8 | 8Gi / 16Gi |
| `bib-disk-configure` | 2 / 4 | 4Gi / 8Gi |
| `reflink-disk` | 100m / 500m | 128Mi / 512Mi |
| `wait-for-vm-ready` | 100m / 500m | 128Mi / 256Mi |
| `run-gnome-tests` | 1 / 2 | 1Gi / 2Gi |
| `delete-hostdisk` | 50m / 200m | 64Mi / 128Mi |
| `dakota-bst-validate` | 2 / 2 | 4Gi / 4Gi |
| `dakota-bst-build-export-push` | 24 / 24 | 48Gi / 48Gi |
| `knuckle resolve-source` | 100m / 500m | 128Mi / 256Mi |
| `knuckle build-installer` | 4 / 4 | 8Gi / 8Gi |
| `knuckle write-ignition` | 100m / 500m | 128Mi / 256Mi |
| `knuckle prepare-target-disk` | 500m / 2 | 512Mi / 2Gi |
| `knuckle boot-installer` | 1 / 2 | 1Gi / 2Gi |
| `knuckle wait-install-complete` | 250m / 1 | 256Mi / 512Mi |
| `knuckle transition-to-installed` | 250m / 1 | 256Mi / 512Mi |
| `knuckle discover-installed-ip` | 250m / 1 | 256Mi / 512Mi |
| `knuckle cleanup-installer-artifacts` | 50m / 200m | 64Mi / 128Mi |
