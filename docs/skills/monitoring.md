---
name: monitoring
description: >
  Loki + Promtail observability stack in the testing-lab. Use when configuring
  pod log scraping, enabling Loki retention, preventing disk fill, querying
  workflow logs, or debugging why a pod's logs are missing from Loki.
metadata:
  context7-sources:
    - /grafana/loki
    - /grafana/alloy
---

# Monitoring — testing-lab Skill

## When to Use

- Pod logs are missing from Loki / not being scraped
- Ghost disk filling up; need to reduce log retention
- Adding a new workflow category that should be logged
- Loki query returning empty results for a running/recent workflow
- Debugging log scraping config (Promtail relabeling)

## When NOT to Use

- Workflow status / failure debugging → `argo-workflows.md`
- VM boot failures → `kubevirt-vms.md`
- ArgoCD sync failures → `gitops-argocd.md`

## Stack

| Component | Version | Namespace | NodePort |
|---|---|---|---|
| Loki | 3.4.2 | `monitoring` | — |
| Promtail | latest | `monitoring` (DaemonSet) | — |
| Grafana | — | `monitoring` | — |

Both Loki and Promtail are **NOT** managed by ArgoCD (installed via Helm outside this
repo). Their ConfigMaps ARE patched by ArgoCD via `testing-lab-infra` Server-Side Apply.
**Never directly `kubectl apply` these — ArgoCD overwrites manual applies.**

## Core Process

### 1. Promtail scrape config (manifests/promtail-config.yaml)

Promtail runs as a DaemonSet on all nodes. It watches pod log files under
`/var/log/pods/<ns>_<pod>_<uid>/<container>/<n>.log`.

k3s/containerd default container log rotation: **10Mi per file, 5 files max = 50Mi
per container**. This is usually sufficient; the bigger risk is Loki PVC fill from
long-lived streams without compaction.

**Canonical scrape job for ALL argo workflow pods:**

```yaml
- job_name: argo-all-pods
  static_configs:
    - targets: [localhost]
      labels:
        namespace: argo
        __path__: /var/log/pods/argo_*/*/*.log
  pipeline_stages:
    # Extract pod and container name from the log file path:
    # /var/log/pods/argo_<pod-name>_<uid>/<container>/<n>.log
    - regex:
        expression: '/var/log/pods/[^_]+_(?P<pod>[^_]+)_[^/]+/(?P<container>[^/]+)/\d+\.log'
        source: filename
    - labels:
        pod:
        container:
    # Drop argo sidecar noise
    - drop:
        expression: "^time=.*level=INFO msg=\"(waiting for|sub-process exited|file signal).*$"
        drop_counter_reason: argo_sidecar_noise
```

**Why static glob over kubernetes_sd_configs:**
Kubernetes service discovery only finds currently-running pods. Static glob catches
logs from pods that have already completed but whose log files still exist on disk.
For workflow debugging, you often need logs from pods that finished 5–10 minutes ago.

**Backoff config to prevent Loki back-pressure from blocking Promtail:**
```yaml
clients:
  - url: http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push
    backoff_config:
      min_period: 100ms
      max_period: 10s
      max_retries: 5
```

### 2. Loki retention (manifests/loki-config.yaml)

**Without a `compactor` block, `retention_period` is NOT enforced.** Loki accumulates
chunks until the PVC fills. Ghost's NVMe is 83% full; Loki's 10Gi PVC MUST have
compaction enabled.

Required `compactor` block (Loki 3.x, TSDB + filesystem backend):

```yaml
compactor:
  working_directory: /loki/compact
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150
```

**Retention period:** Match the workflow TTL in `workflow-controller-configmap`:
- Success TTL: 7 days → `retention_period: 168h`
- Failure TTL: 30 days → you could use 30d, but 7d keeps disk safe

Current setting: `168h` (7 days).

**Ingestion rate limits** — prevent a single runaway pod from filling Loki:

```yaml
limits_config:
  retention_period: 168h
  ingestion_rate_mb: 16
  ingestion_burst_size_mb: 32
  per_stream_rate_limit: 512KB
  per_stream_rate_limit_burst: 1MB
  max_entries_limit_per_query: 10000
```

Limits apply globally (no per-tenant config needed when `auth_enabled: false`).

### 3. ArgoCD sync — how the patch reaches Loki

