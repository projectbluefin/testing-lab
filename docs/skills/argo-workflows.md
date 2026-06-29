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
- Writing a new pipeline (provision, test, teardown)
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

If a step needs shell features (`mkdir`, redirection, `jq`/`awk` parsing, heredocs), do **not** assume a vendor CLI image has `/bin/sh`. Third-party tool images are often distroless. Either:

- run the binary directly with `container.command`/`args` and avoid shell syntax entirely, or
- switch to a shell-capable base image (`cgr.dev/chainguard/wolfi-base:latest`, `cgr.dev/chainguard/kubectl:latest-dev`) and install/fetch the CLI inside the step.

A runtime `/bin/sh: not found` or missing-coreutils failure from a CLI image usually means the image is distroless, not that the WorkflowTemplate syntax is wrong.

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

Any pipeline step that conditionally runs a slow build (compilation, disk conversion)
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
  containerdisk digests — the two images are different (source bootc OCI vs qcow2 OCI containerDisk)
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

### 15. VM concurrency — k8s native scheduling (no semaphores)

VM concurrency is managed by the **k8s scheduler via virt-launcher pod memory requests**, not Argo semaphores. When a node has insufficient RAM, the virt-launcher pod stays Pending. When a VM finishes, resources free up and the scheduler picks the next Pending pod. FIFO ordering follows workflow creation timestamp.

**Do not add `spec.synchronization.semaphores` to VM pipeline specs.** The semaphore approach was removed because:
- Slots were held at workflow scope, not VM-live scope — a 3h pipeline held a slot during build/assert/teardown, not just while the VM was running
- Build workflows (no VM) held VM slots, starving actual test workflows
- The slot count was a manually-maintained number that drifted from actual hardware

**What to do instead:** ensure VM specs have explicit memory requests so the scheduler has accurate data:
```yaml
domain:
  memory:
    guest: "{{inputs.parameters.vm-memory}}"   # KubeVirt sets virt-launcher request from this
```

**All pipelines still need `activeDeadlineSeconds`** so stuck VMs self-evict:
```yaml
activeDeadlineSeconds: 3600   # 1h for containerdisk, 7200 for knuckle
```

**VMs float to any KubeVirt-capable node** — no `nodeSelector: kubernetes.io/hostname: ghost` in VM specs. The registry-mirror-config DaemonSet writes the Zot HTTP registry config to all nodes.

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

**Verified against Context7 `/argoproj/argo-workflows` enhanced-depends-logic docs:**
> "If a downstream task references outputs from a task that was Skipped or Omitted,
> those references will resolve to empty strings."

So `'{{tasks.check.outputs.result}}' != 'exists'` becomes `'' != 'exists'` = `true` when
the upstream is Skipped. In theory the build should run. In practice (Argo v4.0.5), we
observed the downstream task never being scheduled at all — the controller logs show
`"was unable to obtain the node"` for it and the workflow stalls with only 2 nodes.

The safe, version-independent fix: **never put a `when` guard on the task that owns the
gate output. Move the bypass inside the script.**

**Example of the fragile pattern:**
```yaml
- name: check
  when: "'{{inputs.parameters.force}}' != 'true'"   # Skipped when force=true
  template: check

- name: build
  depends: "(check.Succeeded || check.Skipped)"
  when: "'{{tasks.check.outputs.result}}' != 'exists'"  # resolves to '' when Skipped → unpredictable
  template: build
```

**The robust fix:**
```yaml
- name: check           # always runs — no 'when' on this task
  template: check       # script handles force=true internally

- name: build
  depends: "check.Succeeded"
  when: "'{{tasks.check.outputs.result}}' != 'exists'"   # ✅ always defined
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


### 20. Per-workflow ephemeral storage — volumeClaimTemplates

For pipelines that need shared scratch space across steps (e.g. installer binaries, target disks),
use Argo's `volumeClaimTemplates` at the workflow spec level. Argo auto-creates the PVC at workflow
start and auto-deletes it on completion — no manual cleanup step needed.

```yaml
spec:
  volumeClaimTemplates:
    - metadata:
        name: workspace
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: local-path   # k3s default
        resources:
          requests:
            storage: 30Gi

  templates:
    - name: my-step
      script:
        volumeMounts:
          - name: workspace
            mountPath: /mnt/workspace
