# Lab Operations Guide

> **Routine work? Load [`agent-cheatsheet.md`](agent-cheatsheet.md) first.** This guide is the expanded operations manual: more context, longer procedures, and explicit decision trees.

Pair with:
- [`agent-cheatsheet.md`](agent-cheatsheet.md) — canonical command reference
- [`../AGENTS.md`](../AGENTS.md) — policy + architecture
- [`../RUNBOOK.md`](../RUNBOOK.md) — timeless architecture + failure modes
- [`../WORKFLOWS.md`](../WORKFLOWS.md) — WorkflowTemplate parameter contracts
- [`dogtail-testing.md`](dogtail-testing.md) — GUI test authoring
- [`vanguard-report-template.md`](vanguard-report-template.md) — PR verification report

---

## 1. The 60-second mental model

```
You ──submit──► Argo Workflow (argo namespace)
                  │
                  ├─ git-sync clones testing-lab @ <branch>
                  ├─ ensure-disk (optional) builds or validates the golden disk
                  ├─ provision-vm creates a fresh KubeVirt VM (skipped for titan runs)
                  ├─ run-gnome-tests SSHes into the VM and runs qecore + behave/pytest
                  └─ teardown deletes the VM and per-run hostDisk clone
```

Two execution paths:

| Path | Speed | Use when |
|---|---|---|
| Titan (persistent) | ~5 min | Iterating on tests or suites |
| Fresh VM (BIB) | ~10–14 min | Validating image, golden-disk, or pre-merge matrix changes |

---

## 2. Picking the right path

```text
Need to validate a test or step change?
  -> just run-titan-smoke
  -> if it passes and the change is high risk: just run-tests-matrix

Need to validate the system suite?
  -> just run-titan-system

Need to validate a golden-disk or image change?
  -> just ensure-disk <tag>
  -> just run-tests-tag <tag>
  -> if both latest and lts matter: just run-tests-matrix

Need to validate Flatcar?
  -> just run-flatcar-smoke

Need to recover a failed titan fast path?
  -> go to §8
```

---

## 3. Every operator command in current use

### 3.1 Test execution

| Command | Effect |
|---|---|
| `just run-tests` | Smoke against `latest` on a fresh VM |
| `just run-tests-tag <tag>` | Smoke against `latest` or `lts` on a fresh VM |
| `just run-tests-matrix` | Run `latest` and `lts` in parallel |
| `just run-titan-smoke` | Smoke against both titan VMs |
| `just run-titan-system` | Atomic OS contract suite against both titan VMs |
| `just run-titan-developer` | Developer suite against both titan VMs |
| `just run-titan-software` | Software suite against both titan VMs |
| `just run-flatcar-smoke` | Flatcar test lane |

### 3.2 Observation

| Command | Effect |
|---|---|
| `just list-workflows` | List workflows in the `argo` namespace |
| `just list-vms` | List VMs in `bluefin-test`, `bluefin-lts-test`, and `flatcar-test` |
| `just logs` | Tail logs from the most recent workflow |
| `just argocd-status` | Show `testing-lab` and `testing-lab-infra` application status |

### 3.3 Maintenance

| Command | Effect |
|---|---|
| `just argocd-sync` | Force ArgoCD reconciliation now |
| `just ensure-disk <tag>` | Build or refresh the golden disk for `latest` or `lts` |
| `just patch-disk <tag>` | Re-apply SSH auth to an existing golden disk |
| `just delete-workflows` | Delete all workflows in `argo` |
| `just delete-vms` | Delete all VMs in `bluefin-test`, `bluefin-lts-test`, and `flatcar-test` |
| `just teardown` | Run `delete-vms` then `delete-workflows` |
| `just lint` | Run `argo lint` on tracked workflow YAML |

### 3.4 Bootstrap

| Command | Effect |
|---|---|
| `just setup-ssh-secret` | Create `bluefin-test-ssh-key` if it does not already exist |
| `just setup-argocd` | Deploy the ArgoCD applications |

---

## 4. Retrieving evidence

### 4.1 Argo logs

```bash
just logs
argo logs <workflow-name> -n argo --no-color
argo logs <workflow-name> -n argo --follow
```

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
Use Argo logs or Loki instead of `kubectl exec`.

