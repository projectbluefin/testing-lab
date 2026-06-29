#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


REPO_SLUG = 'projectbluefin/testing-lab'
PAGES_BASE = 'https://projectbluefin.github.io/testing-lab'


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_json(path: Path):
    with path.open() as handle:
        return json.load(handle)


def repo_blob_url(relative_path: str) -> str:
    return f'https://github.com/{REPO_SLUG}/blob/main/{relative_path}'


def pages_url(relative_path: str) -> str:
    return f'{PAGES_BASE}/{relative_path.lstrip("/")}'


def normalize_result_source_url(relative_path: str, result: dict) -> str:
    return result.get('source_url') or repo_blob_url(f'docs/{relative_path}')


def row_state(last_run: str | None) -> tuple[str, str | None]:
    if last_run:
        return 'available', None
    return 'unavailable', 'Result file exists, but no completed run is published for this matrix cell yet.'


def iter_surface_cells(root: Path):
    surface = load_json(root / 'docs/data/test-surface.json')
    for cell in surface.get('surface', []):
        yield cell


def load_results_by_relative_path(root: Path) -> dict[str, dict]:
    results = {}
    for result_path in (root / 'docs/results').glob('*.json'):
        relative_path = result_path.relative_to(root / 'docs').as_posix()
        results[relative_path] = load_json(result_path)
    return results


