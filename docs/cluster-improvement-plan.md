# Cluster Improvement Plan

_Generated from design review session, 2026-06-20. Updated 2026-06-20 with rubber-duck findings._

## Context

Ghost is a Ryzen AI MAX+ 395 (16c/32t, 64 GB RAM, ROCm gfx1151) running k3s with KubeVirt,
Argo Workflows, ArgoCD, llm-d, and two Zot pull-through caches. A second identical Strix Halo
64 GB machine is being added soon, with a 5-machine pool as the long-term target.

The strategic direction coming out of this review:

- **ARC-first** — GitHub Actions self-hosted runners are the primary CI surface for bluefin (it's
  GitHub-native). Optimise the cluster for high-throughput parallel PR testing, not general-purpose
  Kubernetes workloads.
- **Cache everything** — 2.5 Gb ethernet between nodes; a local cache at LAN speed is always faster
  than a residential internet uplink.
- **Hummingbird-first images** — Red Hat hummingbird images replace cgr.dev, docker.io
  general-purpose images, and alpine across all workflow templates and manifests.
- **BST and KubeVirt stay on ghost** — BST builds are ghost-local. All KubeVirt test VMs run on
  ghost (~7 concurrent, 8 GB each, plenty of headroom). Other nodes are pure ARC build workers.
- **llm-d floats** — no longer pinned to ghost; scheduler places it on whichever node has 48 GB
  free, freeing ghost for VMs when both are busy.

## Full PR test pipeline (target state)

```
ARC runner (any node)
  → buildah build (layer cache from Zot + per-node hostPath)
  → oras push to local Zot writable registry (ghost:30500)
  → argo submit bluefin-qa-pipeline --parameter image=192.168.1.102:30500/bluefin-pr-NNN:sha
      --parameter pr-number=NNN --parameter sha=<sha> --parameter repo=projectbluefin/bluefin
  → exit immediately (fire-and-forget)

Argo workflow (independent lifecycle):
  → BIB disk build (local Zot image URI)
  → btrfs reflink clone of golden disk
  → provision KubeVirt VM on ghost
  → SSH → behave/dogtail GNOME AT-SPI tests
  → onExit: POST GitHub commit status (token from k8s secret in argo namespace)
```

---

## Phase 0 — Pre-flight bug fixes

These are existing bugs found during the design review. Fix them before anything else —
any one can cause silent test failures independent of the improvements below.

### 0a — Unlock `golden-disk-gc` from dry-run mode

`manifests/golden-disk-gc.yaml` line 25 has `value: "true"` as the `dry-run` argument
default. The CronWorkflow runs daily at 04:00 UTC, logs every `KEEP` and `DELETE`
decision correctly, and then does nothing. Every image release adds ~30 GB to
`/var/tmp/bluefin-golden/` on ghost with no reclamation. When the partition fills,
BIB disk builds fail mid-flight, leaving behind a corrupt `disk.raw` that then blocks
future runs until manually removed.

**Fix:** change the default to `"false"`:

```yaml
arguments:
  parameters:
    - name: dry-run
      value: "false"   # was "true" — GC was never actually deleting anything
```

Keep the `dry-run` parameter so you can still pass `true` for a manual inspection run
(`argo submit --from cronworkflow/golden-disk-gc --parameter dry-run=true -n argo`).

**Validation:**
- Manually submit with `dry-run=false`, check logs show `DELETE` lines and confirm
  disk space is reclaimed: `df -h /var/tmp`.
- Confirm the daily CronWorkflow at 04:00 UTC actually frees space the next morning.

### 0b — Audit and fix the `192.168.1.102:5000` registry references

### 0c — Verify and document what is running on port 30500

Phases 4, 5, and 6 all assume a writable, OCI-compliant Zot instance at
`192.168.1.102:30500`. `AGENTS.md` documents port 30500 as the "BIB push target" but
`manifests/zot-cache.yaml` only defines `zot-ghcr` (30501) and `zot-docker` (30502).
There is no manifest for a 30500 instance in the repo. Before any work that pushes
to 30500 (runner image, GGUF, PR images), this gap must be closed.

