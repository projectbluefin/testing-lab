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

> [!NOTE]
> **CLI-first.** Tool hierarchy: `just` (lifecycle recipes) → `argo`/`kubectl` (cluster ops) → `ssh jorge@ghost` (OS-level only).
> MCP tools are optional — never block on them. One bash call beats a tool search + MCP roundtrip every time.

---

## 1. Command selector — what should I run?

| Situation | Run |
|---|---|
| Validate a smoke test or step change | `just run-tests-tag testing` |
| Validate atomic OS contract checks | `argo submit -n argo --from workflowtemplate/bluefin-qa-pipeline -p suites=system` |
| Validate developer or software suites | `argo submit -n argo --from workflowtemplate/bluefin-qa-pipeline -p suites=developer` |
| Pre-merge gate / promote a passing matrix run | `just run-tests-matrix` |
| Validate a single Bluefin tag end-to-end | `just run-tests-tag <testing\|lts-testing>` |
| Validate released (stable) image | `just run-tests-tag stable` or `just run-tests-tag lts-stable` |
| Validate a golden-disk or image change | `just ensure-disk <tag>` then `just run-tests-tag <tag>` |
| Validate the Flatcar lane | `just run-flatcar-smoke` |
| Check exo-0 kernel canary status (7.1 target) | `kubectl get node exo-0 -o jsonpath='{.status.nodeInfo.kernelVersion}{"\n"}'` |
| Validate the dakota BST element graph (fast, no build) | `just run-dakota-validate` |
| Build a dakota variant via BST on ghost | `just run-dakota-build [variant=default\|nvidia\|all]` |
| Tail the most recent workflow's logs | `just logs` |
| List workflows / VMs | `just list-workflows` · `just list-vms` |
| ArgoCD status / force sync | `just argocd-status` · `just argocd-sync` |
| Lint Argo YAML | `just lint` |
| Bootstrap repo-owner workstation access | §9 |

Rule: **if a `just` recipe exists, use it.** Otherwise use `argo`/`kubectl` directly; do not wait for MCP.

---

## Flatcar kernel lifecycle — quick checks

Use these for lifecycle-state inspection and manual gate runs:

```bash
kubectl get configmap flatcar-kernel-lifecycle-state -n argo -o yaml
argo cron list -n argo | grep flatcar-kernel-gate
argo submit -n argo --from workflowtemplate/flatcar-kernel-gate
```

---

## 2. Failure triage — symptom → exact next command

Run `just logs` first. Then match a row:

| Symptom in logs | Run next |
|---|---|
| `Permission denied (publickey)` at SSH wait | Check `kubectl get vm -n bluefin-test <name> -o yaml \| grep -A10 accessCredentials` — secret must exist. Delete orphaned VM + rerun. |
| Workflow times out at SSH wait | `just list-vms` → confirm VMI is Ready. If SSH port open but auth fails, verify `bluefin-test-ssh-pubkey` secret exists in the VM's namespace: `kubectl get secret -n bluefin-test bluefin-test-ssh-pubkey` |
| LTS VM goes `Stopped` immediately | `bluefin-test-ssh-pubkey` missing from `bluefin-lts-test` — check `manifests/bluefin-test-ssh-pubkey.yaml` covers both namespaces; force ArgoCD sync |
| VMI `NotFound` 1 second after VM creation | Same as above — KubeVirt refused to start VM due to missing accessCredentials secret; VM status will be `Stopped` |
| VM `Stopped` with `FailedCreate: metadata.labels must be no more than 63 characters` | vm-name exceeds K8s label limit. `bluefin-lts-testing-developer-<uuid>` = 67 chars. Fix: use `{{workflow.name}}-{{item}}` in `bluefin-qa-pipeline` (not `{{variant}}-{{item}}-{{uuid}}`). Already fixed in commit `7fca070`. |
| `TypeError: ... requireResult` | Fix the step per [`docs/dogtail-testing.md`](dogtail-testing.md) §6.2 (`findChildren(...)` / `retry=False`) |
| `Application "gnome-shell" is running` step fails | Replace it with `* GNOME Shell is accessible via AT-SPI` |
| All top-bar scenarios fail | Confirm `wait_for_shell.py` is present in the copied suite and that the runner re-asserts `unsafe_mode` |
| `outputs.result` is `Waiting...` or other debug text | Send debug output to `>&2`; keep stdout for the result only |
| VM stuck `Terminating` | `kubectl delete pod -n bluefin-test $(kubectl get pod -n bluefin-test -l kubevirt.io/vm=<name> -o name)` |
| `qemu-img: command not found` (Flatcar prep) | Use `quay.io/fedora/fedora:latest` for the Flatcar prep image |
| exo-0 not on expected 7.1 kernel | `kubectl get node exo-0 -o jsonpath='{.status.nodeInfo.kernelVersion}{"\n"}'` then verify Nebraska packages: `curl -s http://192.168.1.102:30802/api/v1/apps/e96281a6-d1af-4bde-9a0a-97b76e56dc57/packages \| jq '.[-5:]'` |
| Kernel poller keeps retriggering wrong versions | Check state: `kubectl get configmap flatcar-kernel-polling-state -n argo -o yaml` and verify CronWorkflow policy is `Forbid`: `kubectl get cronworkflow flatcar-kernel-poller -n argo -o jsonpath='{.spec.concurrencyPolicy}{"\n"}'` |
| `run-gnome-tests` pod errors immediately | Fix the WorkflowTemplate in git; `volumes:` must live at template scope, not under `container:` |
| Workflow stuck `Pending` | Run §3 |
| Template change did not take effect | Run §4 |

