# bluefin-test-suite Justfile
# GitOps policy:
#   - WorkflowTemplate changes go via git push to main; ArgoCD auto-syncs.
#   - Do NOT kubectl apply templates directly. Do NOT SSH to ghost or exo-1.
#   - Workflow submission and monitoring: use these just targets or Argo MCP tools.
#   - Cluster bootstrap (setup-ssh-secret, setup-argocd) runs once from workstation.

image     := env_var_or_default("BLUEFIN_IMAGE", "ghcr.io/ublue-os/bluefin:latest")
image_tag := env_var_or_default("BLUEFIN_IMAGE_TAG", "latest")
argo_ns   := "argo"

# List all available recipes
default:
    @just --list

# ── Bootstrap (run once) ─────────────────────────────────────────────────────

# Create bluefin-test-ssh-key secret in argo namespace (idempotent)
# The secret is read by bib-disk-configure via secretKeyRef — no pubkey env var needed.
setup-ssh-secret:
    #!/usr/bin/env bash
    set -euo pipefail
    if kubectl get secret bluefin-test-ssh-key -n {{ argo_ns }} &>/dev/null; then
        echo "✓ bluefin-test-ssh-key already exists"
        kubectl get secret bluefin-test-ssh-key -n {{ argo_ns }} \
            -o jsonpath="{.data.id_ed25519\.pub}" | base64 -d | ssh-keygen -lf - \
            && echo "(fingerprint above)"
        exit 0
    fi
    ssh_key=$(mktemp)
    ssh-keygen -t ed25519 -f "${ssh_key}" -N "" -C "bluefin-test-suite@ghost" >/dev/null
    kubectl create secret generic bluefin-test-ssh-key \
        --from-file=id_ed25519="${ssh_key}" \
        --from-file=id_ed25519.pub="${ssh_key}.pub" \
        -n {{ argo_ns }}
    shred -u "${ssh_key}" "${ssh_key}.pub"
    echo "✓ SSH secret created"

# Deploy the ArgoCD Application that auto-syncs argo/workflow-templates from git (run once)
# After this, template changes take effect on git push — no kubectl apply needed.
setup-argocd:
    kubectl apply -f argocd/application.yaml -n argocd
    @echo "✓ ArgoCD Application deployed — syncs argo/workflow-templates from main automatically"

# ── Template management (GitOps — prefer git push over manual sync) ──────────

# Force ArgoCD to sync now instead of waiting for the next poll interval
argocd-sync:
    argocd app sync testing-lab testing-lab-infra --timeout 120
    argocd app wait testing-lab --health --timeout 120
    argocd app wait testing-lab-infra --health --timeout 120

# Show ArgoCD sync status for the test suite
argocd-status:
    argocd app get testing-lab
    argocd app get testing-lab-infra

# ── Disk image management ────────────────────────────────────────────────────

# Pre-build golden disk for a given tag (idempotent — skips if disk already exists)
# Pubkey is injected from the bluefin-test-ssh-key secret automatically.
# Usage: just ensure-disk
# Usage: just ensure-disk lts
ensure-disk tag=image_tag:
    argo submit --from workflowtemplate/bib-build-and-push \
        -p image="ghcr.io/ublue-os/bluefin:{{ tag }}" \
        -p image-tag="{{ tag }}" \
        -n {{ argo_ns }} \
        --watch

# Patch an existing golden disk's SSH config (no SSH to node required)
# Use after secret rotation or when SSH auth fails on an existing disk.
# Usage: just patch-disk
# Usage: just patch-disk lts
patch-disk tag=image_tag:
    argo submit --from workflowtemplate/patch-golden-disk \
        -p image-tag="{{ tag }}" \
        -n {{ argo_ns }} \
        --watch

# ── Test execution ───────────────────────────────────────────────────────────

# Run smoke tests against latest (or BLUEFIN_IMAGE_TAG)
run-tests:
    argo submit argo/bluefin-smoke-test.yaml \
        -p image="{{ image }}" \
        -p image-tag="{{ image_tag }}" \
        -n {{ argo_ns }} \
        --watch

# Run smoke tests against a specific tag
# Usage: just run-tests-tag lts
run-tests-tag tag:
    argo submit argo/bluefin-smoke-test.yaml \
        -p image="ghcr.io/ublue-os/bluefin:{{ tag }}" \
        -p image-tag="{{ tag }}" \
        -n {{ argo_ns }} \
        --watch

