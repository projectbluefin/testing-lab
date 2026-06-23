# Vanguard Lab Strike Report

Copy this template into a PR comment. Fill in every field with real evidence collected
via MCP tools (`argo-mcp-*`, `kubernetes-mcp-*`). Do not post a report with empty fields.

---

## Lab run

| Field | Value |
|---|---|
| Workflow | `<workflow-name>` (link: `http://192.168.1.102:32746/workflows/argo/<name>`) |
| Phase | `Succeeded` / `Failed` |
| Duration | `<N>m<N>s` |
| Variants tested | `testing` / `lts-testing` / both |
| Suites run | smoke / developer / software / system |

## Results

```
<paste relevant lines from argo-mcp-logs_workflow here>
e.g.:
=== BEHAVE RESULTS JSON ===
{"failed": 0, "passed": 12, "skipped": 0}
```

## Evidence collected via

- [ ] `argo-mcp-get_workflow` — workflow phase and node summary
- [ ] `argo-mcp-logs_workflow` — test output and any errors
- [ ] `kubernetes-mcp-resources_list` — VMI state confirmed Ready
- [ ] `just list-vms` — zero orphaned VMs after teardown

## Blockers / issues filed

- None  
  _or_  
- `projectbluefin/testing-lab#<N>` — <one-line description>