If no row matches:

```text
1. just logs
2. argo logs -n argo <workflow-name> --follow
3. argo get -n argo <workflow-name>
```

---

## 3. Capacity triage — cluster feels slow

```text
1. just list-workflows
2. kubectl top nodes
3. kubectl get vmi -A
4. kubectl get pods -A --field-selector=status.phase=Pending
5. kubectl top pods -A
```

| Symptom | Action |
|---|---|
| Workflows `Pending` | `kubectl top nodes` to identify the current CPU hog before submitting more work |
| Many `virt-launcher-*` pods with no corresponding live workflow | `argo submit -n argo --from workflowtemplate/orphan-vm-cleanup` |

Per-template ceilings live in [`AGENTS.md`](../AGENTS.md) under **Resource Limits**.

---

## 4. ArgoCD — my template change did not take effect

### kubectl handles ALL Argo/ArgoCD resources

**`kubectl get/apply/delete` works for any CRD, including:**

| Resource | apiVersion | kind |
|---|---|---|
| ArgoCD Application | `argoproj.io/v1alpha1` | `Application` |
| Argo Workflow | `argoproj.io/v1alpha1` | `Workflow` |
| Argo CronWorkflow | `argoproj.io/v1alpha1` | `CronWorkflow` |
| Argo WorkflowTemplate | `argoproj.io/v1alpha1` | `WorkflowTemplate` |

**Trigger an ArgoCD sync:**
```bash
KUBECONFIG=~/.kube/bluespeed.yaml kubectl -n argocd annotate application testing-lab \
  argocd.argoproj.io/refresh=normal --overwrite
# or via argocd CLI:
argocd app sync testing-lab
```

**Read ArgoCD Application state:**
```bash
KUBECONFIG=~/.kube/bluespeed.yaml kubectl get application testing-lab-infra -n argocd \
  -o jsonpath='{.status.sync.status} {.status.health.status}'
```
Key fields: `.status.operationState.phase`, `.status.sync.status`, `.status.operationState.message`, `.status.operationState.operation.sync.revision`

**Cancel a stuck operation** (PreSync hook looping):
```bash
KUBECONFIG=~/.kube/bluespeed.yaml kubectl patch application testing-lab -n argocd \
  --type=json -p='[{"op":"remove","path":"/operation"}]'
```

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

4. argo template get -n argo <name>
   -> expected: the new field value is live.
   -> if still old: rerun `just argocd-sync`, wait for health, then re-check.

5. Was the workflow submitted before the reconcile finished?
   -> workflows snapshot the template at submit time.
   -> submit a NEW workflow.
```

Do **not** `kubectl apply` a rejected WorkflowTemplate.

---

## 5. CronWorkflow ops — pause / resume / backfill

```bash
# List all cron workflows
argo cron list -n argo

# Suspend during a debugging session:
argo cron suspend nightly-smoke -n argo
argo cron suspend nightly-smoke-lts -n argo

# Resume:
argo cron resume nightly-smoke -n argo
argo cron resume nightly-smoke-lts -n argo