# Run matrix tests (latest + lts in parallel)
# Optional: PR_TITLE and PR_NUMBER env vars for annotations
run-tests-matrix:
    #!/usr/bin/env bash
    set -euo pipefail
    PR_TITLE="${PR_TITLE:-}"
    PR_NUMBER="${PR_NUMBER:-}"
    argo submit argo/bluefin-test-matrix.yaml \
        -p pr-title="${PR_TITLE}" \
        -p pr-number="${PR_NUMBER}" \
        -n {{ argo_ns }} \
        --watch

# One-time: write SSH banner on ghost warning agents to use the K8s MCP.
# Runs as a WorkflowTemplate (not a manifest Job) to avoid ArgoCD reconcile loops.
setup-ghost-ssh-banner:
    argo submit --from workflowtemplate/setup-ghost-ssh-banner \
        -n {{ argo_ns }} \
        --wait --log

# One-time fixture setup for titan VMs: installs Firefox Flatpak and sets default browser.
# Run this before smoke tests that cover xdg-settings (#107).
setup-titan-fixtures:
    #!/usr/bin/env bash
    set -euo pipefail
    IP_LATEST=$(kubectl get vmi titan-bluefin -n bluefin-test \
        -o jsonpath='{.status.interfaces[0].ipAddress}' 2>/dev/null)
    IP_LTS=$(kubectl get vmi titan-lts -n bluefin-lts-test \
        -o jsonpath='{.status.interfaces[0].ipAddress}' 2>/dev/null)
    : "${IP_LATEST:?titan-bluefin VMI not found or has no IP}"
    : "${IP_LTS:?titan-lts VMI not found or has no IP}"
    echo "Setting up titan-bluefin (${IP_LATEST})..."
    argo submit --from workflowtemplate/setup-titan-fixtures \
        -p vm-ip="${IP_LATEST}" \
        -p variant=latest \
        -n {{ argo_ns }} \
        --wait --log
    echo "Setting up titan-lts (${IP_LTS})..."
    argo submit --from workflowtemplate/setup-titan-fixtures \
        -p vm-ip="${IP_LTS}" \
        -p variant=lts \
        -n {{ argo_ns }} \
        --wait --log

# Run smoke against persistent titan VMs (no BIB build, instant start)
run-titan-smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    IP_LATEST=$(kubectl get vmi titan-bluefin -n bluefin-test \
        -o jsonpath='{.status.interfaces[0].ipAddress}' 2>/dev/null)
    IP_LTS=$(kubectl get vmi titan-lts -n bluefin-lts-test \
        -o jsonpath='{.status.interfaces[0].ipAddress}' 2>/dev/null)
    : "${IP_LATEST:?titan-bluefin VMI not found or has no IP}"
    : "${IP_LTS:?titan-lts VMI not found or has no IP}"
    echo "titan-bluefin: ${IP_LATEST}"
    echo "titan-lts:     ${IP_LTS}"
    argo submit --from workflowtemplate/bluefin-titan-smoke \
        -p vm-ip-latest="${IP_LATEST}" \
        -p vm-ip-lts="${IP_LTS}" \
        -n {{ argo_ns }} \
        --watch

# Run system (atomic OS contract) tests on persistent titan VMs (fast path).
run-titan-system:
    #!/usr/bin/env bash
    set -euo pipefail
    LATEST_IP=$(kubectl get vmi titan-bluefin -n bluefin-test -o jsonpath='{.status.interfaces[0].ipAddress}')
    LTS_IP=$(kubectl get vmi titan-lts -n bluefin-lts-test -o jsonpath='{.status.interfaces[0].ipAddress}')
    argo submit --from workflowtemplate/bluefin-titan-smoke \
      --parameter vm-ip-latest="${LATEST_IP}" \
      --parameter vm-ip-lts="${LTS_IP}" \
      --parameter suite=system \
      -n {{ argo_ns }} --wait --log

# Run developer suite tests on persistent titan VMs.
run-titan-developer:
    #!/usr/bin/env bash
    set -euo pipefail
    IP_LATEST=$(kubectl get vmi titan-bluefin -n bluefin-test \
        -o jsonpath='{.status.interfaces[0].ipAddress}' 2>/dev/null)
    IP_LTS=$(kubectl get vmi titan-lts -n bluefin-lts-test \
        -o jsonpath='{.status.interfaces[0].ipAddress}' 2>/dev/null)
    : "${IP_LATEST:?titan-bluefin VMI not found or has no IP}"
    : "${IP_LTS:?titan-lts VMI not found or has no IP}"
    echo "titan-bluefin: ${IP_LATEST}"
    echo "titan-lts:     ${IP_LTS}"
    argo submit --from workflowtemplate/bluefin-titan-smoke \
        -p vm-ip-latest="${IP_LATEST}" \
        -p vm-ip-lts="${IP_LTS}" \
        -p suite=developer \
        -n {{ argo_ns }} \
        --watch

