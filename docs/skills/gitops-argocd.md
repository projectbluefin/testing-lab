---
name: gitops-argocd
description: >
  ArgoCD GitOps model for the testing-lab: what is and isn't managed, sync
  rules, bootstrap vs managed distinction, and common sync failures. Use when
  working with ArgoCD Applications, adding new templates to git, or
  troubleshooting sync issues.
metadata:
  context7-sources:
    - /argoproj/argo-cd
---

# GitOps / ArgoCD — testing-lab Skill

## When to Use

- Adding a new WorkflowTemplate (which git path? ArgoCD managed or bootstrap?)
- Debugging "my template change isn't showing up in the cluster"
- Adding a new CronWorkflow or manifest
- Understanding why ArgoCD reverted a manual change
- Setting up the repo on a new cluster

## When NOT to Use

- Argo Workflows YAML authoring → `argo-workflows.md`
- VM provisioning failures → `kubevirt-vms.md`

## Core Process

### 1. Two ArgoCD Applications — know which owns what

| Application | Git path | Namespace | What it manages |
|---|---|---|---|
| `testing-lab` | `argo/workflow-templates/` | argo | WorkflowTemplates |
| `testing-lab-infra` | `manifests/` | argo + others | CronWorkflows, RBAC, NodePorts, ConfigMaps |

Both use `automated: { prune: true, selfHeal: true }` — per
[Argo CD best practices](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/).

**`prune: true`** — resources removed from git are deleted from the cluster.
**`selfHeal: true`** — manual cluster changes are reverted within ~3 minutes.

### 2. The three-path decision tree

```
New file to add to the repo?
        │
        ├─ Runs every pipeline / changes regularly?
        │   └─ → argo/workflow-templates/   (ArgoCD managed, tested in CI)
        │
        ├─ Runs once to set up the cluster?
        │   └─ → argo/bootstrap/            (NOT ArgoCD managed, apply manually)
        │
        └─ Cluster infrastructure (CronWorkflow, RBAC, NodePort, ConfigMap)?
            └─ → manifests/                 (ArgoCD managed via testing-lab-infra)
```

### 3. The deploy loop

```bash
# Edit a WorkflowTemplate
vim argo/workflow-templates/my-template.yaml

# Lint before committing
argo lint --offline argo/workflow-templates/

# Commit and push — ArgoCD polls or webhooks within ~3 minutes
git add . && git commit -m "feat(templates): ..." && git push

# Force sync if you can't wait
just argocd-sync

# Verify
just argocd-status
```

**Never:**
```bash
kubectl apply -f argo/workflow-templates/my-template.yaml   # ✗ ArgoCD reverts this
argo template create argo/workflow-templates/my-template.yaml  # ✗ same
```

### 4. Bootstrap templates — manual, not GitOps

`argo/bootstrap/` is intentionally **outside** all ArgoCD Applications. These templates
are applied once during cluster setup and left in the cluster as runnable runbooks:

```bash
# Apply all bootstrap templates (once, during cluster setup)
kubectl apply -f argo/bootstrap/ -n argo

# Or just one:
argo submit --from workflowtemplate/install-kubevirt -n argo --wait --log
```

If you add a template to `argo/bootstrap/` and push to main, ArgoCD does nothing —
you must still apply it manually.

### 5. manifests/ uses ServerSideApply

`manifests/` has `ServerSideApply: true` in the ArgoCD Application. This means
manifests **patch** resources rather than replace them. You can add a single key to
a Helm-managed ConfigMap without owning the whole object.

**Consequence:** `generateName:` is forbidden in `manifests/` — ArgoCD needs stable
names to track resources. Always use a fixed `name:`.

### 6. Sync status and forced sync

```bash
# Check status
just argocd-status
# or
argocd app get testing-lab
argocd app get testing-lab-infra

# Force sync
just argocd-sync
# or
argocd app sync testing-lab testing-lab-infra --timeout 120
```