# Backfill / run now:
argo submit -n argo --from cronworkflow/nightly-smoke
argo submit -n argo --from cronworkflow/orphan-vm-cleanup
```

| Name | Schedule (UTC) | Purpose |
|---|---|---|
| `nightly-smoke` | 02:00 | `bluefin-qa-pipeline` (`testing`) |
| `nightly-smoke-lts` | 02:30 | `bluefin-qa-pipeline` (`lts-testing`) |
| `orphan-vm-cleanup` | every 2h | Clean orphan test VMs |

Any patch that must survive beyond a short debug session also needs a matching git change under `manifests/`.

---

## 6. Test-VM key rotation — deliberate, high-risk

This rotates the SSH key used **in-cluster** by workflow pods to reach test VMs. It is not SSH from a workstation — `ssh-keygen` runs locally only to generate key material, which is then stored in a k8s Secret.

```bash
# 1. Generate a new key locally (do not commit it):
ssh_key=$(mktemp)
ssh-keygen -t ed25519 -f "${ssh_key}" -N "" -C "bluefin-test-suite@ghost"

# 2. Replace the client secret (used by workflow pods to SSH into VMs):
kubectl create secret generic bluefin-test-ssh-key \
  --from-file=id_ed25519="${ssh_key}" \
  --from-file=id_ed25519.pub="${ssh_key}.pub" \
  -n argo --dry-run=client -o yaml | kubectl apply -f -

# 3. Replace the server-side public key (used by KubeVirt accessCredentials
#    to inject authorized_keys into VMs via QEMU guest agent):
PUB_KEY=$(cat "${ssh_key}.pub")
kubectl create secret generic bluefin-test-ssh-pubkey \
  --from-literal="key=${PUB_KEY}" \
  -n bluefin-test --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic bluefin-test-ssh-pubkey \
  --from-literal="key=${PUB_KEY}" \
  -n bluefin-lts-test --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null || true

shred -u "${ssh_key}" "${ssh_key}.pub"

# 4. Update manifests/bluefin-test-ssh-pubkey.yaml with the new base64 key
#    so ArgoCD manages the secret going forward.

# 5. Confirm via real runs:
just run-tests-tag testing
just run-tests-tag lts-testing

# 6. Verify the new fingerprint:
kubectl get secret bluefin-test-ssh-key -n argo \
  -o jsonpath='{.data.id_ed25519\.pub}' | base64 -d | ssh-keygen -lf -
```

SSH key rotation now has two parts:
- `bluefin-test-ssh-key` (argo ns): private+public key for the SSH client (workflow pods)
- `bluefin-test-ssh-pubkey` (VM ns): public key for KubeVirt accessCredentials injection

`patch-disk` is no longer needed — SSH keys are injected at VM boot time via KubeVirt
qemuGuestAgent accessCredentials, not baked into the disk image.

---

## 7. PR queue mode — Vanguard Lab Strike Report

Mandatory gate for `knuckle`, `dakota`, and this repo's PRs.

1. Run the lab loop end-to-end — `just run-tests-tag testing` minimum, `just run-tests-matrix` for high-risk changes.
2. Collect **real evidence** using CLI tools:
   - Workflow status/steps → `argo get -n argo <name>` / `argo list -n argo`
   - Log output → `argo logs -n argo <name>`
   - Pod/VMI state → `kubectl get pods -n argo` / `kubectl get vmi -A`
3. Post a report on the PR using the template at [`docs/vanguard-report-template.md`](vanguard-report-template.md).
4. Only then apply `agent-tested` and approve / queue.

Hard exit checklist:

- [ ] Real VM-backed lab evidence exists.
- [ ] Evidence was collected via CLI tools (`argo`, `kubectl`).
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

```bash
kubectl delete vm -n bluefin-test <name>
```

---

## 9. Bootstrap — one-time, fresh cluster access

```bash
just setup-ssh-secret
just setup-argocd
just argocd-sync
just ensure-disk testing
just run-tests-tag testing
```

---

## 10. Self-check before claiming cluster healthy

```bash
1. just argocd-status
2. argo cron list -n argo
3. just list-vms
4. just list-workflows
5. just run-tests-tag testing
```

Expected steady state:
- both ArgoCD applications are Synced + Healthy
- all three CronWorkflows are present
- no idle test VMs remain after workflows finish
- the most recent fresh-VM run is green

---

## 11. ARC runners (GitHub Actions on ghost)
When no jobs are queued, `arc-runners` namespace is empty — that is correct.
Runners are ephemeral and only exist while a job is running.

**Check ARC is healthy:**
```bash
kubectl get pods -n arc-systems
```
Expected: `arc-systems-gha-rs-controller-*` Running + `ghost-runners-*-listener` Running.

**Check a runner set is registered:**
```bash
kubectl get autoscalingrunnersets -n arc-runners
```
Expected: `ghost-runners` with MINIMUM=0 MAXIMUM=4.

**If listener is missing** (arc-systems has only the controller pod, no listener):
1. Check controller logs: `kubectl logs -n arc-systems <controller-pod>`
2. If error is `no route to host` / DNS failure: the controller landed on bazzite (bazzite has no cluster DNS — ARC controller must run on ghost).
   Delete the controller pod — it will reschedule to ghost where DNS works.
3. If error is GitHub API auth failure: check `arc-github-secret` exists in `arc-runners`.

**Trigger a workflow using ARC:**
Add `runs-on: ghost-runners` to any projectbluefin workflow. A listener pod and
ephemeral runner pod will appear in `arc-systems` and `arc-runners` respectively
for the duration of the job.

**ArgoCD Applications for ARC** (stored in `argocd/`, applied manually once):
- `arc-systems` — controller (gha-runner-scale-set-controller 0.9.3)
- `arc-runners` — scale set pointing at `https://github.com/projectbluefin`

