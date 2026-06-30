# Testing Lab Copilot Instructions

Use [`../AGENTS.md`](../AGENTS.md) for repo policy and architecture, and use [`../docs/agent-cheatsheet.md`](../docs/agent-cheatsheet.md) for the canonical command reference.

Keep only these repo-specific inline reminders:

- Use `just` entrypoints first; do not duplicate command tables here.
- No SSH to ghost or exo-1.
- No `kubectl apply` for `argo/workflow-templates/` or `manifests/`; edit git-tracked YAML and let ArgoCD reconcile it.
- All test runs use ephemeral KubeVirt VMs — no persistent titan VMs. `just list-vms` should show empty when no workflows run.
- After pushing a fix, verify the live template via `argo-mcp-get_workflow_template` before resubmitting — templates snapshot at submit time.
- For `docs/` Pages changes, wait for `gh api repos/<owner>/<repo>/pages/builds/latest --jq '.status'` to be `built` and confirm the live page shows the new HTML/JS before claiming success.
- Keep generated dashboard JSON in sync with the workflow that writes it; missing data should render an explicit unavailable state, not disappear silently.
- Wide dashboard tables belong in full-width cards; if a table has many columns, let the card span the full grid row so the columns can scroll instead of collapsing.
- Compare existing subdomains before DNS/TLS changes; keep static GitHub Pages hosts behind the established Cloudflare-proxied pattern unless GitHub cert issuance is confirmed.
- If Cloudflare fronts a Pages site, opt the dashboard entry script out of Rocket Loader with `data-cfasync="false"` and verify the live HTML preserves the raw script tag.
- PR queue work is only complete with real lab evidence.
- At end of any non-trivial session, run the self-improvement loop in `docs/skills/skill-improvement.md` and update the relevant skill file(s) with the durable pattern before handoff.
