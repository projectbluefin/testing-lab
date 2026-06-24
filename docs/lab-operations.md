# Lab Operations Guide

> **Routine work? Load [`agent-cheatsheet.md`](agent-cheatsheet.md) first.** This guide is the expanded operations manual: more context, longer procedures, and explicit decision trees.

Pair with:
- [`agent-cheatsheet.md`](agent-cheatsheet.md) — canonical command reference
- [`../AGENTS.md`](../AGENTS.md) — policy + architecture
- [`../RUNBOOK.md`](../RUNBOOK.md) — timeless architecture + failure modes
- [`../WORKFLOWS.md`](../WORKFLOWS.md) — WorkflowTemplate parameter contracts
- [`dogtail-testing.md`](dogtail-testing.md) — GUI test authoring
- [`vanguard-report-template.md`](vanguard-report-template.md) — PR verification report

> [!WARNING]
> **Use Kubernetes MCP tools for all cluster reads/mutations.** Use Argo MCP or repo-owner `just` wrappers for workflow control. The only acceptable SSH path in this repo is **in-cluster** access from workflow/probe pods into test VMs when the test harness or post-mortem artifact collection requires it.
>
> **Exception:** SSH to ghost is permitted exclusively to start or stop the `k3s` service — you cannot stop the API server via the API itself. See [§ Turning k8s on/off](#turning-k8s-onoff).

---

## 1. The 60-second mental model

```text
You ──submit──► Argo Workflow (argo namespace)
                  │
                  ├─ git-sync clones testing-lab @ <branch>
                  ├─ ensure-disk (optional) builds or validates the golden disk
                  ├─ provision-vm creates a fresh KubeVirt VM
                  ├─ run-gnome-tests SSHes into the VM and runs qecore + behave/pytest
                  └─ teardown deletes the VM and per-run hostDisk clone
```

The normal operator path is now **fresh-VM only**. Persistent titan recovery flows are gone.

---

## 2. Picking the right path

| Goal | Preferred path |
|---|---|
| Validate a smoke test or step change | `just run-tests-tag testing` |
| Validate atomic OS contract checks | Use Argo MCP to submit `bluefin-qa-pipeline` with `suites=system` |
| Validate developer or software suites | Use Argo MCP to submit `bluefin-qa-pipeline` with `suites=developer` or `suites=software` |
| Validate a golden-disk or image change | `just ensure-disk <tag>` then `just run-tests-tag <tag>` |
| Pre-merge gate / promote a passing matrix run | `just run-tests-matrix` |
| Validate Flatcar | `just run-flatcar-smoke` |
| Validate dakota BST graph | `just run-dakota-validate` |
| Build a dakota variant on ghost | `just run-dakota-build [variant=default|nvidia|all]` |

Rule: if a `just` recipe exists, use it. Otherwise use MCP, not workstation `kubectl`/`argo`.

---

## 3. Repo-owner wrappers vs. agent paths

The `Justfile` intentionally keeps local `kubectl` / `argo` convenience wrappers for the repo owner.
Those wrappers are acceptable for Jorge on the workstation, but they are **not** the agent/autonomous path.

For agents and automated systems:
- Workflow reads / logs / control → Argo MCP
- Pod, VM, Secret, and node reads / mutations → Kubernetes MCP
- GitOps changes → edit tracked YAML, push to git, let ArgoCD reconcile
- No SSH to ghost, exo-1, or any node — except `sudo systemctl start|stop k3s` on ghost (see below)

---

## 4. Retrieving evidence

### 4.1 Workflow status and logs

Use MCP first:
- `argo-mcp-list_workflows`
- `argo-mcp-get_workflow`
- `argo-mcp-logs_workflow`
- `argo-mcp-list_workflow_templates`

Repo-owner wrapper when needed:
- `just logs`
- `just list-workflows`

### 4.2 Loki queries

Loki is at <http://192.168.1.102:30100>. Pods carry `app.kubernetes.io/part-of=bluefin-test-suite`.

| What you want | Loki query |
|---|---|
| Full behave JSON | `{app_kubernetes_io_part_of="bluefin-test-suite"} |= "=== BEHAVE RESULTS JSON ==="` |
| Step traceback | `{app_kubernetes_io_part_of="bluefin-test-suite"} |= "STEP_ERROR"` |
| AT-SPI tree dump | `{app_kubernetes_io_part_of="bluefin-test-suite"} |= "AT-SPI tree written"` |
| Variant filter | `{bluefin_io_variant="lts"}` |
| Suite filter | `{bluefin_io_suite="developer"}` |

### 4.3 Runner artifacts

The runner echoes `results.json`, `pytest-results.xml`, and `atspi_tree.txt` into pod stderr before exit.
Use Argo logs or Loki instead of shelling into pods.

### 4.4 Updating files without workstation `scp`

If you need to push helper files or test content into the cluster, do **not** `scp` them to ghost or exo-1 from a workstation. Use a ConfigMap plus a short-lived Job created through Kubernetes MCP (`kubernetes-mcp-resources_create_or_update`):

1. Create or update a ConfigMap containing the files.
2. Create a Job pinned to the target node that mounts the ConfigMap and copies its contents into the required hostPath or workload volume.
3. Wait for the Job to complete, then clean it up if it was ad hoc.

This keeps file staging API-driven and works even when node SSH is unavailable.

---

## 5. Failure triage

Start with the exact workflow that failed.

### 5.1 `Permission denied (publickey)` during SSH wait

SSH key injection now uses KubeVirt `accessCredentials` — not disk injection.

1. Confirm the `bluefin-test-ssh-pubkey` secret exists in the VM's namespace:
   ```bash
   kubectl get secret -n bluefin-test bluefin-test-ssh-pubkey
   ```
   - **Expected:** secret exists.
   - **If missing:** `kubectl apply -f manifests/bluefin-test-ssh-pubkey.yaml` and rerun.
2. Confirm `accessCredentials` is present in the VM spec:
   ```bash
   kubectl get vm -n bluefin-test <name> -o yaml | grep -A10 accessCredentials
   ```
   - **Expected:** `qemuGuestAgent` propagation with `users: [root]`.
3. Confirm qemu-guest-agent is running in the VM (required for injection).
4. Delete the orphaned VM and rerun the workflow.

### 5.2 Workflow timed out while waiting for SSH

1. `just list-vms`
   - **Expected:** the target VM appears in `bluefin-test`, `bluefin-lts-test`, or `flatcar-test`.
2. Use `kubernetes-mcp-resources_get` for the `VirtualMachineInstance`.
   - **Expected:** the VMI is Ready and reports an IP address.
3. If the VMI is Ready but SSH never comes up:
   - Check `bluefin-test-ssh-pubkey` secret and `accessCredentials` in VM spec (see §5.1).
   - Delete the VM and rerun.

### 5.3 `TypeError` mentioning `requireResult`

1. `just logs | grep -n "requireResult"`
   - **Expected:** a traceback line identifying the failing step file.
2. Replace `findChild(..., requireResult=...)` with `findChildren(...)` or `findChild(..., retry=False)`.
3. Rerun the relevant fresh-VM workflow.

### 5.4 All top-bar scenarios fail together

1. `just logs | grep -n "wait_for_shell.py"`
   - **Expected:** the runner copied and invoked `wait_for_shell.py`.
2. `just logs | grep -n "unsafe_mode"`
   - **Expected:** the session enabled `global.context.unsafe_mode = true`.
3. If either check is missing:
   - **Next:** fix the runner/template in git, push, and submit a new workflow.

### 5.5 `Application "gnome-shell" is running` fails

1. `just logs | grep -n 'Application "gnome-shell" is running'`
   - **Expected:** the failing step appears in the log.
2. Replace that scenario step with `* GNOME Shell is accessible via AT-SPI`.
3. Rerun the affected fresh-VM workflow.

### 5.6 Workflow stuck `Pending`

1. `just list-workflows`
2. `kubernetes-mcp-nodes_top`
3. `kubernetes-mcp-pods_list fieldSelector=status.phase=Pending`
4. `kubernetes-mcp-pods_top all_namespaces=true`
5. If orphaned `virt-launcher-*` capacity is the problem:
   - **Next:** use Kubernetes MCP to create a one-shot Job cloned from `orphan-vm-cleanup`.

### 5.7 `outputs.result` contains debug text

1. `just logs | grep -n 'outputs.result'`
   - **Expected:** the polluted result string appears in the workflow log.
2. Edit the offending `script:` template so debug goes to `>&2`.
3. Run `just lint`, push, and verify ArgoCD reconciliation.

### 5.8 VM stuck `Terminating`

1. Use `kubernetes-mcp-pods_list_in_namespace` to find the matching `virt-launcher-*` pod.
2. Delete that pod with `kubernetes-mcp-pods_delete`.
3. Re-check the VM with `kubernetes-mcp-resources_get`.

### 5.9 `run-gnome-tests` pod errors immediately

1. `argo-mcp-get_workflow <workflow-name>`
   - **Expected:** the failing template or pod name is visible.
2. `argo-mcp-logs_workflow <workflow-name>`
   - **Expected:** enough detail to identify the bad template field.
3. If `volumes:` is nested under `container:`:
   - **Next:** move it to template scope in git, push, and run `just lint`.

### 5.10 Unknown failure class

1. `just logs`
2. Query Loki for `=== BEHAVE RESULTS JSON ===`
3. Query Loki for `STEP_ERROR`
4. Query Loki for `AT-SPI tree written`
5. `argo-mcp-get_workflow <workflow-name>`

Expected outcome: after step 4 or 5 you should have a concrete failing template, step, or VM phase to route back into one of the branches above.

---

## 6. ArgoCD operations

### 6.1 What ArgoCD owns

| Application | Syncs |
|---|---|
| `testing-lab` | `argo/workflow-templates/*.yaml` |
| `testing-lab-infra` | `manifests/*.yaml` |

### 6.2 Decision tree — my template change did not take effect

1. `git log -1 origin/main -- argo/workflow-templates/<file>`
   - **Expected:** the output includes your commit.
2. `just argocd-status`
   - **Expected:** `testing-lab` is synced to a revision that matches or post-dates your commit.
   - **If older:** `just argocd-sync`.
3. `just argocd-status`
   - **Expected:** `testing-lab` is Healthy.
4. `argo-mcp-get_workflow_template <name>`
   - **Expected:** the new value is live.
5. Submit a **new** workflow.
   - **Expected:** the new run sees the new template snapshot.

Do **not** `kubectl apply` a rejected WorkflowTemplate.

---

## 7. Load triage

Use these in order:
1. `just list-workflows`
2. `kubernetes-mcp-nodes_top`
3. `kubernetes-mcp-resources_list apiVersion=kubevirt.io/v1 kind=VirtualMachineInstance`
4. `kubernetes-mcp-pods_list fieldSelector=status.phase=Pending`
5. `kubernetes-mcp-pods_top all_namespaces=true`

Answer three questions in order:
1. Are one or more `build-containerdisk-*` pods saturating ghost?
2. Are `virt-launcher-*` pods consuming capacity with no corresponding live workflow?
3. Are runner pods pending because CPU or memory is exhausted?

---

## 8. SSH key rotation

The key rotation flow is still valid because it manages the **in-cluster** test-access secret, not workstation SSH.
Use the exact command block in [docs/agent-cheatsheet.md](agent-cheatsheet.md) §6.

After rotation:
1. Update `manifests/bluefin-test-ssh-pubkey.yaml` with the new base64-encoded public key and push to main.
2. Run `just run-tests-tag testing` and `just run-tests-tag lts-testing`.
3. If fresh workflows still fail SSH, verify the `bluefin-test-ssh-pubkey` secret was updated and ArgoCD synced it.

---

## 9. PR queue mode

1. Run the minimum required lab loop (`just run-tests-tag testing`; use `just run-tests-matrix` for high-risk work).
2. Collect workflow names, behave summaries, and log excerpts via MCP.
3. Post [`vanguard-report-template.md`](vanguard-report-template.md) as a PR comment with real evidence.
4. Only then label / approve / queue.

---

## 10. Turning k8s on/off

The **only** legitimate reason to SSH from a workstation to ghost is to start or stop the `k3s` service. The API server cannot shut itself down — SSH is required.

```bash
# Stop all of Kubernetes (API, etcd, all pods go down)
ssh jorge@192.168.1.102 "sudo systemctl stop k3s"

# Start it back up
ssh jorge@192.168.1.102 "sudo systemctl start k3s"

# Verify
ssh jorge@192.168.1.102 "sudo systemctl is-active k3s"
```

Everything else — pod management, workflow control, ConfigMaps, scaling — goes through MCP. No other workstation SSH to ghost is permitted.
