# Dakota Cluster Build Pipeline — Design

Date: 2026-06-24

## Goal

Run Dakota BST builds on the homelab k3s cluster as a parallel, resource-bounded capability
alongside the existing Hetzner remote CAS. Not a replacement — an addition. Push to
`dakota:testing` triggers a cluster build. Multiple build variants fan out to available nodes.
The Hetzner CAS (`cache.projectbluefin.io:11002`) is untouched.

## Architecture

```
push dakota:testing
    │
    ▼
dakota-commit-poller CronWorkflow (every 5 min)
    │  polls GitHub API; SHA changed → submits dakota-build-pipeline
    ▼
Argo WorkflowTemplate: dakota-build-pipeline
    ├── step: build-bluefin        (bst2 pod, any ready node)
    └── step: build-bluefin-nvidia (bst2 pod, any ready node)
              │                            │
              └────────────┬───────────────┘
                           ▼
              buildbox-casd  (Deployment, local-registry ns)
              PVC: 200Gi local-path on ghost NVMe
                           │
              on success: podman push → Zot :30500  (local)
```

Both build pods share the same in-cluster casd Service. Cache hits from `build-bluefin`
benefit `build-bluefin-nvidia` immediately — shared artifact pool.

## Cluster Topology

| Node  | CPUs | RAM    | Role                     |
|-------|------|--------|--------------------------|
| ghost | 32   | 62.5Gi | casd PVC, heavy builds   |
| bazzite | 12 | 30.5Gi | overflow build pods      |

exo-1 is NotReady — excluded.

## Components

### New files in `testing-lab`

| File | Purpose |
|------|---------|
| `manifests/buildbox-casd.yaml` | casd Deployment + ClusterIP Service + PVC (200Gi) |
| `manifests/bst-build-priorityclass.yaml` | PriorityClass `bst-build` value=500000, PreemptionPolicy=Never |
| `argo/workflow-templates/dakota-build-pipeline.yaml` | WorkflowTemplate: parallel BST build steps |
| `argo/workflow-templates/dakota-commit-poller.yaml` | WorkflowTemplate: poll GitHub API for new commits |
| `manifests/dakota-commit-poller.yaml` | CronWorkflow: every 5 min trigger for commit-poller |

### Modified files in `testing-lab`

| File | Change |
|------|--------|
| `manifests/semaphore-tuner.yaml` | Add `BST_RESERVE_GI=16` subtracted from ghost pool when computing VM slots |
| `manifests/semaphore-config.yaml` | Add `max-bst-builds: 1` semaphore key |

### New files in `dakota` repo

| File | Purpose |
|------|---------|
| `buildstream-cluster.conf` | BST config pointing at in-cluster casd (`buildbox-casd.local-registry.svc.cluster.local:11002`) |

## Resource Management

```yaml
# Per BST build pod
resources:
  requests:
    cpu: "4"
    memory: 12Gi
  limits:
    cpu: "8"
    memory: 16Gi
priorityClassName: bst-build
activeDeadlineSeconds: 7200
```

**Why these numbers:**
- `limit cpu=8` fits bazzite (12c) with headroom. Ghost fits 2 pods (16c/32Gi) safely.
- `limit memory=16Gi` matches dakota docs minimum for a BST build.
- `max-bst-builds: 1` semaphore — one build at a time initially. Bump to 2 when more nodes arrive.
- `bst-build` priority (500000) < `lab-test-vm` (1,000,000): test VMs win scheduling disputes. A preempted BST build restarts and skips already-built elements (casd preserves artifacts).

**Semaphore tuner change:**
```bash
BST_RESERVE_GI=16  # always reserve headroom on ghost for a BST build
ghost_usable=$(( ghost_gi - OVERHEAD_GI - BST_RESERVE_GI ))
```
Result: ghost contributes `floor((62 - 12 - 16) / 8) = 4` VM slots instead of 6.
Nightlies and PR poller still get their VMs. BST build always has guaranteed room.

## Data Flow

1. Dev pushes to `dakota:testing`
2. `dakota-commit-poller` CronWorkflow fires every 5 min, polls GitHub API for HEAD SHA
3. If SHA changed vs `image-polling-digests` ConfigMap → updates ConfigMap, submits `dakota-build-pipeline`
4. Argo DAG starts two parallel steps: `build-bluefin` and `build-bluefin-nvidia`
5. Each pod: `git clone dakota:testing` → `bst --config buildstream-cluster.conf build oci/<variant>.bst`
6. BST pushes each built element to in-cluster casd over gRPC (cluster-local, sub-ms latency)
7. On completion: `bst artifact checkout` → `podman push` to Zot :30500

## Security

- BST pods need `securityContext.seLinuxOptions.type: spc_t` + `--security-opt label=disable` in the bst2 container invocation (required for `bootc install` inside sandbox — see SELinux memory)
- casd runs unauthenticated — in-cluster only, no external exposure (ClusterIP Service, no NodePort)
- No ARC runners — trigger is an in-cluster commit-poller CronWorkflow (same pattern as image-poller)

## What This Is Not

- Not a replacement for `cache.projectbluefin.io:11002` (Hetzner CAS stays)
- Not remote execution (REAPI workers) — parallel pipelines model, one BST process per variant
- Not aarch64 builds (aarch64 has no RE today; in-cluster builds same constraint for now)

## Rollout

1. Deploy casd + PriorityClass via GitOps (ArgoCD syncs `manifests/`)
2. Add `dakota-build-pipeline` WorkflowTemplate (ArgoCD syncs `argo/workflow-templates/`)
3. Update semaphore-tuner to include BST_RESERVE_GI
4. Manual test: `argo submit` the workflow by hand, confirm casd gets populated
5. Add `cluster-build.yml` to dakota repo + `buildstream-cluster.conf`
6. Monitor first automated push-triggered build

## Open Questions

- None. All decisions made.