**Investigate:**
- Is there a writable Zot deployment on ghost running outside of GitOps control?
- Or is port 30500 a plain Docker registry (not Zot)? If so, the `oras` commands
  in Phases 4 and 6d and the Zot GC policy JSON in Phase 6d do not apply.
- Run: `kubectl get svc -n local-registry` to see what is actually exposed on 30500.

**Fix:** add a manifest for the writable registry to `manifests/zot-cache.yaml` (or a
new `manifests/zot-writable.yaml`) so the state is GitOps-managed and documented,
with the correct Zot config (no upstream sync block, GC enabled, writable).

**Validation:**
- `kubectl get svc -n local-registry` shows a service at 30500.
- `oras push 192.168.1.102:30500/test:smoke <(echo test) --media-type text/plain`
  succeeds and `oras pull` retrieves it.

`bib-build-and-push.yaml` references `192.168.1.102:5000` in two detection checks
(lines 131 and 195). AGENTS.md documents the BIB push target NodePort as `30500`,
not `5000`. Port 5000 is Zot's container-internal port; it is reachable from pods
running with `hostNetwork: true` on ghost, but not from pods without it.

**Investigate:** determine whether:
- The `bib-img-build` and `bib-img-pull` steps run with `hostNetwork: true` on ghost
  (in which case `:5000` works today but is fragile), or
- These are stale references that silently fall through to the non-local image path.

**Fix:** normalise to `192.168.1.102:30500` throughout, or extract a workflow-level
parameter `local-registry` defaulting to `192.168.1.102:30500` and reference it
consistently. The same audit applies to `dakota-qa-pipeline.yaml` which also
references `:5000`.

**Validation:**
- `grep -rn ':5000' argo/ manifests/` returns only intentional references.
- Submit `just run-tests-tag latest` and confirm the local-image-detection branch
  triggers correctly when a locally-pushed image is supplied.

> **Note:** Resolve Phase 0c (writable registry identity) before closing this item.
> If port 5000 is reachable from `hostNetwork: true` BIB pods and port 30500 is
> the *same* Zot instance exposed as a NodePort, the fix is purely a normalisation.
> If they are different services, the fix may require credential or policy changes.

---

## Phase 1 — Fill Zot coverage gaps

**Why first:** `quay.io/kubevirt/virt-launcher` is pulled on every single test VM launch.
Every BIB build also hits `quay.io/centos-bootc/bootc-image-builder`. These are the hottest
uncached paths in the cluster right now.

**Audit result** (from `grep -r 'image:' argo/ manifests/`):

| Registry | Uncached images | Action |
|---|---|---|
| `quay.io` | `kubevirt/virt-launcher`, BIB, podman, skopeo, `quay.io/fedora/fedora:latest` | Add `zot-quay` 🔥 |
| `registry.fedoraproject.org` | `fedora:latest` | Add `zot-fedora` |
| `registry.access.redhat.com` | All hummingbird + UBI9 images (Phase 2 target) | **Add `zot-redhat-access`** 🔥 |
| `docker.io` (implicit) | `fedora:41` — bare reference, implicitly docker.io | Replace in Phase 2 |
| `cgr.dev` | bash, kubectl | Eliminate via Phase 2 (hummingbird replaces these) |
| `registry.k8s.io` | `kubectl:v1.32.0` | Decision needed — see Phase 2 |

### Tasks

1. **Add `zot-quay` to `manifests/zot-cache.yaml`** — copy the `zot-ghcr` Deployment/Service/ConfigMap
   block, change upstream to `https://quay.io`, assign NodePort `30503`.

2. **Add `zot-fedora` to `manifests/zot-cache.yaml`** — same pattern, upstream
   `https://registry.fedoraproject.org`, NodePort `30504`.

3. **Add `zot-redhat-access` to `manifests/zot-cache.yaml`** — same pattern, upstream
   `https://registry.access.redhat.com`, NodePort `30505`. This instance is required
   by Phase 2: all hummingbird (`hi/*`) and UBI9 images live at this registry, not
   at `ghcr.io`. Without this, Phase 2 replaces cached `cgr.dev` pulls with uncached
   `registry.access.redhat.com` pulls.

