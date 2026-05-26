# bluefin-test-suite

A cloud-native QA pipeline for [Project Bluefin](https://projectbluefin.io) desktops.

Runs inside Kubernetes on [ghost](https://github.com/castrojo/utah), driven by **Argo Workflows**, booting Bluefin as a **KubeVirt hostDisk VM** (golden disk + btrfs reflink), and executing GUI tests via **behave + qecore + Dogtail (AT-SPI)** — no ISO installer, no pixel matching.

---

## Documentation map

- See [docs/agent-cheatsheet.md](docs/agent-cheatsheet.md) for the canonical command reference.
- See [AGENTS.md](AGENTS.md) for repo policy, scope rules, and architecture tables.
- See [docs/lab-operations.md](docs/lab-operations.md) for long-form operational procedures.
- See [docs/dogtail-testing.md](docs/dogtail-testing.md) for GUI test authoring and debugging.
- See [RUNBOOK.md](RUNBOOK.md) for timeless architecture and failure-mode context.

## Architecture

```
GitHub webhook / just run-tests
        │
        ▼
  Argo Workflow (argo ns)
        │
        ├─ bib-build-and-push ────► BIB golden disk on ghost hostPath
        │                           /var/tmp/bluefin-golden/<tag>/disk.raw
        │
        ├─ provision-bluefin-vm ──► btrfs reflink (~24ms) + KubeVirt VM
        │                           namespace: bluefin-test / bluefin-lts-test
        │
        ├─ run-gnome-tests ────────► runner pod (Fedora + qecore-headless)
        │                           git-sync → SSH → VM
        │                           behave + Dogtail (AT-SPI)
        │
        └─ teardown (onExit) ──────► delete VM + hostDisk clone
```

## Test phases

| Phase | Suite | Runs on |
|---|---|---|
| 1 — Golden Path smoke | `smoke` | Every PR |
| 2 — Developer tooling | `developer` | Merge / targeted validation |
| 3 — Software management | `software` | Targeted validation |
| 4 — Atomic OS contract | `system` | Titan fast-path validation |
| 5 — Flatcar substrate | `flatcar` | Dedicated Flatcar workflow |

## Repository layout

```
bluefin-test-suite/
├── Justfile                          # operator entrypoints
├── tests/
│   ├── smoke/features/               # Phase 1: GNOME Shell, Activities, extensions
│   ├── developer/                    # Phase 2: terminal, brew, podman, micro
│   ├── software/                     # Phase 3: GNOME Software, Flatpak
│   ├── system/                       # Atomic OS contract checks
│   └── flatcar/                      # Flatcar OS tests
├── argo/
│   ├── bluefin-smoke-test.yaml       # single-image workflow
│   ├── bluefin-test-matrix.yaml      # latest + lts workflow
│   ├── flatcar-smoke-test.yaml       # Flatcar workflow
│   └── workflow-templates/           # GitOps-managed WorkflowTemplates
├── manifests/                        # GitOps-managed cluster resources and CronWorkflows
├── AGENTS.md                         # policy + architecture tables
├── RUNBOOK.md                        # timeless architecture + failure modes
└── docs/
    ├── agent-cheatsheet.md           # canonical commands
    ├── lab-operations.md             # long-form procedures
    ├── dogtail-testing.md            # GUI test authoring guide
    └── vanguard-report-template.md   # PR evidence template
```

## Writing new tests

1. Add a `.feature` file under `tests/<suite>/features/`.
2. Add step definitions to `tests/<suite>/features/steps/steps.py`.
3. Start GUI scenarios with `* GNOME Shell is accessible via AT-SPI`.
4. Use `Shell.Eval` for top-bar interactions that GNOME Shell does not expose reliably via AT-SPI.
5. See [docs/dogtail-testing.md](docs/dogtail-testing.md) for dogtail/qecore patterns, runner behavior, and debugging recipes.