```

**RWO PVC + KubeVirt VM co-location:** When a VM uses a `persistentVolumeClaim` volume backed
by a RWO PVC, KubeVirt automatically schedules the VM on the same node as the PVC — no explicit
`nodeSelector` needed. Source: /kubevirt/user-guide — "When using local devices or ReadWriteOnce
(RWO) PVCs, affinity rules on VMs sharing storage ensure they are scheduled on the same node."

**Namespace constraint:** `volumeClaimTemplates` creates the PVC in the workflow's own namespace
(`argo`). If a VM in a different namespace (`knuckle-test`) needs a disk, create a dedicated PVC
in that namespace via a `resource:` step, and delete it in `onExit`.

```yaml
# registry-lint-ignore not needed — no image ref
- name: create-rootdisk-pvc
  resource:
    action: apply
    manifest: |
      apiVersion: v1
      kind: PersistentVolumeClaim
      metadata:
        name: "{{workflow.name}}-rootdisk"
        namespace: knuckle-test
      spec:
        accessModes: [ReadWriteOnce]
        storageClassName: local-path
        resources:
          requests:
            storage: 30Gi
```

**containerDisk OCI format** (source: /kubevirt/user-guide):
```dockerfile
FROM scratch
ADD --chown=107:107 disk.raw /disk/
```
UID 107 = qemu. Required — omitting `--chown` causes VM boot failure (permission denied on disk).

### 21. Log access — Argo is sufficient, no separate stack needed

Argo Server retains all workflow pod logs for the workflow TTL period (7 days success,
30 days failure via `workflow-controller-configmap`). No separate log aggregation stack
(Loki, Promtail, etc.) is needed for a homelab CI cluster.

**Retrieve logs:**
```bash
# most recent workflow
just logs                              # alias: argo logs -n argo @latest

# specific workflow
argo logs -n argo <workflow-name>

# specific pod/container
kubectl logs -n argo <pod> -c main

