---
name: astro-dashboard-pages
description: >
  Building or revising Astro dashboard detail pages backed by repo-tracked JSON and
  browser-side charts. Use when adding docs routes like /tests, /upstream, /bluefin, or
  /applications that must render real evidence, explicit unavailable states, and
  GitHub Pages-safe static output.
metadata:
  context7-sources:
    - /withastro/docs
    - /apache/echarts-doc
    - /addyosmani/agent-skills
---

# Astro Dashboard Pages

## Overview

Astro detail pages in this repo are static evidence pages, not app shells that invent state client-side.
Read the published JSON contract at prerender time, join any linked result JSON explicitly, and pass only real fields into browser-side ECharts.

## When to Use

- Adding or revising `src/pages/*.astro` routes for dashboard detail pages
- Rendering repo-tracked JSON from `docs/data/*.json` plus linked `docs/results/*.json`
- Adding Apache ECharts visualizations to GitHub Pages-safe static output
- Wiring evidence links like `results_path`, `source_url`, screenshots, or workflow URLs into detail cards
- Splitting one dataset across multiple page routes using deterministic build-time filters

## When NOT to Use

- Overview shell work that only mounts the existing legacy dashboard JS
- Workflow/collector changes in `.github/workflows/` (use `ci-tooling.md`)
- Argo/cluster data production bugs (use the matching infra skill)

## Core Process

1. Load the page contract in the Astro frontmatter and type the fields you actually consume.
2. If rows link to per-result JSON files, join them during prerender with repo-root paths (`path.join(process.cwd(), 'docs', ...)`) so build-time resolution does not depend on `import.meta.url`.
3. Compute derived values only from published fields. Valid examples: pass rate from `scenarios` and `failed`; counts from row arrays. Invalid: guessed trendlines, synthetic timestamps, placeholder screenshots.
4. Render the static page first:
   - summary metrics
   - matrix/table view
   - detail cards with evidence links
   - explicit unavailable blocks when state is missing or pending
5. Pass chart payloads to browser code with a static `<script type="application/json">` blob or `data-*` attributes. Astro docs support both; prefer a JSON script blob for larger datasets.
6. Initialize ECharts in a colocated Astro component script:
   - `import * as echarts from 'echarts'`
   - `const chart = echarts.init(element)`
   - `chart.setOption(option)`
   - `window.addEventListener('resize', () => chart.resize())`
7. For unavailable chart inputs, do not hide the chart section. Render an explicit empty-state panel in the chart container.
8. Every detail row must link to raw evidence when present: local result JSON, GitHub source URL, screenshot URL, workflow run URL.
9. Because this repo builds Astro directly into `docs/`, scrub transient build outputs before each build (`docs/.prerender`, `docs/_astro`, generated page directories) so repeated builds do not reuse stale hashed chunks.
10. When splitting one contract across multiple pages (for example `/upstream` vs `/bluefin`), keep one source dataset and apply page-level filters in shared model code. Do not fork collector schemas just to support route splits.
11. Preserve explicit unavailable states and evidence links after filtering. Filtered pages must hide out-of-scope families, not hide missing data within in-scope families.
12. This site is served on the custom domain root (`factory.projectbluefin.io`). Keep Astro paths root-relative (`/`) and still use `import.meta.env.BASE_URL` so links/scripts stay correct if hosting topology changes.
13. Mark every browser-runtime script that must escape Cloudflare Rocket Loader with `data-cfasync="false"`, including bundled Astro page scripts, not just the legacy dashboard shell.
14. Validate with the narrowest commands that prove the page works:
   - targeted Node test covering rendered HTML
   - `npm run build`
   - run `astro check` only if it completes in this repo scope; if it OOMs, record the blocker instead of claiming it passed
