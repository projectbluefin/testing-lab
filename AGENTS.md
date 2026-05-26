# Testing Lab — Agent Instructions

> Load [docs/agent-cheatsheet.md](docs/agent-cheatsheet.md) first for commands. This file is the policy + architecture reference.

## What This Repo Is

Bluefin QA pipeline: Argo Workflows + KubeVirt + ArgoCD + behave/dogtail.
Tests boot Bluefin Linux VMs and run GNOME Shell accessibility smoke tests.
Canonical issue tracker: **castrojo/testing-lab** (this repo). Do NOT file issues in castrojo/copilot-config.

## Test Suite Mantra

This repo's north star is to verify **Bluefin as an image-based, atomic operating system**.
Agents should treat that as the primary culture of the project, not as a side concern.

When deciding what to test or prioritize:

1. **Prefer platform-contract coverage over package-era habits.**
   Validate `bootc`, staged deployments, rollback behavior, read-only `/usr`, signature policy,
   composefs/fs-verity, and `uupd` orchestration before inventing DNF/RPM-style checks.
2. **Treat Homebrew, Flatpak, Podman, and Docker/Colima as decoupled user-space layers.**
   The job is to prove those layers integrate cleanly without mutating the host image.
3. **Use UI coverage to reinforce system guarantees.**
   GNOME, Ptyxis, Podman Desktop, Bazaar, and related flows are valuable when they prove the
   Bluefin contract holds in real user workflows, not when they drift into generic desktop QA.
4. **Bias new issues and tests toward immutable-state evidence.**
   If a choice exists between another cosmetic UI check and a missing image/update/integrity
   assertion, prefer the image/update/integrity work.
5. **Keep everything VM-backed, GitOps-managed, and operator-friendly.**
   The expected output is durable workflow evidence that another agent or operator can rerun.

## Core Tenet: All Agent Operations Are API-Driven

**Agents must use the Kubernetes API and MCP servers. Never SSH to nodes. Never kubectl from outside the cluster.**

For canonical commands — workflow submission, ArgoCD actions, titan recovery, CronWorkflow operations,
SSH rotation, PR queue steps, safe cleanup, bootstrap, and live fact lookup — see
[docs/agent-cheatsheet.md](docs/agent-cheatsheet.md).

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
1. **WorkflowTemplate changes**: edit `argo/workflow-templates/*.yaml` → push to `main` → ArgoCD syncs.
2. **Cluster infra changes**: edit `manifests/*.yaml` → push to `main` → ArgoCD syncs.
3. **Never `kubectl apply`** WorkflowTemplates — ArgoCD overwrites manual applies.
4. **Never `argo-mcp-create_workflow_template`** — ArgoCD owns that reconciliation loop.
5. **Never amend published commits** — create new commits.
6. For force-sync and verification commands, use [docs/agent-cheatsheet.md](docs/agent-cheatsheet.md).

`manifests/` uses `ServerSideApply: true` — manifests patch rather than replace. Safe to define partial resources (for example patching a Helm-managed ConfigMap by adding a key).

## KubeVirt Feature Gates

- `HostDisk` is required for the Bluefin/Flatcar hostDisk VM flows in this repo.
- `ExperimentalIgnitionSupport` is required for installer-style VMs that use the `kubevirt.io/ignitiondata` annotation.
- If VM creation fails with `feature gate is not enabled in kubevirt-config`, treat that as **cluster infra drift** and persist the fix via GitOps under `manifests/`.

## Repo Layout

```
argo/
  workflow-templates/          ← ArgoCD (testing-lab App) syncs these
    bib-build-and-push.yaml       build golden disk via BIB
    provision-vm.yaml             reflink golden disk + boot KubeVirt VM
    provision-flatcar-vm.yaml     provision Flatcar VM
    run-gnome-tests.yaml          SSH into VM, run behave/qecore suite
    run-flatcar-tests.yaml        SSH into Flatcar VM, run tests
    teardown-vm.yaml              delete VM + hostDisk
    teardown-flatcar-vm.yaml      delete Flatcar VM + hostDisk
    bluefin-titan-smoke.yaml      smoke against persistent titan VMs
    bluefin-qa-pipeline.yaml      full pipeline: ensure-disk + provision + tests
    patch-golden-disk.yaml        retroactively fix SSH auth on existing disk
  bluefin-smoke-test.yaml         submit: full BIB+provision+test run (latest)
  bluefin-test-matrix.yaml        submit: parallel latest+lts matrix
  flatcar-smoke-test.yaml         submit: Flatcar test run
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
  smoke/features/                behave/qecore GNOME Shell smoke tests
  developer/features/            behave GNOME desktop tests (podman, ptyxis, etc.)
  software/features/             behave flatpak/Bazaar tests
  system/features/               atomic OS contract tests
  flatcar/                       Flatcar systemd/container tests
AGENTS.md                        This file
RUNBOOK.md                       Timeless architecture + failure modes
SECURITY.md                      Accepted homelab trade-offs and risks
Justfile                         Local shortcuts (require kubectl/argo access)
```

