# Agent Cheatsheet — read this first, then stop

> Deterministic, recipe-only reference for running the testing-lab cluster.
> Designed to be the **single file a weak-capability agent needs to load** for routine cluster operations.
>
> If your task is not in this file, escalate to:
> - [`docs/lab-operations.md`](lab-operations.md) — long-form procedures
> - [`WORKFLOWS.md`](../WORKFLOWS.md) — WorkflowTemplate parameter contracts
> - [`RUNBOOK.md`](../RUNBOOK.md) — architecture + failure-mode index
> - [`docs/dogtail-testing.md`](dogtail-testing.md) — writing GUI tests
> - [`AGENTS.md`](../AGENTS.md) — hard policy and tenets

> [!WARNING]
> **Use Kubernetes MCP tools for all cluster reads/mutations. Never SSH to ghost from a workstation.** Use Argo MCP for workflow and CronWorkflow inspection/control. The only SSH in this system is **in-cluster**: workflow pods and probe pods SSH into test VMs as the test execution mechanism. Workstation operators and agents have no SSH path to anything.

---

## 1. Command selector — what should I run?

| Situation | Run |
|---|---|
| Validate a smoke test or step change | `just run-tests-tag latest` |
| Validate atomic OS contract checks | Use Argo MCP to submit `bluefin-qa-pipeline` with `suites=system` |
| Validate developer or software suites | Use Argo MCP to submit `bluefin-qa-pipeline` with `suites=developer` or `suites=software` |
| Pre-merge gate / promote a passing matrix run | `just run-tests-matrix` |
| Validate a single Bluefin tag end-to-end | `just run-tests-tag <latest\|lts>` |
| Validate a golden-disk or image change | `just ensure-disk <tag>` then `just run-tests-tag <tag>` |
| Validate the Flatcar lane | `just run-flatcar-smoke` |
| Validate the dakota BST element graph (fast, no build) | `just run-dakota-validate` |
| Build a dakota variant via BST on ghost | `just run-dakota-build [variant=default\|nvidia\|all]` |
| Tail the most recent workflow's logs | `just logs` |
| List workflows / VMs | `just list-workflows` · `just list-vms` |
| ArgoCD status / force sync | `just argocd-status` · `just argocd-sync` |
| Lint Argo YAML | `just lint` |
| Fix missing upstream remote on ghost knuckle repo | `just setup-knuckle-upstream` (one-time) |
| Bootstrap repo-owner workstation access | §9 |

Rule: **if a `just` recipe exists, use it.** Otherwise use Kubernetes MCP / Argo MCP recipes from this guide; do not fall back to workstation `kubectl`/`argo`.

---

## 2. Failure triage — symptom → exact next command

Run `just logs` first. Then match a row:

| Symptom in logs | Run next |
|---|---|
| `Permission denied (publickey)` at SSH wait | `just patch-disk <tag>` → rerun |
| Workflow times out at SSH wait | `just list-vms` → inspect the target VMI IP → if the VMI is Ready but SSH never comes up, `just patch-disk <tag>` |
| `TypeError: ... requireResult` | Fix the step per [`docs/dogtail-testing.md`](dogtail-testing.md) §6.2 (`findChildren(...)` / `retry=False`) |
| `Application "gnome-shell" is running` step fails | Replace it with `* GNOME Shell is accessible via AT-SPI` |
| All top-bar scenarios fail | Confirm `wait_for_shell.py` is present in the copied suite and that the runner re-asserts `unsafe_mode` |
| `outputs.result` is `Waiting...` or other debug text | Send debug output to `>&2`; keep stdout for the result only |
| VM stuck `Terminating` | Use `kubernetes-mcp-pods_delete` on the matching `virt-launcher-*` pod |
| `qemu-img: command not found` (Flatcar prep) | Use `quay.io/fedora/fedora:latest` for the Flatcar prep image |
| `run-gnome-tests` pod errors immediately | Fix the WorkflowTemplate in git; `volumes:` must live at template scope, not under `container:` |
| Workflow stuck `Pending` | Run §3 |
| Template change did not take effect | Run §4 |
| `qa-test-pr.sh`: `fatal: 'upstream' does not appear to be a git repository` | `just setup-knuckle-upstream` (one-time fix) |
| `qa-test-pr.sh`: `gh auth login` prompt | Pass `GH_TOKEN=$(gh auth token)` from the calling machine when invoking the script |