4. **Update `manifests/registry-mirror-config.yaml`** — add `quay.io.hosts.toml`,
   `registry.fedoraproject.org.hosts.toml`, and `registry.access.redhat.com.hosts.toml`
   entries in the ConfigMap, pointing to `http://192.168.1.102:30503`,
   `http://192.168.1.102:30504`, and `http://192.168.1.102:30505` respectively.

5. **Rollout restart** the `registry-mirror-config` DaemonSet so all nodes get the new
   `hosts.toml` entries.

### Validation

- Submit `just run-tests-tag latest` and confirm no `quay.io` pulls escape to the internet
  (check `zot-quay` pod logs for incoming requests).
- Check `kubectl logs -n local-registry deploy/zot-quay` shows cache hits on subsequent runs.
- Confirm `zot-redhat-access` pod logs show incoming requests on subsequent Phase 2 runs.

---

## Phase 2 — Hummingbird image migration

**Why second:** Eliminates `cgr.dev` from the image footprint, simplifies the Zot inventory,
and gives workflow steps a consistent Red Hat toolchain.

**Registry note:** Hummingbird images are at `registry.access.redhat.com/hi/` and UBI9
images at `registry.access.redhat.com/ubi9/` — **not at `ghcr.io`**. Phase 1's
`zot-redhat-access` (NodePort 30505) must be deployed first; only then are these images
transparently cached at LAN speed.

### Images to replace

All replacement images verified at `registry.access.redhat.com` as of 2026-06-20.

| Current image | Replace with | Notes |
|---|---|---|
| `cgr.dev/chainguard/bash:latest` | `registry.access.redhat.com/ubi9/ubi-minimal:9.5` | `hi/bash` does not exist; ubi-minimal includes bash |
| `cgr.dev/chainguard/kubectl:latest-dev` | ⚠️ See decision below | `hi/kubectl` does not exist |
| `registry.k8s.io/kubectl:v1.32.0` | ⚠️ See decision below | `hi/kubectl` does not exist |
| `alpine:3.20` | `registry.access.redhat.com/ubi9/ubi-micro:9.5` | |
| `docker.io/alpine:3` | `registry.access.redhat.com/ubi9/ubi-micro:9.5` | |
| `fedora:41` | `registry.fedoraproject.org/fedora:41` | Bare ref missing from earlier audit; implicit `docker.io` |
| `busybox:latest` | `registry.access.redhat.com/ubi9/ubi-micro:9.5` | `registry-mirror-config.yaml` init container **and** pause loop |
| `python:3.12-slim` | `registry.access.redhat.com/hi/python:3.12` | |
| `docker.io/library/nginx:1.27.5-alpine` | `registry.access.redhat.com/hi/nginx:1.30.0` | Version bump 1.27.5 → 1.30.0; verify nginx config compat |

**kubectl decision required:** `hi/kubectl` does not exist at `registry.access.redhat.com`.
Two options — pick one before starting Phase 2:

- **Option A (keep):** Retain `registry.k8s.io/kubectl:v1.32.0` as-is and add
  `registry.k8s.io` to the Phase 3 allowlist (annotate as kubectl-only). Zot does
  not cache `registry.k8s.io`; add a `zot-k8s` pull-through cache in Phase 1 if
  this option is chosen.
- **Option B (replace):** Build a thin image in `images/kubectl/Containerfile`:
  `FROM registry.access.redhat.com/ubi9/ubi-minimal:9.5` + `curl -L dl.k8s.io/...`.
  Push to `192.168.1.102:30500/kubectl:v1.32.0`. Fully eliminates `registry.k8s.io`
  from the fleet.

**Keep as-is** (no hummingbird equivalent):
- `docker.io/rocm/k8s-device-plugin:1.31.0.10` — ROCm-specific; `zot-docker` is
  retained solely for this image after Phase 2
- `quay.io/*` — BIB, podman, skopeo, kubevirt virt-launcher (cached via Phase 1)

### Tasks

1. **Resolve the kubectl decision** (Option A or B above) before touching any files.

2. For each image in the table above, update every YAML reference.

3. Run `just lint` after each file change to verify templates remain valid.

