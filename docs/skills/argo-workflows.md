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
  step 1 (skopeo): GET current GHCR image digest (authenticated via github-token secret)
  step 2 (curl → k8s API): GET stored digest from ConfigMap containerdisk-source-digests
  match?    → exit 0 (skip)
  mismatch? → PATCH ConfigMap with new digest (claim it, create if 404)
              POST Workflow JSON to k8s API (async build)

[test pipeline (bluefin-qa-pipeline)]
  assert-cd: skopeo inspect Zot → tag exists? → proceed
                                → missing?  → exit 1 "containerdisk not ready"
```

**Rules:**
- Digest watch uses `quay.io/skopeo/stable:latest` (has skopeo + curl, no kubectl needed):
  ```bash
  # Authenticated digest fetch — works for all GHCR images (public + org-restricted)
  LIVE_DIGEST=$(skopeo inspect \
    --no-tags \
    --format '{{.Digest}}' \
    --creds "_token:${GITHUB_TOKEN}" \
    "docker://${IMAGE}:${IMAGE_TAG}" 2>/dev/null)
  ```
  Anonymous GHCR token API returns a 60-char non-JWT token that produces 404 on manifest
  requests — do NOT use the anonymous token endpoint. Use PAT via `--creds "_token:PAT"`.
- Use in-cluster k8s API (SA token at `/var/run/secrets/kubernetes.io/serviceaccount/`)
  with `curl` for all ConfigMap and Workflow CRUD — no kubectl image needed.
- **HTTP status detection trap**: `curl -sf -w "%{http_code}" ... || echo "000"` appends
  "000" to curl's stdout output when curl fails. Use a tmpfile instead:
  ```bash
  HTTP_CODE_FILE=$(mktemp)
  curl -s -w "%{http_code}" -o /dev/null ... > "${HTTP_CODE_FILE}" || true
  HTTP=$(cat "${HTTP_CODE_FILE}"); rm -f "${HTTP_CODE_FILE}"
  ```
- The ConfigMap (`containerdisk-source-digests`) stores **GHCR source digests**, not Zot
  containerdisk digests — the two images are different (source bootc OCI vs BIB-built qcow2 OCI)
- ConfigMap is patched by the workflow, NOT managed by ArgoCD. Do not put it in `manifests/`.
  Create it in the first workflow run via POST if PATCH returns 404.
- Submitting a build via k8s API (no extra image dependency):
  ```bash
  curl -sf --cacert "${CACERT}" \
    -H "Authorization: Bearer ${SA_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST \
    "${KS}/apis/argoproj.io/v1alpha1/namespaces/argo/workflows" \
    -d '{"apiVersion":"argoproj.io/v1alpha1","kind":"Workflow","metadata":{"generateName":"build-cd-sync-testing-","namespace":"argo"},"spec":{"workflowTemplateRef":{"name":"build-containerdisk"},"arguments":{"parameters":[{"name":"image","value":"..."}]}}}'
  ```
- `assert-cd` in the test pipeline uses the existing `build-containerdisk/check` template
  but must **exit 1 on missing**, not just output `"missing"` (the original `check` template
  is non-failing — write a new `assert` template that calls skopeo and fails on empty result)

**Why ConfigMap over Zot annotation:**
- Zot annotations require `oras` tooling to set post-push; ConfigMap needs only `curl`
- The ConfigMap stores the *source* digest, not the containerdisk digest — conceptually different

### 15. VM concurrency — semaphore pools (bin-packing)

Use `spec.synchronization.semaphores` to cap concurrent VM-holding workflows. Without it, submitting 20+ PRs at once creates 20+ VMI objects simultaneously — all their resource requests count against node capacity even while Pending, flooding the scheduler.

**The API (v3.6+):**
```yaml
spec:
  synchronization:
    semaphores:                          # plural — "semaphore:" singular is DEPRECATED
      - configMapKeyRef:
          name: semaphore-config
          key: max-containerdisk-vms
  activeDeadlineSeconds: 3600           # always set — prevents stuck VMs holding slots forever
