# Testing Lab — Agent Instructions

> **You have the source code. Read it. Never guess.**
> Image names, tags, workflow behavior, registry paths — all of it is in the repo.
> `gh api`, `read`, `bash` are available. Use them before writing anything.
> See the [incident log in image-registry.md](https://github.com/projectbluefin/common/blob/main/docs/skills/image-registry.md#incident-log) for what happens when you don't.

> **Before using any tool or library: look up its docs via Context7 first. Always.**
> Argo Workflows, KubeVirt, ArgoCD, Kubernetes, Helm, qecore, dogtail — every tool has live, authoritative docs.
> Pattern: `resolve-library-id` → `get-library-docs` → implement → cite the section.
> Guessing, flag-hunting, and trial-and-error are banned. The docs exist. Read them.

> Load [docs/agent-cheatsheet.md](docs/agent-cheatsheet.md) first for commands. This file is the policy + architecture reference.

## Skill routing — read this first

Before changing anything, load the relevant skill file from `docs/skills/`:

| Area | Skill file |
|---|---|
| Argo Workflows YAML, WorkflowTemplate authoring, lint | [`docs/skills/argo-workflows.md`](docs/skills/argo-workflows.md) |
| KubeVirt VMs, btrfs reflink, golden disk, teardown | [`docs/skills/kubevirt-vms.md`](docs/skills/kubevirt-vms.md) |
| ArgoCD sync, GitOps rules, bootstrap vs managed | [`docs/skills/gitops-argocd.md`](docs/skills/gitops-argocd.md) |
| Flatcar node onboarding, k3s join, Nebraska, update_engine | [`docs/skills/flatcar-node-onboarding.md`](docs/skills/flatcar-node-onboarding.md) |
| behave / qecore / dogtail / GNOME AT-SPI tests | [`docs/skills/test-authoring.md`](docs/skills/test-authoring.md) |
| Loki, Promtail, pod log scraping, retention, disk fill | [`docs/skills/monitoring.md`](docs/skills/monitoring.md) |
| End of session — write-back loop | [`docs/skills/skill-improvement.md`](docs/skills/skill-improvement.md) |

**At end of every non-trivial session:** run the write-back loop in `docs/skills/skill-improvement.md`. Every session produces two outputs: the work and the learning.

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

## PR Comment Policy

**One comment per PR event, max.** Combine all findings into a single comment. Never post a follow-up comment for a new observation — edit the existing one instead.

**Never duplicate GitHub UI state.** Do not post approval counts, merge queue status, or CI pass/fail summaries — GitHub already surfaces these natively in the PR timeline.

**Test reports: minimal.** Report what ran, pass/fail, and blockers only. No diff summaries. No tables unless comparing ≥3 divergent approaches that require a human decision.

**@ mentions in context only.** Only ping someone if asking them to do something specific. Always inside the combined comment — never as a standalone comment.

**When in doubt, don't post.** If the only thing to report is "tests pass", post nothing.

## Core Tenet: All Agent Operations Are API-Driven

**Use Kubernetes MCP tools for all cluster reads/mutations. Never SSH to ghost from a workstation.**

The only SSH in this system is **in-cluster**: workflow pods and probe pods SSH into test VMs (fresh KubeVirt VMs) as the test execution mechanism. That is not an operator access pattern — it is how behave/qecore delivers tests. Workstation operators and agents have no SSH path to anything; they submit workflows and query the API.

For canonical commands — workflow submission, ArgoCD actions, CronWorkflow operations,
key secret rotation, PR queue steps, safe cleanup, bootstrap, and live fact lookup — see
[docs/agent-cheatsheet.md](docs/agent-cheatsheet.md).

If an MCP tool doesn't exist for an operation, the right fix is to build or deploy that capability — not to fall back to workstation `kubectl`/`argo`, and never to SSH.

## Core Tenet: Knuckle VM Lifecycle Is Argo-Native

**`ssh $GHOST kubectl/virtctl` is a policy violation. No WorkflowTemplate may add `ssh $GHOST` calls.**

The current `projectbluefin/knuckle` `scripts/lib/vm-kubevirt.sh` tunnels `kubectl`/`virtctl` through SSH to ghost (`_kube()`, `_vc()`). This is a known violation tracked in issues #113–#118 and is being migrated.

The correct pattern is **in-pod kubectl/virtctl on ghost** via Argo workflow steps:
```yaml
nodeSelector:
  kubernetes.io/hostname: ghost
volumes:
  - name: knuckle-test
    hostPath:
      path: /var/tmp/knuckle-test
```
Pods scheduled on ghost have direct k8s API access. No SSH hop needed. See `provision-flatcar-vm.yaml` and `knuckle-qa-pipeline.yaml` for the reference implementation.

**The only permitted SSH** in knuckle workflows is **from workflow pods into the Flatcar test VM** — this is legitimate in-cluster test execution (`kv_wait_ssh`, `kv_ssh`, `kv_scp_to_vm`), not operator access to the host.

## Core Tenet: No Persistent Test VMs

**All test runs use ephemeral KubeVirt VMs. No persistent VMs sit idle consuming cluster resources.**

Every pipeline (Bluefin, Bluefin-LTS, Dakota, Knuckle) provisions a fresh VM on workflow start and tears it down via `onExit` handler. `just list-vms` should show zero VMs when no workflows are running.

## Cluster Topology

| Host | Role | IP | Specs |
|---|---|---|---|
| ghost | k3s control-plane + KubeVirt compute | 192.168.1.102 | Ryzen AI MAX+ 395, 16c/32t, 64GB RAM |
| exo-1 | k3s worker (opt-in) | 192.168.1.239 | Dakota laptop — 22c/15.1Gi; `just k8s-on/off` to join/leave; excludes BST builds (16Gi request) |
| exo-0 | k3s worker (dedicated) | 192.168.1.171 | Flatcar 4593.2.3 — k3s via sysext, k3s-agent enabled at boot; always schedulable |
| exo-2 | k3s worker (dedicated) | 192.168.1.171 | Flatcar 4593.2.3 — k3s via sysext, k3s-agent enabled at boot; always schedulable; update.conf → Nebraska for auto kernel updates |
| bazzite | k3s worker | 192.168.1.223 | Gaming machine — fully schedulable (no taint); k3s-agent enabled and running at boot |
| hamilton | k3s worker (opt-in) | 192.168.1.225 | Bluefin workstation — 16c/31.2Gi; `just k8s-on/off` to join/leave |
| Argo UI | — | http://192.168.1.102:32746 | NodePort; also http://192.168.1.102:2746 on host |
| Loki | log aggregation | http://192.168.1.102:30100 | Scrapes pods labeled `app.kubernetes.io/part-of=bluefin-test-suite` |
| ArgoCD | GitOps controller | https://192.168.1.102 (argocd NS) | Two Applications: `testing-lab` + `testing-lab-infra` |
| llm-d | LLM inference (hive node) | http://192.168.1.102:30800 | OpenAI-compatible API; model: Qwen/Qwen3.6-35B-A3B; namespace: `llm-d` |

**No hostDisk VMs remain.** All VM types use containerDisk or PVC:
- **ContainerDisk VMs** (Bluefin, GnomeOS, Dakota, Flatcar): float freely to any KubeVirt-capable node (ghost or bazzite).
- **PVC-backed VMs** (Knuckle): `local-path` PVC; KubeVirt co-schedules the VM automatically on the PVC's node. No explicit `nodeSelector` needed.

Adding a new KubeVirt node requires no YAML changes — VMs will schedule there automatically.

**Opt-in workers** (exo-1, hamilton): all machines in the homelab run the same opt-in setup —
k3s-agent disabled by default, `~/Justfile` with `just k8s-on/off` to join/leave the cluster,
sleep inhibitor service prevents suspend while connected. See `docs/agent-cheatsheet.md` section 14
for full onboarding steps and `docs/skills/k3s-cluster-ops` for the quick reference.

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

- `HostDisk` is required for KubeVirt hostDisk volumes (not currently used; all VMs use containerDisk or PVC).
- `ExperimentalIgnitionSupport` is required for installer-style VMs that use the `kubevirt.io/ignitiondata` annotation.
- If VM creation fails with `feature gate is not enabled in kubevirt-config`, treat that as **cluster infra drift** and persist the fix via GitOps under `manifests/`.

## Repo Layout

```
argo/
  workflow-templates/          ← ArgoCD (testing-lab App) syncs these
    build-containerdisk.yaml      build containerDisk from bootc image
    bluefin-qa-pipeline.yaml      full pipeline: build + provision + tests
    provision-bluefin-vm.yaml     boot Bluefin KubeVirt VM
    run-gnome-tests.yaml          SSH into VM, run behave/qecore suite
    teardown-bluefin-vm.yaml      delete Bluefin VM + disk
    provision-flatcar-vm.yaml     provision Flatcar VM
    run-flatcar-tests.yaml        SSH into Flatcar VM, run tests
    teardown-flatcar-vm.yaml      delete Flatcar VM + hostDisk
    provision-gnomeos-vm.yaml     provision GnomeOS VM
    teardown-gnomeos-vm.yaml      delete GnomeOS VM
    run-incluster-tests.yaml      run tests inside the cluster
    dakota-qa-pipeline.yaml       full Dakota QA pipeline (pull from ghcr.io/projectbluefin/dakota)
    knuckle-qa-pipeline.yaml      Knuckle installer pipeline
    image-poller.yaml             poll for new image digests
    pr-poller.yaml                poll PRs — auto-tests bluefin, bluefin-lts, common, dakota every PR
    ghost-cleanup.yaml            ghost host maintenance and disk GC
    collect-vm-logs.yaml          collect logs from a running test VM
  bluefin-smoke-test.yaml         submit: full build+provision+test run (latest)
  bluefin-test-matrix.yaml        submit: parallel latest+lts matrix
  flatcar-smoke-test.yaml         submit: Flatcar test run
manifests/                     ← ArgoCD (testing-lab-infra App) syncs these
  argo-server-nodeport.yaml       NodePort 32746 for external Argo API access
  argo-server-auth.yaml           Argo Server auth config
  argo-default-sa-rbac.yaml       default service account RBAC
  kubevirt-rbac.yaml              KubeVirt RBAC for workflow pods
  kubevirt-feature-gates.yaml     KubeVirt feature gates (HostDisk, ExperimentalIgnitionSupport)
  orphan-vm-cleanup.yaml          CronWorkflow: clean orphaned VMs every 2h
  orphan-pod-gc.yaml              CronWorkflow: garbage-collect orphaned pods
  golden-disk-gc.yaml             CronWorkflow: garbage-collect old golden disks
  pr-image-gc.yaml                CronWorkflow: clean up PR test images
  nightly-smoke.yaml              CronWorkflow: nightly smoke latest @ 02:00 UTC
  nightly-smoke-lts.yaml          CronWorkflow: nightly smoke lts @ 02:30 UTC
  nightly-dakota.yaml             CronWorkflow: nightly Dakota QA
  nightly-knuckle.yaml            CronWorkflow: nightly Knuckle pipeline
  workflow-controller-configmap.yaml  global TTL patch (7d success, 30d failure)
  flatcar-test-namespace.yaml     Flatcar test namespace
  gnomeos-test-namespace.yaml     GnomeOS test namespace
  gnomeos-smbios-hook.yaml        GnomeOS SMBIOS MutatingWebhook
  bluefin-test-ssh-pubkey.yaml    SSH public key secret for VM accessCredentials
  image-polling-state.yaml        ConfigMap: per-image last-seen digest
  image-poll-bluefin-testing.yaml CronWorkflow: poll bluefin:testing digest
  image-poll-bluefin-stable.yaml  CronWorkflow: poll bluefin:stable digest
  image-poll-lts-testing.yaml     CronWorkflow: poll bluefin-lts:testing digest
  image-poll-lts-stable.yaml      CronWorkflow: poll bluefin-lts:stable digest
  image-poll-dakota.yaml          CronWorkflow: poll dakota:latest digest
  pr-label-poller.yaml            CronWorkflow: poll PRs for test-me label
  lab-test-vm-priorityclass.yaml  PriorityClass for test VM pods
  homelab-access-auth.yaml        homelab access auth config
  homelab-runner-rbac.yaml        RBAC for homelab ARC runners
  inotify-tuning.yaml             DaemonSet: tune inotify limits on all nodes
  registry-mirror-config.yaml     DaemonSet: write containerd hosts.toml mirror config
  loki-config.yaml                Loki log aggregation config
  promtail-config.yaml            Promtail log scraper config
  zot-cache.yaml                  Zot pull-through cache (port 30501, all upstreams)
  zot-writable.yaml               Zot writable local registry (port 30500)
argocd/
  application.yaml               ArgoCD Application: testing-lab
  infra-application.yaml         ArgoCD Application: testing-lab-infra
  arc-controller-app.yaml        ArgoCD Application: ARC controller
  arc-runners-app.yaml           ArgoCD Application: ARC runner scale set
tests/
  smoke/features/                behave/qecore GNOME Shell smoke tests
  developer/features/            behave GNOME desktop tests (podman, ptyxis, etc.)
  software/features/             behave flatpak/Bazaar tests
  system/features/               atomic OS contract tests
  flatcar/                       Flatcar systemd/container tests
AGENTS.md                        This file
RUNBOOK.md                       Timeless architecture + failure modes
SECURITY.md                      Accepted homelab trade-offs and risks
Justfile                         Repo-owner convenience wrappers (require kubectl/argo access; agents use MCP)
```

## ARC Runners (GitHub Actions on ghost)

Self-hosted GitHub Actions runners via Actions Runner Controller (ARC).

| Resource | Value |
|---|---|
| Runner label | `ghost-runners` |
| GitHub config URL | `https://github.com/projectbluefin` |
| Min runners | 0 (idle — `arc-runners` namespace empty when no jobs; correct) |
| Max runners | 6 |
| GitHub App | `bluefin-ghost-arc` (ID 4099840, Installation 141458121) |
| Credentials secret | `arc-github-secret` in `arc-runners` namespace |
| ArgoCD Applications | `argocd/arc-controller-app.yaml`, `argocd/arc-runners-app.yaml` |

**Use in a workflow:** `runs-on: ghost-runners`

**Never replace the GitHub App credentials with a PAT.**

If the listener is missing from `arc-systems`: check controller logs. Most likely cause
is the controller landing on bazzite (bazzite has no cluster DNS — ARC controller must run on ghost). Delete the controller pod — it
reschedules to ghost.

## Zot Registry Cache

Pull-through OCI cache for container images. Transparent to all pods on ghost via
containerd `hosts.toml` (written by `registry-mirror-config` DaemonSet — no k3s restart needed).

| Instance | Upstream | NodePort | Storage |
|---|---|---|---|
| `registry` (writable) | — write target, no upstream | 30500 | `/var/mnt/ghost-data/zot-local` |
| `zot-cache` | all 6 upstreams (ghcr, docker, quay, fedora, k8s, cgr) | 30501 | `/var/mnt/ghost-data/zot-cache` |

Pull path prefixes (used in hosts.toml mirror URLs and Zot destination mapping):
- `ghcr.io` → `:30501/ghcr`
- `docker.io` → `:30501/docker`
- `quay.io` → `:30501/quay`
- `registry.fedoraproject.org` → `:30501/fedora`
- `registry.k8s.io` → `:30501/k8s`
- `cgr.dev` → `:30501/cgr`

All instances pinned to ghost (hostPath storage) and managed by ArgoCD `testing-lab-infra`
via `manifests/zot-cache.yaml` (pull-through) and `manifests/zot-writable.yaml` (write target).

**Image policy:** all `image:` references in `argo/` and `manifests/` must use a cached registry.
Enforced by the registry allowlist lint step in `.github/workflows/lint.yaml`.
Allowlist: `ghcr.io`, `quay.io`, `registry.fedoraproject.org`, `registry.k8s.io`, `cgr.dev`, `192.168.1.102`, `localhost`.
Exception: `docker.io/rocm/k8s-device-plugin` — annotate `# registry-lint-ignore`.
**Banned registries:** `registry.access.redhat.com` (UBI), `bitnami`, `docker.io` (except rocm exception above).
**Base image preference order:**
1. `cgr.dev/chainguard/*` — Chainguard first always
2. `registry.fedoraproject.org/fedora-hummingbird:latest` — Fedora Hummingbird only; no other Fedora variants
3. `ubuntu` (docker.io) — Ubuntu third
4. Anything else: ask before choosing
**Rule:** for kubectl+shell in workflow templates, use `cgr.dev/chainguard/kubectl:latest-dev`
(has bash; `registry.k8s.io/kubectl` is distroless — no shell).
**Rule:** upstream k8s/CNCF registries (`registry.k8s.io`, `quay.io`) always preferred over
distro-specific replacements when an upstream image exists.

| Tag (image-tag / disk dir) | Image | Golden disk on ghost | Nightly |
|---|---|---|---|
| `testing` | `ghcr.io/projectbluefin/bluefin:testing` | `/var/tmp/bluefin-golden/testing/disk.raw` | 02:00 UTC |
| `lts-testing` | `ghcr.io/projectbluefin/bluefin-lts:testing` | `/var/tmp/bluefin-golden/lts-testing/disk.raw` | 02:30 UTC |
| `stable` | `ghcr.io/projectbluefin/bluefin:stable` | `/var/tmp/bluefin-golden/stable/disk.raw` | — |
| `lts-stable` | `ghcr.io/projectbluefin/bluefin-lts:stable` | `/var/tmp/bluefin-golden/lts-stable/disk.raw` | — |

> **`:stable` and `:testing` are the only production branches.** All other tags (`:latest`, `:lts`, `:gts`, date tags, stream tags) are developer-facing conveniences — never use them in automation, manifests, or docs. `bluefin-lts` has no `:latest` tag at all; `skopeo inspect` returns `manifest unknown` and will fail any workflow that tries it.

## VM Lifecycle

All Bluefin test VMs are now ephemeral. Nightlies and ad hoc validation runs provision fresh VMs through `bluefin-qa-pipeline` and tear them down on workflow exit; GitOps no longer manages persistent titan VM manifests in this repo.

SSH key injection uses KubeVirt `accessCredentials` with `qemuGuestAgent` — the public key is injected into the running VM by virt-controller via QEMU guest agent at boot. Two secrets are required:
- `bluefin-test-ssh-key` in `argo` namespace: private+public key for SSH client (workflow pods)
- `bluefin-test-ssh-pubkey` in the VM namespace (e.g. `bluefin-test`): public key for accessCredentials injection, managed by ArgoCD via `manifests/bluefin-test-ssh-pubkey.yaml`

**Do not use disk injection for SSH keys.** bootc/ostree resets `etc/` files that exist in the image's `usr/etc/` at first boot; `var/` btrfs writes may not survive `qemu-img` conversion.

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
| gnomeos-test | GNOME OS test VMs |
| llm-d | LLM inference hive node (Qwen3.6-35B-A3B Q4_K_M GGUF via llama.cpp on ROCm) |
| local-registry | OCI registry: writable Zot (port 30500), unified pull-through cache — zot-cache (30501, all upstreams) |
| arc-systems | ARC controller + listener pods |
| arc-runners | ARC ephemeral runner pods — **empty when no jobs queued; that is correct** |
| mcp | Kubernetes MCP server |

**Never delete VMs or resources in namespaces outside this list.**

## YAML Authoring Rules

- **No inline Python inside bash inside YAML** — colons and quotes in Python cause YAML parse errors. Use `kubectl` + `jsonpath` instead.
- **No `generateName` in `manifests/`** — ArgoCD needs stable names to track resources. Use fixed `name:` fields.
- **Use `workflowTemplateRef`** in CronWorkflows instead of inlining DAG templates — avoids duplication.
- **Server-side apply is enabled** for `manifests/` — you can patch a subset of a resource's fields without owning the whole object.
- **VM names must be ≤63 chars** — KubeVirt applies the VM name as a label value on the VMI and pod, which has a strict 63-char Kubernetes limit. Prefer `{{workflow.name}}-{{item}}` over `{{variant}}-{{item}}-{{workflow.uid}}`; workflow names are short and unique. A `FailedCreate` condition with `metadata.labels: must be no more than 63 characters` means the name is too long.

## Issue Filing

- All issues go in **castrojo/testing-lab**.
- Label: `bug` for test failures and infrastructure breaks; `enhancement` for new capabilities.
- Include: current behavior, expected behavior, exact file:line if code issue, acceptance criteria.
- For infra failures: include workflow name, pod name, and relevant log excerpt.

## VM Concurrency — k8s Native Scheduling

VM concurrency is managed by the k8s scheduler via **virt-launcher pod memory
requests** (8Gi per VM). No Argo semaphores. No config to maintain.

When a node has insufficient RAM, the virt-launcher pod stays Pending. When a
running VM finishes, resources free up and the scheduler picks the next Pending
pod. FIFO ordering follows workflow creation timestamp automatically.

**Adding a node:** the scheduler starts using it immediately. No YAML changes needed.

**All pipelines have `activeDeadlineSeconds`** (1h containerdisk, 2h knuckle)
so stuck VMs self-evict and release node resources automatically.

**VMs float to any KubeVirt-capable node** (ghost, bazzite). The ghost-pin was
removed — the registry-mirror-config DaemonSet writes hosts.toml for
`192.168.1.102:30500` on all nodes.


| Template | CPU req/limit | Memory req/limit |
|---|---|---|
| `run-gnome-tests` | 1 / 2 | 1Gi / 2Gi |
| `reflink-disk` | 100m / 500m | 128Mi / 512Mi |


## Hive Contributor

Ghost's local llama.cpp model (`Qwen/Qwen3.6-35B-A3B` at `http://192.168.1.102:30800`) can
contribute to the projectbluefin hive swarm as an autonomous agent.

**Start:** `./scripts/hive-contribute.sh`

The script:
1. Clones/refreshes `github.com/kubestellar/hive` at `/tmp/hive`
2. Patches the relay to prepend guardrails to every task prompt
3. Sets `GOOSE_MOIM_MESSAGE_TEXT` so goose's Top-of-Mind extension injects rules on every turn
4. Runs `just contribute-setup goose` (idempotent) then `just contribute-hive goose local`

**Guardrails (enforced at relay + Top-of-Mind layers):**
- ONE comment per issue/PR — edit existing, never post a new one
- Never merge or approve PRs — open for human review only
- No spam / status update comments — only post a concrete complete result
- Conservative — propose changes, don't push code when uncertain
- Don't close issues unless your PR was already merged by a maintainer
- Stay scoped to the assigned repo/issue

**Monitor:** `tmux attach -t hive-goose-<id>` (session name printed on start)

**Contributor ID:** `c-ad58129be630` (registered as `castrojo`, tier: contributor)

## Canonical Command Reference

See [docs/agent-cheatsheet.md](docs/agent-cheatsheet.md) for the canonical command reference.
Use it for workflow run commands, ArgoCD commands, CronWorkflow operations,
SSH rotation, PR queue steps, safe cleanup, bootstrap, self-check commands, and live cluster facts.