def build_upstream_status(root: Path, collected_at: str) -> dict:
    stats = load_json(root / 'docs/data/factory-stats.json')
    publishers = load_json(root / 'docs/data/variant-publishers.json')
    images = ((stats.get('factory') or {}).get('images') or {})

    groups = [
        {
            'id': 'gnome-os',
            'label': 'GNOME OS',
            'description': 'GNOME OS upstream images used for lab expansion and comparison.',
            'source_url': repo_blob_url('argo/workflow-templates/provision-gnomeos-vm.yaml'),
            'collected_at': collected_at,
            'derivation': 'Known upstream scope from the GNOME OS provisioning workflow tracked in git.',
        },
        {
            'id': 'fedora-bootc',
            'label': 'Fedora bootc',
            'description': 'Fedora bootc upstream streams with digest pollers tracked in git.',
            'source_url': repo_blob_url('manifests/image-poll-fedora-bootc-latest.yaml'),
            'collected_at': collected_at,
            'derivation': 'Known upstream scope from Fedora bootc image poller manifests tracked in git.',
        },
        {
            'id': 'projectbluefin',
            'label': 'Project Bluefin variants',
            'description': 'Bluefin family images published by projectbluefin.',
            'source_url': repo_blob_url('docs/data/variant-publishers.json'),
            'collected_at': collected_at,
            'derivation': 'Derived from variant publisher mapping already published in docs/data.',
        },
        {
            'id': 'ublue',
            'label': 'uBlue derivatives',
            'description': 'Derivative desktop images published by ublue-os.',
            'source_url': repo_blob_url('docs/data/variant-publishers.json'),
            'collected_at': collected_at,
            'derivation': 'Derived from variant publisher mapping already published in docs/data.',
        },
    ]

    rows = []
    for variant, details in (publishers.get('variants') or {}).items():
        org = details.get('org')
        if org not in {'projectbluefin', 'ublue-os'}:
            continue
        group = 'projectbluefin' if org == 'projectbluefin' else 'ublue'
        repo = details.get('publisher_repo')
        releases_url = f'https://github.com/{repo}/releases' if repo else repo_blob_url('docs/data/variant-publishers.json')
        image_summary = images.get(variant, {})
        for branch in details.get('branches') or []:
            row_id = f'{variant}-{branch}'
            published_at = image_summary.get(f'{branch}_seen_at')
            freshness_age_days = image_summary.get(f'{branch}_age_days')
            state = 'available' if published_at else 'unavailable'
            state_reason = None if published_at else 'No published release timestamp is present in docs/data/factory-stats.json for this lane.'
            rows.append(
                {
                    'id': row_id,
                    'group': group,
                    'variant': variant,
                    'display_name': f'{variant} {branch}',
                    'publisher_repo': repo,
                    'org': org,
                    'branch': branch,
                    'published_at': published_at,
                    'freshness_age_days': freshness_age_days,
                    'open_prs': None,
                    'state': state,
                    'state_reason': state_reason,
                    'source_url': image_summary.get(f'{branch}_source_url') or releases_url,
                    'collected_at': collected_at,
                    'derivation': (
                        f'Join docs/data/variant-publishers.json branches with '
                        f'docs/data/factory-stats.json factory.images.{variant}.{branch}_seen_at/{branch}_age_days.'
                    ),
                }
            )

    rows.extend(
        [
            {
                'id': 'gnomeos-nightly',
                'group': 'gnome-os',
                'variant': 'gnomeos',
                'display_name': 'GNOME OS nightly',
                'publisher_repo': None,
                'org': None,
                'branch': 'nightly',
                'published_at': None,
                'freshness_age_days': None,
                'open_prs': None,
                'state': 'unavailable',
                'state_reason': 'Known GNOME OS workflow exists, but no repo-owned artifact publishes a nightly release timestamp yet.',
                'source_url': repo_blob_url('argo/workflow-templates/provision-gnomeos-vm.yaml'),
                'collected_at': collected_at,
                'derivation': 'Scope placeholder derived from the existing GNOME OS provisioning workflow tracked in git.',
            },
            {
                'id': 'fedora-bootc-stable',
                'group': 'fedora-bootc',
                'variant': 'fedora-bootc',
                'display_name': 'Fedora bootc stable',
                'publisher_repo': 'fedora/fedora-bootc',
                'org': 'fedora',
                'branch': 'stable',
                'published_at': None,
                'freshness_age_days': None,
                'open_prs': None,
                'state': 'unavailable',
                'state_reason': 'Known Fedora bootc poller exists, but no repo-owned artifact publishes a stable release timestamp yet.',
                'source_url': repo_blob_url('manifests/image-poll-fedora-bootc-latest.yaml'),
                'collected_at': collected_at,
                'derivation': 'Map the git-tracked latest poller manifest to the stable Fedora bootc lane until repo data publishes release timestamps.',
            },
            {
                'id': 'fedora-bootc-testing',
                'group': 'fedora-bootc',
                'variant': 'fedora-bootc',
                'display_name': 'Fedora bootc testing',
                'publisher_repo': 'fedora/fedora-bootc',
                'org': 'fedora',
                'branch': 'testing',
                'published_at': None,
                'freshness_age_days': None,
                'open_prs': None,
                'state': 'unavailable',
                'state_reason': 'Known Fedora bootc poller exists, but no repo-owned artifact publishes a testing release timestamp yet.',
                'source_url': repo_blob_url('manifests/image-poll-fedora-bootc-rawhide.yaml'),
                'collected_at': collected_at,
                'derivation': 'Map the git-tracked rawhide poller manifest to the testing Fedora bootc lane until repo data publishes release timestamps.',
            },
        ]
    )

    release_rows = [row for row in rows if row.get('published_at')]
    unavailable_rows = [row for row in rows if row.get('state') == 'unavailable']

    return {
        'schema_version': 'v1',
        '_meta': {
            'page': 'upstream',
            'description': 'Collector-derived contract for the multipage upstream status view.',
            'generated_at': collected_at,
            'starter_artifact': False,
            'status': 'partial' if unavailable_rows else 'ready',
        },
        'summary_metrics': [
            {
                'id': 'tracked_upstream_lanes',
                'label': 'Tracked upstream lanes',
                'value': len(rows),
                'unit': 'count',
                'state': 'available',
                'state_reason': None,
                'source_url': repo_blob_url('docs/data/variant-publishers.json'),
                'collected_at': collected_at,
                'derivation': 'Count concrete upstream rows assembled from publisher mappings and known workflow placeholders.',
            },
            {
                'id': 'lanes_with_release_data',
                'label': 'Lanes with published release data',
                'value': len(release_rows),
                'unit': 'count',
                'state': 'available',
                'state_reason': None,
                'source_url': repo_blob_url('docs/data/factory-stats.json'),
                'collected_at': collected_at,
                'derivation': 'Count upstream rows whose published_at is present in docs/data/factory-stats.json.',
            },
            {
                'id': 'lanes_without_release_data',
                'label': 'Lanes awaiting collectors',
                'value': len(unavailable_rows),
                'unit': 'count',
                'state': 'available',
                'state_reason': None,
                'source_url': repo_blob_url('docs/data/page-contracts.md'),
                'collected_at': collected_at,
                'derivation': 'Count upstream rows still marked unavailable after deriving from repo-owned inputs.',
            },
        ],
        'groups': groups,
        'rows': rows,
    }


