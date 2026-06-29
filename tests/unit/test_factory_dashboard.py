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
    assert len(history['rollups']) == 7


def test_dashboard_data_files_still_exist():
    assert (ROOT / 'docs/data/factory-stats.json').exists()
    assert (ROOT / 'docs/screenshots/bluefin-testing-smoke-latest.png').exists()
