---
name: argo-workflows
description: >
  Authoring, linting, and submitting Argo Workflows and WorkflowTemplates in
  the testing-lab. Use when writing or editing any .yaml file under
  argo/workflow-templates/, argo/bootstrap/, or argo/*.yaml, or when
  debugging a failed workflow run.
metadata:
  context7-sources:
    - /argoproj/argo-workflows
---

# Argo Workflows — testing-lab Skill

## When to Use

- Editing any `argo/workflow-templates/*.yaml` or `argo/bootstrap/*.yaml`
- Writing a new pipeline (bib-build, provision, test, teardown)
- Adding a new `argo/*.yaml` submit-time Workflow
- Debugging a stuck or failed workflow
- Adding a CronWorkflow to `manifests/`

## When NOT to Use

- ArgoCD Application changes → `gitops-argocd.md`
- KubeVirt VM manifest design → `kubevirt-vms.md`
- behave/dogtail test authoring → `test-authoring.md`

## Core Process

### 1. Template structure rules

Every WorkflowTemplate in `argo/workflow-templates/` must follow this shape:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: WorkflowTemplate
metadata:
  name: my-template
  namespace: argo
  annotations:
    description: |
      One-paragraph description of what this template does and when to use it.
  labels:
    app.kubernetes.io/part-of: bluefin-test-suite
spec:
  serviceAccountName: argo
  templates:
    - name: entrypoint-template
      inputs:
        parameters:
          - name: my-param
            value: "default"
      # ...
```

- `serviceAccountName: argo` on every WorkflowTemplate
- `namespace: argo` always
- `description:` annotation on every template — one paragraph saying what it does

### 2. Parameter passing — always explicit

Sub-templates never inherit parameters from the caller scope. Pass every parameter explicitly:

```yaml
# ✅ CORRECT — explicit argument passing
- name: pipeline
  steps:
  - - name: build
      template: build-step
      arguments:
        parameters:
        - name: variant
          value: '{{workflow.parameters.variant}}'
        - name: image-tag
          value: '{{workflow.parameters.image-tag}}'

# ✗ WRONG — sub-template cannot see workflow.parameters directly
- name: pipeline
  steps:
  - - name: build
      template: build-step   # missing arguments: — lint will catch this
```

> Verified against: `/argoproj/argo-workflows` — WorkflowTemplate docs

### 3. Referencing external templates

Use `templateRef` for cross-WorkflowTemplate calls:

```yaml
- name: run-tests
  depends: "provision.Succeeded"
  templateRef:
    name: run-gnome-tests          # WorkflowTemplate name
    template: run-gnome-tests      # template name within that WorkflowTemplate
  arguments:
    parameters:
    - name: vm-ip
      value: "{{tasks.provision.outputs.parameters.vm-ip}}"
```

### 4. Output parameters — use `script` with stdout

For steps that produce a value consumed by downstream steps, write the result to stdout and nothing else:

```yaml
- name: wait-for-vm-ready
  script:
    image: cgr.dev/chainguard/kubectl:latest-dev
    command: [bash]
    source: |
      # Send all debug output to stderr
      echo "Waiting for VMI..." >&2
      kubectl wait vmi ...
      # Only the result goes to stdout
      echo "${POD_IP}"
  outputs: {}    # outputs.result captures the last stdout line automatically
```

Then consume via `{{steps.wait-for-vm.outputs.result}}`.

**`cgr.dev/chainguard/kubectl:latest-dev`** is the correct image for any step that needs both `kubectl` and `bash`. `registry.k8s.io/kubectl` is distroless (no shell — `nc`, `bash /dev/tcp` all fail). Add `cgr.dev` to the registry lint allowlist when using it.

### 5. Always use `onExit` for teardown

Every pipeline that provisions a VM must have a guaranteed teardown:

```yaml
spec:
  entrypoint: pipeline
  onExit: cleanup     # runs on success, failure, and error
  templates:
  - name: cleanup
    steps:
    - - name: teardown
        templateRef:
          name: teardown-bluefin-vm
          template: teardown-vm
        arguments:
          parameters:
          - name: vm-name
            value: "{{workflow.parameters.vm-name}}"
```

### 6. Resource limits — required on all script/container templates

Every pod-running template needs explicit resource requests and limits. Reference values from AGENTS.md:

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

### 7. Conditional chains: use `dag` + `depends` instead of repeating `when`

When multiple sequential steps are all guarded by the same `when` condition, convert from `steps` to `dag` and put the `when` only on the first task. Subsequent tasks use `depends: "prior.Succeeded"` — if the first task is Skipped, downstream tasks are automatically Omitted:

```yaml
# ✗ VERBOSE — same when condition repeated on every step
steps:
  - - name: check
      template: check-disk
  - - name: pull
      when: "{{steps.check.outputs.result}} != exists"
      template: pull-image
  - - name: build
      when: "{{steps.check.outputs.result}} != exists"  # redundant
      template: build-image
  - - name: configure
      when: "{{steps.check.outputs.result}} != exists"  # redundant
      template: configure-disk

# ✅ CLEAN — one when, cascade-omit via depends chain
dag:
  tasks:
    - name: check
      template: check-disk
    - name: pull
      depends: "check.Succeeded"
      when: "{{tasks.check.outputs.result}} != exists"
      template: pull-image
    - name: build
      depends: "pull.Succeeded"   # Omitted if pull was Skipped
      template: build-image
    - name: configure
      depends: "build.Succeeded"  # Omitted if build was Omitted
      template: configure-disk
```

Argo DAG semantics: a task with `depends: "X.Succeeded"` is **Omitted** (not an error) when X is Skipped. The overall DAG succeeds if all non-Omitted tasks succeeded.

**Optional upstream:** when a task has its own `when` guard and a downstream task must run regardless of whether the upstream was skipped, use OR:

```yaml
- name: run-system
  depends: "(run-software.Succeeded || run-software.Skipped)"
  when: "'{{workflow.parameters.suites}}' =~ 'system'"
```

This fires `run-system` whether `run-software` succeeded or was skipped by its own `when` condition.

### 8. File names must match `metadata.name`

WorkflowTemplate file names in `argo/workflow-templates/` must match the resource's `metadata.name`. Divergence (e.g. `provision-vm.yaml` containing `name: provision-bluefin-vm`) confuses ArgoCD tracking and grep-based navigation:

```
# ✗ WRONG — file name diverged from resource name
argo/workflow-templates/provision-vm.yaml  →  metadata.name: provision-bluefin-vm

# ✅ CORRECT — file name matches resource name
argo/workflow-templates/provision-bluefin-vm.yaml  →  metadata.name: provision-bluefin-vm
```

ArgoCD tracks by GVK + resource name, not filename. A rename is safe — just git mv and push.

### 9. Dead templates: prune promptly, don't leave DEPRECATED annotations

When a WorkflowTemplate is superseded:
1. Delete the file from `argo/workflow-templates/` in the same PR that removes the dependency
2. `prune: true` on the ArgoCD Application will delete it from the cluster automatically on next sync
3. Do not leave templates with `DEPRECATED` annotations in git — they accumulate and confuse agents

One-shot bootstrap templates (`install-*`, `setup-*`, `titan-disk-cleanup`) should not persist indefinitely in the cluster. If they have no git backing, `kubectl delete workflowtemplate -n argo <name>` is safe since ArgoCD won't recreate what isn't in git.

Two CronWorkflows at the same schedule covering overlapping namespaces → consolidate into one. Check `kubectl get cronworkflows -n argo` before adding a new cleanup job.

### 10. BIB build failures — stale containers-storage locks

When a BIB workflow is force-killed mid-run, podman lock files remain at
`/var/lib/containers/storage/overlay-containers/*/userdata/*.lock`. Subsequent
BIB runs fail immediately with:

```
acquiring lock N for container <sha>: file exists
Error: ghcr.io/projectbluefin/bluefin-lts: image not known
```

Fix: submit the `ghost-cleanup` WorkflowTemplate before resubmitting:
```bash
just run-ghost-cleanup
```

This is safe to run any time no active BIB workflows are running. The `ghost-heavy-compute`
Argo mutex serializes BIB builds but does not clean stale locks from killed workflows.

### 11. Templates snapshot at submit time — always sync before resubmit

Argo snapshots the full WorkflowTemplate body into the Workflow object at submit time.
A workflow submitted before ArgoCD synced a fix will run the **old** template, even if
the live cluster template has since been updated.

**Always verify ArgoCD has synced before resubmitting after a template fix:**

```bash
# Confirm revision on cluster matches your push
just argocd-status   # check both apps show Synced + Healthy

# Then verify the live template has your change
argo-mcp-get_workflow_template name=<template> namespace=argo
# grep for the specific changed value

# Only then submit
```

If you report a fix is deployed without verifying the live template, you will waste the
next run on the same bug. Verification is not optional.

```bash
# Lint workflow-templates (offline, cross-file refs resolve)
argo lint --offline argo/workflow-templates/

# Lint bootstrap templates
argo lint --offline argo/bootstrap/

# Lint standalone submit Workflows (online, needs live server)
argo lint argo/bluefin-smoke-test.yaml
```

Or use the convenience wrapper: `just lint`

### 12. ArgoCD ownership — never apply manually

`argo/workflow-templates/` is managed by the `testing-lab` ArgoCD Application with `prune: true` and `selfHeal: true`. Manual `kubectl apply` or `argo create workflow-template` for templates in this directory is forbidden — ArgoCD will overwrite or conflict.

`argo/bootstrap/` is **not** ArgoCD managed. Apply manually once:
```bash
kubectl apply -f argo/bootstrap/ -n argo
```

### 13. TTL and podGC — always set

Prevent accumulation of completed workflow pods:

```yaml
spec:
  podGC:
    strategy: OnWorkflowSuccess   # delete pods on success; keep on failure for debugging
  ttlStrategy:
    secondsAfterCompletion: 86400  # 24h for successful runs
    secondsAfterFailure: 604800    # 7d for failed runs (matches controller configmap)
```

### 14. Decoupling slow build steps from test pipelines (image-sync pattern)

Any pipeline step that conditionally runs a slow build (BIB, compilation, disk conversion)
belongs in a **separate CronWorkflow**, not inline in the test pipeline. The test pipeline
asserts the artifact exists and fails fast — it never triggers a rebuild.

**Two-component design:**

```
[digest-watch CronWorkflow, every 5 min]
  step 1 (curl): GET current GHCR image digest (cheap — single HTTP HEAD, ~100ms)
  step 2 (kubectl): GET stored digest from ConfigMap containerdisk-source-digests
  match?    → exit 0 (skip)
  mismatch? → PATCH ConfigMap with new digest (claim it)
              kubectl apply Workflow from workflowtemplate/build-containerdisk (async)

[test pipeline (bluefin-qa-pipeline)]
  assert-cd: skopeo inspect Zot → tag exists? → proceed
                                → missing?  → exit 1 "containerdisk not ready"
```

**Rules:**
- Digest watch uses `curl` + GHCR anonymous token (no skopeo, no image pull):
  ```bash
  TOKEN=$(curl -sL "https://ghcr.io/token?scope=repository:projectbluefin/bluefin:pull" \
    | sed 's/.*"token":"\([^"]*\)".*/\1/')
  DIGEST=$(curl -sI -H "Authorization: Bearer ${TOKEN}" \
    -H "Accept: application/vnd.oci.image.index.v1+json" \
    "https://ghcr.io/v2/projectbluefin/bluefin/manifests/testing" \
    | grep -i docker-content-digest | awk '{print $2}' | tr -d '\r\n')
  ```
- The ConfigMap (`containerdisk-source-digests`) stores **GHCR source digests**, not Zot
  containerdisk digests — the two images are different (source bootc OCI vs BIB-built qcow2 OCI)
- ConfigMap is patched by the workflow, NOT managed by ArgoCD. Do not put it in `manifests/`.
  Create it in the first workflow run via `kubectl create configmap ... || kubectl patch ...`
- Submitting a build via `kubectl apply` (not `argo submit` CLI, no extra image dependency):
  ```bash
  cat > /tmp/build.yaml << EOF
  apiVersion: argoproj.io/v1alpha1
  kind: Workflow
  metadata:
    generateName: build-cd-sync-
    namespace: argo
  spec:
    workflowTemplateRef:
      name: build-containerdisk
    arguments:
      parameters:
      - name: image
        value: "${IMAGE}"
  EOF
  kubectl apply -f /tmp/build.yaml
  ```
- `assert-cd` in the test pipeline uses the existing `build-containerdisk/check` template
  but must **exit 1 on missing**, not just output `"missing"` (the original `check` template
  is non-failing — write a new `assert` template that calls skopeo and fails on empty result)

**Why ConfigMap over Zot annotation:**
- Zot annotations require `oras` tooling to set post-push; ConfigMap needs only `kubectl`
- The ConfigMap stores the *source* digest, not the containerdisk digest — conceptually different

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll skip the description annotation for now." | ArgoCD prune and agent navigation both rely on the annotation. Add it. |
| "The sub-template will see workflow.parameters directly." | It will not. Argo Workflows scopes parameters per-template. Always pass explicitly. |
| "I applied the template with kubectl — it's fine." | ArgoCD selfHeal will overwrite it within minutes. Use git. |
| "The lint passed locally, I'll skip CI." | CI runs against the same offline linter. If it passed locally, it passes in CI. |
| "The template is DEPRECATED, I'll clean it up later." | It will never get cleaned up. Delete it now — `prune: true` handles the rest. |
| "I need each step in the chain to have its own `when` guard." | Use a `dag` with `depends: "prior.Succeeded"` — downstream tasks cascade-omit automatically. |

## Red Flags

- A WorkflowTemplate missing `serviceAccountName: argo`
- A `steps` or `dag` task calling a sub-template without `arguments:`
- A pipeline with no `onExit` handler (VM will leak on failure)
- Any `script:` template without `resources:` limits
- Templates in `argo/workflow-templates/` applied with `kubectl apply` (not via git)
- `generateName:` in `manifests/` (ArgoCD needs stable names)
- Python inside bash inside YAML (colons + quotes cause parse errors — use `kubectl jsonpath` or `jq` instead, never inline python3 -c)
- `registry.k8s.io/kubectl` used as a shell-capable image — it is distroless, has no bash, nc, or any shell utilities. Use `cgr.dev/chainguard/kubectl:latest-dev` when you need kubectl + bash together
- A WorkflowTemplate file name that doesn't match its `metadata.name` (confuses ArgoCD tracking)
- Templates annotated `DEPRECATED` that haven't been deleted from git
- Two CronWorkflows with the same schedule covering overlapping namespaces
- A `steps` template with the same `when` condition on 3+ sequential steps (convert to `dag` + `depends` chain)
- A CronWorkflow that has a `dry-run` parameter defaulting to `"true"` — it will log `KEEP`/`DELETE` decisions and then do nothing; disk fills silently
- Any `image:` in `argo/` or `manifests/` referencing `:5000` for the local OCI registry — `:5000` is the container-internal Zot port; use the NodePort `192.168.1.102:30500` so non-hostNetwork pods can reach it
- Any `image:` referencing a registry not in the allowlist (`ghcr.io`, `quay.io`, `registry.fedoraproject.org`, `registry.access.redhat.com`, `registry.k8s.io`, `192.168.1.102`, `localhost`) — enforce with the lint gate in `.github/workflows/lint.yaml`
- `depends: "X.Succeeded"` on a task that follows a conditionally-skippable upstream — if upstream is Skipped, the downstream task is Omitted and the whole DAG may appear to succeed even though the chain broke; use `depends: "(X.Succeeded || X.Skipped)"` when the upstream has its own `when` guard
- Commit message not in Conventional Commits format — the pre-commit hook rejects any commit not matching `<type>(<scope>): <description>`. Valid types: `feat fix ci chore docs refactor test build perf revert`

## Verification

Before marking any WorkflowTemplate change done:

- [ ] `argo lint --offline argo/workflow-templates/` passes with zero errors
- [ ] All sub-template calls include explicit `arguments:` blocks
- [ ] Pipeline has `onExit: cleanup` handler
- [ ] All pod-running templates have `resources:` requests and limits
- [ ] Change is committed and pushed — not manually applied to cluster
- [ ] `description:` annotation present on the new/modified template
- [ ] File name matches `metadata.name` (e.g. `provision-bluefin-vm.yaml` for `name: provision-bluefin-vm`)
- [ ] No DEPRECATED templates left in git
- [ ] `kubectl get workflowtemplate -n argo` shows no cluster-only templates (not in git) unless they're intentional bootstrap one-shots
- [ ] No CronWorkflow with a `dry-run` parameter whose default is `"true"` — verify GC jobs actually delete
- [ ] All local OCI registry references use `:30500` (NodePort), not `:5000` (container-internal)
- [ ] `grep -rn 'image:' argo/ manifests/` shows only allowlisted registries: `ghcr.io`, `quay.io`, `registry.fedoraproject.org`, `registry.access.redhat.com`, `registry.k8s.io`, `192.168.1.102`, `localhost`