---

## 5. Failure triage

Every branch in this section is **command → expected output → next command**. Start with the exact workflow that failed.

### 5.1 `Permission denied (publickey)` during SSH wait

1. `just logs | grep -n "Permission denied (publickey)"`
   - **Expected:** at least one matching line.
   - **Next:** `just patch-disk <tag>` for the tag that failed.
2. `just patch-disk <tag>`
   - **Expected:** the `patch-golden-disk` workflow exits `Succeeded`.
   - **Next:** rerun the failing fresh-VM command (`just run-tests-tag <tag>` or `just run-tests-matrix`).
3. If the retry still fails and the failing target is `just run-titan-*`
   - **Next:** stop and file an issue; titan `authorized_keys` refresh is human-gated.

### 5.2 Workflow timed out while waiting for SSH

1. `just list-vms`
   - **Expected:** the target VM appears in `bluefin-test` or `bluefin-lts-test`.
   - **If the VM is missing:** `argo get <workflow-name> -n argo` and inspect the provisioning step before rerunning.
2. `kubectl get vmi <vm-name> -n <namespace> -o jsonpath='{.status.interfaces[0].ipAddress}{"\n"}'`
   - **Expected:** an IP address.
   - **If blank:** `kubectl get vmi <vm-name> -n <namespace> -o yaml | grep -n 'phase:'` then go to §8 if the VM is a titan, otherwise rerun after the VM becomes Ready.
3. If the VM has an IP but the runner still times out
   - **Next:** `just patch-disk <tag>` and rerun the failing fresh-VM workflow.

### 5.3 `TypeError` mentioning `requireResult`

1. `just logs | grep -n "requireResult"`
   - **Expected:** a traceback line identifying the failing step file.
   - **Next:** open that step and replace `findChild(..., requireResult=...)` with `findChildren(...)` or `findChild(..., retry=False)`.
2. Rerun `just run-titan-smoke`
   - **Expected:** the traceback disappears.
   - **Next:** if green, optionally promote to `just run-tests-matrix`.

### 5.4 All top-bar scenarios fail together

1. `just logs | grep -n "wait_for_shell.py"`
   - **Expected:** the runner copied and invoked `wait_for_shell.py`.
   - **If missing:** fix the runner/template so the file is SCP'd, then rerun.
2. `just logs | grep -n "unsafe_mode"`
   - **Expected:** the session enabled `global.context.unsafe_mode = true`.
   - **If missing:** fix the runner or environment hook, then rerun `just run-titan-smoke`.

### 5.5 `Application "gnome-shell" is running` fails

1. `just logs | grep -n 'Application "gnome-shell" is running'`
   - **Expected:** the failing step appears in the log.
   - **Next:** replace that scenario step with `* GNOME Shell is accessible via AT-SPI`.
2. `just run-titan-smoke`
   - **Expected:** the shell readiness check now passes.

### 5.6 Workflow stuck `Pending`

1. `kubectl get pods -A --field-selector=status.phase=Pending`
   - **Expected:** a list of pending pods.
   - **Next:** identify whether they are `bib-img-*`, `virt-launcher-*`, or runner pods.
2. `kubectl top pods -A --sort-by=cpu | head -10`
   - **Expected:** the current CPU hogs.
   - **Next:** wait for the active BIB workload to finish before submitting more fresh-VM jobs.
3. If orphaned VMs are consuming capacity
   - **Next:** `kubectl create job --from=cronworkflow/orphan-vm-cleanup orphan-$(date +%s) -n argo`

### 5.7 `outputs.result` contains debug text

1. `just logs | grep -n 'outputs.result'`
   - **Expected:** the polluted result string appears in the workflow log.
   - **Next:** edit the offending `script:` template so debug goes to `>&2`.
2. `argo lint argo/workflow-templates/<file>.yaml`
   - **Expected:** lint succeeds.
   - **Next:** push and verify ArgoCD reconciliation via §6.

### 5.8 VM stuck `Terminating`

1. `kubectl get pod -n <namespace> | grep virt-launcher`
   - **Expected:** the launcher pod for the stuck VM is still present.
   - **Next:** `kubectl delete pod <virt-launcher-pod> -n <namespace> --force`.
