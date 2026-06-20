# Ghost cluster — operating model and runbook

The ghost k3s cluster is managed **exclusively through MCP and Argo Workflows**.
No SSH to ghost, no raw `kubectl` for routine operations.

## Operating model

| Task | Tool | Notes |
|---|---|---|
| List/inspect workflows | `argo_list_workflows`, `argo_get_workflow` | MCP tool |
| Submit workflows | `argo_submit_workflow` | MCP tool |
| Stream workflow logs | `argo_logs_workflow` | MCP tool |
| List pods, VMs, nodes | `k8s_pods_list`, `k8s_resources_list` | MCP tool |
| Cluster bootstrap / emergency | `kubectl` with `~/.kube/bluespeed.yaml` | **Break-glass only** — document why |
| OS-level ghost work | SSH to `jorge@ghost` | **Break-glass only** — infra changes only |

The `argo_*` and `k8s_*` tools are pi extensions that load from
`~/.pi/agent/extensions/`. They require the ghost k3s API (`192.168.1.102:6443`)
to be reachable. If the extensions show `offline`, run `/argo-reconnect` and
`/k8s-reconnect` in the pi TUI — no `/reload` needed.

## Cluster configuration

| Node | Role | Schedulable | Notes |
|---|---|---|---|
| `ghost` | control-plane + master | Yes | Taint: none — general scheduling allowed |
| `exo-1` | worker | Yes | Taint: none — general scheduling allowed |
| `bazzite` | worker | On demand only | Taint: `node-role.kubernetes.io/gaming:NoSchedule` — gaming machine, k3s disabled at boot; `ujust toggle-k8s` to start/stop. Only pods with matching toleration land here. |

`/etc/rancher/k3s/config.yaml` on ghost:

```yaml
kube-apiserver-arg:
  - "event-ttl=30m"
kube-controller-manager-arg:
  - "node-monitor-period=20s"      # polls nodes every 20s
  - "node-monitor-grace-period=90s" # marks node NotReady after 90s of silence
kubelet-arg:
  - "node-status-update-frequency=20s"  # must be < grace-period / 3
```

**Grace period math**: `node-status-update-frequency` × 3 < `node-monitor-grace-period`.
With 20s × 3 = 60s < 90s, this is satisfied. When exo-1 goes offline, pods on
exo-1 are evicted within ~90s and rescheduled on ghost.

**Previous setting of 2m was wrong** — it caused CoreDNS and other pods to stay
in `Unknown` state for 2+ minutes when exo-1 went offline, blocking cluster
recovery. Reduced to 90s on 2026-06-20.

## Scheduling model

### Rule: only use nodeSelector/nodeAffinity when hardware requires it

Do **not** pin pods to specific nodes to "be safe" or "reduce load on the control
plane". The k8s scheduler is correct by default. Hard placement constraints
create fragility and waste capacity.

**Valid reasons to pin a pod to a node:**
- Pod needs a hostPath on ghost's local disk (KubeVirt disks, Zot cache, local registry)
- Pod needs the AMD GPU on ghost (ROCm / llm-d)
- Pod is a DaemonSet component (by definition runs everywhere)

**Not valid reasons to pin:**
- "The control plane is on ghost" — schedulable nodes handle all workloads
- "I want to be safe" — use resource requests and let the scheduler decide
- "exo-1 is a worker" — ghost is also schedulable; treat them equivalently

### What requires a nodeSelector

| Workload | Node | Reason |
|---|---|---|
| KubeVirt virt-* components | ghost | KubeVirt operator pins these |
| KubeVirt VMs (VirtualMachineInstance) | ghost | hostPath disk on ghost's local storage |
| `kubernetes-mcp-server` | ghost | nodeSelector in manifest (MCP socket dependency) |
| `zot-ghcr`, `zot-docker` (registry cache) | ghost | hostPath cache at `/var/mnt/ghost-data/zot-*` |
| `local-registry` (registry:2) | ghost | hostPath at `/var/mnt/ghost-data/dist-registry` |
| `llm-d` model server | ghost | AMD GPU (amd.com/gpu resource) |

### What schedules freely (no nodeSelector)

- Argo Workflow step pods (BIB builds, BST builds, test runners)
- ARC runner pods and listener (`arc-systems`, `arc-runners`)
- ArgoCD components
- Argo controller and server
- All other stateless workloads

### Bazzite taint

bazzite carries taint `node-role.kubernetes.io/gaming:NoSchedule` — persisted via
`manifests/bazzite-node-taint.yaml`. Critical infra pods never land there.
Workloads that opt in via `tolerations` can use bazzite's capacity when it is online.
bazzite's k3s is disabled at boot; enable with `ujust toggle-k8s`.