def build_tests_matrix(root: Path, collected_at: str) -> dict:
    results_by_path = load_results_by_relative_path(root)
    rows = []
    variants = set()
    branches = set()
    suites = set()

    for cell in iter_surface_cells(root):
        variant = cell['variant']
        branch = cell['branch']
        suite = cell['suite']
        relative_results_path = cell['results_path']
        result = results_by_path.get(relative_results_path, {})
        last_run = result.get('last_run')
        state, state_reason = row_state(last_run)
        scenarios_total = result.get('scenarios', 0)
        scenarios_failed = result.get('failed', 0)
        pass_rate = None
        if scenarios_total:
            pass_rate = round(((scenarios_total - scenarios_failed) / scenarios_total) * 100, 2)
        screenshot_path = cell.get('screenshot_path')
        screenshot_url = result.get('screenshot_url')
        if not screenshot_url and screenshot_path:
            screenshot_url = pages_url(screenshot_path)

        rows.append(
            {
                'id': f'{variant}-{branch}-{suite}',
                'variant': variant,
                'branch': branch,
                'suite': suite,
                'result_status': result.get('status', 'missing'),
                'last_run': last_run,
                'workflow_name': result.get('workflow_name'),
                'scenarios_total': scenarios_total,
                'scenarios_failed': scenarios_failed,
                'pass_rate': pass_rate,
                'history_points': len(result.get('history', [])),
                'results_path': relative_results_path,
                'screenshot_path': screenshot_path,
                'screenshot_url': screenshot_url,
                'state': state,
                'state_reason': state_reason,
                'source_url': normalize_result_source_url(relative_results_path, result),
                'collected_at': collected_at,
                'derivation': (
                    f'Join docs/data/test-surface.json row with docs/{relative_results_path}; '
                    'compute pass_rate when scenarios_total > 0.'
                ),
            }
        )
        variants.add(variant)
        branches.add(branch)
        suites.add(suite)

    completed_rows = [row for row in rows if row['state'] == 'available']
    unavailable_rows = [row for row in rows if row['state'] == 'unavailable']

    return {
        'schema_version': 'v1',
        '_meta': {
            'page': 'tests',
            'description': 'Collector-derived contract for the multipage tests matrix view.',
            'generated_at': collected_at,
            'starter_artifact': False,
            'status': 'partial' if unavailable_rows else 'ready',
        },
        'summary_metrics': [
            {
                'id': 'published_matrix_rows',
                'label': 'Published matrix rows',
                'value': len(rows),
                'unit': 'count',
                'state': 'available',
                'state_reason': None,
                'source_url': repo_blob_url('docs/data/test-surface.json'),
                'collected_at': collected_at,
                'derivation': 'Count rows in docs/data/test-surface.json surface[].',
            },
            {
                'id': 'rows_with_completed_runs',
                'label': 'Rows with completed runs',
                'value': len(completed_rows),
                'unit': 'count',
                'state': 'available',
                'state_reason': None,
                'source_url': repo_blob_url('docs/results'),
                'collected_at': collected_at,
                'derivation': 'Count matrix rows whose joined docs/results/*.json file has last_run set.',
            },
            {
                'id': 'rows_waiting_for_results',
                'label': 'Rows waiting for results',
                'value': len(unavailable_rows),
                'unit': 'count',
                'state': 'available',
                'state_reason': None,
                'source_url': repo_blob_url('docs/data/test-surface.json'),
                'collected_at': collected_at,
                'derivation': 'Count matrix rows still marked unavailable after joining published results.',
            },
        ],
        'dimensions': {
            'variants': sorted(variants),
            'branches': sorted(branches),
            'suites': sorted(suites),
        },
        'rows': rows,
    }