**GitHub App:** `bluefin-ghost-arc` (App ID 4099840, Installation 141458121)
installed on the `projectbluefin` org. Credentials in `arc-github-secret`
(namespace `arc-runners`) — never replace with a PAT.

---

## 12. Discover live cluster facts — do not trust stale docs

| Fact | Command |
|---|---|
| SSH key fingerprint | `kubectl get secret bluefin-test-ssh-key -n argo -o jsonpath='{.data.id_ed25519\.pub}' \| base64 -d \| ssh-keygen -lf -` |
| Live WorkflowTemplate body | `argo template get -n argo <name>` |
| CronWorkflow schedules | `argo cron list -n argo` |
| ArgoCD revision in cluster | `just argocd-status` |
| Pending pods | `kubectl get pods -A --field-selector=status.phase=Pending` |

---

## 13. llm-d hive node — local model inference

Ghost runs an OpenAI-compatible inference server at **`http://192.168.1.102:30800`**.
Model: `Qwen/Qwen3.6-35B-A3B` Q4_K_M GGUF via `ghcr.io/ggml-org/llama.cpp:server-rocm` (~60 tok/s, gfx1151).
Namespace: `llm-d`. Managed by GitOps (`testing-lab-infra` ArgoCD app).

**Check status:**
```bash
kubectl get pods -n llm-d
```

**Test the API:**
```bash
curl http://192.168.1.102:30800/v1/models
curl http://192.168.1.102:30800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen3.6-35B-A3B","messages":[{"role":"user","content":"hello"}]}'
```

**If pod is stuck Pending:** Check two things:
1. AMD ROCm device plugin registered: `kubectl get pods -n kube-system | grep amdgpu` — look for `amdgpu-device-plugin`. After a k3s restart the plugin needs a pod delete/respawn to re-register with kubelet. Verify `amd.com/gpu` appears in `kubectl get node ghost -o jsonpath='{.status.allocatable}'`.
2. Memory fits: ghost has ~62.5Gi allocatable. Manifest requests 48Gi — check for other large pods consuming RAM if you see `Insufficient memory`.

**If k3s is down** (kubectl returns "connection refused"):
k3s can stop after host sleep/resume. Recovery:
```bash
ssh jorge@ghost "sudo systemctl start k3s"
```
After restart, delete the `amdgpu-device-plugin` pod so it re-registers with the new kubelet socket.

**kubelet device-plugin socket path:** `/var/lib/kubelet/device-plugins/kubelet.sock` (standard path — NOT the rancher/k3s path). Verify with: `ssh jorge@ghost "sudo ss -lx | grep kubelet"`.

**If pod is CrashLoopBackOff:** Check init container logs first — it downloads the GGUF on first start:
```bash
kubectl logs -n llm-d <pod-name> -c download-gguf
```
The GGUF (`Qwen3.6-35B-A3B-Q4_K_M.gguf`) is cached at `/var/tmp/llm-models/` on ghost.
If the file is missing, delete the pod and let the init container re-download it (~21GB from HuggingFace).

**Key constraints:**
- `ROCBLAS_USE_HIPBLASLT=1` for best matmul throughput on gfx1151 (strixhalo.wiki)
- `hostNetwork: true` + `hostIPC: true` required for ROCm IPC
- `HSA_OVERRIDE_GFX_VERSION=11.5.1` required — gfx1151 is RDNA 3.5, not RDNA 4
- Qwen3 uses chain-of-thought thinking by default; add `/no_think` prefix or increase `max_tokens`

---

## 14. Node onboarding — adding a worker to the cluster

