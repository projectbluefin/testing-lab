# Service-Catalog Workload Contract (#66)

This document defines the shared workload contract for all service-catalog
validation lanes under the homelab service-catalog epic (#51). Every lane
— media (#59), non-media (#64), Home Assistant-class (#69), and any future
service lane — must satisfy this contract before it is considered durable.

This contract is **the single source of truth** for what every service-catalog
workload must prove. Individual lane definitions inherit this contract and
add lane-specific requirements on top.

---

## 1. K8s-Native First-Pass Assumption

All service-catalog workloads run **directly in Kubernetes** as container
workloads. This is an explicit design choice:

- Workloads are deployed via raw Kubernetes manifests (Deployment, Service,
  PVC, Secret, ConfigMap) applied with `kubectl apply`.
- No Helm charts, Kustomize overlays, or operator CRDs in the first pass.
  Raw manifests keep the validation surface minimal and debuggable.
- No VM-backed role validation. Workloads do not run inside KubeVirt VMs
  or require homelab-role provisioning. VM-backed validation is tracked
  under #54 and is **not a blocker** for any service-catalog lane.
- Workloads target the `ghost` node via `nodeSelector` (consistent with
  the existing homelab lanes).

### Why raw manifests

The contract validates whether a service **can run correctly in the lab
cluster**, not whether a packaging tool works. Raw manifests make failure
evidence unambiguous: if a Deployment doesn't schedule, the manifest and
pod events tell the full story without an abstraction layer in between.

---

## 2. Deployment Contract

Every service-catalog workload lane must prove the following deployment
behavior:

### Namespace isolation

- Each workflow run creates a **dedicated namespace** with a unique suffix
  (e.g., `svc-<lane>-{{workflow.uid}}`).
- The namespace must carry labels:
  - `app.kubernetes.io/part-of: bluefin-test-suite`
  - `bluefin.io/lane: <lane-name>`
- The namespace is deleted during cleanup (see §6).

### Manifest application

- All resources are applied via `kubectl apply -n <namespace> -f -` from
  an inline heredoc or a manifest file in the repo.
- No resources are created outside the dedicated namespace (except
  cluster-scoped resources that must be explicitly justified and cleaned up).
- Manifests must be **self-contained**: no external image registries that
  require authentication, no references to resources in other namespaces.

### Deployment readiness

The lane must capture evidence that the workload reached a ready state:

| Evidence artifact | Content | Pass criteria |
|---|---|---|
| `<lane>-deployment.json` | `kubectl get deployment <name> -n <ns> -o json` | `status.availableReplicas >= 1` and `status.readyReplicas >= 1` |
| `<lane>-pods.json` | `kubectl get pods -n <ns> -l <app-label> -o json` | At least one pod in `Running` phase with all containers ready |
| `<lane>-events.txt` | `kubectl get events -n <ns> --sort-by=.lastTimestamp` | Captured for debugging; no pass/fail assertion |

### Secrets and environment

- Secrets required by the workload (TLS certs, auth credentials, API keys)
  must be created as Kubernetes Secrets within the dedicated namespace.
- Secrets must be created **before** the Deployment is applied (the workflow
  DAG enforces ordering).
- Environment variables are injected via `env` or `envFrom` in the pod spec,
  referencing Secrets or ConfigMaps — never hardcoded in the container image.
- No Secret may contain real production credentials. All secrets in the test
  fixture are synthetic/throwaway.

---

## 3. Persistence Contract

Every service-catalog workload that declares persistent state must prove:

### PVC lifecycle

| Evidence artifact | Content | Pass criteria |
|---|---|---|
| `<lane>-pvc.json` | `kubectl get pvc <name> -n <ns> -o json` | PVC phase is `Bound`; storage class is `local-path` (or the expected class) |
| `<lane>-pvc-mount.txt` | `stat <mount-path>` inside the pod | Mount path exists, is a directory, and is writable |

### Survive restart

The workload must prove that persistent data survives a `rollout restart`:

1. Write a sentinel file to the PVC mount path.
2. Capture pod UIDs before restart (`<lane>-pods-before.json`).
3. Execute `kubectl rollout restart deployment/<name> -n <ns>`.
4. Wait for rollout to complete (`kubectl rollout status --timeout=300s`).
5. Capture pod UIDs after restart (`<lane>-pods-after.json`).
6. Verify pod UIDs changed (proving new pods were created).
7. Read the sentinel file from the new pod and verify it matches.

| Evidence artifact | Content |
|---|---|
| `<lane>-sentinel-write.txt` | Confirmation that sentinel was written |
| `<lane>-pods-before.json` | Pod state before restart |
| `<lane>-restart.txt` | Rollout restart output |
| `<lane>-rollout-status.txt` | Rollout status output |
| `<lane>-pods-after.json` | Pod state after restart |
| `<lane>-sentinel-read.txt` | Sentinel file content read from new pod |

### Workloads without persistence

If a lane's workload is stateless (no PVC), it must explicitly document why
persistence is not required and skip the persistence checks with:
```python
pytest.skip("Stateless workload — no persistence contract to validate")
```

### Storage dependencies

- All persistence checks assume `local-path` storage class (RWO).
- Workloads that require `ReadWriteMany` must skip with a reference to #62
  until shared storage is available.
- Workloads that require specific storage features (snapshot, resize, etc.)
  must document the dependency and skip if not available.

---

## 4. Reachability Contract

Every service-catalog workload that exposes a network endpoint must prove:

### Cluster-internal reachability

| Evidence artifact | Content | Pass criteria |
|---|---|---|
| `<lane>-dns.txt` | `getent hosts <service>.<ns>.svc.cluster.local` | Resolves to a cluster IP |
| `<lane>-endpoints.json` | `kubectl get endpoints <service> -n <ns> -o json` | At least one address in subsets |
| `<lane>-http.txt` | `curl` or `urllib` response from the service | Expected status code and body |

### Protocol-specific evidence

Lanes that expose HTTPS must additionally capture the evidence defined by
the HTTPS exposure lane (#58): TLS handshake, certificate subject, TLS
version. Lanes that enforce auth must capture the evidence defined by the
auth-gating lane (#61).

These are additive — the reachability contract here covers the baseline
(DNS, endpoints, HTTP response). Lanes reference #58 and #61 for transport
and auth layers rather than re-defining them.

### Workloads without network endpoints

If a lane's workload does not expose a Service (e.g., a batch job or
cron-style workload), it must document why and skip reachability checks.

---

## 5. Upgrade / Redeploy Evidence

The contract distinguishes two levels of deployment validation:

### One-shot bring-up (required for all lanes)

Every lane must prove the workload can deploy from scratch into an empty
namespace and reach a ready state. This is the minimum bar — the deployment
and reachability evidence in §2 and §4 cover this.

### Upgrade / redeploy (required for lanes claiming durability)

Lanes that claim their workload survives upgrades must additionally prove:

1. **Image tag change**: Apply a manifest with an updated container image
   tag. The rollout must complete without error. The new pod must be running
   the updated image.
2. **Config change**: Apply a manifest with an updated ConfigMap or env var.
   The rollout must complete. The workload must reflect the new config.

| Evidence artifact | Content |
|---|---|
| `<lane>-upgrade-before.json` | Deployment state before the upgrade |
| `<lane>-upgrade-apply.txt` | `kubectl apply` output for the updated manifest |
| `<lane>-upgrade-rollout.txt` | Rollout status after the upgrade |
| `<lane>-upgrade-after.json` | Deployment state after the upgrade |
| `<lane>-upgrade-image.txt` | Container image from the running pod (must match new tag) |

Lanes that do not yet validate upgrades must explicitly state this as a
gap rather than leaving it implicit.

---

## 6. Teardown Contract

Every service-catalog workflow must clean up after itself:

- **Namespace deletion**: The `onExit` handler deletes the dedicated
  namespace, which cascades to all namespaced resources.
- **Timeout**: Namespace deletion must complete within 180 seconds.
  The cleanup step waits until the namespace is gone or the timeout
  expires.
- **Idempotency**: Cleanup must use `--ignore-not-found=true` so it
  succeeds even if resources were already deleted (e.g., by a previous
  failed run).
- **No cluster-scoped leaks**: If any cluster-scoped resources were
  created (ClusterRole, ClusterRoleBinding), they must be explicitly
  deleted in the cleanup step.

### Evidence

| Evidence artifact | Content |
|---|---|
| Cleanup step exit code | 0 (or the workflow's `onExit` logs) |

The teardown contract is enforced by the Argo Workflow `onExit` handler,
not by the test code. Tests assume the namespace exists and is populated;
cleanup happens regardless of test outcome.

---

## 7. Cross-Epic Dependencies

The service-catalog workload contract depends on infrastructure validated
by other epics. These dependencies are **explicit requirements**, not
assumed capabilities.

| Dependency | Epic | What it provides | Status |
|---|---|---|---|
| **Storage persistence** | #52 (storage/role-template) | `local-path` PVC lifecycle, restart survival, observability artifacts | ✅ Validated by `homelab-storage` lane |
| **HTTPS exposure** | #53 (access/TLS/security) | TLS handshake, certificate, HTTPS reachability | Defined in #58 |
| **Auth-gating** | #53 (access/TLS/security) | Credential enforcement, 401 challenges | Defined in #61 |
| **Cluster DNS** | #53 (access/TLS/security) | Service FQDN resolution | ✅ Validated by `homelab-access-probe` |
| **k8s scheduling** | #54 (substrate/fleet-client) | Pod scheduling on ghost, namespace lifecycle | ✅ Validated by `homelab-substrate` lane |

### VM-backed role validation (#54)

VM-backed role validation (running services inside KubeVirt VMs that
simulate a homelab role) is **not a dependency** for service-catalog lanes.
It is tracked under #54 as a separate follow-up track. Service-catalog
lanes run workloads directly in k8s.

If a future lane discovers it cannot validate a service without VM-backed
infrastructure, it must file a dependency on #54 explicitly rather than
silently building VM support into the service-catalog pipeline.

---

## 8. Shared Test Infrastructure

All service-catalog lanes share the test infrastructure in
`tests/service_catalog/shared/kube.py`. This module provides:

| Symbol | Purpose |
|---|---|
| `NAMESPACE` | The test namespace (from `TEST_NAMESPACE` env var) |
| `APP_LABEL` | The pod label selector (from `TEST_APP_LABEL` env var) |
| `SERVICE_NAME` | The Service name (from `TEST_SERVICE_NAME` env var) |
| `TEST_LANE` | The lane identifier (from `TEST_LANE` env var) |
| `RESULTS_DIR` | The artifact output directory (from `TEST_RESULTS_DIR`, default `/tmp/results`) |
| `run_kubectl()` | Run a kubectl command with capture and timeout |
| `require_kubectl()` | Run kubectl and assert success |
| `write_artifact()` | Write a named artifact to the results directory |
| `get_pods_json()` | Get pods matching the app label as JSON |
| `restart_workload()` | Rollout restart + wait + artifact capture |
| `first_pod_name()` | Get the name of the first matching pod |
| `http_get()` | HTTP GET the service endpoint and capture the response |

New lanes should import from this module rather than re-implementing
kubectl wrappers or artifact writing. Lane-specific helpers belong in
the lane's own test directory.

### Environment variables

The `run-incluster-tests` WorkflowTemplate passes these env vars to the
test runner container:

| Env var | Source | Used by |
|---|---|---|
| `TEST_NAMESPACE` | Workflow parameter `namespace` | `kube.py` → `NAMESPACE` |
| `TEST_APP_LABEL` | Workflow parameter `app-label` | `kube.py` → `APP_LABEL` |
| `TEST_SERVICE_NAME` | Workflow parameter `service-name` | `kube.py` → `SERVICE_NAME` |
| `TEST_LANE` | Workflow parameter `lane` | `kube.py` → `TEST_LANE` |
| `TEST_RESULTS_DIR` | Hardcoded `/tmp/results` | `kube.py` → `RESULTS_DIR` |

---

## 9. Lane Compliance Checklist

Every new service-catalog lane PR must include or reference evidence for
each section of this contract:

- [ ] **§1 K8s-native**: Workload runs directly in k8s, no VM dependency
- [ ] **§2 Deployment**: Namespace isolation, manifest application, readiness evidence
- [ ] **§2 Secrets**: All secrets are synthetic, created before Deployment, in-namespace
- [ ] **§3 Persistence**: PVC lifecycle + restart survival evidence (or documented skip)
- [ ] **§4 Reachability**: DNS + endpoints + HTTP evidence (or documented skip)
- [ ] **§5 Upgrade**: Upgrade evidence or explicit gap statement
- [ ] **§6 Teardown**: `onExit` namespace cleanup with timeout
- [ ] **§7 Dependencies**: Cross-epic dependencies called out if applicable
- [ ] **§8 Shared infra**: Uses `tests/service_catalog/shared/kube.py`

---

## Links

- Parent epic: #51
- Source idea: `projectbluefin/bluespeed#4`
- Storage dependency: #52
- Access/TLS dependency: #53
- VM follow-up (not a blocker): #54
- Media lane (consumer): #59
- Non-media lane (consumer): #64
- Deferred HA-class lane (consumer): #69
