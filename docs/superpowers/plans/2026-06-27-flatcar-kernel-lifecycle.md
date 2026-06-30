# Flatcar Kernel Lifecycle Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an end-to-end Flatcar kernel lifecycle where exo-0 validates the rebuilt 7.1.x kernel (with USB4/Thunderbolt support for the 40Gbps mesh) first for 24h and successful candidates are then promoted cluster-wide via the existing Nebraska service.

**Architecture:** Keep a single `GROUP=stable` for all Flatcar nodes and enforce canary behavior as workflow policy. The poller detects upstream versions, build workflow registers candidate packages, and a new gate workflow evaluates exo-0 health for 24h before promotion. Promotion and rollback are explicit state transitions recorded in a ConfigMap.

**Tech Stack:** Argo Workflows/CronWorkflows, Kubernetes ConfigMap state, Nebraska package API, Flatcar update_engine, `kubectl`/`curl`/`jq`

## Current execution status (2026-06-29)

- Day 4: no successful `flatcar-kernel-build` completion yet.
- Recent dominant failure mode: long-running `build-kernel` executions timing out or being terminated before artifact registration.
- Immediate corrective baseline in git: extend kernel build workflow timeout to 6h and remove duplicate tighter step-level deadline.
- Until one successful build is recorded, treat this as a release blocker for the 7.1 USB4/Thunderbolt rollout.

## Global Constraints

- Use one Flatcar update group: `GROUP=stable` for all nodes.
- Canary policy is exo-0-first with a strict 24h health window.
- Gate pass conditions: exo-0 Ready, flatcar-update pods healthy, one successful update/reboot validation.
- Keep lifecycle cluster-hosted (Nebraska + package hosting on-cluster).
- Never `kubectl apply` WorkflowTemplates or manifests directly; edit git-tracked YAML and let ArgoCD reconcile.
- Use `just lint` after changing `argo/` or `manifests/`.

---

### Task 1: Add lifecycle state contract

**Files:**
- Create: `manifests/flatcar-kernel-lifecycle-state.yaml`
- Modify: `docs/skills/flatcar-node-onboarding.md`
- Modify: `docs/agent-cheatsheet.md`

**Interfaces:**
- Produces: ConfigMap `flatcar-kernel-lifecycle-state` (namespace `argo`) with keys:
  - `candidate-version` (string)
  - `candidate-package` (string)
  - `candidate-created-at` (RFC3339)
  - `gate-status` (`pending|pass|fail`)
  - `stable-version` (string)
  - `stable-package` (string)
- Consumes: existing Nebraska package records (`filename`, `version`)

- [ ] **Step 1: Create the lifecycle state manifest**

```yaml
# manifests/flatcar-kernel-lifecycle-state.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: flatcar-kernel-lifecycle-state
  namespace: argo
  labels:
    app.kubernetes.io/part-of: testing-lab
data:
  candidate-version: ""
  candidate-package: ""
  candidate-created-at: ""
  gate-status: ""
  stable-version: ""
  stable-package: ""
```

- [ ] **Step 2: Document keys and operator meaning**

Add a short table in `docs/skills/flatcar-node-onboarding.md` under kernel lifecycle:

```md
| Key | Meaning |
|---|---|
| `candidate-version` | Kernel version currently under exo-0 canary gate |
| `gate-status` | `pending`, `pass`, or `fail` for current candidate |
| `stable-version` | Last promoted known-good kernel version |
```

- [ ] **Step 3: Lint**

Run: `cd /var/home/jorge/src/testing-lab && just lint`  
Expected: exit 0

- [ ] **Step 4: Commit**

```bash
git add manifests/flatcar-kernel-lifecycle-state.yaml docs/skills/flatcar-node-onboarding.md docs/agent-cheatsheet.md
git commit -m "feat(flatcar): add kernel lifecycle state contract"
```

---

### Task 2: Record candidate state during kernel build