If no row matches:

```text
1. just logs
2. Query Loki for "=== BEHAVE RESULTS JSON ==="
3. Query Loki for "STEP_ERROR"
4. Query Loki for "AT-SPI tree written"
5. argo-mcp-get_workflow <workflow-name>
```

Loki: <http://192.168.1.102:30100>. Pod label: `app.kubernetes.io/part-of=bluefin-test-suite`.

---

## 3. Capacity triage — cluster feels slow

```text
1. just list-workflows
2. kubernetes-mcp-nodes_top
3. kubernetes-mcp-resources_list apiVersion=kubevirt.io/v1 kind=VirtualMachineInstance
4. kubernetes-mcp-pods_list fieldSelector=status.phase=Pending
5. kubernetes-mcp-pods_top all_namespaces=true
```

| Symptom | Action |
|---|---|
| Many `bib-img-*` pods Running | Avoid starting another fresh-VM lane until the current BIB workload finishes |
| Workflows `Pending` | Use `kubernetes-mcp-pods_top` to identify the current CPU hog before submitting more work |
| Many `virt-launcher-*` pods with no corresponding live workflow | Use Kubernetes MCP to create a one-shot cleanup Job from `orphan-vm-cleanup` |

Per-template ceilings live in [`AGENTS.md`](../AGENTS.md) under **Resource Limits**.

---

## 4. ArgoCD — my template change did not take effect

```text
1. git log -1 origin/main -- argo/workflow-templates/<file>
   -> expected: your commit is visible on origin/main.
   -> if not: push first.

2. just argocd-status
   -> expected: `testing-lab` is synced to a revision that matches or post-dates your commit.
   -> if older: just argocd-sync

3. just argocd-status
   -> expected: `testing-lab` is Healthy.
   -> if not Healthy: inspect the reported condition, fix the rejected field in git, push again, then repeat step 2.

4. argo-mcp-get_workflow_template <name>
   -> expected: the new field value is live.
   -> if still old: rerun `just argocd-sync`, wait for health, then re-check.

5. Was the workflow submitted before the reconcile finished?
   -> workflows snapshot the template at submit time.
   -> submit a NEW workflow.
```

Do **not** `kubectl apply` a rejected WorkflowTemplate.

---

## 5. CronWorkflow ops — pause / resume / backfill

```text
Suspend during a debugging session:
- argo-mcp-suspend_cron_workflow nightly-smoke
- argo-mcp-suspend_cron_workflow nightly-smoke-lts

Resume:
- argo-mcp-resume_cron_workflow nightly-smoke
- argo-mcp-resume_cron_workflow nightly-smoke-lts

Backfill / run now:
- Use Kubernetes MCP to create a one-shot Job cloned from `nightly-smoke`, `nightly-smoke-lts`, or `orphan-vm-cleanup`
```

| Name | Schedule (UTC) | Purpose |
|---|---|---|
| `nightly-smoke` | 02:00 | `bluefin-qa-pipeline` (`latest`) |
| `nightly-smoke-lts` | 02:30 | `bluefin-qa-pipeline` (`lts`) |
| `orphan-vm-cleanup` | every 2h | Clean orphan test VMs |

Any patch that must survive beyond a short debug session also needs a matching git change under `manifests/`.

---

## 6. Test-VM key rotation — deliberate, high-risk

This rotates the SSH key used **in-cluster** by workflow pods to reach test VMs. It is not SSH from a workstation — `ssh-keygen` runs locally only to generate key material, which is then stored in a k8s Secret.

