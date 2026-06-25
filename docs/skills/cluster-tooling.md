---
name: cluster-tooling
description: "Cluster management tools for the testing-lab: helm, kubectl, k3s, zot, and external-secrets. Use when managing cluster state, installing charts, or configuring the OCI registry."
metadata:
  type: reference
  context7-sources:
    - /helm/helm
    - /k3s-io/k3s
    - /project-zot/zot
    - /external-secrets/external-secrets
---

# Cluster Tooling — testing-lab

## Mandatory first step

Before any helm, kubectl, or k3s operation, look up the current API via Context7:

```
resolve-library-id "/helm/helm"  → get-library-docs
resolve-library-id "/k3s-io/k3s" → get-library-docs
```

Do not guess flags or chart schema. The Helm API and k3s config have changed across releases.

## Tool roles

| Tool | Role |
|------|------|
| `k3s` | Lightweight Kubernetes — cluster runtime |
| `helm` | Chart installation and upgrades |
| `kubectl` | Direct cluster inspection and apply |
| `zot` | OCI registry for test artifacts |
| `external-secrets` | Pulls secrets from vault into k8s Secrets |

## Key references

- Cluster topology: `AGENTS.md`
- Bootstrap procedure: `docs/bootstrap.md`
- Recovery: `docs/skills/k3s-cluster-ops` (user skill, load before any cluster recovery)
