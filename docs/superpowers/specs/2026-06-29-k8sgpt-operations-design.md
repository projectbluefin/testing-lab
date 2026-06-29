# K8sGPT On-Demand Operator Assistant — Design

Date: 2026-06-29  
Repo: `projectbluefin/testing-lab`  
Status: Approved design (ready for implementation planning)

## Goal

Integrate K8sGPT into day-to-day cluster operations as an **on-demand operator assistant** with:

1. `just` entrypoint for operators.
2. Argo Workflow execution history for auditability.
3. JSON artifact output plus concise human summary per run.

## Scope

In scope:

- Add an on-demand Argo `WorkflowTemplate` for K8sGPT analysis.
- Add a `just` wrapper that submits the template.
- Add/align a GitOps-managed `K8sGPT` custom resource for cluster-wide core-filter defaults.
- Preserve existing `manifests/k8sgpt-operator.yaml` operator management.

Out of scope:

- Persistent alert routing (Slack/webhook sink).
- Autonomous issue/PR commenting.
- Scheduled CronWorkflow operation for this first phase.

## Architecture

### Components

1. **K8sGPT Operator (existing)**  
   Managed by ArgoCD from `manifests/k8sgpt-operator.yaml`.

2. **K8sGPT CR (new/updated manifest)**  
   GitOps object defining analysis defaults:
   - cluster-wide scope
   - filters: `Pod`, `Deployment`, `Service`, `Ingress`, `Node`
   - explain mode enabled by default

3. **WorkflowTemplate `k8sgpt-on-demand` (new)**  
   Runs analysis and produces:
   - machine-readable JSON artifact (`/tmp/results/k8sgpt-results.json`)
   - concise stdout summary

4. **Justfile recipe `run-k8sgpt` (new)**  
   Submits `workflowtemplate/k8sgpt-on-demand` with optional parameter overrides.

## Runtime Flow

1. Operator runs `just run-k8sgpt`.
2. Recipe submits Argo workflow from `k8sgpt-on-demand`.
3. Workflow step executes K8sGPT analysis with defaults (cluster-wide core filters).
4. Full result JSON is written to artifact path.
5. Summary is printed to workflow logs.
6. Operator views quick result in logs, downloads full JSON from Argo artifact UI/CLI if needed.

## Parameters and Defaults

Template parameters (with defaults):

- `namespace`: empty/cluster-wide
- `filters`: `Pod,Deployment,Service,Ingress,Node`
- `explain`: `true`

Behavior:

- No params passed → cluster-wide core-filter analysis.
- Params passed → narrow namespace and/or resource filters for focused debugging.

## Error Handling

- Analyzer command failures are fatal (non-zero exit).
- API/RBAC/config errors surface explicitly in stderr.
- No silent fallback to success.
- Workflow sets bounded runtime (`activeDeadlineSeconds`) and conservative resources.

## Security and Operational Constraints

- Follow repo GitOps policy: manifests/templates changed in git only; ArgoCD reconciles.
- No direct host SSH for workload execution.
- Keep implementation in existing allowed registries and image policy.
- Avoid writing findings to long-lived mutable cluster state for this phase.

## Validation Plan

1. `just lint` passes after YAML/Justfile updates.
2. Run one manual `just run-k8sgpt`.
3. Confirm workflow completes and prints concise summary.
4. Confirm artifact exists and contains machine-readable JSON output.
5. Confirm optional parameter overrides function (namespace/filter).

## Acceptance Criteria

1. Operator can trigger K8sGPT via `just run-k8sgpt`.
2. Execution is tracked as Argo workflow history.
3. Each run produces both:
   - concise summary in logs
   - JSON artifact for detailed analysis
4. Default run is cluster-wide using core filters.
5. No policy violations against GitOps and CLI-first operating model.