4. After all replacements, confirm:
   ```bash
   grep -r 'cgr.dev' argo/ manifests/
   ```
   returns empty (and `registry.k8s.io` is empty if Option B was chosen).

5. **`registry-mirror-config.yaml` specifically** — replace both the init container
   (`busybox:latest` writing the `hosts.toml` files) and the pause loop container
   (`busybox:latest` kept alive to preserve the DaemonSet) with
   `registry.access.redhat.com/ubi9/ubi-micro:9.5`. The pause loop has a
   `# ponytail:` comment explaining its purpose; preserve it.

### Validation

- `just lint` passes cleanly.
- `grep -r 'cgr.dev\|alpine:\|busybox:\|python:3.12-slim\|fedora:41' argo/ manifests/` — empty.
- `grep -r 'registry.k8s.io' argo/ manifests/` — empty if Option B was chosen.
- Submit a smoke test run and confirm no new registry errors.

---

## Phase 3 — CI lint gate for uncached registries

**Why after Phase 2:** The lint gate enforces the clean post-migration state. Adding it before
Phase 2 is complete would fail on every current PR.

> **Sequencing note:** Phases 2 and 3 must land in the same PR (or Phase 3 must be
> merged in the same commit as the final Phase 2 change). Merging Phase 3 before all
> Phase 2 replacements are complete will cause CI to fail on every open PR until Phase 2
> is finished.

### Tasks

1. **Add a lint step to `.github/workflows/lint.yaml`** that:
   - Greps all `argo/` and `manifests/` YAML files for `image:` references.
   - Extracts the registry hostname from each image reference.
   - Fails if any registry is not in the allowlist:
     ```
     ghcr.io
     quay.io
     registry.fedoraproject.org
     registry.access.redhat.com
     192.168.1.102
     localhost
     # docker.io — intentionally absent after Phase 2, except ROCm device plugin:
     # docker.io/rocm/k8s-device-plugin is exempted via per-line ignore comment
     ```
   - If Option A (keep kubectl) was chosen: also allowlist `registry.k8s.io` and
     add a comment noting it is kubectl-only.
   - Add a per-line escape hatch (e.g., `# registry-lint-ignore`) for the
     `docker.io/rocm/k8s-device-plugin` line in `rocm-device-plugin.yaml` — this
     image has no Red Hat equivalent and must remain.
   - Prints the offending image and file on failure.

2. Keep the check fast — a single shell `grep + awk` pipeline is sufficient; no external tools.

### Validation

- PR that adds `alpine:3.20` triggers a lint failure.
- PR that adds `registry.access.redhat.com/hi/nginx:1.30.0` passes.
- The `rocm-device-plugin.yaml` `docker.io` reference does **not** trigger a failure.
- PR that adds `cgr.dev/chainguard/bash:latest` triggers a lint failure.

---

## Phase 4 — LLM float + all model artifacts in Zot

**Why here:** Depends on the writable Zot registry (port 30500) being stable and trusted.
Floating llm-d frees ghost's 48 GB RAM for the full 7-VM concurrent test capacity.

> **Single-node note:** On a single-node cluster, removing `nodeSelector` and setting
> `resources.requests.memory: 48Gi` is harmless — the scheduler has nowhere to float
> but the manifest is already correct for when a second node arrives. No changes needed
> for single-node adoption.

> **Prerequisite:** Phase 0c must be complete before starting Phase 4. Port 30500's
> identity and writeability must be verified and documented in GitOps before any
> `oras push` commands are attempted here.

### Pre-check: verify Zot port 30500 accepts OCI artifacts

Port 30500 was originally configured as a BIB push target for container image blobs. Before
pushing a raw GGUF, verify the Zot config in `manifests/zot-cache.yaml` (or wherever
30500 is managed after Phase 0c) has no `mediaType` filter that rejects
`application/octet-stream`. If it does, relax the content policy or add a separate
Zot instance for model artifacts.

### Tasks

1. **Push the GGUF as an OCI artifact** to local Zot:
   ```bash
   oras push 192.168.1.102:30500/llm-models/gemma-4-31B-it-Q8_0:latest \
     ./gemma-4-31B-it-Q8_0.gguf:application/octet-stream
   ```
   _(Run once from ghost where the file already lives at `/var/tmp/llm-models/`.)_