2. `kubectl get vm <vm-name> -n <namespace>`
   - **Expected:** the VM eventually disappears.
   - **Next:** rerun the workflow if needed.

### 5.9 `run-gnome-tests` pod errors immediately

1. `argo get <workflow-name> -n argo`
   - **Expected:** the failing template or pod name is visible.
   - **Next:** `argo logs <workflow-name> -n argo --no-color | grep -n 'volumes:' -C 2`
2. If the template error shows `volumes:` nested under `container:`
   - **Next:** move `volumes:` to template scope in git, push, then run §6.
3. `argo lint argo/workflow-templates/run-gnome-tests.yaml`
   - **Expected:** lint succeeds before rerun.

### 5.10 Titan has no IP

1. `kubectl get vmi titan-bluefin -n bluefin-test -o jsonpath='{.status.interfaces[0].ipAddress}{"\n"}'`
2. `kubectl get vmi titan-lts -n bluefin-lts-test -o jsonpath='{.status.interfaces[0].ipAddress}{"\n"}'`
   - **Expected:** both commands print an IP.
   - **If either is blank:** go to §8 and run the titan recovery path.

### 5.11 Unknown failure class

1. `just logs`
2. Query Loki for `=== BEHAVE RESULTS JSON ===`
3. Query Loki for `STEP_ERROR`
4. Query Loki for `AT-SPI tree written`
5. `argo get <workflow-name> -n argo`

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
   - **If not:** push first and stop here.
2. `argocd app get testing-lab | grep '^Revision:'`
   - **Expected:** the revision matches or is newer than your commit.
   - **If older:** `just argocd-sync`.
3. `argocd app get testing-lab | grep '^Health Status:'`
   - **Expected:** `Healthy`.
   - **If not Healthy:** `argocd app get testing-lab | sed -n '/Conditions:/,$p'`, fix the rejected field in git, push, then repeat step 2.
4. `kubectl get workflowtemplate <name> -n argo -o yaml | grep <field>`
   - **Expected:** the new value is live.
   - **If still old:** `just argocd-sync && argocd app wait testing-lab --health`.
5. Submit a **new** workflow.
   - **Expected:** the new run sees the new template snapshot.

---

## 7. Load triage

```bash
just list-workflows
kubectl top nodes
kubectl get vmi -A
kubectl get pods -A --field-selector=status.phase=Pending
kubectl top pods -A --sort-by=cpu | head -10
```

Use the output to answer three questions in order:
1. Are one or more `bib-img-*` builds saturating ghost?
2. Are `virt-launcher-*` pods consuming capacity with no corresponding live workflow?
3. Are runner pods pending because CPU or memory is exhausted?

If you answer yes to question 2, run:

```bash
kubectl create job --from=cronworkflow/orphan-vm-cleanup orphan-$(date +%s) -n argo
```

---

## 8. Titan recovery

```bash
just argocd-sync
kubectl get vmi titan-bluefin -n bluefin-test -w
kubectl get vmi titan-lts     -n bluefin-lts-test -w
just run-titan-smoke
```

Expected output sequence:
- ArgoCD sync finishes successfully.
- Each titan VMI publishes an IP.
- `just run-titan-smoke` succeeds.

If the VM objects exist but SSH still fails after key rotation, stop and file an issue for a human operator; titan disk key refresh is not automated.

---

## 9. SSH key rotation

1. Rotate the `bluefin-test-ssh-key` secret.
2. Run `just patch-disk latest` and `just patch-disk lts`.
3. Run `just run-tests-matrix`.
4. Run `just run-titan-smoke`.
5. If the titan path still fails, file an issue for human key injection.

Use the exact command block in [docs/agent-cheatsheet.md](agent-cheatsheet.md) §7.

---

## 10. PR queue mode

1. Run the minimum required lab loop (`just run-titan-smoke` or `just run-tests-matrix` for high-risk work).
2. Collect workflow names, behave summaries, and log excerpts.
3. Post [`vanguard-report-template.md`](vanguard-report-template.md) as a PR comment with real evidence.
4. Only then label / approve / queue.
