# bluefin-test-suite Justfile
# GitOps policy:
#   - WorkflowTemplate changes go via git push to main; ArgoCD auto-syncs.
#   - Do NOT kubectl apply templates directly. Do NOT SSH to ghost or exo-1.
#   - Workflow submission and monitoring: use these just targets or Argo MCP tools.
#   - These recipes are convenience wrappers for the repo owner on a workstation.
#   - Agents and automated systems should use MCP instead of invoking local kubectl/argo.
#   - No recipe SSHes to ghost; do NOT add workstation SSH hops.
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

# Run rechunk-to-chunkah migration validation against latest + stable in parallel.
# Usage: just run-migration-test
# Usage: just run-migration-test stable=stable latest=latest
run-migration-test latest="latest" stable="stable":
    argo submit argo/rechunk-to-chunkah-migration.yaml \
        -p image-tag-latest="{{ latest }}" \
        -p image-tag-stable="{{ stable }}" \
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

# DEPRECATED: persistent titan VMs are no longer GitOps-managed in this repo.
# This recipe only works if titan-bluefin and titan-lts were created manually.
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

# One-shot cleanup of titan VM disk files after ArgoCD prunes the VMs.
# dry-run=true by default — pass false to actually delete.
run-titan-disk-cleanup dry-run="true":
    argo submit --from workflowtemplate/titan-disk-cleanup \
      -p dry-run={{ dry-run }} \
      -n {{ argo_ns }} --watch

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
# Repo-owner convenience wrappers only; agents and automation should observe/clean up via MCP, never via SSH.

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

# Run first PVC/local-path restore drill (#60 #74 #84)
run-homelab-restore:
    argo submit --from workflowtemplate/homelab-restore-drill \
      -n {{ argo_ns }} --wait --log

# ── Service-catalog workload lanes ───────────────────────────────────────────

# Run the non-media (OpenPrinting/CUPS base) service-catalog lane (#81)
run-service-nonmedia:
    argo submit --from workflowtemplate/homelab-nonmedia-service \
      -n {{ argo_ns }} --wait --log

# ── Ghost maintenance ─────────────────────────────────────────────────────────

# Patch ghost OTel collector config to remove noisy process scraper (#117)
run-otel-patch:
    argo submit --from workflowtemplate/ghost-otel-patch \
      -n {{ argo_ns }} --wait --log

# Set Strix Halo performance kernel args on ghost via rpm-ostree (reboot required after)
run-kernel-args:
    argo submit --from workflowtemplate/ghost-kernel-args \
      -n {{ argo_ns }} --wait --log

# ── Dakota BST builds ────────────────────────────────────────────────────────

# Report lab build result as a GitHub commit status (updates in-place, no comment spam).
# Posting to the same context always overwrites the previous result — one indicator, ever.
# Also syncs lab:pass / lab:fail labels on the PR.
# Usage: just lab-report <pr_number> <pass|fail> <argo_workflow_name>
lab-report pr_number status workflow:
    #!/usr/bin/env bash
    set -euo pipefail
    REPO="projectbluefin/dakota"
    SHA=$(gh pr view {{ pr_number }} --repo "${REPO}" --json headRefOid --jq .headRefOid)
    if [ "{{ status }}" = "pass" ]; then
        STATE=success; LABEL="lab:pass"; REMOVE="lab:fail"
        DESC="BST build passed ({{ workflow }})"
    else
        STATE=failure; LABEL="lab:fail"; REMOVE="lab:pass"
        DESC="BST build failed ({{ workflow }})"
    fi
    gh api "repos/${REPO}/statuses/${SHA}" \
        --method POST \
        --field state="${STATE}" \
        --field description="${DESC}" \
        --field context="ghost-lab / bst-build" \
        --field target_url="http://192.168.1.102:2746/workflows/argo/{{ workflow }}"
    gh pr edit {{ pr_number }} --repo "${REPO}" \
        --add-label "${LABEL}" --remove-label "${REMOVE}" 2>/dev/null || true

# Validate dakota element graph (bst show, no build — fast)
# ref_type: branch | pr | sha   ref_value: branch name, PR number, or commit SHA
run-dakota-validate ref_type="branch" ref_value="main":
    argo submit --from workflowtemplate/dakota-bst \
      -p ref_type={{ ref_type }} \
      -p ref_value={{ ref_value }} \
      --entrypoint bst-validate \
      -n {{ argo_ns }} --watch

# Build a dakota variant (default | nvidia | all) and lint the result.
# Automatically reports build result as a commit status when ref_type=pr.
# ref_type: branch | pr | sha   ref_value: branch name, PR number, or commit SHA
run-dakota-build variant="default" ref_type="branch" ref_value="main":
    #!/usr/bin/env bash
    set -euo pipefail
    WF=$(argo submit --from workflowtemplate/dakota-bst \
      -p variant={{ variant }} \
      -p ref_type={{ ref_type }} \
      -p ref_value={{ ref_value }} \
      -n {{ argo_ns }} \
      --output name)
    echo "Submitted: ${WF}"
    argo watch "${WF}" -n {{ argo_ns }} && RC=0 || RC=$?
    if [ "{{ ref_type }}" = "pr" ]; then
        [ "${RC}" -eq 0 ] && STATUS=pass || STATUS=fail
        just lab-report {{ ref_value }} "${STATUS}" "${WF}"
    fi
    exit "${RC}"

# Full Dakota QA pipeline: BST build → BIB disk → VM → smoke tests
# ref_type: branch | pr | sha   ref_value: branch name, PR number, or commit SHA
run-dakota-qa variant="default" ref_type="branch" ref_value="main":
    argo submit --from workflowtemplate/dakota-qa-pipeline \
      -p variant={{ variant }} \
      -p ref_type={{ ref_type }} \
      -p ref_value={{ ref_value }} \
      -n {{ argo_ns }} --watch

# ── Validation ───────────────────────────────────────────────────────────────

# Lint all Argo YAML manifests.
# WorkflowTemplates are linted together (--offline) so cross-file templateRef
# references (e.g. dakota-qa-pipeline → dakota-bst) resolve without needing
# the Argo server to have the new templates already synced.
# Standalone Workflow files (argo/*.yaml) reference server-side templates and
# are linted individually against the live server.
lint:
    @echo "Linting argo/workflow-templates/ (offline, cross-file refs)..."
    @argo lint --offline argo/workflow-templates/
    @echo "✔ workflow-templates: no linting errors found!"
    @for f in argo/*.yaml; do \
        echo "Linting $f..."; \
        argo lint "$f" || exit 1; \
    done
    @echo "✓ All manifests valid"
