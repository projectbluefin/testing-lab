---
name: ci-tooling
description: >
  GitHub Actions workflow authoring and debugging for testing-lab dashboards and
  automation. Use when changing .github/workflows/, troubleshooting stale Pages
  data, or wiring CI jobs that need private-cluster data.
metadata:
  context7-sources:
    - /websites/github_en_actions
---

# CI Tooling — GitHub Actions in testing-lab

## When to Use

- Editing `.github/workflows/*.yml`
- Dashboard data is stale, empty, or inconsistent with cluster state
- A workflow needs homelab/private network data
- GitHub Pages shows JSON/JS fetch errors after CI changes

## When NOT to Use

- Argo WorkflowTemplate logic in `argo/workflow-templates/` (use `argo-workflows.md`)
- ArgoCD reconciliation policy work (use `gitops-argocd.md`)
- VM lifecycle/scheduling behavior (use `kubevirt-vms.md`)

## Core Process

1. Confirm runner network model first: GitHub-hosted runners have public internet by default; private network access requires an overlay/VPN setup or a self-hosted runner.
2. For dashboard stats jobs, treat private-cluster snapshots as optional: when live fetch fails, preserve last known live values and set explicit freshness/state flags.
3. Never wipe `recent_runs` or `factory.cluster.nodes` just because a hosted runner cannot reach `192.168.x.x`; preserve and annotate.
4. Add explicit metadata in JSON (`_meta.live_snapshot_ok`, `_meta.refreshed_at`) so UI can show freshness honestly.
5. For GitHub Pages sites, verify the Pages source and build state before assuming a push is live:
   - `gh api repos/<owner>/<repo>/pages --jq '.source'`
   - `gh api repos/<owner>/<repo>/pages/builds/latest --jq '.status'`
   - Pages can legitimately stay in `building` for a while even after the commit is on `main`.
6. For browser-side `fetch`, avoid custom request headers that force CORS preflight against GitHub APIs (for example `Cache-Control` request headers).
7. After push, validate production Pages with a real browser render (not raw HTML fetch only): confirm no loading placeholders and key sections render.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "If live fetch fails, clearing fields is safer." | Clearing makes the dashboard lie by omission; preserve last known and mark freshness/state. |
| "Custom `Cache-Control` headers are harmless." | They can trigger CORS preflight and block cross-origin GitHub API fetches. |
| "Raw JSON looks right, so UI is fine." | JS/runtime errors can still break rendering; always validate in a browser. |

## Red Flags

- Workflow writes empty arrays for cluster/runs after transient network failure
- Dashboard shows `Loading…` or stale placeholder rows for long periods
- Browser console logs CORS preflight failures to GitHub API endpoints
- CI changes are declared fixed without checking production Pages render

## Verification

- [ ] Workflow logic preserves last known live snapshot when private endpoint fetch fails
- [ ] `_meta.live_snapshot_ok` and `_meta.refreshed_at` are present and updated
- [ ] GitHub Pages source/build state was checked before declaring a site live
- [ ] Browser fetch code avoids unnecessary custom headers that trigger preflight
- [ ] Production `https://projectbluefin.github.io/testing-lab/` renders with real table/cluster content (no loading placeholders)
- [ ] Render validation includes a real browser run (headless is fine) and captures evidence