If a template change is in git but not yet live:
1. Check `argocd app get testing-lab` — is it Synced?
2. If OutOfSync, run `just argocd-sync`
3. If sync fails, check ArgoCD logs: `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller`

### 7. OCI Helm chart Applications (arc-systems, arc-runners)

ArgoCD can deploy OCI Helm charts directly. These Applications live under `argocd/`
and are applied once as control-plane resources (not GitOps-managed by ArgoCD itself).

```bash
# Apply ARC ArgoCD Applications (one-time, or after cluster rebuild)
kubectl apply -f argocd/arc-controller-app.yaml -n argocd
kubectl apply -f argocd/arc-runners-app.yaml -n argocd
```

**CRD annotation size limit** — Large CRDs (e.g. `autoscalingrunnersets.actions.github.com`)
exceed ArgoCD's 262KB client-side annotation limit. Fix: `ServerSideApply=true` in
`syncOptions`. Already set in `argocd/arc-controller-app.yaml`.

**Stuck retry loop** — if ArgoCD retries a failed sync with stale syncOptions:
```bash
kubectl patch application <name> -n argocd \
  --type=json -p='[{"op":"remove","path":"/operation"}]'
kubectl annotate application <name> -n argocd \
  argocd.argoproj.io/refresh=hard --overwrite
```

**Controller service account discovery** — `gha-runner-scale-set` discovers the
controller SA by label lookup. Fails when controller and runners are in different
namespaces. Always set explicitly in helm values:
```yaml
controllerServiceAccount:
  namespace: arc-systems
  name: arc-systems-gha-rs-controller
```

**bazzite taint** — bazzite carries `node-role.kubernetes.io/gaming:NoSchedule`
(persisted in `manifests/bazzite-node-taint.yaml`). Infra pods landing there fail
DNS resolution (`no route to host` to CoreDNS) because bazzite's CNI may not be
fully initialised on join. If a pod lands on bazzite and fails, delete it — it will
reschedule to ghost automatically.

### 8. Reconciling orphan templates (cluster-only → git)

When a template exists in the cluster but not in git:
```bash
# Export and clean metadata
kubectl get workflowtemplate -n argo <name> -o json \
  | python3 -c "
import json,sys,yaml
d=json.load(sys.stdin)
for k in ['resourceVersion','uid','creationTimestamp','generation','managedFields']:
    d['metadata'].pop(k,None)
d.pop('status',None)
print(yaml.dump(d,default_flow_style=False,sort_keys=False))" \
  > argo/workflow-templates/<name>.yaml
```

Then lint, commit, push. ArgoCD will adopt the resource on next sync.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll apply it manually just this once." | selfHeal: true will revert it within minutes. Use git. |
| "It's in bootstrap/ so ArgoCD won't prune it from the cluster." | Correct — but you still have to `kubectl apply -f argo/bootstrap/ -n argo` to put it there. |
| "I pushed to a feature branch — why isn't it live?" | Both Applications track `main`. Feature branch changes don't sync. |
| "The diff looks right in `argocd app diff`." | Diff shows desired vs actual. Sync makes it actual. |

## Red Flags

- A WorkflowTemplate in `argo/workflow-templates/` that exists only in the cluster (not in git) — ArgoCD will prune it on next sync
- `generateName:` in any file under `manifests/`
- A template that was `kubectl apply`d and is showing as OutOfSync in ArgoCD
- Bootstrap templates accidentally placed in `argo/workflow-templates/` (ArgoCD will prune them if removed from git)
- ArgoCD Application in `Degraded` state after a template deletion

## Verification

Before merging a GitOps change:

- [ ] New WorkflowTemplate is in the correct path (`workflow-templates/` vs `bootstrap/`)
- [ ] `argo lint --offline argo/workflow-templates/` passes
- [ ] No `generateName:` in `manifests/`
- [ ] Pushed to `main` (not a feature branch)
- [ ] After push: `just argocd-status` shows both Applications as `Synced` and `Healthy`
- [ ] `kubectl get workflowtemplate -n argo <name>` confirms the template is live
