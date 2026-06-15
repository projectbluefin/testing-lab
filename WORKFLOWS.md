# WorkflowTemplates — Agent Contract

This is the canonical interface for driving the lab. Every supported
operation is a single `argo submit --from workflowtemplate/<name> [-p k=v]`
invocation. No bash, no `kubectl apply`, no SSH.

Conventions:

- All templates live in `argo/workflow-templates/*.yaml` and are reconciled
  to namespace `argo` by the ArgoCD `testing-lab` Application.
- Workflow-level parameters listed below are passed via `-p name=value`.
- Wall-clock targets are warm-cache numbers; cold-cache figures (BIB build
  on a missing golden disk) add ~5–10 min.
- The agent contract: prefer the **top-level** templates (`bluefin-qa-pipeline`,
  `bluefin-titan-smoke`). The supporting templates (provision, run, teardown)
  are called as `templateRef` and rarely submitted directly.

---

## Top-level entry points

### `bluefin-qa-pipeline`

Full pipeline: ensure golden disk → reflink + boot a fresh KubeVirt VM →
run test suites → teardown VM on exit.

| Parameter | Default | Notes |
|---|---|---|
| `image` | `ghcr.io/projectbluefin/bluefin` | Source image. Tag is appended from `image-tag` for some callers; pass with tag if invoking directly. |
| `image-tag` | `latest` | `latest`, `lts`, etc. Also used as the golden-disk dir name. |
| `namespace` | `bluefin-test` | KubeVirt VM namespace. Use `bluefin-lts-test` for LTS. |
| `suites` | `smoke,developer` | Comma list; valid: `smoke`, `developer`, `software`. |
| `variant` | `bluefin` | Selects test fixtures (e.g. `dakota` for Ghostty). |
| `ssh-key-secret` | `bluefin-test-ssh-key` | Secret in `argo` ns with `id_ed25519`. |

Wall-clock: ~5 min (warm), ~10–14 min (cold BIB rebuild).

```
argo submit --from workflowtemplate/bluefin-qa-pipeline \
  -p image-tag=latest -p suites=smoke --wait
```

### `knuckle-qa-pipeline`

Builds the Knuckle installer ISO from source, boots a blank KubeVirt VM in
`knuckle-test`, runs a headless install with an explicit `/install-complete`
signal, reboots from the installed disk, rediscovers the new VMI IP, then runs
smoke tests against the installed system.

| Parameter | Default | Notes |
|---|---|---|
| `branch` | `main` | Knuckle source branch to clone and build. |
| `namespace` | `knuckle-test` | KubeVirt namespace for the ephemeral installer VM. |
| `suite` | `smoke` | Single GNOME test suite to run after install. |
| `ssh-key-secret` | `bluefin-test-ssh-key` | Secret in `argo` ns used for installer access and installed-system SSH. |
| `tests-branch` | `main` | `testing-lab` branch cloned by `run-gnome-tests`. |

Wall-clock: ~12–20 min depending on ISO build cache and Flatcar download time.

```
argo submit --from workflowtemplate/knuckle-qa-pipeline \
  -p branch=main -p suite=smoke --wait
```

### `bluefin-titan-smoke`

Runs smoke tests against the **persistent** titan VMs (`titan-bluefin`,
`titan-lts`). Skips BIB and VM provisioning entirely. Use when iterating on
tests or when BIB is slow/broken.

Prerequisites: both titan VMs running. Fetch IPs:

```
kubectl get vmi titan-bluefin -n bluefin-test -o jsonpath='{.status.interfaces[0].ipAddress}'
kubectl get vmi titan-lts    -n bluefin-lts-test -o jsonpath='{.status.interfaces[0].ipAddress}'
```

| Parameter | Default | Notes |
|---|---|---|
| `vm-ip-latest` | *(required)* | titan-bluefin IP |
| `vm-ip-lts` | *(required)* | titan-lts IP |
| `suite` | `smoke` | Single suite name. |
| `ssh-key-secret` | `bluefin-test-ssh-key` | |
| `issue-title` | `titan smoke run` | Free-text label, appears in pod annotation. |

Wall-clock: ~3 min (test-only, no provisioning).

```
argo submit --from workflowtemplate/bluefin-titan-smoke \
  -p vm-ip-latest=10.42.x.y -p vm-ip-lts=10.42.x.z --wait
```

### `patch-golden-disk`

One-shot maintenance: re-runs the disk configuration step (SSH key,
selinux=0, sudoers) on an existing golden disk without rebuilding it.

| Parameter | Default | Notes |
|---|---|---|
| `image-tag` | `latest` | Disk dir under `/var/tmp/bluefin-golden/`. |

---

## Supporting templates (called via `templateRef`)

These are exposed only because they are referenced by the entry points;
submit them directly only for diagnosis.

### `bib-build-and-push` (template: `ensure-disk`)

