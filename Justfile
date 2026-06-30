# bluefin-test-suite Justfile
# GitOps policy:
#   - WorkflowTemplate changes go via git push to main; ArgoCD auto-syncs.
#   - Do NOT kubectl apply templates directly.
#   - Workflow submission and monitoring: use these just targets (argo/kubectl CLI).
#   - These recipes are the canonical interface for all routine lifecycle operations.
#   - Agents use these recipes or call argo/kubectl directly. No MCP required.
#   - ssh jorge@ghost is permitted for OS-level tasks only (k3s restart, systemd, brew).
#   - No recipe SSHes to ghost; do NOT add workstation SSH hops.
#   - Cluster bootstrap (setup-ssh-secret, setup-argocd) runs once from workstation.

image     := env_var_or_default("BLUEFIN_IMAGE", "ghcr.io/projectbluefin/bluefin:testing")
image_tag := env_var_or_default("BLUEFIN_IMAGE_TAG", "testing")
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
    argo submit --from workflowtemplate/build-containerdisk \
        -p image="ghcr.io/projectbluefin/bluefin:{{ tag }}" \
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

# Run migration validation (bootc switch: ublue-os/bluefin → projectbluefin/bluefin)
# Usage: just run-migration-test
# Usage: just run-migration-test lts
run-migration-test tag=image_tag:
    argo submit --from workflowtemplate/bluefin-migration-test \
        -p image-tag="{{ tag }}" \
        -n {{ argo_ns }} \
        --watch

# One-time: write SSH banner on ghost.
setup-ghost-ssh-banner:
    argo submit --from workflowtemplate/setup-ghost-ssh-banner \
        -n {{ argo_ns }} \
        --wait --log


# —— [REMOVED] titan VM recipes ——
# run-titan-smoke, run-titan-system, run-titan-developer, run-titan-software,
# setup-titan-fixtures, run-titan-disk-cleanup
# Titan persistent VMs are no longer GitOps-managed. See argo/deprecated/ for history.

# PLACEHOLDER for removed recipes (kept to avoid recipe renaming surprises)
_titan-removed:
    @echo "Titan VM recipes removed. See argo/deprecated/README.md"

# DEPRECATED placeholder — slot reserved
setup-titan-fixtures:
    @echo "Titan fixtures removed — titan VMs are no longer used"

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

# Run on-demand K8sGPT cluster analysis
# Usage: just run-k8sgpt
# Usage: just run-k8sgpt argo "Pod,Deployment"
run-k8sgpt namespace="" filters="Pod,Deployment,Service,Ingress,Node":
    argo submit --from workflowtemplate/k8sgpt-on-demand \
      -p namespace="{{ namespace }}" \
      -p filters="{{ filters }}" \
      -n {{ argo_ns }} --wait --log

# Run first PVC/local-path restore drill (#60 #74 #84)
run-homelab-restore:
    argo submit --from workflowtemplate/homelab-restore-drill \
      -n {{ argo_ns }} --wait --log

# ── Ghost maintenance ─────────────────────────────────────────────────────────

# Patch ghost OTel collector config to remove noisy process scraper (#117)
run-otel-patch:
    argo submit --from workflowtemplate/ghost-otel-patch \
      -n {{ argo_ns }} --wait --log

# Clear stale podman containers-storage lock files on ghost (run when no BIB workflows active)
run-ghost-cleanup:
    argo submit --from workflowtemplate/ghost-cleanup \
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
        --field context="testing-lab / bst-build" \
        --field target_url="http://192.168.1.102:2746/workflows/argo/{{ workflow }}"
    gh pr edit {{ pr_number }} --repo "${REPO}" \
        --add-label "${LABEL}" --remove-label "${REMOVE}" 2>/dev/null || true

# Run Dakota BST pipeline (build bluefin + bluefin-nvidia variants in parallel)
# Usage: just run-bst-build
# Usage: just run-bst-build testing https://github.com/projectbluefin/dakota.git
run-bst-build ref="testing" repo="https://github.com/projectbluefin/dakota.git":
    argo submit --from workflowtemplate/dakota-build-pipeline \
      -p ref={{ ref }} \
      -p repo={{ repo }} \
      -n {{ argo_ns }} --watch

# Compatibility alias for older docs/callers.
run-dakota-validate ref="testing" repo="https://github.com/projectbluefin/dakota.git":
    just run-bst-build {{ ref }} {{ repo }}

# Compatibility alias for older docs/callers.
run-dakota-build ref="testing" repo="https://github.com/projectbluefin/dakota.git":
    just run-bst-build {{ ref }} {{ repo }}

# Full Dakota QA pipeline: VM-based suite run against dakota containerdisk.
run-dakota-qa branch="main" variant="dakota":
    argo submit --from workflowtemplate/dakota-qa-pipeline \
      -p variant={{ variant }} \
      -p branch={{ branch }} \
      -n {{ argo_ns }} --watch

# Run the in-cluster BuildStream build pipeline for bluefin-server
# Usage: just run-bluefin-server-build
run-bluefin-server-build ref="main" repo="https://github.com/castrojo/bluefin-server.git":
    argo submit --from workflowtemplate/bluefin-server-build-pipeline \
      -p ref={{ ref }} \
      -p repo={{ repo }} \
      -n {{ argo_ns }} --watch

# ── Validation ───────────────────────────────────────────────────────────────

# Apply bootstrap WorkflowTemplates to the cluster (run once during initial setup)
apply-bootstrap:
    kubectl apply -f argo/bootstrap/ -n {{ argo_ns }}
    @echo "✓ Bootstrap templates applied — run individual templates with: argo submit --from workflowtemplate/<name> -n argo --wait --log"

# Lint all Argo YAML manifests.
# WorkflowTemplates are linted together (--offline) so cross-file templateRef
# references (e.g. dakota-commit-poller → dakota-build-pipeline) resolve without needing
# the Argo server to have the new templates already synced.
# Standalone Workflow files (argo/*.yaml) reference server-side templates and
# are linted individually against the live server.
lint:
    @echo "Linting argo/workflow-templates/ (offline, cross-file refs)..."
    @argo lint --offline argo/workflow-templates/
    @echo "✔ workflow-templates: no linting errors found!"
    @echo "Linting argo/bootstrap/ (offline)..."
    @argo lint --offline argo/bootstrap/
    @echo "✔ bootstrap: no linting errors found!"
    @for f in argo/*.yaml; do \
        echo "Linting $f..."; \
        argo lint "$f" || exit 1; \
    done
    @echo "✓ All manifests valid"

# Run the interactive Flatcar clone systemd-sysext & bootc state machine prototype
run-flatcar-clone-prototype:
	@python3 flatcar-clone-prototype.py