**Files:**
- Modify: `argo/workflow-templates/flatcar-kernel-build.yaml`
- Test: `argo/workflow-templates/flatcar-kernel-build.yaml` (workflow lint via `just lint`)

**Interfaces:**
- Consumes: build outputs (`kernel-version`, `filename`)
- Produces: updates ConfigMap `flatcar-kernel-lifecycle-state` with:
  - `candidate-version={{inputs.parameters.kernel-version}}`
  - `candidate-package={{inputs.parameters.filename}}`
  - `candidate-created-at=<UTC timestamp>`
  - `gate-status=pending`

- [ ] **Step 1: Add a `record-candidate-state` template**

Insert a new script template:

```yaml
- name: record-candidate-state
  inputs:
    parameters:
    - name: kernel-version
    - name: filename
  script:
    image: cgr.dev/chainguard/kubectl:latest-dev
    command: [bash]
    source: |
      set -euo pipefail
      apk add --no-cache bash kubectl >/dev/null 2>&1
      TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      kubectl patch configmap flatcar-kernel-lifecycle-state -n argo --type=merge -p "{
        \"data\": {
          \"candidate-version\": \"{{inputs.parameters.kernel-version}}\",
          \"candidate-package\": \"{{inputs.parameters.filename}}\",
          \"candidate-created-at\": \"${TS}\",
          \"gate-status\": \"pending\"
        }
      }"
```

- [ ] **Step 2: Call `record-candidate-state` after `register-package`**

Add a new pipeline step:

```yaml
- - name: record-candidate-state
    template: record-candidate-state
    arguments:
      parameters:
      - name: kernel-version
        value: "{{workflow.parameters.kernel-version}}"
      - name: filename
        value: "{{steps.build-kernel.outputs.parameters.filename}}"
```

- [ ] **Step 3: Lint**

Run: `cd /var/home/jorge/src/testing-lab && just lint`  
Expected: exit 0

- [ ] **Step 4: Commit**

```bash
git add argo/workflow-templates/flatcar-kernel-build.yaml
git commit -m "feat(flatcar): persist kernel candidate state after build"
```

---

### Task 3: Add exo-0 24h gate workflow

**Files:**
- Create: `argo/workflow-templates/flatcar-kernel-gate.yaml`
- Modify: `manifests/flatcar-kernel-rbac.yaml`

**Interfaces:**
- Consumes: `flatcar-kernel-lifecycle-state` candidate keys
- Produces:
  - `gate-status=pass|fail`
  - `stable-version` + `stable-package` updates on pass
  - explicit failure reason in workflow logs on fail

- [ ] **Step 1: Create `flatcar-kernel-gate` WorkflowTemplate**

Create a template with one script step that:

```bash
# Pseudocode implemented as bash in the template:
# 1) read candidate-version/candidate-created-at
# 2) verify age >= 24h
# 3) check exo-0 Ready=True
# 4) check no unhealthy pods in namespace flatcar-update
# 5) check update/reboot validation marker exists (ConfigMap key or workflow label)
# 6) if pass -> patch gate-status=pass and stable-* keys
# 7) if fail -> patch gate-status=fail and exit 1
```

Use image: `cgr.dev/chainguard/kubectl:latest-dev`.

- [ ] **Step 2: Ensure argo SA has required read/patch permissions**

Update `manifests/flatcar-kernel-rbac.yaml` to allow:

```yaml
resources: ["configmaps", "nodes", "pods", "workflows"]
verbs: ["get", "list", "watch", "patch"]
```

for namespace/resource scopes used by the gate template.

- [ ] **Step 3: Lint**

Run: `cd /var/home/jorge/src/testing-lab && just lint`  
Expected: exit 0

- [ ] **Step 4: Commit**

```bash
git add argo/workflow-templates/flatcar-kernel-gate.yaml manifests/flatcar-kernel-rbac.yaml
git commit -m "feat(flatcar): add exo-0 24h kernel promotion gate"
```