15. When simulating or seeding results (such as primary application-specific results files), ensure you regenerate the core contracts using `python3 scripts/generate_page_datasets.py` so build-time Astro frontmatter picks up the changes immediately.
16. In unit tests that validate dataset collectors, mock any dependencies on dynamically-updated or live-polled files (like `factory-stats.json`) by monkeypatching the loader to keep tests completely deterministic and isolated from homelab poller updates.
17. When rendering outcomes charts or heatmaps, conditionally format labels (e.g. 'primary' vs 'fallback' vs 'none') depending on whether the primary result is completed or in a fallback-only/pending state.
18. If a hero status card is made dynamic, conditionally render it to summarize partial/full primary coverage while preserving any expected smoke-test regex assertions (e.g. `/No completed Bazaar-specific software result is published/i`) in the text output.
19. Ensure state/status calculations are resilient to all published status strings. For example, check for specific incomplete states (like 'pending' or 'missing') rather than asserting negative checks on specific completed states (like 'completed') when the true completed statuses are 'passed' or 'failed'.
20. When a page evolves from one tracked entity to multiple (for example adding Firefox alongside Bazaar), include the new dimension in chart/table labels and category keys (app + variant + branch) so rendering stays unambiguous.
21. If you reuse distro-wide or global source data across multiple branch rows, the caveat must be visible in rendered HTML, not only in JSON `derivation`. Call out scope plainly (for example global formula analytics, distro-wide snapshot, reused across branches, and snapshot window) and assert that disclosure in the built-page test.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The chart can omit unavailable rows to stay clean." | Omission hides data gaps; gray/unavailable cells are part of the truth. |
| "I can pull result JSON in the browser after load." | The page contract already lives in git; prerender it so Pages output is deterministic and linkable. |
| "One inline object literal is easier than a JSON blob." | Large payloads become brittle and hard to escape safely; use `application/json` for chart payloads. |
| "No need to link the raw result file if the summary card exists." | Summary cards are derived views; operators need the raw evidence path. |
| "I should mint a second dataset file for every new route." | Split views should reuse one contract with deterministic page-level filtering unless semantics actually diverge. |

## Red Flags

- Astro page reads `docs/results/*` through fragile `import.meta.url` math
- Repeated `npm run build` fails because `docs/.prerender` still points at old hashed chunks
- Generated HTML references a stale path prefix (for example `/testing-lab/_astro/*`) that does not match the active custom-domain root hosting
- Chart section disappears entirely when data is missing
- Detail cards show pass/fail text without raw result, source, screenshot, or workflow links
- Browser script invents fallback metrics not present in the contract
- Runtime script tags lose `data-cfasync="false"` and Cloudflare rewrites the page boot path
- Route split duplicates collector logic instead of reusing one shared model with page-level filters
- Validation mentions `astro check` as passing when it actually OOMed
- Disclosure about reused global or distro-wide values exists only in JSON fields and is absent from rendered HTML

## Verification

- [ ] Page prerender loads repo-tracked JSON at build time with repo-root paths
- [ ] Derived numbers come only from published fields in `docs/data/*` or linked `docs/results/*`
- [ ] Matrix/table view keeps unavailable states visible with the collector reason
- [ ] ECharts mounts at least one real chart from published fields and shows explicit empty states otherwise
- [ ] Detail cards link to `results_path`, `source_url`, and screenshot/workflow evidence when present
- [ ] Repeated `npm run build` runs succeed from the same worktree without stale chunk imports
- [ ] Build cleanup includes every generated route directory (for example `docs/upstream`, `docs/bluefin`, `docs/tests`, `docs/applications`)
- [ ] Built HTML prefixes Astro `_astro` assets with the active domain root path contract (currently `/_astro/*` on `factory.projectbluefin.io`)
- [ ] Runtime script tags that must execute unmodified keep `data-cfasync="false"` in built HTML
- [ ] Targeted HTML test covers chart section labels, evidence links, and unavailable copy
- [ ] Any reused global or distro-wide metrics disclose their scope in rendered HTML, and the page test asserts that disclosure
- [ ] `npm run build` succeeds for the Astro worktree
- [ ] Any failed/blocked validation step (for example `astro check` OOM) is reported explicitly, not silently dropped
