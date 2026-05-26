# Testing Lab Copilot Instructions

Use [`../AGENTS.md`](../AGENTS.md) for repo policy and architecture, and use [`../docs/agent-cheatsheet.md`](../docs/agent-cheatsheet.md) for the canonical command reference.

Keep only these repo-specific inline reminders:

- Use `just` entrypoints first; do not duplicate command tables here.
- No SSH to ghost or exo-1.
- No `kubectl apply` for `argo/workflow-templates/` or `manifests/`; edit git-tracked YAML and let ArgoCD reconcile it.
- Prefer titan workflows for test-only iteration and fresh-VM workflows for image or golden-disk validation.
- PR queue work is only complete with real lab evidence in [`../docs/vanguard-report-template.md`](../docs/vanguard-report-template.md).
- Titan `authorized_keys` refresh is human-gated; if titan SSH breaks after key rotation, file an issue for a human operator to run the manual key-injection procedure.