```

`semaphore:` (singular) is deprecated and rejected by ArgoCD schema validation. Use `semaphores:` (list). Verified against Context7 `/argoproj/argo-workflows` deprecations doc.

**Two pools in this repo:**

| ConfigMap key | Pipelines | Nodes |
|---|---|---|
| `max-containerdisk-vms` | bluefin-qa-pipeline, dakota-qa-pipeline | any Ready node |
| `max-hostdisk-vms` | knuckle-qa-pipeline, flatcar-smoke-test | ghost only |

hostDisk VMs (knuckle, flatcar) are ghost-pinned because their disk images live in ghost's local hostPath. containerDisk VMs (bluefin, dakota) can schedule on any node with KubeVirt. Two separate pools prevents knuckle builds from starving bluefin PR tests.

**Auto-tuning (semaphore-tuner CronWorkflow, hourly):**
```
slots = clamp(floor((sum_ready_node_ram - OVERHEAD_GI) / SLOT_GI), MIN, MAX)
```
Adding a node → slots auto-increase within 1 hour. Values written to `manifests/semaphore-config.yaml`. Tune constants in `manifests/semaphore-tuner.yaml`.

### 16. GitHub Contents API write-back — curl+jq only

When a workflow pod needs to push a file to a GitHub repo (e.g. Pages results JSON), use `curl` + `jq` inside the bash script. Never use inline Python (`python3 -c "..."`) — colons and quotes in Python code break YAML block scalar parsing and produce ArgoCD `ManifestGenerationError`.

**Pattern (verified against Context7 `/websites/github_en_rest`):**
```bash
# GET current file sha (required for updates)
CURRENT=$(curl -sf \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/OWNER/REPO/contents/PATH/file.json" || echo "{}")
FILE_SHA=$(echo "$CURRENT" | jq -r '.sha // empty')

# Build payload with jq — no Python, no heredocs
CONTENT=$(echo "$PAYLOAD_OBJ" | base64 -w0)
BODY=$(jq -nc \
  --arg msg "commit message" \
  --arg content "$CONTENT" \
  --arg sha "$FILE_SHA" \
  'if $sha != "" then {message:$msg,content:$content,sha:$sha} else {message:$msg,content:$content} end')

# PUT — sha required for updates, omit for new files
HTTP_CODE=$(curl -sf -w "%{http_code}" -o /tmp/response.json \
  -X PUT \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "Content-Type: application/json" \
  -d "$BODY" "https://api.github.com/repos/OWNER/REPO/contents/PATH/file.json")
```

Key rules:
- `sha` field required when updating an existing file; omit for new files (404 on GET = new file)
- `content` must be base64 encoded; use `base64 -w0` (no line wraps)
- `X-GitHub-Api-Version: 2022-11-28` header required by current GitHub API
- Log output to a file on persistent storage (hostPath) — pod stdout is GC'd
- Concurrent pipeline exits conflict on SHA → last writer wins; 409 = silent skip. Acceptable for metrics files.

**Why no inline Python or heredocs (root cause):** YAML `source: |` literal blocks use indentation to determine block extent. Any line at column 0 (including unindented `python3 -c "...\nimport json\n..."` continuation lines, or heredoc bodies like `<<'EOF'\nimport json\n`) terminates the block — YAML treats those lines as new top-level keys. The `yaml: could not find expected ':'` error is the symptom. Fix: use `jq` one-liners, keep everything on the same indented line, or `--rawfile` to read from a pre-staged file.

**onExit dashboard update pattern (bluefin-qa-pipeline + dakota-qa-pipeline):**
```yaml
- name: update-factory-stats
  script:
    image: quay.io/fedora/fedora:latest
    command: [bash]
    env:
      - name: GITHUB_TOKEN
        valueFrom:
          secretKeyRef:
            name: github-token
            key: token
    source: |
      set -euo pipefail
      API_URL="https://api.github.com/repos/projectbluefin/testing-lab/contents/docs/data/factory-stats.json"
      # Fetch JSON file + SHA
      CURRENT=$(curl -sf -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Accept: application/vnd.github+json" "${API_URL}" || echo "{}")
      FILE_SHA=$(echo "$CURRENT" | jq -r '.sha // empty')
      [[ -z "$FILE_SHA" ]] && echo "No SHA — skipping" && exit 0
      STATS=$(echo "$CURRENT" | jq -r '.content // ""' | tr -d '\n' | base64 -d \
        | jq '.')
      # Build run entry with jq — no Python, no heredocs
      NEW_RUN=$(jq -nc --arg id "{{workflow.name}}" --arg overall "pass_or_fail" \
        '{id:$id,overall:$overall,...}')
      UPDATED=$(echo "$STATS" | jq -c --argjson run "$NEW_RUN" --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '.recent_runs = ([$run] + (.recent_runs // []) | .[:15]) | ._meta.generated = $now')
      BODY=$(jq -nc --arg msg "chore: update dashboard run data" \
        --arg content "$(echo "$UPDATED" | base64 -w0)" --arg sha "$FILE_SHA" \
        '{message:$msg,content:$content,sha:$sha}')
      curl -sf -w "%{http_code}" -o /dev/null -X PUT \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Accept: application/vnd.github+json" \
        -H "Content-Type: application/json" \
        -d "$BODY" "${API_URL}"
```
The real implementation in `bluefin-qa-pipeline.yaml` also fetches per-suite result files into `/tmp/suite-scores/` and merges them via `jq --argjson` one-liners before building `NEW_RUN`.

### 17. CronWorkflow — `schedules` not `schedule`

CronWorkflow uses `schedules` (plural array), not `schedule` (singular string). The singular field does not exist in the CRD schema — ArgoCD's ServerSideApply validation will reject it.

```yaml
# ✗ WRONG — rejected by ArgoCD schema validation
spec:
  schedule: "0 * * * *"

# ✅ CORRECT
spec:
  schedules:
    - "0 * * * *"
```

Verified against Context7 `/argoproj/argo-workflows` CronWorkflow spec docs.

CronWorkflows also cannot be invoked via `workflowTemplateRef` — if you need a CronWorkflow to be submittable manually, extract its logic into a WorkflowTemplate and have the CronWorkflow reference it with `workflowTemplateRef`.

### 18. `when` condition trap — never reference a Skipped task's outputs

When a DAG task is Skipped (its own `when` condition evaluated false), its `outputs.result`
is **undefined**. Any downstream task whose `when` references that output will fail to
evaluate and will also be Skipped — silently, with no error. The entire chain dies.

**Example of the bug:**
```yaml
- name: check
  when: "'{{inputs.parameters.force}}' != 'true'"   # Skipped when force=true
  template: check

- name: build
  depends: "(check.Succeeded || check.Skipped)"
  when: "'{{tasks.check.outputs.result}}' != 'exists'"  # ✗ undefined when check is Skipped
  template: build
```

When `force=true`: `check` is Skipped → `tasks.check.outputs.result` is undefined →
`build`'s `when` fails to evaluate → `build` is also Skipped → nothing runs. No error logged.

**The fix: never skip the task that owns the gate decision. Move the bypass logic inside the script.**

```yaml
- name: check           # always runs — no 'when' on this task
  template: check       # script checks force param internally and outputs "missing" if force=true

- name: build
  depends: "check.Succeeded"
  when: "'{{tasks.check.outputs.result}}' != 'exists'"   # ✅ output always defined
  template: build
```

Inside the `check` script:
```bash
if [[ "{{inputs.parameters.force}}" == "true" ]]; then
  echo "missing"   # short-circuit — always rebuild
  exit 0
fi
# … real existence check …
```

**Rule:** If a task has a `when` guard AND downstream tasks reference its outputs,
remove the `when` guard and move the bypass into the script body.

**Symptoms of this bug:**
- Workflow shows phase `Running` but only 1–2 nodes (the DAG + the Skipped task)
- No `install-to-disk` or equivalent node ever created
- Controller logs show `"was unable to obtain the node"` for the downstream task (normal reconciliation noise)
- `force=true` workflows submitted after a digest change never actually build

### 19. Mutex contention from stuck failed builds

The `ghost-heavy-compute` mutex (on the `install-to-disk` template) allows only one
concurrent build at a time. Failed workflows that were stopped via `shutdown: Stop` **release
the mutex**, but workflows that exit with a non-zero script error may hold the mutex until
the workflow GC TTL clears them.

**Check what holds the mutex:**
```bash
kubectl logs -n argo -l app=workflow-controller --since=2m 2>/dev/null \
  | grep -i "ghost-heavy\|mutex\|Could not acquire"
```

**Stop a workflow holding the mutex:**
```bash
kubectl patch workflow <name> -n argo -p '{"spec":{"shutdown":"Stop"}}' --type=merge
```

**Dakota builds and the mutex:** `dakota-qa-pipeline` is permanently blocked (composefs image
without UKI — `bootc install to-disk` fails). The `image-poll-dakota` CronWorkflow is
suspended in `manifests/image-poll-dakota.yaml` (`spec.suspend: true`). **Never un-suspend
it** until upstream ships a UKI or the pipeline switches to a golden-disk approach.
If dakota builds appear again, stop them immediately — each one holds the mutex for its
`activeDeadlineSeconds` and starves LTS/aurora/bazzite rebuilds.


|---|---|
| "I'll skip the description annotation for now." | ArgoCD prune and agent navigation both rely on the annotation. Add it. |
| "The sub-template will see workflow.parameters directly." | It will not. Argo Workflows scopes parameters per-template. Always pass explicitly. |
| "I applied the template with kubectl — it's fine." | ArgoCD selfHeal will overwrite it within minutes. Use git. |
| "The lint passed locally, I'll skip CI." | CI runs against the same offline linter. If it passed locally, it passes in CI. |
| "The template is DEPRECATED, I'll clean it up later." | It will never get cleaned up. Delete it now — `prune: true` handles the rest. |
| "I need each step in the chain to have its own `when` guard." | Use a `dag` with `depends: "prior.Succeeded"` — downstream tasks cascade-omit automatically. |

## Red Flags

- `synchronization.semaphore:` (singular) in any pipeline — deprecated, rejected by ArgoCD schema. Use `synchronization.semaphores:` (list with `- configMapKeyRef:` item)
- `spec.schedule:` (singular) on a CronWorkflow — field does not exist in CRD schema; use `spec.schedules:` (array)
- A pipeline with VMs and no `spec.activeDeadlineSeconds` — a stuck VM holds its semaphore slot forever
- A pipeline with VMs and no semaphore — submitting 20 PRs at once floods the scheduler with VMI resource requests
- A `steps` or `dag` task calling a sub-template without `arguments:`
- A pipeline with no `onExit` handler (VM will leak on failure)
- Any `script:` template without `resources:` limits
- Templates in `argo/workflow-templates/` applied with `kubectl apply` (not via git)
- A `pr-poller` (or any PR-gating workflow) that skips on ANY existing commit status — it must skip only `pending` (in-flight) and `success` (already passed), and re-test on `error`/`failure`. Skipping `error` means stale statuses from deleted workflows permanently block retests.
- A hostDisk VM pipeline (`knuckle-qa-pipeline`, `flatcar-smoke-test`) with `nodeSelector` only on individual templates but not at `spec.nodeSelector` — the DAG entrypoint pod can land on the wrong node. Set `spec.nodeSelector: kubernetes.io/hostname: ghost` at the WorkflowTemplate spec level for all hostDisk pipelines.
- Python inside bash inside YAML (colons + quotes cause parse errors — use `curl`+`jq` instead; never `python3 -c` or heredoc Python; see §16 GitHub Contents API pattern)
- Heredoc `<< 'EOF'` inside a YAML block scalar — indentation breaks the YAML parser. ArgoCD returns `ManifestGenerationError: yaml: could not find expected ':'`. Write scripts to files in initContainers or use inline jq instead.
- `registry.k8s.io/kubectl` used as a shell-capable image — it is distroless, has no bash, nc, or any shell utilities. Use `cgr.dev/chainguard/kubectl:latest-dev` when you need kubectl + bash together
- A WorkflowTemplate file name that doesn't match its `metadata.name` (confuses ArgoCD tracking)
- Templates annotated `DEPRECATED` that haven't been deleted from git
- Two CronWorkflows with the same schedule covering overlapping namespaces
- A `steps` template with the same `when` condition on 3+ sequential steps (convert to `dag` + `depends` chain)
- A CronWorkflow that has a `dry-run` parameter defaulting to `"true"` — it will log `KEEP`/`DELETE` decisions and then do nothing; disk fills silently
- Setting a global Argo `parallelism` / `namespaceParallelism` cap in the workflow-controller-configmap — the real backpressure is Kubernetes pod scheduling (pod resource requests). Remove the cap; let the scheduler self-limit.
- Using `pr-test-N-` as a workflow generateName prefix — use the repo slug: `blu-N-`, `lts-N-`, `dak-N-`, `knu-N-` so k9s and the Argo UI show meaningful names at a glance
- **GC CronWorkflow using `registry.k8s.io/kubectl`** — distroless, no bash; every run exits with `bash: not found` and the GC step is skipped silently. Pods and orphaned objects accumulate until the cluster fills. Use `cgr.dev/chainguard/kubectl:latest-dev`. Symptom: `kubectl get cronworkflow orphan-pod-gc -n argo` shows `LAST SCHEDULE` advancing but pods keep piling up; check the workflow pod logs for `bash: not found`.
- Any `image:` in `argo/` or `manifests/` referencing `:5000` for the local OCI registry — `:5000` is the container-internal Zot port; use the NodePort `192.168.1.102:30500` so non-hostNetwork pods can reach it
- Any `image:` referencing a registry not in the allowlist (`ghcr.io`, `quay.io`, `registry.fedoraproject.org`, `registry.access.redhat.com`, `registry.k8s.io`, `192.168.1.102`, `localhost`) — enforce with the lint gate in `.github/workflows/lint.yaml`
- `depends: "X.Succeeded"` on a task that follows a conditionally-skippable upstream — if upstream is Skipped, the downstream task is Omitted and the whole DAG may appear to succeed even though the chain broke; use `depends: "(X.Succeeded || X.Skipped)"` when the upstream has its own `when` guard
- A downstream `when` condition that references `{{tasks.X.outputs.result}}` where task X has its own `when` guard — if X is Skipped its output is undefined and the downstream task silently skips too. Fix: let X always run; handle the bypass inside the script (see §18).
- A `force=true` rebuild workflow where only 1–2 nodes appear (DAG + a Skipped check) and no build step ever runs — this is the §18 `when`/Skipped output bug, not a semaphore or mutex issue
- Dakota builds (`build-cd-sync-dakota-latest-*`) running at all — dakota pipeline is permanently blocked; these builds always fail and hold the `ghost-heavy-compute` mutex, starving LTS/aurora/bazzite rebuilds. `image-poll-dakota` must remain suspended in git.
- Commit message not in Conventional Commits format — the pre-commit hook rejects any commit not matching `<type>(<scope>): <description>`. Valid types: `feat fix ci chore docs refactor test build perf revert`

## Verification

Before marking any WorkflowTemplate change done:

- [ ] All VM-running pipelines have `spec.synchronization.semaphores:` (plural) pointing to `semaphore-config`
- [ ] All VM-running pipelines have `spec.activeDeadlineSeconds` set
- [ ] Any new CronWorkflow uses `spec.schedules:` (array), not `spec.schedule:` (singular)
- [ ] All sub-template calls include explicit `arguments:` blocks
- [ ] Pipeline has `onExit: cleanup` handler
- [ ] All pod-running templates have `resources:` requests and limits
- [ ] Change is committed and pushed — not manually applied to cluster
- [ ] `description:` annotation present on the new/modified template
- [ ] File name matches `metadata.name` (e.g. `provision-bluefin-vm.yaml` for `name: provision-bluefin-vm`)
- [ ] hostDisk pipelines (knuckle, flatcar) have `spec.nodeSelector: kubernetes.io/hostname: ghost` at WorkflowTemplate spec level — not just on individual templates
- [ ] GitHub Contents API write-backs use curl+jq, not inline Python; output teed to a file on persistent hostPath storage
- [ ] `kubectl get workflowtemplate -n argo` shows no cluster-only templates (not in git) unless they're intentional bootstrap one-shots
- [ ] No CronWorkflow with a `dry-run` parameter whose default is `"true"` — verify GC jobs actually delete
- [ ] All local OCI registry references use `:30500` (NodePort), not `:5000` (container-internal)
- [ ] `grep -rn 'image:' argo/ manifests/` shows only allowlisted registries: `ghcr.io`, `quay.io`, `registry.fedoraproject.org`, `registry.access.redhat.com`, `registry.k8s.io`, `192.168.1.102`, `localhost`