2. **Update `manifests/llm-d.yaml`**:
   - Remove `nodeSelector: kubernetes.io/hostname: ghost`.
   - Replace the init container download logic with:
     1. `oras pull 192.168.1.102:30500/llm-models/gemma-4-31B-it-Q8_0:latest` → target dir.
     2. Fall back to HuggingFace download + `oras push` to Zot on first run (seeds the cache).
   - Verify `resources.requests.memory: 48Gi` is set (scheduler float mechanism — pod only
     lands on a node with 48 GB free).
   - The llama.cpp container image (`ghcr.io/ggml-org/llama.cpp:server-rocm`) is already
     transparently cached by `zot-ghcr` — no change needed there.
   - Future LoRA adapters and quantized variants follow the same `oras push` → `oras pull`
     pattern.

3. **Verify all Strix Halo ROCm env vars are still present** after manifest edit:
   `HSA_OVERRIDE_GFX_VERSION=11.5.1`, `HSA_XNACK=1`, `ROCBLAS_USE_HIPBLASLT=1`, `-fa`,
   `--no-mmap` — these are required on every Strix Halo node and must not be lost.

### Validation

- Delete the llm-d pod. Confirm it reschedules on whichever node has RAM headroom (not
  necessarily ghost).
- Confirm init container pulls GGUF from `192.168.1.102:30500` at LAN speed (check init
  container logs for the source URL).
- Confirm the model loads and responds: `curl http://192.168.1.102:30800/v1/models`.

---

## Phase 5 — ARC runner improvements

**Why here:** Depends on the hummingbird images from Phase 2 (for the custom runner base)
and Zot being solid (to store and serve the custom runner image).

### 5a — Custom runner image

Build a custom runner image on top of Red Hat hummingbird with the bluefin toolchain
pre-installed: `buildah`, `skopeo`, `cosign`, `oras`, `argo` CLI, and any other tools
currently installed per-job.

1. Create `images/arc-runner/Containerfile` in this repo with the hummingbird base +
   toolchain install steps.
2. Build and push to local Zot: `192.168.1.102:30500/arc-runner:latest`.
3. Update `argocd/arc-runners-app.yaml` Helm values:
   ```yaml
   template:
     spec:
       containers:
         - name: runner
           image: 192.168.1.102:30500/arc-runner:latest
   ```
4. Tag the image by date or git SHA, not `latest`, so rollbacks are trivial.

### 5b — maxRunners and per-node buildah cache

Update `argocd/arc-runners-app.yaml`:

```yaml
maxRunners: 4    # single-node default; scale up as nodes join (4 per ARC node × N + 2 on ghost)

template:
  spec:
    volumes:
      - name: buildah-cache
        hostPath:
          path: /var/tmp/arc-buildah-cache
          type: DirectoryOrCreate
    containers:
      - name: runner
        volumeMounts:
          - name: buildah-cache
            mountPath: /home/runner/.local/share/containers/storage
```

**Volume distinction:** the existing `kubernetesModeWorkVolumeClaim` (`local-path`, 10 Gi,
`ReadWriteOnce`) is the **job workspace** providing per-job isolation for source checkouts
and build outputs — keep it. The `buildah-cache` hostPath above is **additional**, mounted
only for layer storage. Do not replace the work volume.

The `hostPath` is node-local and persists across jobs on the same node. Zot provides
cross-node OCI layer deduplication — if node B needs a layer node A already built, it
pulls from Zot at LAN speed, not the internet.

**Ghost capacity constraint:** with the LLM floating at 48 Gi and up to 7 VMs at 8 Gi
each, ghost has limited headroom for runner pods. The `resources.requests` on the LLM and
VMs will naturally push the scheduler toward other nodes. Monitor with
`kubectl get pods -n arc-runners -o wide` after Framework desktop joins — if more than
2–3 runners land on ghost consistently, add a node taint or runner `nodeAffinity` to
steer excess runners away.

### Validation

- Verify runners spread across both ghost and Framework desktop once it joins:
  `kubectl get pods -n arc-runners -o wide`
