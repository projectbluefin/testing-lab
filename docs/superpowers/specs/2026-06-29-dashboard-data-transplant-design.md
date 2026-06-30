# Dashboard Data Transplant Design

Date: 2026-06-29

## Goal
Fill the missing migrated data on the new `testing-lab` Homebrew and Adoption pages by transplanting the old `bootc-ecosystem` evidence into this repo's existing JSON-contract model.

This is a data migration, not a redesign.

## Constraints
- Keep the current Astro routes, page models, charts, and row-oriented contracts.
- Do not treat the retiring `bootc-ecosystem` website as a source of truth.
- Prefer transplanted repo-owned artifacts over new collector work for this pass.
- Keep explicit `state` / `state_reason` gaps whenever no honest in-scope mapping exists.

## Scope
### Homebrew
- Add a repo-tracked source artifact derived from the old `brewfile-stats.json`.
- Filter it to the packages and taps that matter for this factory's tracked variants.
- Aggregate that source into the existing `docs/data/homebrew-ecosystem.json` contract:
  - populate `taps[]`
  - populate per-lane `install_count` / `download_count`
  - keep per-row provenance pointing at the migrated artifact or upstream tap evidence

### Adoption
- Add repo-tracked source artifacts derived from the old `countme.json` and any transplantable registry-pull data.
- Map only in-scope tracked variants into `docs/data/adoption-metrics.json`.
- Populate lane rows when the transplanted source has a real match.
- Leave unmatched lanes explicitly unavailable instead of keeping the whole page empty.

## Mapping rules
- `bluefin`, `aurora`, and `bazzite` should inherit countme data when present in the migrated source.
- `bluefin-lts`, `dakota`, and `flatcar` remain unavailable unless the migrated source has an honest equivalent.
- Do not invent per-branch splits from distro-wide numbers. If a source is distro-level only, either:
  - apply it at the page/card level with clear derivation text, or
  - leave branch rows unavailable.
- Do not backfill `pull_count` from unrelated ecosystems or image families.

## Implementation shape
1. Commit migrated raw artifacts under `docs/data/` so the site reads repo-owned inputs.
2. Extend `scripts/generate_page_datasets.py` to join those artifacts into the existing Homebrew and Adoption contracts.
3. Preserve the current pages and tests; update only the contract expectations and page assertions that currently assume all data is unavailable.

## Success criteria
- Homebrew page stops rendering as all-unavailable when migrated Brewfile evidence exists.
- Adoption page shows partial real coverage instead of all-or-nothing emptiness.
- Every filled field has provenance.
- Every missing field stays visibly unavailable.
- No new page architecture or chart redesign is introduced in this pass.