---

### Task 4: Trigger gate workflow and finalize operator docs

**Files:**
- Modify: `manifests/flatcar-kernel-poller.yaml`
- Modify: `docs/skills/flatcar-node-onboarding.md`
- Modify: `docs/agent-cheatsheet.md`

**Interfaces:**
- Consumes: candidate state written by Task 2
- Produces: deterministic orchestration: poller triggers build, gate workflow runs on schedule with `concurrencyPolicy: Forbid`

- [ ] **Step 1: Add gate CronWorkflow**

In `manifests/flatcar-kernel-poller.yaml`, append:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: CronWorkflow
metadata:
  name: flatcar-kernel-gate
  namespace: argo
spec:
  schedules:
    - "*/30 * * * *"
  timezone: "UTC"
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 300
  workflowSpec:
    workflowTemplateRef:
      name: flatcar-kernel-gate
```

- [ ] **Step 2: Add operator runbook commands**

In cheatsheet and onboarding docs, add exact commands for:

```bash
kubectl get configmap flatcar-kernel-lifecycle-state -n argo -o yaml
argo cron list -n argo | grep flatcar-kernel-gate
argo submit -n argo --from workflowtemplate/flatcar-kernel-gate
```

- [ ] **Step 3: Lint**

Run: `cd /var/home/jorge/src/testing-lab && just lint`  
Expected: exit 0

- [ ] **Step 4: Commit**

```bash
git add manifests/flatcar-kernel-poller.yaml docs/skills/flatcar-node-onboarding.md docs/agent-cheatsheet.md
git commit -m "feat(flatcar): wire kernel gate automation and operator runbook"
```

---

### Task 5: Verify promotion and rollback behavior with real evidence

**Files:**
- No new files (operational verification)
- Modify (if needed): docs updated in prior tasks with actual observed evidence notes

**Interfaces:**
- Consumes: deployed workflows/templates from Tasks 1-4
- Produces: verifiable evidence that lifecycle works end-to-end

- [ ] **Step 1: Trigger candidate build**

```bash
argo submit -n argo --from workflowtemplate/flatcar-kernel-build -p kernel-version=7.1.1
```

Expected: workflow completes `Succeeded`; lifecycle ConfigMap shows `gate-status: pending`.

- [ ] **Step 2: Observe gate transition**

```bash
argo submit -n argo --from workflowtemplate/flatcar-kernel-gate
kubectl get configmap flatcar-kernel-lifecycle-state -n argo -o jsonpath='{.data.gate-status}{"\n"}'
```

Expected: `pass` after conditions are met; `fail` with explicit reason otherwise.

- [ ] **Step 3: Verify exo-0 kernel and stable state**

```bash
kubectl get node exo-0 -o jsonpath='{.status.nodeInfo.kernelVersion}{"\n"}'
kubectl get configmap flatcar-kernel-lifecycle-state -n argo -o jsonpath='{.data.stable-version}{"\n"}'
```

Expected: exo-0 kernel matches promoted `stable-version`.

- [ ] **Step 4: Rollback drill**

```bash
kubectl patch configmap flatcar-kernel-lifecycle-state -n argo --type=merge -p '{"data":{"gate-status":"fail"}}'
argo submit -n argo --from workflowtemplate/flatcar-kernel-gate
```

Expected: gate workflow refuses promotion and logs rollback/blocked reason.

- [ ] **Step 5: Commit evidence doc updates**

```bash
git add docs/skills/flatcar-node-onboarding.md docs/agent-cheatsheet.md
git commit -m "docs(flatcar): add verified kernel lifecycle promotion evidence"
```

---

## Self-review checklist (completed)

- Spec coverage: all required lifecycle stages (detect/build/register/gate/promote/rollback) are mapped to Tasks 1-5.
- Placeholder scan: removed TODO/TBD text; all tasks include concrete file paths and commands.
- Interface consistency: candidate and stable key names are consistent across tasks.
