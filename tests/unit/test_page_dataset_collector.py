from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/generate_page_datasets.py'


def load_module():
    spec = importlib.util.spec_from_file_location('generate_page_datasets', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upstream_dataset_derives_required_families(monkeypatch):
    module = load_module()

    # Monkeypatch load_json to intercept factory-stats.json and make bluefin-testing available
    orig_load_json = module.load_json
    def mock_load_json(path):
        if Path(path).name == 'factory-stats.json':
            data = orig_load_json(path)
            # Restore the 8 lanes to their expected available timestamps for test determinism
            if 'factory' in data and 'images' in data['factory']:
                images = data['factory']['images']
                for variant in ['bluefin', 'bluefin-lts', 'aurora', 'bazzite']:
                    if variant in images:
                        images[variant]['stable_seen_at'] = '2026-06-28T16:10:04Z'
                        images[variant]['testing_seen_at'] = '2026-06-28T16:10:04Z'
                        images[variant]['stable_age_days'] = 1
                        images[variant]['testing_age_days'] = 1
            return data
        return orig_load_json(path)

    monkeypatch.setattr(module, 'load_json', mock_load_json)

    dataset = module.build_upstream_status(ROOT, '2026-06-29T19:22:22Z')

    assert dataset['schema_version'] == 'v1'
    assert dataset['_meta']['page'] == 'upstream'
    assert dataset['_meta']['starter_artifact'] is False
    assert {group['id'] for group in dataset['groups']} == {
        'gnome-os',
        'fedora-bootc',
        'projectbluefin',
        'ublue',
    }

    rows = {row['id']: row for row in dataset['rows']}
    assert rows['bluefin-testing']['state'] == 'available'
    assert rows['bluefin-testing']['published_at'] == '2026-06-28T16:10:04Z'
    assert rows['dakota-testing']['state'] == 'unavailable'
    assert rows['gnomeos-nightly']['state'] == 'unavailable'
    assert rows['fedora-bootc-stable']['source_url'].endswith(
        '/manifests/image-poll-fedora-bootc-latest.yaml'
    )

    metrics = {metric['id']: metric for metric in dataset['summary_metrics']}
    assert metrics['tracked_upstream_lanes']['value'] == 12
    assert metrics['lanes_with_release_data']['value'] == 8
    assert metrics['lanes_without_release_data']['value'] == 4
    assert all(metric['collected_at'] == '2026-06-29T19:22:22Z' for metric in dataset['summary_metrics'])


def test_tests_matrix_derives_rows_from_surface_and_results():
    module = load_module()

    dataset = module.build_tests_matrix(ROOT, '2026-06-29T19:22:22Z')

    assert dataset['schema_version'] == 'v1'
    assert dataset['_meta']['page'] == 'tests'
    assert dataset['_meta']['starter_artifact'] is False
    assert len(dataset['rows']) == 22

    metrics = {metric['id']: metric for metric in dataset['summary_metrics']}
    assert metrics['published_matrix_rows']['value'] == 22
    assert metrics['rows_with_completed_runs']['value'] == 7
    assert metrics['rows_waiting_for_results']['value'] == 15

    rows = {row['id']: row for row in dataset['rows']}
    assert rows['bluefin-testing-developer']['state'] == 'available'
    assert rows['bluefin-testing-developer']['pass_rate'] == 100.0
    assert rows['bluefin-testing-developer']['history_points'] == 5
    assert rows['bluefin-testing-smoke']['state'] == 'available'
    assert rows['bluefin-testing-smoke']['pass_rate'] == 87.59
    assert rows['aurora-testing-smoke']['state'] == 'unavailable'
    assert rows['aurora-testing-smoke']['state_reason']
    assert rows['dakota-testing-smoke']['screenshot_url'].endswith(
        '/screenshots/dakota-testing-smoke-latest.png'
    )


def test_applications_matrix_keeps_bazaar_fallbacks_explicit():
    module = load_module()

    dataset = module.build_applications_matrix(ROOT, '2026-06-29T19:22:22Z')

    assert dataset['schema_version'] == 'v1'
    assert dataset['_meta']['page'] == 'applications'
    assert dataset['_meta']['starter_artifact'] is False
    assert [app['id'] for app in dataset['applications']] == ['bazaar', 'firefox']

    metrics = {metric['id']: metric for metric in dataset['summary_metrics']}
    assert metrics['tracked_applications']['value'] == 2
    assert metrics['application_rows']['value'] == 10
    assert metrics['rows_with_primary_app_results']['value'] == 6
    assert metrics['rows_with_fallback_signals']['value'] == 1

    rows = {row['id']: row for row in dataset['rows']}
    bluefin = rows['bazaar-bluefin-testing']
    assert bluefin['state'] == 'available'
    assert bluefin['fallback_signal_count'] == 1
    assert len(bluefin['fallback_signals']) == 1
    assert bluefin['fallback_signals'][0]['state'] == 'unavailable'
    assert bluefin['fallback_signals'][0]['matched_scenarios'] == [
        'Bazaar flatpak preinstall file is present',
        'bazaar user service is available',
    ]
    assert rows['bazaar-dakota-testing']['fallback_signal_count'] == 0
    assert rows['bazaar-aurora-testing']['state'] == 'unavailable'
    assert rows['firefox-bluefin-testing']['state'] == 'available'
    assert rows['firefox-bluefin-testing']['fallback_signal_count'] == 0
