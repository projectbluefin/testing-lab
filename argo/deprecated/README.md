# Deprecated Workflow Files

Do not use these files. The canonical files are in `../workflow-templates/`.

## Titan persistent VMs (superseded by ephemeral VM pipeline)

- `bluefin-titan-smoke.yaml` — ran tests against always-on titan VMs. Replaced by `bluefin-qa-pipeline` which provisions fresh VMs per-run.
- `setup-titan-fixtures.yaml` — installed Firefox Flatpak on titan VMs. No longer needed; ephemeral VMs provision from golden disk which already has fixtures.
- `titan-disk-cleanup.yaml` — cleaned up titan VM disk files. No longer needed; ephemeral VM teardown handles cleanup via `onExit` handler.

## CDI/PVC v1 (superseded by btrfs reflink v2)

- `provision-vm.yaml` — used CDI DataVolume + PVC. Replaced by hostDisk + btrfs reflink.
- `bib-build-and-push.yaml` — pushed disk to zot OCI registry. Now stores golden disk on hostPath.
- `teardown-vm.yaml` — deleted PVC. Now deletes hostDisk file.
- `bluefin-smoke-test.yaml` — inline DAG. Replaced by bluefin-qa-pipeline WorkflowTemplate.

## tmt/fmf runner (superseded by behave + qecore)

- `run-tmt.yaml` — tmt SSH runner using `bluefin-tmt-runner` container image. Replaced by
  `run-gnome-tests` which uses inline bash + git-sync + qecore-headless over SSH.
- `Containerfile` — Dockerfile for `192.168.1.102:5000/bluefin-tmt-runner:latest`.
  No longer needed; runner is now `quay.io/fedora/fedora:latest` with inline dnf/pip install.
- `plan-tmt.fmf` — fmf test plans for bluefin (smoke, developer-tools, software-management).
  Replaced by `tests/smoke/features/`, `tests/developer/`, `tests/software/` behave suites.