All nodes in this cluster run immutable Linux (Bluefin, Dakota, Bazzite — ostree-based).
`/usr/local/bin` is a symlink to `/var/usrlocal/bin` (the writable overlay). The k3s install
script must be told to use this path or it fails on a fresh system.

### Get the join token (run from ghost or this workstation)

```bash
ssh jorge@192.168.1.102 "sudo cat /var/lib/rancher/k3s/server/node-token"
```

### Bootstrap a new worker node (run ON the new node, with sudo)

```bash
# 1. Ensure writable bin directory exists (required on ostree/immutable Linux)
sudo mkdir -p /var/usrlocal/bin

# 2. Install k3s agent — joins the cluster immediately
curl -sfL https://get.k3s.io | \
  K3S_URL="https://192.168.1.102:6443" \
  K3S_TOKEN="<token from above>" \
  INSTALL_K3S_BIN_DIR="/var/usrlocal/bin" \
  sh -s -

# 3. Disable auto-start — nodes opt in to the cluster (see Justfile below)
sudo systemctl disable k3s-agent

# 4. Install sleep inhibitor (prevents suspend while k3s is active — critical for laptops)
sudo tee /etc/systemd/system/k3s-sleep-inhibit.service << 'EOF'
[Unit]
Description=Inhibit sleep while k3s agent is running
BindsTo=k3s-agent.service
After=k3s-agent.service

[Service]
Type=simple
ExecStart=/usr/bin/systemd-inhibit --what=sleep:handle-lid-switch --who=k3s --why="k3s running - use just k8s-off before travel" --mode=block sleep infinity
Restart=on-failure
RestartSec=5
EOF

sudo mkdir -p /etc/systemd/system/k3s-agent.service.d
sudo tee /etc/systemd/system/k3s-agent.service.d/sleep-inhibit.conf << 'EOF'
[Unit]
Wants=k3s-sleep-inhibit.service
EOF

sudo systemctl daemon-reload
```

### Install the cluster Justfile in the node's home directory

```bash
cat > ~/Justfile << 'EOF'
# Cluster controls — opt in/out of the ghost k3s cluster
# k8s-on  — join the cluster (laptop stays awake while connected)
# k8s-off — leave the cluster (safe to travel, close lid, suspend)

k8s-on:
    sudo systemctl enable --now k3s-agent
    @echo "k3s agent started — sleep/lid inhibited while connected"

k8s-off:
    sudo systemctl stop k3s-agent
    sudo systemctl disable k3s-agent
    @echo "k3s agent stopped — normal sleep restored"

k8s-status:
    @systemctl is-active k3s-agent 2>/dev/null && echo "k8s: ON (inhibiting sleep)" || echo "k8s: OFF (normal sleep)"
EOF
```

### Label the node and verify

```bash
# From workstation / ghost
KUBECONFIG=~/.kube/bluespeed.yaml kubectl label node <hostname> \
  node-role.kubernetes.io/worker=true --overwrite

KUBECONFIG=~/.kube/bluespeed.yaml kubectl get nodes -o wide
```

Expected: new node appears as `Ready  worker`.

### Passwordless sudo for agents (required for non-interactive SSH management)

On the new node, the `jorge-nopasswd` sudoers file must sort AFTER `wheel` and include `!requiretty`:

```bash
sudo bash -c 'echo -e "Defaults:jorge !requiretty\njorge ALL=(ALL) NOPASSWD: ALL" \
  > /etc/sudoers.d/zzz-jorge && chmod 440 /etc/sudoers.d/zzz-jorge'
```

### Node offboarding — removing a worker

```bash
# 1. Drain the node (from workstation)
KUBECONFIG=~/.kube/bluespeed.yaml kubectl drain <hostname> \
  --ignore-daemonsets --delete-emptydir-data

# 2. Delete from cluster
KUBECONFIG=~/.kube/bluespeed.yaml kubectl delete node <hostname>

# 3. On the node itself (optional cleanup)
sudo /var/usrlocal/bin/k3s-agent-uninstall.sh
```

### Key facts for immutable Linux nodes

- **Binary path:** `/var/usrlocal/bin/k3s` — always set `INSTALL_K3S_BIN_DIR=/var/usrlocal/bin`
- **Flannel backend:** `host-gw` — pure L2 routes, no VXLAN/WireGuard kernel modules needed
- **All nodes must be on 192.168.1.0/24** for host-gw to work
- **Upgrades:** handled by system-upgrade-controller via `manifests/k3s-upgrade-plans.yaml` — ArgoCD manages it
- **Version skew rule:** agents must never be newer than the server (ghost)
