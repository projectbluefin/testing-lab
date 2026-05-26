# ADR 0001 — Homelab-scale CNCF minimalism

Status: Accepted
Date: 2026-05-25

## Context

The testing-lab is a single-user, single-cluster homelab on `ghost`
(one k3s node). It is not multi-tenant, not internet-exposed, not on a
compliance schedule, and never grows past three nodes by design.

CNCF best practices were written for cloud-native production. Applying them
verbatim at this scale spends time on theater: every new controller adds
admission-webhook latency, every Vault-style abstraction adds a credential
plane outside git, every policy framework adds a debugger between agent and
cluster. The cost is paid every push; the benefit is hypothetical.

This ADR codifies what we accept and what we do not, so future agents and
contributors do not re-litigate the same decisions.

## Decisions

### Controller-acceptance rule

A new in-cluster controller is acceptable iff:

1. Its desired state lives in git (GitOps-native), AND
2. It introduces no credential plane outside git.

Under this rule:

| Tool | Verdict |
|---|---|
| ArgoCD | ✅ already in use |
| sealed-secrets | ✅ git-native, no external plane |
| zot (in-cluster) | ✅ stateful but git-friendly; today runs on host systemd |
| External Secrets + Vault | ❌ credential plane outside git |
| Argo Events | ❌ event bus outside git; ArgoCD reconciliation already covers what we need |
| Kyverno / Gatekeeper | ❌ admission webhook adds latency + debug surface for no homelab benefit |
| ESO + cert-manager Vault issuer | ❌ as above |

### Node-scale assumption

Single-node assumptions (hostPath, `nodeSelector: ghost`, btrfs reflink) are
acceptable today. Each occurrence is tagged with a `# TODO(adr-0001):
single-node` comment so a future scale event can `grep` them in one pass.

### Lint and policy

All lint runs locally as a pre-commit hook (`.githooks/pre-commit`). `main`
is auto-synced by ArgoCD; broken pushes recover on the next pre-commit fix.
No GitHub Actions, no admission-controller policy, no Rego/conftest.

### Mutable image tags

Per SECURITY.md: `:latest` and `:latest-dev` tags are an accepted trade-off
for homelab iteration speed. Determinism for the *bootable* image is
recovered at BIB time via the source-digest marker (ADR-adjacent: see
`bib-build-and-push.yaml`). Pod images stay on tags.

### MinIO non-use

MinIO went source-restricted in 2024. The CNCF-aligned replacement for
artifact storage is the OCI Artifact spec backed by zot (CNCF Sandbox),
already on ghost. If artifact persistence is needed, use `oras push` to
zot, not S3-compatible blob storage.

### Duplication over parameterization

Two near-clone WorkflowTemplates (Bluefin/Flatcar provisioning,
Bluefin/Flatcar teardown) are simpler than one parameterized template with
Argo `when:` / `if:` conditionals. Keep them as separate files. The
maintenance cost of duplication is lower than the cognitive cost of
conditional logic across YAML, especially for autonomous agents reading
the templates.

### Out of scope (do not re-propose without a new ADR)

- MinIO or any S3-compatible artifact store
- Kyverno / OPA Gatekeeper / admission webhooks
- Conftest / Rego policy framework
- Cosign signature verification, SBOM generation, Rekor / sigstore
- OpenTelemetry tracing **deployment** (host collector exists; use it)
- App-of-apps + Kustomize overlays beyond the two existing Applications
- External Secrets Operator + Vault
- Argo Events controllers + GitHub webhook trigger
- Default-deny NetworkPolicy
- `.github/workflows/` CI
- Parameterized Bluefin/Flatcar WorkflowTemplate collapse
- Multi-node HA for results storage

If a future requirement justifies one of these, that requires ADR-0002 —
never a silent re-introduction.

## Consequences

- Future agents have a one-line check for "is this proposal scoped to this
  lab?": run it through the controller-acceptance rule and the out-of-scope
  list.
- When the lab does grow (≥3 nodes, multi-user, internet-exposed), this ADR
  must be revised — every accepted trade-off becomes a migration item.