# Run software suite tests on persistent titan VMs.
run-titan-software:
    #!/usr/bin/env bash
    set -euo pipefail
    IP_LATEST=$(kubectl get vmi titan-bluefin -n bluefin-test \
        -o jsonpath='{.status.interfaces[0].ipAddress}' 2>/dev/null)
    IP_LTS=$(kubectl get vmi titan-lts -n bluefin-lts-test \
        -o jsonpath='{.status.interfaces[0].ipAddress}' 2>/dev/null)
    : "${IP_LATEST:?titan-bluefin VMI not found or has no IP}"
    : "${IP_LTS:?titan-lts VMI not found or has no IP}"
    echo "titan-bluefin: ${IP_LATEST}"
    echo "titan-lts:     ${IP_LTS}"
    argo submit --from workflowtemplate/bluefin-titan-smoke \
        -p vm-ip-latest="${IP_LATEST}" \
        -p vm-ip-lts="${IP_LTS}" \
        -p suite=software \
        -n {{ argo_ns }} \
        --watch

# Run Flatcar smoke tests
run-flatcar-smoke:
    argo submit argo/flatcar-smoke-test.yaml \
        -n {{ argo_ns }} \
        --watch

# ── Observation ─────────────────────────────────────────────────────────────

# List all test workflows
list-workflows:
    argo list -n {{ argo_ns }}

# Tail logs from the most recent workflow
logs:
    argo logs -n {{ argo_ns }} @latest

# List VMs in all test namespaces
list-vms:
    @echo "=== bluefin-test ===" && kubectl get vm -n bluefin-test 2>/dev/null || true
    @echo "=== bluefin-lts-test ===" && kubectl get vm -n bluefin-lts-test 2>/dev/null || true
    @echo "=== flatcar-test ===" && kubectl get vm -n flatcar-test 2>/dev/null || true

# ── Cleanup ──────────────────────────────────────────────────────────────────

# Delete orphaned VMs in test namespaces (safe — never touches knuckle-test)
delete-vms:
    kubectl delete vm --all -n bluefin-test --ignore-not-found
    kubectl delete vm --all -n bluefin-lts-test --ignore-not-found
    kubectl delete vm --all -n flatcar-test --ignore-not-found

# Delete all test workflows
delete-workflows:
    argo delete --all -n {{ argo_ns }} || true

# Full teardown of in-flight resources
teardown:
    just delete-vms
    just delete-workflows

# ── In-cluster homelab substrate ─────────────────────────────────────────────

# Run in-cluster homelab substrate lifecycle tests
run-homelab-substrate:
    argo submit --from workflowtemplate/homelab-substrate \
      -n {{ argo_ns }} --wait --log

# Run in-cluster homelab storage persistence tests
run-homelab-storage:
    argo submit --from workflowtemplate/homelab-storage \
      -n {{ argo_ns }} --wait --log

# Run in-cluster homelab access probe
run-homelab-access:
    argo submit --from workflowtemplate/homelab-access-probe \
      -n {{ argo_ns }} --wait --log

# ── Dakota BST builds ────────────────────────────────────────────────────────

# Validate dakota element graph (bst show, no build — fast)
run-dakota-validate branch="main":
    argo submit --from workflowtemplate/dakota-bst \
      -p variant=default \
      -p branch={{ branch }} \
      --entrypoint bst-validate \
      -n {{ argo_ns }} --watch

# Build a dakota variant (default | nvidia | all) and lint the result
run-dakota-build variant="default" branch="main":
    argo submit --from workflowtemplate/dakota-bst \
      -p variant={{ variant }} \
      -p branch={{ branch }} \
      -n {{ argo_ns }} --watch

# ── Validation ───────────────────────────────────────────────────────────────

# Lint all Argo YAML manifests
lint:
    @for f in argo/*.yaml argo/workflow-templates/*.yaml; do \
        echo "Linting $f..."; \
        argo lint "$f" || exit 1; \
    done
    @echo "✓ All manifests valid"