Builds the golden raw disk via `bootc-image-builder` if missing or stale.
Stale detection compares the upstream image digest (via skopeo) against the
`source-digest` marker written next to the disk on hostPath.

Outputs: no `outputs.parameters`; side effect is
`/var/tmp/bluefin-golden/<image-tag>/disk.raw` and `source-digest` on ghost.

### `provision-bluefin-vm` (template: `provision-vm`)

btrfs `cp --reflink=auto` from the golden disk, applies SVirt label, creates
a KubeVirt VM, waits for SSH/IP, emits `vm-ip` as an output parameter.

### `provision-flatcar-vm` (template: `provision-vm`)

Same shape for Flatcar — accepts an `ssh-pubkey` parameter directly instead
of relying on the bluefin-test secret for cloud-init injection.

### `run-gnome-tests` (template: `run-gnome-tests`)

`git-sync` initContainer clones testing-lab → main container SSHes to the VM
IP → installs deps (skipped if present) → runs qecore-headless + behave →
captures `results.json` to pod stdout (Loki + `argo logs`).

Resource limits and `hostNetwork: true` are set on the pod (KubeVirt
masquerade only routes from host netns).

### `run-flatcar-tests` (template: `run-flatcar-tests`)

Same shape for Flatcar; uses `core` as the SSH user and runs pytest+dogtail
fixtures from `tests/flatcar/`.

### `teardown-bluefin-vm` / `teardown-flatcar-vm`

Delete the VM, wait for the VMI object to drain, then `rm` the per-run
hostDisk clone. Invoked as `onExit` from the pipeline templates.

---

## Homelab in-cluster probe lanes

Stateless probe workflows that deploy a fixture workload, run pytest checks
against the live Kubernetes objects, and clean up on exit.  Delegated runner
pod uses `run-incluster-tests / run-pytest`.

### `homelab-access-probe` (issues #82 / #83)

Validates hostname resolution, HTTPS reachability, and (optionally) auth gating
for k8s-hosted homelab workloads.  A self-contained Python HTTPS server is
deployed inline as the probe target; TLS cert and auth credentials are
generated fresh each run.

| Parameter | Default | Notes |
|---|---|---|
| `auth-mode` | `false` | `false` runs `test_access_probe.py`; `true` runs `test_auth_probe.py` |
| `branch` | `main` | testing-lab git ref cloned by the runner |

**Non-auth mode** (`auth-mode=false`) — suite `tests/homelab_access/test_access_probe.py`:
- Cluster DNS resolves the service FQDN
- HTTPS handshake exposes a valid certificate
- Expected Host header reaches the fixture and returns `access-ok`

**Auth mode** (`auth-mode=true`) — suite `tests/homelab_access/test_auth_probe.py` (15 tests; 1 explicit skip for SSO — issue #61):
- Unauthenticated request returns HTTP 401
- 401 carries `WWW-Authenticate: Basic realm="homelab"` header
- Wrong credentials are rejected
- Authenticated request returns HTTP 200 with `access-ok` body
- TLS handshake completes independently of auth status
- Failure artifacts captured: response status, headers, body, TLS evidence

Artifacts are written to `/tmp/results/` inside the runner pod and collected by the workflow log tail.

```
just run-homelab-access        # non-auth probe, ~4–6 min
just run-homelab-auth          # auth-gated probe, ~4–6 min
```

Out of scope: SSO / identity-provider integration (see issue #61).

---

## Dakota BST builds

### `dakota-bst`

Drives dakota BuildStream builds on ghost via the existing `just` recipes.
Mounts jorge's BST cache for warm builds (~2–5 min warm, ~60–90 min cold).
No changes to the dakota repo — this is purely an orchestration wrapper.

| Parameter | Default | Notes |
|---|---|---|
| `variant` | `default` | `default`, `nvidia`, or `all` |
| `branch` | `main` | dakota branch to clone |

Pipeline: `bst-validate` (fast graph check) → `bst-build` (build + lint).

```
just run-dakota-validate              # bst show only, ~5 min
just run-dakota-build                 # default variant
just run-dakota-build nvidia          # nvidia variant
just run-dakota-build all             # both variants sequentially
```

---

## CronWorkflows

Lives in `manifests/`, applied via the `testing-lab-infra` ArgoCD app:

| Schedule | Cron | Template called | Purpose |
|---|---|---|---|
| `nightly-smoke` | 02:00 UTC | `bluefin-qa-pipeline` (latest) | Catch upstream regressions |
| `nightly-smoke-lts` | 02:30 UTC | `bluefin-qa-pipeline` (lts)    | Same, for LTS branch; first fire builds the missing golden disk |
| `orphan-vm-cleanup` | every 2h | inline | GC stale per-run hostDisks in bluefin, flatcar, and knuckle namespaces |

---

## Editing this contract

When you add or rename a template, update this file in the same PR. Drift
between templates and this doc is what breaks autonomous agents.