**Why this matters:** bazzite's CNI/network may not be fully initialised when it
first joins. Pods landing on bazzite before networking is ready will fail DNS
resolution (`no route to host` to CoreDNS). The taint prevents this for infra workloads.

### CoreDNS placement

**CoreDNS is NOT pinned via manifest** — k3s overwrites its own manifests on
every restart. CoreDNS is kept on ghost by the `node-monitor-grace-period=90s`
configuration: when exo-1 is down, the scheduler naturally places CoreDNS on ghost.
If CoreDNS ends up on exo-1 and exo-1 fails, see the recovery procedure below.

## Reboot recovery procedure

After a `ghost` reboot, the cluster takes ~2 minutes to fully recover:

1. k3s starts and writes its built-in manifests (`coredns.yaml`, `local-storage.yaml`)
2. The scheduler places critical pods on ghost (exo-1 is NotReady after a ghost reboot)
3. CoreDNS and local-path-provisioner should be Running within ~90s

**To verify recovery** (use MCP tools, not kubectl):
```
k8s_resources_list apiVersion=v1 kind=Pod namespace=kube-system
```
All pods should be `Running` or `Completed` within 2 minutes.

### Pods stuck Pending with "failed to fetch token" error

This is a k3s startup race: the node authorizer's internal graph is built
from watch events, and Deployment pods (where `nodeName` is set via a Binding
update) may not appear in the graph immediately after restart. DaemonSet pods
(where `nodeName` is set at creation) are immune.

**Symptom**: `kubectl describe pod` shows:
```
MountVolume.SetUp failed for volume "kube-api-access-*": failed to fetch token: pod "..." not found
```

**Fix**: force an UPDATE event on the stuck pod — this causes the node authorizer
informer to re-process it and add it to the graph:

```bash
export KUBECONFIG=~/.kube/bluespeed.yaml
kubectl annotate pod <pod-name> -n <namespace> ghost.io/graph-nudge="$(date +%s)" --overwrite
```

Repeat for each stuck pod. CoreDNS should transition from Pending to Running
within the next kubelet retry interval (up to 2 minutes due to exponential
backoff — wait for it).

**Why this happens**: The kubelet calls the TokenRequest API using its node
credential (`system:node:ghost`). The node authorizer checks its in-memory
graph to decide if ghost is allowed to create a token for the pod. The graph
is populated by a pod informer. After k3s restarts, the graph rebuilds from
watch events. Deployment pods (bound via a Binding update) may miss the initial
sync window. The annotation triggers an UPDATE event that the informer processes,
putting the pod into the graph.

### CoreDNS stuck on exo-1 (Unknown) after exo-1 goes offline

If CoreDNS was on exo-1 when exo-1 went offline:

1. Wait 90s for `node-monitor-grace-period` to expire
2. k3s evicts the Unknown CoreDNS pod
3. Scheduler creates a new CoreDNS pod on ghost
4. If the new pod gets stuck Pending: use the graph-nudge annotation above

Do NOT force-delete the Unknown pod immediately — let k3s handle eviction
naturally. Force-deleting creates a new pod with a new UID, which is more
likely to trigger the node authorizer race.

## Removed components

### superlocalmemory (removed 2026-06-20)

The `superlocalmemory` container was a user-level podman container on ghost,
exposing an MCP server on port 3333. It has been permanently removed:

- Quadlet file deleted: `~/.config/containers/systemd/superlocalmemory.container`
- Container and image removed from ghost
- Volume `superlocalmemory-data` deleted

Port 3333 is now unused.

## BST workload priority for dakota

Dakota builds use BST (BuildStream) which is CPU and memory intensive.
The `ghost-heavy-compute` Argo mutex serializes BST builds to prevent
resource contention. All dakota BST workflows acquire this mutex before
running.

To check if a BST build is running before submitting dakota:
```
argo_list_workflows namespace=argo
```
If a BST workflow is active, a new one will queue on the mutex and start
automatically when the running build finishes. Do not submit multiple dakota
workflows simultaneously.

## MCP server endpoints

| Service | Address | Protocol |
|---|---|---|
| kubernetes-mcp-server | `http://192.168.1.102:32767/sse` | SSE |
| kubernetes-mcp-server | `http://192.168.1.102:32767/mcp` | Streamable HTTP |
| Argo Workflows UI | `http://192.168.1.102:32746` | HTTP |

Port 3333 (superlocalmemory) has been decommissioned.
