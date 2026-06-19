# CNCF Homelab Reference: bootc Image Testing Lab

> A production-quality, fully GitOps-driven QA pipeline for testing
> [bootc](https://containers.github.io/bootc/) (image-based Linux) deployments,
> built entirely on CNCF projects running on a single homelab node.

---

## What This Is

A reference architecture for validating bootc atomic OS images — boot a real VM from
a real OCI image, run GUI acceptance tests, tear it down, repeat. Everything is
declared in git, reconciled by ArgoCD, and orchestrated by Argo Workflows.

**No persistent VMs. No manual `kubectl`. No SSH to the cluster host.**

Built for and used by [Project Bluefin](https://projectbluefin.io) and
[Project Dakota](https://github.com/projectbluefin/dakota). Designed to be cloned
and adapted for any bootc-based OS project.

---

## CNCF Project Stack

| Layer | Project | CNCF Status | Role |
|---|---|---|---|
| Kubernetes | [k3s](https://k3s.io) | [Sandbox](https://www.cncf.io/projects/k3s/) | Lightweight single-node cluster |
| VM workloads | [KubeVirt](https://kubevirt.io) | [Incubating](https://www.cncf.io/projects/kubevirt/) | Ephemeral test VMs on bare metal |
| CI/CD | [Argo Workflows](https://argoproj.github.io/argo-workflows/) | [Graduated](https://www.cncf.io/projects/argo/) | DAG pipeline orchestration |
| GitOps | [Argo CD](https://argo-cd.readthedocs.io) | [Graduated](https://www.cncf.io/projects/argo/) | Declarative cluster state from git |
| Observability | [Grafana Loki](https://grafana.com/oss/loki/) | CNCF landscape | Log aggregation for workflow pods |
| Images | [OCI](https://opencontainers.org) + [bootc](https://containers.github.io/bootc/) | Standard | Atomic OS image format |

> All pipelines run on commodity x86_64 hardware (single Ryzen AI node, 64GB RAM).
> The architecture scales horizontally — add worker nodes and the workflows follow.

---

## Architecture

```
Git push / manual submit
        │
        ▼
  Argo Workflow (argo namespace)
        │
        ├─ bib-build-and-push ──────► BIB golden disk on ghost hostPath
        │   (bootc image builder)       /var/tmp/bluefin-golden/<tag>/disk.raw
        │                               btrfs reflink (~24ms clone, CoW, ~0 extra space)
        │
        ├─ provision-variant-vm ────► KubeVirt VM in test namespace
        │   (reflink clone + VMI)       hw-profile: standard | full-hw (TPM, watchdog)
        │
        ├─ run-gnome-tests ─────────► runner pod (Fedora + qecore-headless)
        │   (behave + AT-SPI)           git-sync → SSH → VM → behave + Dogtail
        │
        └─ teardown (onExit) ───────► delete VM + hostDisk clone
            (always runs)               guaranteed cleanup on success or failure
```

**GitOps loop:**

```
git push main
    │
    ▼
ArgoCD polls (or webhook)
    │
    ├─ argo/workflow-templates/ ──► WorkflowTemplates reconciled in cluster
    └─ manifests/               ──► CronWorkflows, RBAC, infra reconciled in cluster
```

---

## Repository Layout

```
testing-lab/
├── README.md                         # This file
├── RUNBOOK.md                        # Timeless architecture + failure modes
├── AGENTS.md                         # Agent policy, scope rules, cluster topology
├── Justfile                          # Operator convenience wrappers
│
├── argo/
│   ├── workflow-templates/           # ← ArgoCD (testing-lab App) auto-syncs these
│   │   ├── bib-build-and-push.yaml       build / cache golden bootc disk via BIB
│   │   ├── bluefin-qa-pipeline.yaml      full pipeline: disk + VM + tests
│   │   ├── bluefin-migration-test.yaml   bootc switch migration validation
│   │   ├── provision-variant-vm.yaml     reflink golden disk + boot KubeVirt VM
│   │   ├── run-gnome-tests.yaml          behave + qecore + Dogtail GNOME tests
│   │   ├── run-variant-tests.yaml        multi-variant test runner
│   │   ├── run-incluster-tests.yaml      in-cluster (kubectl-based) tests
│   │   ├── run-flatcar-tests.yaml        Flatcar OS test runner
│   │   ├── provision-flatcar-vm.yaml     provision Flatcar test VM
│   │   ├── teardown-vm.yaml              delete Bluefin VM + hostDisk
│   │   ├── teardown-flatcar-vm.yaml      delete Flatcar VM + hostDisk
│   │   ├── bst-build.yaml               BuildStream (BST) build + zot push
│   │   ├── dakota-bst.yaml              Dakota BST validate / build pipeline
│   │   ├── dakota-iso-pr-test.yaml      Dakota ISO PR end-to-end pipeline
│   │   ├── dakota-qa-pipeline.yaml      Full Dakota QA: BST → BIB → VM → tests
│   │   ├── knuckle-qa-pipeline.yaml     Knuckle QA pipeline
│   │   └── patch-golden-disk.yaml       SSH key rotation helper
│   │
│   ├── bootstrap/                    # ← NOT ArgoCD managed — run once to set up cluster
│   │   ├── README.md                     bootstrap guide
│   │   ├── install-kubevirt.yaml         install KubeVirt (CNCF Incubating)
│   │   ├── install-cdi.yaml             install Containerized Data Importer
│   │   ├── install-kubevirt-manager.yaml install KubeVirt Manager web UI
│   │   ├── install-kubestellar.yaml     install KubeStellar (optional, multi-cluster)
│   │   ├── install-test-vms.yaml        apply initial test VM manifests
│   │   ├── ghost-kernel-args.yaml       set Strix Halo performance kernel args
│   │   ├── setup-ghost-ssh-banner.yaml  install API-only warning banner on ghost
│   │   └── setup-otel.yaml              deploy OTel observability stack
│   │
│   ├── deprecated/                   # Old CDI/PVC v1 and tmt runner — do not use
│   │
│   ├── bluefin-smoke-test.yaml       submit: single-image smoke run
│   ├── bluefin-test-matrix.yaml      submit: parallel latest + lts matrix
│   ├── flatcar-smoke-test.yaml       submit: Flatcar smoke run
│   ├── rechunk-to-chunkah-migration.yaml  submit: migration validation
│   └── zstd-migration-test.yaml      submit: zstd compression validation
│
├── manifests/                        # ← ArgoCD (testing-lab-infra App) auto-syncs these
│   ├── nightly-smoke.yaml                CronWorkflow: nightly latest @ 02:00 UTC
│   ├── nightly-smoke-lts.yaml            CronWorkflow: nightly lts @ 02:30 UTC
│   ├── nightly-dakota.yaml               CronWorkflow: nightly dakota @ 03:00 UTC
│   ├── nightly-knuckle.yaml              CronWorkflow: nightly knuckle @ 03:30 UTC
│   ├── orphan-vm-cleanup.yaml            CronWorkflow: clean orphaned VMs every 2h
│   ├── golden-disk-gc.yaml               CronWorkflow: GC stale golden disks
│   ├── workflow-controller-configmap.yaml TTL patch (7d success, 30d failure)
│   ├── argo-default-sa-rbac.yaml         Argo executor RBAC
│   ├── homelab-runner-rbac.yaml          homelab-runner SA + ClusterRole
│   ├── argo-server-nodeport.yaml         NodePort for external Argo API access
│   ├── flatcar-test-namespace.yaml       Flatcar test namespace
│   ├── promtail-config.yaml              Loki log scraping config
│   ├── rocm-device-plugin.yaml           AMD ROCm GPU device plugin
│   ├── llm-d-gateway-crds.yaml           Gateway API Inference Extension CRDs
│   └── llm-d.yaml                        Qwen3.6-35B-A3B model server on ROCm
│
├── argocd/
│   ├── application.yaml              ArgoCD App: argo/workflow-templates → cluster
│   └── infra-application.yaml        ArgoCD App: manifests/ → cluster
│
├── tests/
│   ├── smoke/features/               Phase 1: GNOME Shell, Activities, top-bar
│   ├── developer/features/           Phase 2: terminal, Homebrew, Podman, micro
│   ├── software/features/            Phase 3: Flatpak, Bazaar, GNOME Software
│   ├── system/features/              Phase 4: bootc contract, atomic OS assertions
│   └── flatcar/features/             Phase 5: Flatcar systemd + container tests
│
└── docs/
    ├── bootstrap.md                  ← how to replicate this lab from scratch
    ├── agent-cheatsheet.md           canonical command reference
    ├── lab-operations.md             long-form operator procedures
    ├── dogtail-testing.md            GUI test authoring + debugging
    ├── homelab-contracts.md          expected cluster behaviour contracts
    └── WORKFLOWS.md                  WorkflowTemplate parameter contracts
```

---

## Test Phases

| Phase | Suite | Trigger |
|---|---|---|
| 1 — Smoke | `smoke` | Every PR, nightly |
| 2 — Developer tooling | `developer` | Nightly, targeted |
| 3 — Software management | `software` | Targeted |
| 4 — Atomic OS contract | `system` | Nightly, every image build |
| 5 — Flatcar substrate | `flatcar` | Dedicated workflow |
| — Migration validation | `migration` | On rechunk → chunkah switches |
| — Dakota BST | `dakota` | Every Dakota PR |

---

## GitOps Model

This repo follows [Argo CD best practices](https://argo-cd.readthedocs.io/en/stable/user-guide/best_practices/)
with two ArgoCD Applications that own distinct resource classes:

| Application | Syncs path | Namespace | prune | selfHeal |
|---|---|---|---|---|
| `testing-lab` | `argo/workflow-templates/` | argo | ✅ | ✅ |
| `testing-lab-infra` | `manifests/` | argo (+ others) | ✅ | ✅ |

**Rules:**
1. Edit files in `argo/workflow-templates/` or `manifests/` → push to `main` → ArgoCD reconciles within ~3 minutes.
2. **Never** `kubectl apply` WorkflowTemplates directly — ArgoCD will overwrite it.
3. **Never** `argo create workflow-template` for production templates — same reason.
4. Bootstrap templates in `argo/bootstrap/` are **not** in any ArgoCD sync path — run them once by hand during cluster setup.

---

## Getting Started

See **[docs/bootstrap.md](docs/bootstrap.md)** for the complete lab setup guide.

**TL;DR for an existing k3s + KubeVirt cluster:**

```bash
git clone https://github.com/castrojo/testing-lab
cd testing-lab

# 1. Bootstrap ArgoCD Applications (once)
just setup-argocd

# 2. Create SSH key secret for VM access (once)
just setup-ssh-secret

# 3. Push — ArgoCD reconciles all WorkflowTemplates automatically
git push origin main

# 4. Run smoke tests
just run-tests
```

---

## Cluster Topology

| Host | Role | Specs |
|---|---|---|
| ghost | k3s control-plane + KubeVirt compute | Ryzen AI MAX+ 395, 16c/32t, 64GB RAM |
| exo-1 | k3s worker (workflow pods only) | — |

**Namespaces:**

| Namespace | Purpose |
|---|---|
| `argo` | Argo Workflows + ArgoCD (control plane) |
| `argocd` | ArgoCD controller |
| `bluefin-test` | `latest` test VMs |
| `bluefin-lts-test` | `lts` test VMs |
| `flatcar-test` | Flatcar test VMs |
| `llm-d` | Qwen3.6-35B-A3B on ROCm (hive swarm node) |
| `mcp` | Kubernetes MCP server |

---

## Key Design Decisions

**btrfs reflink over CDI/PVC** — Golden disk is a single `.raw` file on `hostPath`.
Each test run reflinking it takes ~24ms (copy-on-write, near-zero extra disk). No
CDI DataVolume overhead, no registry round-trips. Teardown is `rm -f disk.raw`.

**No persistent test VMs** — All VMs are ephemeral. Every pipeline provisions a
fresh VM on start and destroys it via `onExit` handler. `just list-vms` should
show zero VMs when no workflows are running.

**API-only operator model** — All cluster reads and mutations go through the
Kubernetes API (MCP tools or `just` wrappers). No SSH to the cluster host for
operations. The only SSH in this system is **in-cluster**: workflow pods SSHing
into freshly-booted test VMs to run behave steps.

**WorkflowTemplate over inline DAG** — All reusable pipeline logic lives in
`WorkflowTemplate` objects in `argo/workflow-templates/`. Submit-time `Workflow`
files in `argo/` reference templates via `workflowTemplateRef` or `templateRef`.
This lets ArgoCD own the template lifecycle while keeping submission flexible.

---

## Writing New Tests

1. Add a `.feature` file under `tests/<suite>/features/`.
2. Add step definitions in `tests/<suite>/features/steps/`.
3. Tag new scenarios `@wip` until stable.
4. Submit a run: `just run-tests` (smoke) or `just run-tests-tag lts`.

See [docs/dogtail-testing.md](docs/dogtail-testing.md) for AT-SPI test authoring.

---

## Documentation Map

| Doc | Purpose |
|---|---|
| [README.md](README.md) | Architecture overview (this file) |
| [docs/bootstrap.md](docs/bootstrap.md) | How to replicate this lab from scratch |
| [RUNBOOK.md](RUNBOOK.md) | Timeless architecture + failure-mode reference |
| [AGENTS.md](AGENTS.md) | Agent policy, cluster topology, issue filing rules |
| [docs/agent-cheatsheet.md](docs/agent-cheatsheet.md) | Canonical command reference |
| [docs/lab-operations.md](docs/lab-operations.md) | Long-form operator procedures |
| [docs/dogtail-testing.md](docs/dogtail-testing.md) | GUI test authoring + debugging |
| [docs/WORKFLOWS.md](docs/WORKFLOWS.md) | WorkflowTemplate parameter contracts |

---

## Related Projects

- [Project Bluefin](https://projectbluefin.io) — primary consumer of this test suite
- [Project Dakota](https://github.com/projectbluefin/dakota) — BST-built Bluefin variant
- [bootc](https://containers.github.io/bootc/) — image-based Linux standard
- [ublue-os/bluefin](https://github.com/ublue-os/bluefin) — upstream Bluefin images
- [KubeVirt](https://kubevirt.io) — CNCF Incubating, VM workloads on Kubernetes
- [Argo Workflows](https://argoproj.github.io/argo-workflows/) — CNCF Graduated
- [Argo CD](https://argo-cd.readthedocs.io) — CNCF Graduated
- [k3s](https://k3s.io) — CNCF Sandbox