# via MCP
argo-mcp-logs_workflow <workflow-name>
```

**Why a separate log stack is redundant:**
- Pod logs are already captured and served by the Argo Server
- Artifacts (`results.json`, `atspi_tree.txt`) echo to stderr — accessible via `argo logs`
- Cross-workflow queries → `argo list -n argo` then `argo logs` per workflow
- Adding Loki + Promtail duplicates storage, adds 2–3 pods, and a 10Gi PVC for no
  additional capability that `argo logs` doesn't already provide

| "The sub-template will see workflow.parameters directly." | It will not. Argo Workflows scopes parameters per-template. Always pass explicitly. |
| "I applied the template with kubectl — it's fine." | ArgoCD selfHeal will overwrite it within minutes. Use git. |
| "The lint passed locally, I'll skip CI." | CI runs against the same offline linter. If it passed locally, it passes in CI. |
| "The template is DEPRECATED, I'll clean it up later." | It will never get cleaned up. Delete it now — `prune: true` handles the rest. |
| "I need each step in the chain to have its own `when` guard." | Use a `dag` with `depends: "prior.Succeeded"` — downstream tasks cascade-omit automatically. |

## Red Flags

- Adding a separate log aggregation stack (Loki, Promtail, Vector, etc.) alongside Argo — Argo Server already retains pod logs for the workflow TTL. A separate stack duplicates storage, adds pods/PVCs, and creates a Helm-outside-ArgoCD installation with GitOps debt. `argo logs` covers the same use case.
- **Outage Risk**: Leaving nodes cordoned (`SchedulingDisabled`) after k3s upgrades or manual interventions. This completely blocks system pods (including CoreDNS!) from scheduling, causing cluster-wide DNS timeouts (`read udp i/o timeout`) and a silent, complete cluster outage. Always ensure nodes are uncordoned (`kubectl uncordon`) and `Ready`.
- **Outage Risk**: Setting low memory limits (under 2Gi) for any runner/script step that performs large file transfers (e.g. copying 400MB+ Flatcar update payloads over SCP/kubectl cp). File caching and transfer buffers will instantly trigger the container OOM-killer (exit code 137). Always set memory limits to at least 2Gi–4Gi for transfer-heavy steps.
- `synchronization.semaphore:` (singular) in any pipeline — deprecated, rejected by ArgoCD schema. Use `synchronization.semaphores:` (list with `- configMapKeyRef:` item)
- `spec.schedule:` (singular) on a CronWorkflow — field does not exist in CRD schema; use `spec.schedules:` (array)
- A pipeline with VMs and no `spec.activeDeadlineSeconds` — a stuck VM holds its semaphore slot forever
- A pipeline with VMs that adds `spec.synchronization.semaphores` — semaphores are removed; k8s scheduler handles concurrency via virt-launcher memory requests
- A `steps` or `dag` task calling a sub-template without `arguments:`
- A pipeline with no `onExit` handler (VM will leak on failure)
- Any `script:` template without `resources:` limits
- Templates in `argo/workflow-templates/` applied with `kubectl apply` (not via git)
- A `pr-poller` (or any PR-gating workflow) that skips on ANY existing commit status — it must skip only `pending` (in-flight) and `success` (already passed), and re-test on `error`/`failure`. Skipping `error` means stale statuses from deleted workflows permanently block retests.
- A hostDisk VM pipeline (`flatcar-smoke-test`) with `nodeSelector` only on individual templates but not at `spec.nodeSelector` — the DAG entrypoint pod can land on the wrong node. Set `spec.nodeSelector: kubernetes.io/hostname: ghost` at the WorkflowTemplate spec level for all hostDisk pipelines. Knuckle and GnomeOS no longer use hostDisk.
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

- [ ] All VM-running pipelines have `spec.activeDeadlineSeconds` set
- [ ] Any new CronWorkflow uses `spec.schedules:` (array), not `spec.schedule:` (singular)
- [ ] All sub-template calls include explicit `arguments:` blocks
- [ ] Pipeline has `onExit: cleanup` handler
- [ ] All pod-running templates have `resources:` requests and limits
- [ ] Change is committed and pushed — not manually applied to cluster
- [ ] `description:` annotation present on the new/modified template
- [ ] File name matches `metadata.name` (e.g. `provision-bluefin-vm.yaml` for `name: provision-bluefin-vm`)
- [ ] VM pipeline spec has NO `synchronization.semaphores` block — k8s scheduler handles VM concurrency
- [ ] VM pipeline spec has `activeDeadlineSeconds` (1h or 2h) so stuck VMs self-evict
- [ ] No `nodeSelector: kubernetes.io/hostname: ghost` in VM specs — VMs float to any KubeVirt-capable node
- [ ] GitHub Contents API write-backs use curl+jq, not inline Python; output teed to a file on persistent hostPath storage
- [ ] `kubectl get workflowtemplate -n argo` shows no cluster-only templates (not in git) unless they're intentional bootstrap one-shots
- [ ] No CronWorkflow with a `dry-run` parameter whose default is `"true"` — verify GC jobs actually delete
- [ ] All local OCI registry references use `:30500` (NodePort), not `:5000` (container-internal)
- [ ] `grep -rn 'image:' argo/ manifests/` shows only allowlisted registries: `ghcr.io`, `quay.io`, `registry.fedoraproject.org`, `registry.access.redhat.com`, `registry.k8s.io`, `192.168.1.102`, `localhost`
