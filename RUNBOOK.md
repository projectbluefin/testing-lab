# Bluefin QA Pipeline — Runbook

> Timeless architecture and failure-mode reference. For commands see [docs/agent-cheatsheet.md](docs/agent-cheatsheet.md). For long-form operator procedures see [docs/lab-operations.md](docs/lab-operations.md).

## Architecture summary

```
Git push / manual submit
        │
        ▼
Argo Workflow (argo namespace)
        │
        ├─ build-containerdisk    ─► containerDisk in local Zot registry (digest-checked)
        ├─ provision-bluefin-vm   ─► boot KubeVirt VM from containerDisk
        ├─ run-gnome-tests        ─► runner pod SSHes VM, executes qecore + behave
        └─ teardown (onExit)      ─► delete VM (always runs, success or failure)
```

All pipelines use ephemeral VMs — every run provisions a fresh VM and tears it down on exit. There are no persistent test VMs.

## Cluster topology

| Host | Role | IP | Notes |
|---|---|---|---|
| ghost | k3s control-plane + KubeVirt compute | 192.168.1.102 | Runs VM workloads and Argo control-plane services |
| exo-1 | k3s worker | 192.168.1.239 | Workflow pods only |
| bazzite | k3s worker | 192.168.1.223 | Gaming machine — fully schedulable; k3s-agent enabled at boot |
| Argo UI | external entrypoint | http://192.168.1.102:32746 | Host-local service also exposed on port 2746 |
| Loki | log aggregation | http://192.168.1.102:30100 | Captures workflow pod logs |
| ArgoCD | GitOps controller | https://192.168.1.102 | Reconciles this repo into the cluster |

ArgoCD intentionally scales `argocd-applicationset-controller`, `argocd-dex-server`, and
`argocd-notifications-controller` to zero in this homelab. K8sGPT may flag those Services as
no-endpoint findings; that is expected, not drift.

HostDisk VMs (Flatcar, Knuckle, GnomeOS) must pin to ghost — their disk files live on ghost's local storage.
ContainerDisk VMs (Bluefin test VMs) float freely and can schedule on ghost or bazzite.

## GitOps ownership

| Area | Source of truth | Reconciler |
|---|---|---|
| WorkflowTemplates | `argo/workflow-templates/*.yaml` | ArgoCD application `testing-lab` |
| Cluster infra and CronWorkflows | `manifests/*.yaml` | ArgoCD application `testing-lab-infra` |
| Operator entrypoints | `Justfile` | Local operator / MCP tooling |

The repo is intentionally GitOps-first: cluster state should converge from git, not from manual template applies or node SSH.

## Operator access model

- Use Kubernetes MCP and Argo MCP for workstation-side cluster reads and mutations.
- Prefer the `just` entrypoints when they exist; they are the human-facing wrappers around the same API-driven workflow.
- Do not SSH from a workstation into `ghost` or `exo-1` for inspection, recovery, or file transfer.
- In-workflow SSH into test VMs remain valid because they originate inside the cluster and are part of the test harness, not node administration.

## Image, disk, and VM model

| Object | Backing location | Used by | Notes |
|---|---|---|---|
| ContainerDisk (`testing`) | `192.168.1.102:30500/bluefin-containerdisk:testing` | Bluefin QA pipeline | Built by `build-containerdisk` |
| ContainerDisk (`lts-testing`) | `192.168.1.102:30500/bluefin-containerdisk:lts-testing` | Bluefin QA pipeline | Built by `build-containerdisk` |
| Flatcar hostDisk | `/var/mnt/ghost-data/flatcar-test/<vm-name>/disk.raw` | Flatcar pipeline | Reflinked from golden, removed by teardown |
| Knuckle hostDisk | `/var/mnt/ghost-data/knuckle-test/<vm-name>/disk.raw` | Knuckle pipeline | Reflinked from golden, removed by teardown |

The SSH secret lives in the `bluefin-test-ssh-key` Kubernetes secret in namespace `argo`.
Golden disks can be rotated via the `build-containerdisk` template.

## Test execution stack

| Component | Responsibility |
|---|---|
| `git-sync` initContainer | Clone the requested repo ref into the runner pod |
| `run-gnome-tests` | Copy suites to the VM and orchestrate execution |
| `qecore-headless` | Start the Wayland GNOME session inside the VM |
| `dogtail` | Traverse and interact with the AT-SPI tree |
| `gnome-ponytail-daemon` | Translate AT-SPI coordinates into Wayland input |
| `Shell.Eval` | Handle GNOME Shell 50 top-bar interactions that AT-SPI cannot drive reliably |
| Loki | Preserve logs and emitted test artifacts after pod cleanup |