```bash
# 1. Generate a new key locally (do not commit it):
ssh_key=$(mktemp)
ssh-keygen -t ed25519 -f "${ssh_key}" -N "" -C "bluefin-test-suite@ghost"

# 2. Replace the secret in-place:
kubectl create secret generic bluefin-test-ssh-key \
  --from-file=id_ed25519="${ssh_key}" \
  --from-file=id_ed25519.pub="${ssh_key}.pub" \
  -n argo --dry-run=client -o yaml | kubectl apply -f -
shred -u "${ssh_key}" "${ssh_key}.pub"

# 3. Patch every existing golden disk:
just patch-disk latest
just patch-disk lts

# 4. Confirm via real runs:
just run-tests-tag latest
just run-tests-tag lts

# 5. Verify the new fingerprint:
kubectl get secret bluefin-test-ssh-key -n argo \
  -o jsonpath='{.data.id_ed25519\.pub}' | base64 -d | ssh-keygen -lf -
```

If `patch-disk` fails because the old key can no longer SSH into the golden disk, rebuild that golden disk with `just ensure-disk <tag>`.

If `patch-disk` succeeds but fresh workflows still fail SSH, file an issue with the failing workflow name, pod name, and log excerpt.

---

## 7. PR queue mode — Vanguard Lab Strike Report

Mandatory gate for `knuckle`, `dakota`, and this repo's PRs.

1. Run the lab loop end-to-end — `just run-tests-tag latest` minimum, `just run-tests-matrix` for high-risk changes.
2. Collect **real evidence** using **MCP tools only** — not bash `argo`/`kubectl` commands:
   - Workflow status/steps → `argo-mcp-get_workflow` / `argo-mcp-list_workflows`
   - Log output → `argo-mcp-logs_workflow`
   - Pod/VMI state → `kubernetes-mcp-pods_get` / `kubernetes-mcp-resources_list`
3. Post the report on the PR using [`docs/vanguard-report-template.md`](vanguard-report-template.md).
4. Only then apply `agent-tested` and approve / queue.

Hard exit checklist:

- [ ] Real VM-backed lab evidence exists.
- [ ] Evidence was collected via MCP tools (not bash CLI fallback).
- [ ] The entire loop was tested, not isolated commands.
- [ ] A canonical Vanguard report with real data is posted on the PR.
- [ ] Any blocker is filed as an issue in the owning repo.

---

## 8. Safe cleanup — what you may delete

| Resource | Safe? |
|---|---|
| VM in `bluefin-test` / `bluefin-lts-test` / `flatcar-test`, with no live workflow | Yes — delete the single VM or run `orphan-vm-cleanup` |
| `just delete-vms` | Only for full teardown when you intentionally accept that all test VMs in those namespaces will be deleted |
| Workflows in `argo` | Yes — `just delete-workflows` |

Single-VM deletion:

```text
Use `kubernetes-mcp-resources_delete` with `apiVersion: kubevirt.io/v1`, `kind: VirtualMachine`, the VM name, and the target namespace.
```

---

## 9. Bootstrap — one-time, fresh cluster access

```bash
just setup-ssh-secret
just setup-argocd
just argocd-sync
just ensure-disk latest
just run-tests-tag latest
```

---

## 10. Self-check before claiming cluster healthy

```text
1. just argocd-status
2. argo-mcp-list_cron_workflows namespace=argo
3. just list-vms
4. just list-workflows
5. just run-tests-tag latest
```

Expected steady state:
- both ArgoCD applications are Synced + Healthy
- all three CronWorkflows are present
- no idle test VMs remain after workflows finish
- the most recent fresh-VM run is green

---

## 11. Discover live cluster facts — do not trust stale docs

| Fact | Command |
|---|---|
| SSH key fingerprint | `kubernetes-mcp-resources_get` the `bluefin-test-ssh-key` Secret, decode `.data.id_ed25519.pub`, then run `ssh-keygen -lf -` locally |
| Live WorkflowTemplate body | `argo-mcp-get_workflow_template <name>` |
| CronWorkflow schedules | `argo-mcp-list_cron_workflows namespace=argo` |
| ArgoCD revision in cluster | `just argocd-status` |
| Pending pods | `kubernetes-mcp-pods_list fieldSelector=status.phase=Pending` |