def bazaar_fallback_signals(relative_results_path: str, result: dict, collected_at: str) -> list[dict]:
    matches = [scenario for scenario in result.get('failed_scenarios', []) if 'bazaar' in scenario.lower()]
    if not matches:
        return []
    return [
        {
            'suite': result.get('suite'),
            'matched_scenarios': matches,
            'status': result.get('status'),
            'last_run': result.get('last_run'),
            'workflow_name': result.get('workflow_name'),
            'state': 'unavailable',
            'state_reason': 'Coarse fallback only: Bazaar evidence comes from scenario-name substring matching in a non-application suite.',
            'source_url': normalize_result_source_url(relative_results_path, result),
            'collected_at': collected_at,
            'derivation': f'Case-insensitive /bazaar/ match against failed_scenarios in docs/{relative_results_path}.',
        }
    ]


def build_applications_matrix(root: Path, collected_at: str) -> dict:
    results_by_path = load_results_by_relative_path(root)
    software_cells = [cell for cell in iter_surface_cells(root) if cell['suite'] == 'software']
    rows = []

    applications = [
        {
            'id': 'bazaar',
            'display_name': 'Bazaar',
            'scope': 'v1',
            'primary_suite': 'software',
            'fallback_suites': ['common'],
            'state': 'available',
            'state_reason': None,
            'source_url': repo_blob_url('docs/data/page-contracts.md'),
            'collected_at': collected_at,
            'derivation': 'Catalog entry from the page contract: applications v1 includes Bazaar and Firefox.',
        },
        {
            'id': 'firefox',
            'display_name': 'Firefox',
            'scope': 'v1',
            'primary_suite': 'software',
            'fallback_suites': [],
            'state': 'available',
            'state_reason': None,
            'source_url': repo_blob_url('docs/data/page-contracts.md'),
            'collected_at': collected_at,
            'derivation': 'Catalog entry from the page contract: applications v1 includes Bazaar and Firefox.',
        },
    ]

    rows_with_primary_results = 0
    rows_with_fallbacks = 0
    for application in applications:
        app_id = application['id']
        app_name = application['display_name']
        for cell in software_cells:
            variant = cell['variant']
            branch = cell['branch']
            relative_results_path = cell['results_path']
            primary_result = results_by_path.get(relative_results_path, {})
            primary_last_run = primary_result.get('last_run')
            if primary_last_run:
                rows_with_primary_results += 1

            fallback_signals = []
            if app_id == 'bazaar':
                fallback_relative_path = f'results/{variant}-{branch}-common.json'
                fallback_result = results_by_path.get(fallback_relative_path, {})
                fallback_signals = bazaar_fallback_signals(fallback_relative_path, fallback_result, collected_at)
            if fallback_signals:
                rows_with_fallbacks += 1

            state = 'available' if primary_last_run else 'unavailable'
            state_reason = None if primary_last_run else (
                f'No completed {app_name}-specific software result is published for this variant/branch; '
                'fallback signals remain coarse only.'
            )
            rows.append(
                {
                    'id': f'{app_id}-{variant}-{branch}',
                    'app_id': app_id,
                    'variant': variant,
                    'branch': branch,
                    'primary_suite': 'software',
                    'primary_result_status': primary_result.get('status', 'missing'),
                    'primary_last_run': primary_last_run,
                    'scenario_total': primary_result.get('scenarios'),
                    'scenario_failed': primary_result.get('failed'),
                    'fallback_signal_count': len(fallback_signals),
                    'fallback_signals': fallback_signals,
                    'state': state,
                    'state_reason': state_reason,
                    'source_url': normalize_result_source_url(relative_results_path, primary_result),
                    'collected_at': collected_at,
                    'derivation': (
                        f'Seed row from docs/data/test-surface.json software cells for {app_name}; '
                        f'join docs/{relative_results_path} for primary evidence.'
                        + (
                            ' Attach coarse Bazaar fallback signals from matching non-application results.'
                            if app_id == 'bazaar'
                            else ' No fallback suite is configured for Firefox yet.'
                        )
                    ),
                }
            )

    unavailable_rows = [row for row in rows if row['state'] == 'unavailable']

    return {
        'schema_version': 'v1',
        '_meta': {
            'page': 'applications',
            'description': 'Collector-derived contract for the multipage applications matrix view.',
            'generated_at': collected_at,
            'starter_artifact': False,
            'status': 'partial' if unavailable_rows else 'ready',
        },
        'summary_metrics': [
            {
                'id': 'tracked_applications',
                'label': 'Tracked applications',
                'value': len(applications),
                'unit': 'count',
                'state': 'available',
                'state_reason': None,
                'source_url': repo_blob_url('docs/data/page-contracts.md'),
                'collected_at': collected_at,
                'derivation': 'Count applications[] entries in this collector-derived artifact.',
            },
            {
                'id': 'application_rows',
                'label': 'Application matrix rows',
                'value': len(rows),
                'unit': 'count',
                'state': 'available',
                'state_reason': None,
                'source_url': repo_blob_url('docs/data/test-surface.json'),
                'collected_at': collected_at,
                'derivation': 'Count software suite rows in docs/data/test-surface.json.',
            },
            {
                'id': 'rows_with_primary_app_results',
                'label': 'Rows with primary app results',
                'value': rows_with_primary_results,
                'unit': 'count',
                'state': 'available',
                'state_reason': None,
                'source_url': repo_blob_url('docs/results'),
                'collected_at': collected_at,
                'derivation': 'Count application rows whose software suite has a completed result with last_run.',
            },
            {
                'id': 'rows_with_fallback_signals',
                'label': 'Rows with fallback Bazaar signals',
                'value': rows_with_fallbacks,
                'unit': 'count',
                'state': 'available',
                'state_reason': None,
                'source_url': repo_blob_url('docs/results/bluefin-testing-common.json'),
                'collected_at': collected_at,
                'derivation': 'Count application rows that picked up coarse Bazaar fallback signals from published non-application results.',
            },
        ],
        'applications': applications,
        'rows': rows,
    }


def write_page_datasets(root: Path, collected_at: str) -> dict[str, dict]:
    data_dir = root / 'docs/data'
    datasets = {
        'upstream-status.json': build_upstream_status(root, collected_at),
        'tests-matrix.json': build_tests_matrix(root, collected_at),
        'applications-matrix.json': build_applications_matrix(root, collected_at),
    }
    for name, payload in datasets.items():
        (data_dir / name).write_text(json.dumps(payload, indent=2) + '\n')
    return datasets


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate page-owned dashboard datasets.')
    parser.add_argument('--root', default='.', help='Repository root')
    parser.add_argument('--collected-at', default=None, help='ISO8601 timestamp override')
    args = parser.parse_args()

    root = Path(args.root).resolve()
    collected_at = args.collected_at or now_utc_iso()
    write_page_datasets(root, collected_at)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
