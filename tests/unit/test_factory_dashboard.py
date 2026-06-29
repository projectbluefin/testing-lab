from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_shell_points_at_assets():
    html = (ROOT / 'docs/index.html').read_text()
    assert 'factory-dashboard.css' in html
    assert 'factory-dashboard.js' in html
    assert 'id="factory-dashboard"' in html


def test_factory_copy_and_history_have_expected_shape():
    copy = json.loads((ROOT / 'docs/data/factory-copy.json').read_text())
    history = json.loads((ROOT / 'docs/data/factory-history.json').read_text())

    assert copy['brand']['title']
    assert len(copy['station_labels']) == 4
    assert len(copy['trust_labels']) >= 4
    assert len(copy['screenshots']) == 3
    assert history['window_days'] == 7
    assert 0 < len(history['rollups']) <= 7


def test_dashboard_data_files_still_exist():
    assert (ROOT / 'docs/data/factory-stats.json').exists()
    assert (ROOT / 'docs/screenshots/bluefin-testing-smoke-latest.png').exists()


def test_factory_public_telemetry_contract_shape():
    telemetry = json.loads((ROOT / 'docs/data/factory-telemetry.json').read_text())
    snapshot = telemetry['snapshot']
    coverage = telemetry['coverage']
    lineage = telemetry['lineage']['collector']

    assert telemetry['schema_version'] == 'v2'
    assert snapshot['generated_at']
    assert snapshot['state'] in {'fresh', 'stale', 'unknown', 'partial', 'degraded'}
    if snapshot['age_minutes'] is not None:
        assert snapshot['age_minutes'] >= 0

    assert coverage['expected_result_docs'] >= coverage['observed_result_docs']
    assert 0 <= coverage['coverage_ratio'] <= 1
    if snapshot['state'] == 'partial':
        assert coverage['coverage_ratio'] < 0.9

    assert lineage['run_url'].startswith('https://github.com/')
    assert lineage['commit_url'].startswith('https://github.com/')

    for metric in telemetry['metrics']:
        assert metric['id']
        assert metric['formula']
        assert metric['window_hours'] > 0
        assert metric['confidence'] in {'high', 'medium', 'low'}
        assert metric['state'] in {'fresh', 'stale', 'unknown', 'partial', 'degraded'}
        assert 'numerator' in metric and 'denominator' in metric
        assert metric['evidence']
        assert all(ref.get('url', '').startswith('https://') for ref in metric['evidence'])

    if telemetry.get('errors'):
        for err in telemetry['errors']:
            assert err['source']
            assert err['reason']
            assert err['effect'] == 'public telemetry downgraded to unknown/degraded'


def test_factory_copy_links_are_public():
    copy = json.loads((ROOT / 'docs/data/factory-copy.json').read_text())
    for link in copy['links']:
        assert '192.168.' not in link['href']


def test_dashboard_renderer_loads_public_telemetry():
    js = (ROOT / 'docs/assets/factory-dashboard.js').read_text()
    assert "loadJson('./data/factory-telemetry.json'" in js
    assert 'numerator' in js
    assert 'denominator' in js
    assert 'confidence' in js
    assert 'Promotion timeline' in js
    assert 'Lineage & data quality' in js


def test_dashboard_default_copy_has_no_private_links():
    js = (ROOT / 'docs/assets/factory-dashboard.js').read_text()
    assert '192.168.' not in js