- Confirm buildah cache dir persists between jobs on the same node:
  run two consecutive builds on the same node and confirm the second is faster.
- Check runner image pulls from `192.168.1.102:30500`, not `ghcr.io`.

---

## Phase 6 — PR pipeline wiring

**Why last:** Depends on everything above: Zot (images), ARC runner (custom image + toolchain),
and the bib-build-and-push fix.

### 6a — Fix `bib-build-and-push.yaml` local image source

> **Note:** Phase 0c (writable registry identity) must be resolved before 6a.
> Assume `192.168.1.102:30500` is writable Zot throughout sections 6a–6d.

The `ensure-disk` template already accepts an `image` parameter. Verify it passes through
correctly to `bib-img-pull` and `bib-img-build` when given a local Zot URI
(`192.168.1.102:30500/bluefin-pr-NNN:sha`). Fix any hardcoded `ghcr.io` references inside
those sub-templates. Add a note in the template annotation documenting the local Zot URI
pattern.

Note on `bib-img-pull`: this step calls `skopeo` to pull the image from the upstream
registry. For a locally-pushed image the pull is still valid (Zot serves it), but if
the `bib-disk-check` step returns `exists` the entire pull+build chain is already
skipped. For the `stale` / `missing` path, Zot will serve the locally-pushed image
without touching the internet — no special casing needed as long as Zot is reachable.

### 6b — GitHub commit status reporting in Argo

1. Create a `github-token` secret in the `argo` namespace:
   ```bash
   kubectl create secret generic github-token \
     --from-literal=token=<PAT or GitHub App token> \
     -n argo
   ```
   The token needs `statuses:write` and `pull_requests:read` scope (or the equivalent
   GitHub App permissions).

2. Add an `onExit` template to `bluefin-qa-pipeline.yaml` that posts a GitHub commit status.
   Use `jq -n` to build the JSON payload — do not manually escape quotes inside a bash
   double-quoted string, as `{{inputs.parameters.repo}}` contains a forward slash that
   becomes ambiguous in complex quoting contexts:
   ```yaml
   onExit: post-github-status
   templates:
     - name: post-github-status
       inputs:
         parameters:
           - name: pr-number
           - name: sha
           - name: repo
       script:
         image: 192.168.1.102:30500/arc-runner:latest
         source: |
           STATE=$([ "{{workflow.status}}" = "Succeeded" ] && echo success || echo failure)
           PAYLOAD=$(jq -n \
             --arg state "$STATE" \
             --arg ctx "ghost-lab" \
             --arg desc "Bluefin lab test $STATE" \
             --arg url "http://192.168.1.102:32746/workflows/argo/{{workflow.name}}" \
             '{state:$state, context:$ctx, description:$desc, target_url:$url}')
           curl -sf -X POST \
             -H "Authorization: token $(cat /var/run/secrets/github-token/token)" \
             -H "Accept: application/vnd.github+json" \
             -H "Content-Type: application/json" \
             "https://api.github.com/repos/{{inputs.parameters.repo}}/statuses/{{inputs.parameters.sha}}" \
             -d "$PAYLOAD"
   ```
3. Thread `pr-number`, `sha`, and `repo` as parameters through `bluefin-qa-pipeline.yaml`
   inputs down to the `post-github-status` template (they're optional — omit them in nightly
   CronWorkflow invocations, skip the status post if absent).

### 6c — GitHub Actions trigger workflow (in bluefin repo)

Every PR push creates a `192.168.1.102:30500/bluefin-pr-NNN:sha` image in the local
writable Zot registry. Unlike the pull-through caches, the writable registry has no
automatic expiry. At scale (many contributors, many pushes per PR) these accumulate on
ghost's disk indefinitely, reproducing the same silent disk-fill failure as Phase 0a.

**Fix — Zot GC policy:** enable storage GC on the writable Zot instance (port 30500)
in `manifests/zot-cache.yaml`:

```json
"storage": {
  "rootDirectory": "/var/lib/registry",
  "gc": true,
  "gcDelay": "1h",
  "gcInterval": "24h"
}
```

