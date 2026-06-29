---
name: cluster-tooling
description: "Cluster management tools for the testing-lab: kubectl, k3s, zot, external-secrets, and K8sGPT. Use when managing cluster state, installing cluster add-ons, configuring the OCI registry, or running cluster analysis through MCP."
metadata:
  type: reference
  context7-sources:
    - /helm/helm
    - /k3s-io/k3s
    - /project-zot/zot
    - /external-secrets/external-secrets
    - /k8sgpt-ai/k8sgpt
---

# Cluster Tooling — testing-lab

## Mandatory first step

Before any kubectl, k3s, or K8sGPT operation, look up the current API via Context7:

```
resolve-library-id "/k3s-io/k3s" → get-library-docs
resolve-library-id "/k8sgpt-ai/k8sgpt" → get-library-docs
```

Do not guess flags, chart schema, or MCP method names. The K8sGPT MCP server exposes `analyze`, `cluster-info`, `list-resources`, `get-resource`, `list-namespaces`, `get-logs`, `list-events`, `list-filters`, `add-filters`, `remove-filters`, `list-integrations`, and `config`; verify the current docs before wiring it into a client.

## Tool roles

| Tool | Role |
|------|------|
| `k3s` | Lightweight Kubernetes — cluster runtime |
| `kubectl` | Direct cluster inspection and apply |
| `zot` | OCI registry for test artifacts |
| `external-secrets` | Pulls secrets from vault into k8s Secrets |
| `k8sgpt` | Cluster analysis / MCP troubleshooting bridge |

## Key references

- Cluster topology: `AGENTS.md`
- Bootstrap procedure: `docs/bootstrap.md`
- Recovery: `docs/skills/k3s-cluster-ops` (user skill, load before any cluster recovery)
- K8sGPT MCP config: `~/.copilot/mcp-config.json` on this machine, with `k8sgpt serve --mcp` or `--mcp --mcp-http` as the client target

## K8sGPT usage notes

- Use `k8sgpt analyze --explain` for broad triage.
- Narrow with `--filter=Pod`, `--filter=Deployment`, or `--namespace=<ns>`.
- For assistant integration, prefer the MCP server mode (`k8sgpt serve --mcp`) and register it in Copilot/Claude-style MCP configs.
- Verified source: `/k8sgpt-ai/k8sgpt`
