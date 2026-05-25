# Testing Lab — Agent Instructions

> Read this before touching anything. Last updated: 2026-05-25.

## What This Repo Is

Bluefin QA pipeline: Argo Workflows + KubeVirt + ArgoCD + behave/dogtail.
Tests boot Bluefin Linux VMs and run GNOME Shell accessibility smoke tests.
Canonical issue tracker: **castrojo/testing-lab** (this repo). Do NOT file issues in castrojo/copilot-config.

## Core Tenet: All Agent Operations Are API-Driven

**Agents must use the Kubernetes API and MCP servers. Never SSH to nodes. Never kubectl from outside the cluster.**

| Operation | Correct tool |
|---|---|
| Submit a workflow | Argo MCP `submit_workflow` or `just <target>` from a host with cluster access |
| Check workflow status | Argo MCP `get_workflow` / `list_workflows` |
| Get workflow logs | Argo MCP `get_workflow_logs` |
| Update a WorkflowTemplate | Edit YAML → `git push main` → ArgoCD auto-syncs (~3 min) |
| Update cluster infra | Edit `manifests/` → `git push main` → ArgoCD auto-syncs |
| Read cluster state | kubectl MCP or Argo MCP |

If an MCP tool doesn't exist for an operation, the right fix is to build or deploy that capability — not to fall back to SSH.

## Cluster Topology

| Host | Role | IP | Specs |
|---|---|---|---|
| ghost | k3s control-plane + KubeVirt compute | 192.168.1.102 | Ryzen AI MAX+ 395, 16c/32t, 64GB RAM |
| exo-1 | k3s worker (workflow pods only) | 192.168.1.239 | — |
| Argo UI | — | http://192.168.1.102:32746 | NodePort; also http://192.168.1.102:2746 on host |
| Loki | log aggregation | http://192.168.1.102:30100 | Scrapes pods labeled `app.kubernetes.io/part-of=bluefin-test-suite` |
| ArgoCD | GitOps controller | https://192.168.1.102 (argocd NS) | Two Applications: `testing-lab` + `testing-lab-infra` |

All KubeVirt VMs are pinned to ghost via `nodeSelector: kubernetes.io/hostname: ghost`.

## GitOps Rules

Two ArgoCD Applications manage this repo:

| Application | Syncs | Namespace |
|---|---|---|
| `testing-lab` | `argo/workflow-templates/` | argo |
| `testing-lab-infra` | `manifests/` | argo (+ others via namespace in manifest) |

Rules:
1. **WorkflowTemplate changes**: edit `argo/workflow-templates/*.yaml` → push to `main` → ArgoCD syncs
2. **Cluster infra changes**: edit `manifests/*.yaml` → push to `main` → ArgoCD syncs
3. **Never `kubectl apply`** WorkflowTemplates — ArgoCD overwrites manual applies
4. **Never `argo-mcp-create_workflow_template`** — ArgoCD owns that reconciliation loop
5. **Never amend published commits** — create new commits
6. Force sync when needed: `just argocd-sync`

`manifests/` uses `ServerSideApply: true` — manifests patch rather than replace. Safe to define partial resources (e.g. patching a Helm-managed ConfigMap by adding a key).

## Repo Layout

```
argo/
  workflow-templates/          ← ArgoCD (testing-lab App) syncs these
    bib-build-and-push.yaml       build golden disk via BIB
    provision-vm.yaml             reflink golden disk + boot KubeVirt VM
    run-gnome-tests.yaml          SSH into VM, run behave/qecore suite
    teardown-vm.yaml              delete VM + hostDisk
    bluefin-titan-smoke.yaml      smoke against persistent titan VMs (fast path)
    bluefin-qa-pipeline.yaml      full pipeline: ensure-disk + provision + tests
    patch-golden-disk.yaml        retroactively fix SSH auth on existing disk
  bluefin-smoke-test.yaml         submit: full BIB+provision+test run (latest)
  bluefin-test-matrix.yaml        submit: parallel latest+lts matrix
manifests/                     ← ArgoCD (testing-lab-infra App) syncs these
  argo-server-nodeport.yaml       NodePort 32746 for external Argo API access
  titan-bluefin.yaml              persistent titan VM (latest)
  titan-lts.yaml                  persistent titan VM (lts)
  orphan-vm-cleanup.yaml          CronWorkflow: clean orphaned VMs every 2h
  nightly-smoke.yaml              CronWorkflow: nightly smoke latest @ 02:00 UTC
  nightly-smoke-lts.yaml          CronWorkflow: nightly smoke lts @ 02:30 UTC
  workflow-controller-configmap.yaml  global TTL patch (7d success, 30d failure)
  flatcar-test-namespace.yaml     Flatcar test namespace
argocd/
  application.yaml               ArgoCD Application: testing-lab
  infra-application.yaml         ArgoCD Application: testing-lab-infra
tests/
  smoke/features/                behave/qecore GNOME Shell smoke tests ← ACTIVE
  developer/features/            behave GNOME desktop tests (podman, ptyxis, etc.)
  software/features/             behave flatpak/Bazaar tests
  flatcar/                       Flatcar systemd/container tests
AGENTS.md                        This file
RUNBOOK.md                       Operations reference — read before debugging
SECURITY.md                      Accepted homelab trade-offs and risks
Justfile                         Local shortcuts (require kubectl/argo access)
```

## Image Variants

| Tag | Image | Golden disk | Nightly |
|---|---|---|---|
| `latest` | `ghcr.io/ublue-os/bluefin:latest` | `/var/tmp/bluefin-golden/latest/disk.raw` on ghost | 02:00 UTC |
| `lts` | `ghcr.io/ublue-os/bluefin:lts` | `/var/tmp/bluefin-golden/lts/disk.raw` — built on first nightly fire | 02:30 UTC |