This reclaims layers no longer referenced by any tag. It does not delete tags
themselves — add a tag cleanup CronWorkflow alongside it.

**Fix — tag cleanup CronWorkflow:** add `manifests/pr-image-gc.yaml`, a CronWorkflow
that runs daily and deletes Zot tags matching `bluefin-pr-*` older than 7 days, and
any `bluefin-pr-*` tag whose PR is closed or merged (query the GitHub API with the
same `github-token` secret from Phase 6b):

```bash
# pseudocode — implement as a script step in the CronWorkflow
for tag in $(oras repo tags 192.168.1.102:30500/bluefin-pr-* --older-than 7d); do
  oras manifest delete 192.168.1.102:30500/${tag}
done
```

**Validation:**
- After 8+ days of PR activity, confirm `oras repo tags` shows no tags older than 7d.
- Confirm `df -h /var/tmp` on ghost is not growing monotonically.

### 6d — PR image cleanup in Zot

Add a workflow in `projectbluefin/bluefin` (or equivalent repo) that triggers on
`pull_request` and runs on `ghost-runners`:

```yaml
jobs:
  lab-test:
    runs-on: ghost-runners
    steps:
      - uses: actions/checkout@v4
      - name: Build image locally
        run: |
          buildah build -t 192.168.1.102:30500/bluefin-pr-${{ github.event.pull_request.number }}:${{ github.sha }} .
          buildah push 192.168.1.102:30500/bluefin-pr-${{ github.event.pull_request.number }}:${{ github.sha }}
      - name: Submit Argo test workflow
        run: |
          argo submit --from workflowtemplate/bluefin-qa-pipeline \
            --parameter image=192.168.1.102:30500/bluefin-pr-${{ github.event.pull_request.number }}:${{ github.sha }} \
            --parameter pr-number=${{ github.event.pull_request.number }} \
            --parameter sha=${{ github.sha }} \
            --parameter repo=${{ github.repository }} \
            -n argo
          # fire-and-forget: runner exits, Argo owns the lifecycle and reports back
```

### Validation

- Open a test PR in the bluefin repo, confirm:
  1. The ARC runner builds and exits within a few minutes.
  2. An Argo workflow appears in the `argo` namespace with the PR image tag.
  3. After the workflow completes, a commit status appears on the PR in GitHub.

---

## Phase 7 — System contract tests in the nightly pipeline

> **Note:** `ghost-kernel-args` WorkflowTemplate is referenced in the node join
> checklist below. Verify it exists in `argo/workflow-templates/` before the first
> new node joins — it does not appear in the current file list and may be on-cluster
> only (a GitOps violation) or may need to be created.

**Why it matters:** `tests/system/features/` contains the atomic OS contract test suite —
`bootc.feature`, `filesystem.feature`, `integrity.feature`, `uupd.feature`. These tests
verify Bluefin's core identity as an image-based, atomic operating system (bootc staging,
read-only `/usr`, composefs/fs-verity, `uupd` orchestration). Per the AGENTS.md test
suite mantra, these take priority over cosmetic UI checks. The nightlies currently only
run `smoke/` (browser, flatpak health, GNOME shell) via `run-gnome-tests.yaml`. The
`system/` tests have no corresponding WorkflowTemplate and are not in any nightly.

### Tasks

1. **Audit `tests/system/features/` step files** to understand what the tests need:
   which AT-SPI calls, which system commands, which dependencies beyond `qecore-headless`.
   The `bootc` and `uupd` tests are likely command-line only (no Wayland session required);
   `gnome_shell` shell interactions may still need the Wayland session.

2. **Create `argo/workflow-templates/run-system-tests.yaml`** following the same pattern
   as `run-gnome-tests.yaml`:
   - SSH into the test VM.
   - Run `qecore-headless --session-type wayland --session-desktop gnome` only if the
     tests require a graphical session; otherwise run `behave tests/system/` directly.
   - Output: pass/fail, test log artifact.

3. **Wire into `bluefin-qa-pipeline.yaml`** sequentially after `run-gnome-tests`.
   Both test suites share the same VM — no new VM provision needed. Use `dag` with
   `depends: run-gnome-tests` (not `depends: provision-vm`). Running in parallel
   risks system tests triggering a `bootc` staged deployment or reboot that
   interrupts the live GNOME Wayland session mid-test.

