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

---

## 1. Command selector — what should I run?

| Situation | Run |
|---|---|
| Validate a smoke test or step change | `just run-titan-smoke` |
| Validate atomic OS contract checks | `just run-titan-system` |
| Validate developer or software suites | `just run-titan-developer` · `just run-titan-software` |
| Pre-merge gate / promote a passing titan run | `just run-tests-matrix` |
| Validate a single Bluefin tag end-to-end | `just run-tests-tag <latest\|lts>` |
| Validate a golden-disk or image change | `just ensure-disk <tag>` then `just run-tests-tag <tag>` |
| Validate the Flatcar lane | `just run-flatcar-smoke` |
| Tail the most recent workflow's logs | `just logs` |
| List workflows / VMs | `just list-workflows` · `just list-vms` |
| ArgoCD status / force sync | `just argocd-status` · `just argocd-sync` |
| Lint Argo YAML | `just lint` |
| Bootstrap a fresh workstation-to-cluster connection | §10 |

Rule: **if a `just` recipe exists, use it.** Submit a `workflowtemplate/...` directly only when the situation is not in this table.

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
| VM stuck `Terminating` | `kubectl delete pod virt-launcher-<vm> -n <ns> --force` |
| `qemu-img: command not found` (Flatcar prep) | Use `quay.io/fedora/fedora:latest` for the Flatcar prep image |
| `run-gnome-tests` pod errors immediately | Fix the WorkflowTemplate in git; `volumes:` must live at template scope, not under `container:` |
| Titan has no IP | Run §5 |
| Workflow stuck `Pending` | Run §3 |
| Template change did not take effect | Run §4 |

If no row matches:

```text
1. just logs
2. Query Loki for "=== BEHAVE RESULTS JSON ==="
3. Query Loki for "STEP_ERROR"
4. Query Loki for "AT-SPI tree written"
5. argo get <workflow-name> -n argo
```

Loki: <http://192.168.1.102:30100>. Pod label: `app.kubernetes.io/part-of=bluefin-test-suite`.

---

## 3. Capacity triage — cluster feels slow

```bash
just list-workflows
kubectl top nodes
kubectl get vmi -A
kubectl get pods -A --field-selector=status.phase=Pending
kubectl top pods -A --sort-by=cpu | head -10
```

| Symptom | Action |
|---|---|
| Many `bib-img-*` pods Running | Avoid starting another fresh-VM lane until the current BIB workload finishes |
| Workflows `Pending` | `kubectl top pods -A --sort-by=cpu | head -10` → identify the hog before submitting more work |
| Many `virt-launcher-*` pods with no corresponding live workflow | `kubectl create job --from=cronworkflow/orphan-vm-cleanup orphan-$(date +%s) -n argo` |

Per-template ceilings live in [`AGENTS.md`](../AGENTS.md) under **Resource Limits**.

---

## 4. ArgoCD — my template change did not take effect

```text
1. git log -1 origin/main -- argo/workflow-templates/<file>
   -> expected: your commit is visible on origin/main.
   -> if not: push first.

2. argocd app get testing-lab | grep '^Revision:'
   -> expected: the revision matches or post-dates your commit.
   -> if older: just argocd-sync

3. argocd app get testing-lab | grep '^Health Status:'
   -> expected: Healthy
   -> if not Healthy: argocd app get testing-lab | sed -n '/Conditions:/,$p'
      fix the rejected field in git, push again, then repeat step 2.

4. kubectl get workflowtemplate <name> -n argo -o yaml | grep <field>
   -> expected: the new field value is live.
   -> if still old: just argocd-sync && argocd app wait testing-lab --health

5. Was the workflow submitted before the reconcile finished?
   -> workflows snapshot the template at submit time.
   -> submit a NEW workflow.
```

Do **not** `kubectl apply` a rejected WorkflowTemplate.

---

## 5. Titan recovery — fast path is down

```bash
just argocd-sync
kubectl get vmi titan-bluefin -n bluefin-test -w
kubectl get vmi titan-lts     -n bluefin-lts-test -w
just run-titan-smoke
```

Expected sequence:
1. `argocd-sync` finishes with both applications Healthy.
2. Each `kubectl get vmi ... -w` stream eventually shows an IP in `.status.interfaces[0].ipAddress`.
3. `just run-titan-smoke` completes successfully.

**Do not rebuild a golden disk to fix a titan.** Titans use separate persistent disks under `/var/home/jorge/VMs/titans/...`.

If titan SSH fails after key rotation, the titan `authorized_keys` refresh path is human-gated — file an issue for a human operator to run the manual key-injection procedure.

---

## 6. CronWorkflow ops — pause / resume / backfill