## GNOME Shell 50 constraints

- Clock, quick-settings, and calendar interactions are not reliably actionable through AT-SPI alone.
- `global.context.unsafe_mode = true` must be enabled before top-bar interaction.
- `findChild(..., requireResult=...)` is not a supported dogtail pattern in this repo's stack.
- `findChildren(...)` and `findChild(..., retry=False)` are the canonical presence-check APIs.

## Common failure modes

| Symptom | Root cause | Durable fix |
|---|---|---|
| `Permission denied (publickey)` during SSH wait | ContainerDisk or hostDisk contains an old public key | Rebuild the containerDisk via `build-containerdisk` |
| `wait-for-vm` exits 1 with `Error from server (Forbidden)` | argo SA has no kubevirt-manager Role in the VM namespace | Add Role + RoleBinding to `manifests/kubevirt-rbac.yaml` for the new namespace |
| `AccessCredentialsSynchronized` never becomes True; `wait-for-vm` times out | `qemu-guest-agent.service` not enabled in VM image | `build-containerdisk` symlinks it; check post-install step was preserved |
| `force=true` rebuild workflow stalls with only 2 nodes (DAG + Skipped check) | Downstream `when` references a Skipped task's outputs (resolves to empty string); Argo v4 does not schedule the task | Let `check` always run; handle `force=true` bypass inside the script body (see `argo-workflows.md` §18) |
| dakota builds accumulate, hold `ghost-heavy-compute` mutex, starve other rebuilds | `image-poll-dakota` CronWorkflow not suspended; dakota pipeline permanently blocked (composefs, no UKI) | `image-poll-dakota` has `spec.suspend: true` in git; if builds appear, stop them immediately |
| Cross-node SSH from workflow pods to VM fails (bazzite VM, ghost pod) | firewalld on node blocks flannel/pod-to-pod traffic | `k3s-firewalld-config` DaemonSet disables firewalld on all nodes; if re-enabled, rollout restart the DaemonSet |
| Workflow hangs before GUI steps start | VM boot or SSH readiness never completed | Inspect VMI readiness and runner logs, then re-run the appropriate recovery path |
| K8sGPT reports no-endpoint Services for `argocd-applicationset-controller`, `argocd-dex-server`, `argocd-notifications-controller-metrics`, or `virt-exportproxy` | These are documented control-plane exceptions in this cluster shape | Ignore those specific findings; they are intentional |
| `TypeError` involving `requireResult` | Stale dogtail step pattern | Replace with `findChildren(...)` or `findChild(..., retry=False)` |
| Clock / quick-settings scenarios miss their targets | GNOME Shell AT-SPI geometry gap | Drive the interaction via `Shell.Eval` |
| `outputs.result` contains debug text | Script template wrote extra stdout | Send debug output to stderr and reserve stdout for the actual result |
| VM stuck `Terminating` | KubeVirt controller race with launcher cleanup | Delete the `virt-launcher-*` pod and let reconciliation finish |
| `run-gnome-tests` pod fails at startup | Workflow template structure error, often misplaced `volumes:` | Fix the template in git and let ArgoCD reconcile it |
| WorkflowTemplate change appears ignored | Workflow was submitted before the new template was reconciled | Verify ArgoCD revision, wait or sync, then submit a new workflow |
| `flatcar-kernel-build` fails after hours with `Pod was active on the node longer than the specified deadline` | Workflow/template `activeDeadlineSeconds` too short for a full Flatcar SDK kernel+image compile | Use a 6h workflow deadline for the pipeline and avoid tighter per-step deadline caps; if still blocked, use bare-metal fallback in `docs/skills/flatcar-node-onboarding.md` |
| `flatcar-kernel-build` sits at `Preflight SDK pull` with an active `docker pull --quiet` in the VM | Docker daemon is still coming up or the mirror pull is just slow; the SDK layers are large | Keep the SDK data-root on the PVC, watch `/var/tmp/build/docker` grow, and use the cache-first timeout + upstream fallback pattern rather than killing the run immediately |
| Flatcar runner: `pip3: command not found` | Fedora minimal lacks standalone `pip3` | Use `python3 -m pip install` in runner pods |
| Flatcar runner: exit code 64 | Template has `outputs.artifacts` but Argo artifact storage is not configured | Remove artifact `outputs:` from the template |
| Flatcar test: `ctr version` fails as `core` | containerd socket requires root | Use `sudo ctr version` (core has passwordless sudo) |

## Historical notes

Keep this file timeless: architecture, topology, and durable failure modes only.