## Image Variants

| Tag | Image | Golden disk | Nightly |
|---|---|---|---|
| `latest` | `ghcr.io/ublue-os/bluefin:latest` | `/var/tmp/bluefin-golden/latest/disk.raw` on ghost | 02:00 UTC |
| `lts` | `ghcr.io/ublue-os/bluefin:lts` | `/var/tmp/bluefin-golden/lts/disk.raw` on ghost | 02:30 UTC |

`gts` and `lts-hwe` do NOT exist. Never use these tags.

## Persistent (Titan) VMs

Two always-on VMs provide the fast test-iteration path — no BIB build and no VM provisioning wait:

| VM | Namespace | Disk |
|---|---|---|
| `titan-bluefin` | `bluefin-test` | `/var/home/jorge/VMs/titans/titan-bluefin/image/disk.raw` |
| `titan-lts` | `bluefin-lts-test` | `/var/home/jorge/VMs/titans/image/disk.raw` |

Managed by ArgoCD via `manifests/titan-bluefin.yaml` and `manifests/titan-lts.yaml`.
SSH key secret: `bluefin-test-ssh-key` in the `argo` namespace.
Titan IPs drift; use the live lookup commands in [docs/agent-cheatsheet.md](docs/agent-cheatsheet.md) instead of hardcoding them.
Titan `authorized_keys` refresh remains human-gated; if titan SSH fails after rotation, file an issue for a human operator.

## Test Stack

| Component | Role |
|---|---|
| **behave** | BDD test runner |
| **qecore** | Red Hat test framework; `qecore-headless` starts Wayland session |
| **dogtail** | AT-SPI accessibility tree traversal |
| **gnome-ponytail-daemon** | Bridges AT-SPI coordinates to Wayland surface coordinates |
| **Shell.Eval** | `gdbus call --session --dest org.gnome.Shell --method org.gnome.Shell.Eval` — required for GNOME Shell 50 top-bar interactions |

`qecore-headless` must be invoked with `--session-type wayland --session-desktop gnome`.
`unsafe_mode` (`global.context.unsafe_mode = true`) must be enabled before top-bar AT-SPI interactions.

## Known GNOME Shell 50 Limitations

On Bluefin 44 / GNOME Shell 50.1, the clock and system-status area are not reliably actionable via AT-SPI.
Clock, quick-settings, and calendar interactions must use Shell.Eval JS. The top-bar nodes exposed normally are `Activities` and `Show Apps`.

## dogtail API Notes

- `findChild(pred, requireResult=True/False)` is invalid in this repo's stack.
- Use `findChildren(pred)` for no-raise presence checks.
- Use `findChild(pred, retry=False)` for fast failure without the default long retry loop.

For command recipes and deeper debugging flow, see [docs/dogtail-testing.md](docs/dogtail-testing.md).

## Workflow History

Workflows are retained for 7 days on success and 30 days on failure via `workflow-controller-configmap`.
Loki captures workflow pod logs. Use the commands in [docs/agent-cheatsheet.md](docs/agent-cheatsheet.md) or the expanded procedures in [docs/lab-operations.md](docs/lab-operations.md) to retrieve results.

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

- All issues go in **castrojo/testing-lab**.
- Label: `bug` for test failures and infrastructure breaks; `enhancement` for new capabilities.
- Include: current behavior, expected behavior, exact file:line if code issue, acceptance criteria.
- For infra failures: include workflow name, pod name, and relevant log excerpt.

## Resource Limits (all workflow pods)

| Template | CPU req/limit | Memory req/limit |
|---|---|---|
| `bib-img-build` | 4 / 8 | 8Gi / 16Gi |
| `bib-img-pull` | 2 / 4 | 2Gi / 4Gi |
| `bib-disk-configure` | 2 / 4 | 4Gi / 8Gi |
| `bib-disk-check` | 100m / 500m | 128Mi / 512Mi |
| `run-gnome-tests` | 1 / 2 | 1Gi / 2Gi |
| `reflink-disk` | 100m / 500m | 128Mi / 512Mi |
| `preflight` (titan) | 100m / 200m | 64Mi / 128Mi |

## Canonical Command Reference

See [docs/agent-cheatsheet.md](docs/agent-cheatsheet.md) for the canonical command reference.
Use it for workflow run commands, ArgoCD commands, titan recovery, CronWorkflow operations,
SSH rotation, PR queue steps, safe cleanup, bootstrap, self-check commands, and live cluster facts.