The `testing-lab-infra` ArgoCD Application uses `ServerSideApply: true`. When
`manifests/loki-config.yaml` is pushed to `main`, ArgoCD patches the existing
`loki-config` ConfigMap in the `monitoring` namespace (which Loki's Helm release owns)
without adopting ownership.

**Loki will NOT reload automatically.** After ArgoCD syncs the ConfigMap, you must
restart the Loki StatefulSet to apply the new config:

```bash
# Do NOT SSH to ghost — submit a workflow step or use kubernetes-mcp
kubernetes-mcp-resources_delete apiVersion=apps/v1 kind=Pod \
  namespace=monitoring name=loki-0
# k8s will recreate loki-0 with the new ConfigMap
```

Similarly, Promtail DaemonSet pods must be restarted after `promtail-config` changes:
```bash
kubernetes-mcp-resources_list apiVersion=v1 kind=Pod namespace=monitoring
# then delete each promtail-* pod to trigger rolling restart
```

### 4. Verifying logs are reaching Loki

```bash
# Query recent argo logs from the last hour
curl -s "http://192.168.1.102:30100/loki/api/v1/query_range" \
  --data-urlencode 'query={namespace="argo"}' \
  --data-urlencode 'start=1h' \
  --data-urlencode 'limit=10' | python3 -c "
import json, sys
d = json.load(sys.stdin)
streams = d.get('data', {}).get('result', [])
print(f'{len(streams)} streams found')
for s in streams[:3]:
    print('labels:', s['stream'])
    for ts, line in s['values'][:2]:
        print(' ', line[:100])
"
```

Loki NodePort is `30100` on ghost (`192.168.1.102`).

### 5. Disk usage monitoring

Ghost NVMe (`/dev/nvme0n1p3`) is 83% full as of 2026-06-23. Monitor regularly:

```bash
# Check Loki PVC usage
kubernetes-mcp-resources_get apiVersion=v1 kind=Pod namespace=monitoring name=loki-0
# then:
# kubectl exec -n monitoring loki-0 -- df -h /loki
```

Loki data directories:
- `/loki/chunks` — raw chunk data (26.4M as of 2026-06-23)
- `/loki/index` — TSDB index
- `/loki/compact` — compactor working directory (empty until first compaction run)

After enabling compaction, chunks older than `retention_period` are deleted on the
`compaction_interval` schedule.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "`retention_period: 744h` already set — retention is working." | Without the `compactor` block, retention is NOT enforced. Logs accumulate forever. |
| "I'll add specific prefixes to the static_configs." | A single `argo_*/*/*.log` glob is simpler and catches ALL argo pods including ad-hoc debug runs. |
| "Promtail auto-reloads ConfigMap changes." | It does not. Delete the promtail pods after ArgoCD syncs to apply the new config. |
| "Loki auto-reloads ConfigMap changes." | Loki does NOT hot-reload. Delete `loki-0` pod to apply. |
| "Ghost disk fill is a host concern, not a k8s concern." | Loki, Zot, golden disk files, and container logs all live on the same nvme. All sources of growth must be guarded. |

## Red Flags

- `retention_period` set but no `compactor` block — retention is silently ignored
- `per_stream_rate_limit` not set — a single runaway build pod can saturate Loki
- Static configs with per-prefix entries (`argo_bluefin-*`, `argo_dakota-*`, etc.) — use `argo_*` glob instead; individual prefixes miss ad-hoc and debug pods
- Modifying `loki-config` or `promtail-config` directly with `kubectl apply` — ArgoCD overwrites; always go through git
- Forgetting to restart Loki/Promtail pods after ConfigMap update — old config stays until pod restarts
- Ghost NVMe at >90% — investigate zot, golden disk files, and Loki chunks; do not increase retention

## Verification

Before claiming logging is working:

- [ ] `promtail-config.yaml` has `argo_*/*/*.log` glob in `argo-all-pods` job
- [ ] `loki-config.yaml` has `compactor` block with `retention_enabled: true`
- [ ] `retention_period` ≤ `168h` (7 days)
- [ ] Per-stream rate limits set (`per_stream_rate_limit: 512KB`)
- [ ] Loki pod restarted after config change
- [ ] Promtail pods restarted after config change
- [ ] Query to `http://192.168.1.102:30100/loki/api/v1/query_range?query={namespace="argo"}` returns recent logs
- [ ] Ghost NVMe < 90% used
