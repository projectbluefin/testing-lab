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
| Submit a workflow | Argo MCP `submit_workflow` |
| Check workflow status | Argo MCP `get_workflow` / `list_workflows` |
| Get workflow logs | Argo MCP `get_workflow_logs` |
| Update a WorkflowTemplate | Edit YAML → `git push main` → ArgoCD auto-syncs |
| Read cluster state | kubectl MCP or Argo MCP |

If an MCP tool doesn't exist for an operation, the right fix is to build or deploy that capability — not to fall back to SSH.

## Cluster Topology

| Host | Role | IP | Specs |
|---|---|---|---|
| ghost | k3s control-plane + KubeVirt compute | 192.168.1.102 | Ryzen AI MAX+ 395, 16c/32t, 64GB RAM |
| exo-1 | k3s worker (workflow pods only) | 192.168.1.239 | — |
| Argo UI | — | http://192.168.1.102:2746 | — |
| Loki | log aggregation | http://192.168.1.102:30100 | Scrapes pods labeled `app.kubernetes.io/part-of=bluefin-test-suite` |
| ArgoCD | GitOps controller | https://192.168.1.102 (argocd NS) | Application: `bluefin-test-suite` |

All KubeVirt VMs are pinned to ghost via `nodeSelector: kubernetes.io/hostname: ghost`.

## GitOps Rules

1. **WorkflowTemplate changes**: edit `argo/workflow-templates/*.yaml` → push to `main` → ArgoCD syncs in ~3 min
2. **Never `kubectl apply`** WorkflowTemplates — ArgoCD overwrites manual applies
3. **Never `argo-mcp-create_workflow_template`** — ArgoCD owns that reconciliation loop
4. **Never amend published commits** — create new commits
5. Force sync when needed: `just argocd-sync`

ArgoCD Application `bluefin-test-suite` (namespace: argocd) syncs `argo/workflow-templates/` from this repo's `main` branch.

Note: `argo/*.yaml` (bluefin-smoke-test.yaml, etc.) are Workflow *submission* files, not managed by ArgoCD. Submit them via `just run-tests` or Argo MCP.

## Repo Layout

```
argo/
  workflow-templates/     ← ArgoCD syncs these to cluster
    bib-build-and-push.yaml     build golden disk via BIB
    provision-vm.yaml           reflink golden disk + boot KubeVirt VM
    run-gnome-tests.yaml        SSH into VM, run behave/qecore suite
    teardown-vm.yaml            delete VM + hostDisk
    bluefin-titan-smoke.yaml    run smoke against persistent titan VMs (fast path)
    patch-golden-disk.yaml      retroactively fix SSH auth on existing disk
  bluefin-smoke-test.yaml       submit: full BIB+provision+test run
  bluefin-test-matrix.yaml      submit: parallel latest+lts matrix
argocd/
  application.yaml              ArgoCD Application definition (apply once per cluster)
tests/
  smoke/features/               behave/qecore GNOME Shell smoke tests ← ACTIVE
  developer/features/           behave GNOME desktop tests (podman, ptyxis, etc.)
  software/features/            behave flatpak/Bazaar tests
  flatcar/                      Flatcar systemd/container tests
RUNBOOK.md                      Operations reference — read before debugging
Justfile                        Local shortcuts (require kubectl/argo access)
```

## Image Variants

| Tag | Image | Golden disk |
|---|---|---|
| `latest` | `ghcr.io/ublue-os/bluefin:latest` | ✅ `/var/tmp/bluefin-golden/latest/disk.raw` on ghost |
| `lts` | `ghcr.io/ublue-os/bluefin:lts` | ❌ needs rebuild (see open issues) |

`gts` and `lts-hwe` do NOT exist. Never use these tags.

## Persistent (Titan) VMs

Two always-on VMs for fast test iteration (no BIB build needed):

| VM | Namespace | IP | Disk |
|---|---|---|---|
| `titan-bluefin` | bluefin-test | 10.42.0.27 | `/var/home/jorge/VMs/titans/titan-bluefin/image/disk.raw` on ghost |
| `titan-lts` | bluefin-lts-test | 10.42.0.26 | `/var/home/jorge/VMs/titans/titan-lts/image/disk.raw` on ghost |

These VMs are NOT managed by any workflow — they run continuously. SSH key: `bluefin-test-ssh-key` k8s secret in `argo` namespace.

To run smoke against them: `just run-titan-smoke` (or use Argo MCP to submit `bluefin-titan-smoke` WorkflowTemplate with the current VM IPs).

## Test Stack

- **behave** — BDD test runner
- **qecore** — Red Hat test framework; provides `TestSandbox`, `common_steps`, `run_and_save`
- **qecore-headless** — starts Wayland session inside VM, hands off to behave
- **dogtail** — AT-SPI accessibility tree traversal
- **gnome-ponytail-daemon** — bridges AT-SPI coordinates to Wayland surface coordinates
- **Shell.Eval** — `gdbus call --session --dest org.gnome.Shell --method org.gnome.Shell.Eval` — required for GNOME Shell 50 top-bar interactions (AT-SPI gaps)

**unsafe_mode** (`global.context.unsafe_mode = true`) must be set before AT-SPI top-bar access. Set in `environment.py` `before_all`. See RUNBOOK for details.

## Known GNOME Shell 50 Limitations

On Bluefin 44 (GNOME Shell 50.1), the clock and system-status area are NOT exposed as AT-SPI nodes. All clock/quick-settings/calendar interactions use Shell.Eval JS. See `steps.py` for `_shell_eval_inner()` and the `via Shell.Eval` step definitions.

## dogtail 4.16 API

`findChild(pred, requireResult=True/False)` is broken — `requireResult` raises TypeError at the logging decorator. Use:
- `findChildren(pred)` → returns list, never raises
- `findChild(pred, retry=False)` → fast fail without 20s wait

## SSH Key

`bluefin-test-ssh-key` secret in `argo` namespace. Contains `id_ed25519` and `id_ed25519.pub`.
Current fingerprint (2026-05-25): `SHA256:4iazqYR3lM2tOuniG4MOSERDz0+qaq12qoM/WqP5qLw`

## Namespaces

| Namespace | Purpose |
|---|---|
| argo | Argo Workflows control plane |
| argocd | ArgoCD |
| bluefin-test | latest variant test VMs |
| bluefin-lts-test | lts variant test VMs |
| flatcar-test | Flatcar test VMs |

**Never delete VMs in namespaces outside this list.**

## Issue Filing

- All issues go in **castrojo/testing-lab** (this repo)
- Label: `bug` for test failures and infrastructure breaks
- Label: `enhancement` for new capabilities
- Include: current behavior, expected behavior, exact file:line if code issue, acceptance criteria with checkboxes
- For infra failures: include the workflow name, pod name, and relevant log excerpt
- Link related issues in the body

## Common Operations

```bash
# Check cluster state
just list-vms
just list-workflows

# Run smoke against titan VMs (fast — no BIB needed)
just run-titan-smoke

# Run full smoke (BIB + provision + test + teardown, ~10min)
just run-tests

# Build/rebuild golden disk
just ensure-disk         # latest
just ensure-disk lts     # lts

# Fix SSH auth on existing disk after secret rotation
just patch-disk          # latest
just patch-disk lts

# Force ArgoCD sync
just argocd-sync

# Clean up orphaned VMs
just delete-vms

# Lint Argo YAML
just lint
```