```bash
# Suspend during a debugging session:
kubectl patch cronworkflow nightly-smoke     -n argo --type=merge -p '{"spec":{"suspend":true}}'
kubectl patch cronworkflow nightly-smoke-lts -n argo --type=merge -p '{"spec":{"suspend":true}}'

# Resume:
kubectl patch cronworkflow nightly-smoke     -n argo --type=merge -p '{"spec":{"suspend":false}}'
kubectl patch cronworkflow nightly-smoke-lts -n argo --type=merge -p '{"spec":{"suspend":false}}'

# Backfill / run now:
kubectl create job --from=cronworkflow/nightly-smoke       backfill-$(date +%s) -n argo
kubectl create job --from=cronworkflow/nightly-smoke-lts   backfill-lts-$(date +%s) -n argo
kubectl create job --from=cronworkflow/orphan-vm-cleanup   orphan-$(date +%s) -n argo
```

| Name | Schedule (UTC) | Purpose |
|---|---|---|
| `nightly-smoke` | 02:00 | `bluefin-qa-pipeline` (`latest`) |
| `nightly-smoke-lts` | 02:30 | `bluefin-qa-pipeline` (`lts`) |
| `orphan-vm-cleanup` | every 2h | Clean orphan test VMs |

Any patch that must survive beyond a short debug session also needs a matching git change under `manifests/`.

---

## 7. SSH key rotation — deliberate, high-risk

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
just run-tests-matrix
just run-titan-smoke

# 5. Verify the new fingerprint:
kubectl get secret bluefin-test-ssh-key -n argo \
  -o jsonpath='{.data.id_ed25519\.pub}' | base64 -d | ssh-keygen -lf -
```

If `patch-disk` fails because the old key can no longer SSH into the golden disk, rebuild that golden disk with `just ensure-disk <tag>`.

If `run-titan-smoke` fails after the secret rotation, stop there: titan `authorized_keys` refresh is human-gated — file an issue for a human operator to run the manual key-injection procedure on the titan disk.

---

## 8. PR queue mode — Vanguard Lab Strike Report

Mandatory gate for `knuckle`, `dakota`, and this repo's PRs.

1. Run the lab loop end-to-end — `just run-titan-smoke` minimum, `just run-tests-matrix` for high-risk changes.
2. Collect **real evidence**: workflow names, behave summary, and log excerpts.
3. Post the report on the PR using [`docs/vanguard-report-template.md`](vanguard-report-template.md).
4. Only then apply `agent-tested` and approve / queue.

Hard exit checklist:

- [ ] Real VM-backed lab evidence exists.
- [ ] The entire loop was tested, not isolated commands.
- [ ] A canonical Vanguard report with real data is posted on the PR.
- [ ] Any blocker is filed as an issue in the owning repo.

---

## 9. Safe cleanup — what you may delete

| Resource | Safe? |
|---|---|
| VM in `bluefin-test` labelled `app=titan-bluefin` | **No.** Never. |
| VM in `bluefin-lts-test` labelled `app=titan-lts` | **No.** Never. |
| Non-titan VM in `bluefin-test` / `bluefin-lts-test` / `flatcar-test`, with no live workflow | Yes — delete the single VM after the label preflight below, or run `orphan-vm-cleanup` |
| `just delete-vms` | Only for full teardown when you intentionally accept that all test VMs in those namespaces will be deleted |
| Workflows in `argo` | Yes — `just delete-workflows` |

Single-VM deletion preflight:

```bash
kubectl get vm <name> -n <ns> -o jsonpath='{.metadata.labels.app}{"\n"}'
# Starts with "titan-"? Stop.
kubectl delete vm <name> -n <ns> --wait=false
```

---

## 10. Bootstrap — one-time, fresh cluster access

```bash
just setup-ssh-secret
just setup-argocd
just argocd-sync
just ensure-disk latest
just run-titan-smoke
```

---

## 11. Self-check before claiming cluster healthy

```bash
just argocd-status
kubectl get cronworkflow -n argo
just list-vms
just list-workflows | head -20
just run-titan-smoke
```

Expected steady state:
- both ArgoCD applications are Synced + Healthy
- all three CronWorkflows are present
- titan VMs are Running
- the most recent fast-path run is green

---

## 12. Discover live cluster facts — do not trust stale docs

| Fact | Command |
|---|---|
| SSH key fingerprint | `kubectl get secret bluefin-test-ssh-key -n argo -o jsonpath='{.data.id_ed25519\.pub}' \| base64 -d \| ssh-keygen -lf -` |
| Titan latest IP | `kubectl get vmi titan-bluefin -n bluefin-test -o jsonpath='{.status.interfaces[0].ipAddress}{"\n"}'` |
| Titan lts IP | `kubectl get vmi titan-lts -n bluefin-lts-test -o jsonpath='{.status.interfaces[0].ipAddress}{"\n"}'` |
| Live WorkflowTemplate body | `kubectl get workflowtemplate <name> -n argo -o yaml` |
| CronWorkflow schedules | `kubectl get cronworkflow -n argo` |
| ArgoCD revision in cluster | `argocd app get testing-lab | grep '^Revision:'` |