4. **Update nightly CronWorkflows** — system tests run automatically as part of the
   `bluefin-qa-pipeline` call; no separate CronWorkflow needed.

5. **Wire into the PR pipeline** (Phase 6) — the same `bluefin-qa-pipeline` invocation
   from the ARC runner will pick up system tests automatically once they are added to
   the pipeline.

### Validation

- Submit `just run-tests-tag latest` and confirm both `run-gnome-tests` and
  `run-system-tests` steps appear in the Argo DAG and complete.
- Confirm `bootc.feature` and `integrity.feature` pass on a known-good Bluefin image.
- Confirm a deliberate regression (e.g., mock a broken `uupd` output) causes
  `uupd.feature` to fail and the pipeline to report failure.

---

## What is deferred

| Item | Reason |
|---|---|
| **k3s control plane HA** | Homelab; embedded etcd HA requires 3 control-plane nodes, high complexity, low ROI. Ghost reboots recover in minutes. |
| **Observability / alerting** | Argo UI is sufficient for now. Add Argo Notifications or an `onExit` webhook when a missed nightly failure actually causes a problem. |
| **KubeVirt on non-ghost nodes** | Ghost alone handles ~7 concurrent VMs (7 × 8 GB = 56 GB). No bottleneck at current PR volume. Revisit if VM slots queue. |
| **knuckle SSH migration** | Tracked in #113–118. Ongoing migration to in-pod kubectl/virtctl pattern. |
| **NFS / shared build cache** | Per-node hostPath + Zot deduplication is sufficient. NFS adds locking risk with no clear benefit at 5-node scale. |
| **bazzite as burst ARC capacity** | bazzite is ~90% available but k3s is disabled at boot and the node is tainted `NoSchedule`. When more ARC capacity is needed, enable k3s at boot, remove the taint, and it joins the runner pool automatically. No manifest changes needed. |
| **exo-1 role** | exo-1 is a workflow pod worker. Once 5 Strix Halo nodes are in the pool it becomes redundant. Decommission or repurpose when convenient — no plan changes required. |
| **Test dependency install time** | `run-gnome-tests` installs qecore, behave, dogtail, gnome-ponytail-daemon, and python-uinput on every run. Estimated 5–10 min per run, not yet measured on a real warm run. Options: bake into golden disk (best, zero per-run cost), pip wheel cache on hostPath (medium), or accept current cost. **Measure a real warm run first** — file an issue once the baseline is known. |

---

## Node join checklist (for Framework desktop and future nodes)

When a new Strix Halo node joins the pool:

1. Join as k3s agent: `k3s agent --server https://ghost:6443 --token <token>`
2. The `registry-mirror-config` DaemonSet applies `hosts.toml` automatically — no manual
   containerd config needed.
3. The `arc-runners` ARC scale set schedules runner pods on it automatically — no
   `nodeSelector` or label needed.
4. The `buildah-cache` hostPath directory (`/var/tmp/arc-buildah-cache`) is created by
   `DirectoryOrCreate` on first pod — no manual setup.
5. **Apply Strix Halo performance kernel args** via the `ghost-kernel-args` WorkflowTemplate:
   ```bash
   argo submit --from workflowtemplate/ghost-kernel-args -n argo \
     --parameter node=<new-node-hostname>
   ```
   Required args: `amd_iommu=off amdgpu.gttsize=61440 ttm.pages_limit=15728640`.
   The WorkflowTemplate currently targets ghost by name — update it to accept a `node`
   parameter so it works for any Strix Halo node. A reboot is required after.
   Without these args, ROCm performance is degraded and llm-d may crash on the new node.

   > ⚠️ **`ghost-kernel-args` must exist in `argo/workflow-templates/` before the first
   > new node joins.** Verify it is in git (not just on-cluster) and accepts a `node`
   > parameter. If it only exists on-cluster, commit it to the repo first — see Phase 7 note.

6. Verify the node appears in `kubectl get nodes` and runner pods land on it within a few
   minutes of a GitHub Actions job being queued.
