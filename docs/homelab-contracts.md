# Homelab Validation Contracts

This document defines the in-cluster workload validation contracts for the
testing-lab QA factory. It covers the workload matrix (#57), shared-storage
and RWX limits (#62), storage observability surface (#70, #78), and the
fleet-client vs. cluster-node boundary (#72).

For the service-catalog workload contract that all service lanes must
satisfy, see [`docs/service-catalog-contract.md`](service-catalog-contract.md)
(#66).

---

## 1. In-Cluster Workload Matrix (#57)

The cluster currently validates three workload classes. Each class maps to a
WorkflowTemplate lane, a test module, and a concrete set of persistence and
access guarantees it must prove.

| Workload class | Lane WorkflowTemplate | Test module | What it proves |
|---|---|---|---|
| **General-purpose** | `homelab-substrate` | `tests/homelab_substrate/` | k3s scheduling, pod lifecycle, in-cluster HTTP/TCP reachability, `local-path` PVC allocation |
| **NAS / storage** | `homelab-storage` | `tests/homelab_storage/` | PVC bound on `local-path`, data survives `rollout restart`, `findmnt`/`df`/`lsblk`/ZFS artifacts captured |
| **Service access** | `homelab-access-probe` | `tests/homelab_access/` | Cluster-DNS resolution, TLS handshake, expected-host routing via SNI |

### Minimum persistence contract per class

#### General-purpose
- Pod scheduled on ghost and reaches Running state.
- HTTP endpoint reachable within the cluster namespace.
- PVC allocates on `local-path` and mounts read-write.

#### NAS / storage
- PVC binds within 60 s with `local-path` storage class.
- Declared mount path is a directory, writable, and survives `rollout restart`.
- Disk-usage, mount table, and block-device evidence is captured as artifacts
  in every run (see §3 for artifact names).
- **RWX blocked until #62 is resolved** — see §2.

#### Service access
- Cluster DNS resolves `<service>.<namespace>.svc.cluster.local`.
- TLS handshake reports a certificate with `Protocol version` in the output.
- Health endpoint returns `access-ok` with `Host:` header routing.

### Gaps surfaced explicitly
- Media streaming / transcoding lane: not yet defined. GPU passthrough is a
  known blocker; filed as a follow-up under the service-catalog epic.
- ReadWriteMany / shared-media access: blocked by #62.
- Service-to-service auth: deferred to service-catalog auth-gating lane (#61).

---

## 2. Shared-Storage / RWX Blocker (#62)

The current k3s cluster uses the **`local-path`** storage provisioner, which
only supports `ReadWriteOnce` (RWO) access mode. This means:

### What can proceed on current storage
| Scenario | Status |
|---|---|
| Single-pod PVC lifecycle (create, mount, write, survive restart) | ✅ Validated by `homelab-storage` |
| Storage observability artifact collection (PVC status, df, lsblk) | ✅ Validated by `homelab-storage` |
| ZFS pool/list evidence collection (conditional on tool presence) | ✅ Validated by `homelab-storage` |
| First restore drill with single-pod PVC | ✅ Unblocked — #60 / #84 |

### What is blocked by the RWX gap
| Scenario | Blocked until |
|---|---|
| NAS-style concurrent write access from multiple pods | RWX-capable storage class (NFS CSI, Longhorn, etc.) |
| Media service with shared read-only media volume | At minimum: `ReadOnlyMany` via NFS |
| Cross-pod restore validation | RWX storage class |
| Service-catalog workloads that share a data directory | Same |

### Minimum evidence to unblock shared-storage
1. A `ReadWriteMany` or `ReadOnlyMany` PVC successfully created on the cluster.
2. Two distinct pods both mounting the same PVC simultaneously.
3. A write from pod A visible from pod B.

Until that evidence exists, every test that depends on shared access **must**
call `pytest.skip` with a reference to this issue (#62):
```python
pytest.skip("RWX/shared-storage scenarios blocked by #62 until ReadWriteMany storage class is available")
```

---

## 3. Storage Observability Surface (#70, #78)

### Generic storage artifacts (always collected)

These artifacts are written to `/tmp/results/` by `test_collects_storage_observability_artifacts`
in `tests/homelab_storage/test_local_path_persistence.py` on every storage-lane run:

| Artifact | Command | What it shows |
|---|---|---|
| `storage-pvc.json` | `kubectl get pvc <name> -o json` | PVC phase, capacity, access modes, storage class, bound PV |
| `storage-disk-usage.txt` | `df -h <mount-path>` | Capacity, used, available, mount point |
| `storage-ownership.txt` | `stat <mount-path>` | UID/GID, permissions, inode |
| `storage-findmnt.txt` | `findmnt <mount-path>` | Filesystem type, source device, mount options |
| `storage-df.txt` | `df -h <mount-path>` | Redundant human-readable capacity snapshot |
| `storage-statfs.txt` | `stat -f <mount-path>` | Block size, total/free/available blocks |
| `storage-lsblk.txt` | `lsblk -f` | Block devices, filesystem labels, UUIDs |
| `storage-pods-before.json` | `kubectl get pods` | Pod state snapshot before rollout restart |
| `storage-pods-after.json` | `kubectl get pods` | Pod state snapshot after rollout restart |
| `storage-restart.txt` | `kubectl rollout restart` | Restart command output |
| `storage-rollout-status.txt` | `kubectl rollout status` | Rollout convergence confirmation |

### ZFS-specific artifacts (collected only when tools present)

| Artifact | Command | Condition |
|---|---|---|
| `storage-zpool.txt` | `zpool status -x` | `command -v zpool` exits 0 |
| `storage-zfs.txt` | `zfs list` | `command -v zfs` exits 0 |

ZFS checks use `|| true` so they degrade gracefully on non-ZFS nodes. Absence
of ZFS evidence is not a test failure; the artifacts will be empty or contain
the "not found" message.

### Relationship to persistence claims
The storage observability artifacts support restart/update persistence
validation as follows:
- **Pre-restart snapshot** (`storage-pods-before.json`) and **post-restart snapshot**
  (`storage-pods-after.json`) prove pod identity changed while the data file survived.
- **`storage-findmnt.txt`** proves the bind mount used the expected filesystem type
  (typically `ext4` on local-path, `zfs` on ZFS-backed nodes).
- **`storage-lsblk.txt`** proves the block device backing the PV is the expected one.
- ZFS artifacts provide pool-health evidence that a failing pool would surface before
  data loss occurs.

---

## 4. Fleet-Client Contract (#72)

### Cluster nodes vs. bootc clients

The lab hardware has two distinct roles that **must not be conflated**:

| Role | Hosts | k3s member | KubeVirt capable | In scope for cluster workload validation |
|---|---|---|---|---|
| **Cluster node** | ghost, exo-1 | Yes | ghost only | Yes |
| **Bootc client** | jorge's Bluefin laptop, other contributor machines | No | No | No |

### What this repo validates for bootc clients
- `bootc status` reports the expected image reference and digest.
- `bootc upgrade --check` exits 0 when no update is pending.
- Staged-deployment and rollback contracts (via ephemeral VM tests in the
  `system/` behave suite, not via live client enrollment).
- `uupd` orchestration smoke (`tests/system/features/uupd.feature`).

### What this repo explicitly does not validate
- Enrolling contributor laptops as k3s agents or KubeVirt nodes.
- MDM / fleet-dashboard product features.
- Bluetooth, Wi-Fi, or peripheral hardware on client machines.
- Any workload that would require the client to run workflow pods.

### Evidence model
Tests that distinguish cluster-member behavior from client behavior should
label their test environment in artifacts:
```python
write_artifact("cluster-node-info.json",
    json.dumps({"hostname": socket.gethostname(), "role": "cluster-node"}))
```
Client-side bootc assertions run inside ephemeral KubeVirt VMs (not on live
client hardware) so evidence is always VM-scoped and cluster-managed.

---

## 5. Local Hostname and Routing Contract (#73)

### First representative contract

The lab validates the following hostname/routing pattern for exposed in-cluster services:

| Layer | Contract | Evidence |
|---|---|---|
| **Cluster DNS** | `<service>.<namespace>.svc.cluster.local` resolves from within the cluster | `getent hosts` in test pod (`access-dns.txt`) |
| **TLS handshake** | Service on port 8443 completes TLS with a valid certificate | `openssl s_client` output with `Protocol version` (`access-openssl.txt`) |
| **SNI routing** | `Host: <hostname>` header routes to the correct backend | `curl -H "Host: <hostname>"` returns `access-ok` (`access-curl.txt`) |

### Separation of concerns
- **Service discovery** (this contract): cluster DNS + in-cluster reachability.
- **TLS issuance**: tracked separately; current test uses a self-signed cert in the fixture.
- **Auth-gating**: deferred to service-catalog auth-gating lane (#61).
- **External/LAN reachability**: `bluespeed.local` reverse proxy patterns are
  tracked under bluespeed; this repo validates only in-cluster service access.

### Non-goals
- Validating ingress controllers or NodePort exposure from outside the cluster.
- Testing ACME/Let's Encrypt certificate rotation.
- Any LAN hostname that requires mDNS or split-horizon DNS on the workstation.

---

## 6. Known Blockers and Deferred Work

| Issue | Status | Dependency |
|---|---|---|
| #62 RWX / shared-storage | ❌ blocked | NFS CSI or Longhorn installation on ghost |
| #63 GPU transcoding lane | ❌ deferred | GPU passthrough KubeVirt feature gate |
| #61 auth-gated service UI | ❌ deferred | service-catalog baseline lane first |
| #60 first restore drill | ✅ implemented | `homelab-restore-drill` WorkflowTemplate + `tests/homelab_backup/` |
| #84 PVC restore drill with backup artifact | ✅ implemented | `homelab-restore-drill` WorkflowTemplate + `tests/homelab_backup/` |
| Media service lane | ❌ deferred | #62 (shared mount) + #63 (GPU) |
