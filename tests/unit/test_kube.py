import pytest
import json
from unittest.mock import MagicMock, patch
import subprocess

from tests.service_catalog.shared.kube import (
    run_kubectl,
    require_kubectl,
    get_pods_json,
    first_pod_name,
)


@patch("tests.service_catalog.shared.kube.subprocess.run")
def test_run_kubectl(mock_run):
    mock_res = MagicMock()
    mock_run.return_value = mock_res
    
    run_kubectl("get", "pods")
    mock_run.assert_called_once_with(
        ["kubectl", "get", "pods"],
        capture_output=True,
        text=True,
        timeout=120,
    )


@patch("tests.service_catalog.shared.kube.subprocess.run")
def test_require_kubectl_success(mock_run):
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "pod-output"
    mock_run.return_value = mock_res
    
    res = require_kubectl("get", "pods")
    assert res == "pod-output"


@patch("tests.service_catalog.shared.kube.subprocess.run")
def test_require_kubectl_failure(mock_run):
    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stdout = "some stdout"
    mock_res.stderr = "error message"
    mock_run.return_value = mock_res
    
    with pytest.raises(AssertionError) as exc_info:
        require_kubectl("get", "pods")
    assert "kubectl get pods failed" in str(exc_info.value)
    assert "error message" in str(exc_info.value)


@patch("tests.service_catalog.shared.kube.require_kubectl")
def test_get_pods_json(mock_require):
    mock_require.return_value = json.dumps({"items": [{"metadata": {"name": "test-pod"}}]})
    
    data = get_pods_json()
    assert data["items"][0]["metadata"]["name"] == "test-pod"


@patch("tests.service_catalog.shared.kube.get_pods_json")
def test_first_pod_name_success(mock_get_json):
    mock_get_json.return_value = {"items": [{"metadata": {"name": "pod-123"}}]}
    
    assert first_pod_name() == "pod-123"


@patch("tests.service_catalog.shared.kube.get_pods_json")
def test_first_pod_name_empty(mock_get_json):
    mock_get_json.return_value = {"items": []}
    
    with pytest.raises(AssertionError) as exc_info:
        first_pod_name()
    assert "No service-catalog pod found" in str(exc_info.value)
