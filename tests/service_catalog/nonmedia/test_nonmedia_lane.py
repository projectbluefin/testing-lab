"""
Non-media (OpenPrinting/CUPS) service-catalog lane test suite.

Validates the base homelab workload contract for network-only print services:
  1. Workload deploys and becomes ready within timeout.
  2. Config PVC is present and Bound.
  3. IPP port 631 is reachable at the service address.
  4. Required environment variables are injected.
  5. A rollout restart produces a fresh Ready pod that remains reachable.
  6. Observability: lane/env metadata is available in pod labels.
  7. Namespace and fixture are cleaned up by the workflow teardown step.

Out-of-scope for this lane (see issues #67 and #63):
  - USB printer device hostPath passthrough
  - avahi mDNS / LAN discovery
  - GPU or hardware transcoding
"""

from __future__ import annotations

import os
import urllib.request

import pytest

from tests.service_catalog.shared.kube import (
    NAMESPACE,
    APP_LABEL,
    SERVICE_NAME,
    TEST_LANE,
    RESULTS_DIR,
    run_kubectl,
    require_kubectl,
    write_artifact,
    get_pods_json,
    first_pod_name,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IPP_PORT = int(os.environ.get("TEST_IPP_PORT", "631"))
_ROLLOUT_TIMEOUT = "300s"


def _http_get_ipp() -> str:
    url = f"http://{SERVICE_NAME}.{NAMESPACE}.svc.cluster.local:{_IPP_PORT}/"
    with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310
        body = response.read().decode()
    write_artifact(f"{TEST_LANE}-ipp-body.txt", body)
    return body


def _rollout_restart() -> None:
    restart = run_kubectl(
        "rollout", "restart", f"deployment/{SERVICE_NAME}", "-n", NAMESPACE
    )
    assert restart.returncode == 0, restart.stdout + restart.stderr
    write_artifact(f"{TEST_LANE}-restart.txt", restart.stdout + restart.stderr)
    status = run_kubectl(
        "rollout",
        "status",
        f"deployment/{SERVICE_NAME}",
        "-n",
        NAMESPACE,
        f"--timeout={_ROLLOUT_TIMEOUT}",
    )
    assert status.returncode == 0, status.stdout + status.stderr
    write_artifact(f"{TEST_LANE}-rollout-status.txt", status.stdout + status.stderr)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestNonmediaLaneDeployment:
    """Validate the base workload contract for network-only print services."""

    def test_namespace_exists(self):
        """Namespace created by the workflow's create-namespace step must exist."""
        out = require_kubectl("get", "namespace", NAMESPACE, "-o", "name")
        assert NAMESPACE in out

    def test_deployment_exists(self):
        """Deployment fixture applied by deploy-fixture step must be present."""
        out = require_kubectl(
            "get", "deployment", SERVICE_NAME, "-n", NAMESPACE, "-o", "name"
        )
        assert SERVICE_NAME in out

    def test_deployment_ready(self):
        """All desired replicas must reach Ready state before the test window."""
        out = require_kubectl(
            "rollout",
            "status",
            f"deployment/{SERVICE_NAME}",
            "-n",
            NAMESPACE,
            "--timeout=300s",
        )
        write_artifact(f"{TEST_LANE}-deploy-status.txt", out)
        assert "successfully rolled out" in out

    def test_pod_running(self):
        """At least one pod must be in Running phase."""
        data = get_pods_json()
        items = data.get("items", [])
        assert items, "No pods found for the nonmedia-service workload"
        phases = {p["status"].get("phase") for p in items}
        assert "Running" in phases, f"No Running pod; phases observed: {phases}"

    def test_pod_labels_contain_app(self):
        """Pod must carry the app= label used by the lane selector."""
        pod_name = first_pod_name()
        out = require_kubectl(
            "get", "pod", pod_name, "-n", NAMESPACE, "-o",
            "jsonpath={.metadata.labels.app}"
        )
        assert out.strip() == SERVICE_NAME, (
            f"Expected label app={SERVICE_NAME}, got: {out.strip()!r}"
        )

    def test_pvc_bound(self):
        """Config PVC must be Bound before the fixture is considered healthy."""
        pvc_name = f"{SERVICE_NAME}-config"
        out = require_kubectl(
            "get", "pvc", pvc_name, "-n", NAMESPACE, "-o",
            "jsonpath={.status.phase}"
        )
        write_artifact(f"{TEST_LANE}-pvc-phase.txt", out)
        assert out.strip() == "Bound", f"PVC {pvc_name} is not Bound: {out.strip()!r}"

    def test_service_exists(self):
        """A Kubernetes Service exposing port 631 must exist in the namespace."""
        out = require_kubectl(
            "get", "service", SERVICE_NAME, "-n", NAMESPACE, "-o", "name"
        )
        assert SERVICE_NAME in out

    def test_service_port_631(self):
        """Service spec must expose the IPP-standard port 631."""
        out = require_kubectl(
            "get", "service", SERVICE_NAME, "-n", NAMESPACE, "-o",
            "jsonpath={.spec.ports[*].port}"
        )
        ports = [int(p) for p in out.split()]
        assert _IPP_PORT in ports, (
            f"Expected port {_IPP_PORT} in service spec; found: {ports}"
        )

    def test_ipp_port_reachable(self):
        """HTTP GET on port 631 at the cluster-internal service address must succeed."""
        body = _http_get_ipp()
        assert body is not None and len(body) >= 0  # any HTTP 2xx is sufficient

    def test_env_puid_injected(self):
        """PUID env var must be present in the running container."""
        pod_name = first_pod_name()
        out = require_kubectl(
            "exec", pod_name, "-n", NAMESPACE, "--",
            "sh", "-c", "echo $PUID"
        )
        assert out.strip() != "", "PUID env var is not set in the container"

    def test_env_pgid_injected(self):
        """PGID env var must be present in the running container."""
        pod_name = first_pod_name()
        out = require_kubectl(
            "exec", pod_name, "-n", NAMESPACE, "--",
            "sh", "-c", "echo $PGID"
        )
        assert out.strip() != "", "PGID env var is not set in the container"

    def test_env_tz_injected(self):
        """TZ env var must be present in the running container."""
        pod_name = first_pod_name()
        out = require_kubectl(
            "exec", pod_name, "-n", NAMESPACE, "--",
            "sh", "-c", "echo $TZ"
        )
        assert out.strip() != "", "TZ env var is not set in the container"

    def test_rollout_persistence(self):
        """After a rollout restart the deployment must return to Ready and remain reachable."""
        _rollout_restart()
        body = _http_get_ipp()
        assert body is not None

    def test_observability_artifact_written(self):
        """Lane must emit at least one result artifact that an operator can inspect."""
        artifacts = list(RESULTS_DIR.iterdir())
        assert artifacts, (
            f"No artifacts written to {RESULTS_DIR}; lane produced no observable output"
        )

    @pytest.mark.skip(reason="USB printer device access requires hardware fixture — tracked in issue #67")
    def test_usb_printer_device_passthrough(self):
        """USB printer hostPath passthrough: deferred to issue #67 (print-device lane)."""

    @pytest.mark.skip(reason="avahi/mDNS LAN discovery requires hardware fixture — tracked in issue #67")
    def test_avahi_lan_discovery(self):
        """avahi mDNS LAN discovery: deferred to issue #67 (print-device lane)."""