`gts` and `lts-hwe` do NOT exist. Never use these tags.

## Persistent (Titan) VMs

Two always-on VMs for fast test iteration — no BIB build needed, no VM provisioning wait:

| VM | Namespace | IP | Disk |
|---|---|---|---|
| `titan-bluefin` | bluefin-test | 10.42.0.27 | `/var/home/jorge/VMs/titans/titan-bluefin/image/disk.raw` |
| `titan-lts` | bluefin-lts-test | 10.42.0.26 | `/var/home/jorge/VMs/titans/image/disk.raw` |

Managed by ArgoCD via `manifests/titan-bluefin.yaml` and `manifests/titan-lts.yaml`.
SSH key: `bluefin-test-ssh-key` secret in `argo` namespace.

**Titan run time**: ~5 min (SSH wait + dep check + copy + behave).
Deps skip if already installed — check is: `python3 -c 'import qecore, behave, dogtail'` + `rpm -q` + `qecore-headless` binary.

To run smoke against them: `just run-titan-smoke` or submit `bluefin-titan-smoke` WorkflowTemplate via Argo MCP with current VM IPs.

## Test Stack

| Component | Role |
|---|---|
| **behave** | BDD test runner |
| **qecore** | Red Hat test framework; `qecore-headless` starts Wayland session |
| **dogtail** | AT-SPI accessibility tree traversal |
| **gnome-ponytail-daemon** | Bridges AT-SPI coordinates to Wayland surface coordinates |
| **Shell.Eval** | `gdbus call --session --dest org.gnome.Shell --method org.gnome.Shell.Eval` — required for GNOME Shell 50 top-bar interactions (AT-SPI gaps) |

`qecore-headless` must be invoked with `--session-type wayland --session-desktop gnome` (explicit flags required).

**unsafe_mode** (`global.context.unsafe_mode = true`) must be enabled before top-bar AT-SPI interactions. Set via `gdbus call` in `environment.py` `before_all`.

## Known GNOME Shell 50 Limitations

On Bluefin 44 / GNOME Shell 50.1, the clock and system-status area are **not exposed as AT-SPI nodes**. All clock/quick-settings/calendar interactions must use Shell.Eval JS. The AT-SPI tree only has `Activities` and `Show Apps` on the top bar.

## dogtail 4.16 API

`findChild(pred, requireResult=True/False)` — `requireResult` kwarg raises TypeError at the logging decorator. Use instead:
- `findChildren(pred)` → returns list, never raises
- `findChild(pred, retry=False)` → fast fail without 20s wait
- `searchCutoffCount` and `searchBackoffDuration` are deprecated no-ops

## Resource Limits (all workflow pods)

| Template | CPU req/limit | Memory req/limit |
|---|---|---|
| bib-img-build | 4 / 8 | 8Gi / 16Gi |
| bib-img-pull | 2 / 4 | 2Gi / 4Gi |
| bib-disk-configure | 2 / 4 | 4Gi / 8Gi |
| bib-disk-check | 100m / 500m | 128Mi / 512Mi |
| run-gnome-tests | 1 / 2 | 1Gi / 2Gi |
| reflink-disk | 100m / 500m | 128Mi / 512Mi |
| preflight (titan) | 100m / 200m | 64Mi / 128Mi |

Global TTL default (via workflow-controller-configmap): 7 days success, 30 days failure.

## Workflow History

Workflows are retained: 7 days on success, 30 days on failure (global workflowDefaults in workflow-controller-configmap). No external archive database. Loki captures all pod logs. Use Argo MCP `get_workflow_logs` to retrieve results from completed runs.

## SSH Key

`bluefin-test-ssh-key` secret in `argo` namespace. Contains `id_ed25519` and `id_ed25519.pub`.
Current fingerprint (2026-05-25): `SHA256:4iazqYR3lM2tOuniG4MOSERDz0+qaq12qoM/WqP5qLw`

## Namespaces

| Namespace | Purpose |
|---|---|
| argo | Argo Workflows + ArgoCD control plane |
| argocd | ArgoCD |
| bluefin-test | latest variant test VMs |
| bluefin-lts-test | lts variant test VMs |
| flatcar-test | Flatcar test VMs |

**Never delete VMs or resources in namespaces outside this list.**

## YAML Authoring Rules

- **No inline Python inside bash inside YAML** — colons and quotes in Python cause YAML parse errors. Use `kubectl` + `jsonpath` instead.
- **No `generateName` in `manifests/`** — ArgoCD needs stable names to track resources. Use fixed `name:` fields.
- **Use `workflowTemplateRef`** in CronWorkflows instead of inlining DAG templates — avoids duplication.
- **Server-side apply is enabled** for `manifests/` — you can patch a subset of a resource's fields without owning the whole object.

## Issue Filing

- All issues go in **castrojo/testing-lab** (this repo)
- Label: `bug` for test failures and infrastructure breaks; `enhancement` for new capabilities
- Include: current behavior, expected behavior, exact file:line if code issue, acceptance criteria
- For infra failures: include workflow name, pod name, and relevant log excerpt

## Common Operations

```bash
# Check cluster state
just list-vms
just list-workflows

# Run smoke against titan VMs (fast — no BIB needed, ~5min)
just run-titan-smoke

# Run full smoke (BIB + provision + test + teardown, ~10min warm)
just run-tests

# Build/rebuild golden disk
just ensure-disk         # latest
just ensure-disk lts     # lts

# Fix SSH auth on existing disk after secret rotation
just patch-disk          # latest
just patch-disk lts

# Force ArgoCD sync
just argocd-sync

# Check ArgoCD status
just argocd-status

# Clean up orphaned VMs
just delete-vms

# Lint Argo YAML
just lint
```
