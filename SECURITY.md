# Security Posture (Homelab)

This is a single-tenant homelab. The trade-offs below are intentional and
accepted for this environment. They are documented here so future agents can
distinguish deliberate decisions from oversights.

## Accepted trade-offs

| Trade-off | Risk accepted | Production fix |
|---|---|---|
| Workflow pods run as `runAsUser: 0` | Required for BIB disk manipulation (losetup, mount, chown), ostree unlock | Rootless podman with user namespaces; separate privileged step with minimal scope |
| `hostNetwork: true` in run-gnome-tests | Required for KubeVirt masquerade networking — VM IPs only route from the host network namespace | Multus secondary network or a CNI that routes pod→VM without hostNetwork |
| hostPath volumes for golden disks | BIB output and reflink clones require direct node filesystem access | CSI driver with btrfs reflink support (none exist today) |
| No NetworkPolicy in `argo` namespace | Workflow pods can reach all cluster services | Restrict egress to argo-server + ghost node IPs; deny inter-pod lateral movement |
| Mutable image tags (`:latest`, `:latest-dev`) | Silent upstream breakage if image changes incompatibly | Pin to digest; add a nightly digest-update workflow |
| `argo-server` ClusterRole | Broad cluster-wide read access for workflow submission | Namespace-scoped RBAC scoped to `argo`, `bluefin-test`, `bluefin-lts-test`, `flatcar-test` |
| `selinux=0` in BLS boot entries | SELinux disabled on test VMs — reduces isolation | Accept for test VMs; production VMs should have SELinux enforcing |
| NodePort 32746 on LAN | Argo API reachable on 192.168.1.0/24 without TLS | TLS termination + token rotation; restrict to specific agent IPs |
| `StrictHostKeyChecking=no` in SSH opts | MITM possible if a VM IP is reused for a different host | Acceptable on isolated homelab VLAN; use known_hosts in production |

## What is NOT a concern in this environment

- **Multi-tenancy**: single user (jorge), single cluster purpose (Bluefin QA)
- **Data sensitivity**: test VMs contain no production data or secrets
- **Compliance scope**: no PCI, HIPAA, or SOC2 requirements
- **Internet exposure**: NodePort 32746 is LAN-only, not internet-facing

## What WOULD change before production use

1. Replace `runAsUser: 0` with a purpose-built privileged init container (min scope)
2. Add NetworkPolicy: deny all → allow only required paths
3. Pin all image tags to digests and automate rotation
4. TLS on argo-server with cert-manager
5. Namespace-scoped RBAC replacing ClusterRole
6. Remove `selinux=0` from BLS entries; enforce SELinux on all VMs
