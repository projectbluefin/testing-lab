# Cluster MCP servers

In-cluster MCP server that lets agents (Claude Code, etc.) drive the lab
without SSH to ghost and without a local kubeconfig.

| Server | URL | Backing project |
|---|---|---|
| `k8s` | http://192.168.1.102:32767/sse | [containers/kubernetes-mcp-server](https://github.com/containers/kubernetes-mcp-server) |

Argo Workflows is driven through the same server — its ClusterRole grants
`get/list/watch/create/delete` on `argoproj.io` `Workflows`, `WorkflowTemplates`,
and `CronWorkflows`. No separate Argo MCP server is needed.

## Register with Claude Code

```sh
claude mcp add --transport sse k8s http://192.168.1.102:32767/sse
claude mcp list  # `k8s` should report ✓ Connected
```

## Permissions model

Scoped ClusterRole — no cluster-admin. RBAC:

- core/apps/batch: read-only (pods, services, deployments, jobs, events, ...)
- argoproj.io: read + create/delete on Workflow (so agents can submit and
  clean up runs); WorkflowTemplate stays read-only (edits go via GitOps)
- kubevirt.io: read-only

Tighten further once usage patterns are clear — see ADR 0001
(`docs/adr/0001-homelab-scale-cncf-minimalism.md`).

## Why no Argo-native MCP server?

The available Argo Workflows MCP servers (`Heapy/argo-workflows-mcp`,
`kushthedude/argo-workflows-mcp`) are **stdio-only** — they're designed to be
launched per-session as a local container, not deployed as a cluster Service.
Wrapping one in a stdio→SSE bridge is more moving parts than the
kubernetes-mcp-server's built-in CRD coverage warrants. Revisit if an
SSE-native Argo MCP server appears.
