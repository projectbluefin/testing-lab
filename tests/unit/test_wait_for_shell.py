import sys
from unittest.mock import MagicMock, patch
import pytest

from tests.shared.wait_for_shell import wait_for_shell


@patch("tests.shared.wait_for_shell.subprocess.run")
@patch("tests.shared.wait_for_shell.time.sleep")
@patch("tests.shared.wait_for_shell.dtree")
def test_wait_for_shell_success(mock_dtree, mock_sleep, mock_run):
    # 1. Mock subprocess.run to simulate gdbus returning (true, ...)
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "(true, true)"
    mock_run.return_value = mock_res

    # 2. Mock dogtail components
    mock_app = MagicMock()
    mock_panel = MagicMock()
    mock_panel.roleName = "panel"
    mock_toggle = MagicMock()
    mock_toggle.name = "Activities"
    mock_toggle.roleName = "toggle button"
    
    mock_panel.findChildren.return_value = [mock_toggle]
    mock_app.findChildren.return_value = [mock_panel]
    mock_dtree.root.application.return_value = mock_app

    # 3. Call function with 1 attempt
    assert wait_for_shell(attempts=1, sleep_time=0) is True
    assert mock_run.call_count == 1


@patch("tests.shared.wait_for_shell.subprocess.run")
@patch("tests.shared.wait_for_shell.time.sleep")
@patch("tests.shared.wait_for_shell.dtree")
def test_wait_for_shell_failure_gdbus(mock_dtree, mock_sleep, mock_run):
    # Simulate gdbus failure
    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stderr = "gdbus connection refused"
    mock_run.return_value = mock_res

    assert wait_for_shell(attempts=2, sleep_time=0) is False
    assert mock_run.call_count == 2
    assert mock_sleep.call_count == 2
