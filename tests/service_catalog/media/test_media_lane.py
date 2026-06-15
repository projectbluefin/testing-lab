"""
Media-service lane tests for the service-catalog pipeline.

Validates the base Jellyfin (linuxserver.io) media-service workload
running in Kubernetes. Proves deployment, persistence, reachability,
and teardown behaviors defined in the workload contract (#66).

GPU transcoding, device passthrough, and codec-heavy assertions are
explicitly out of scope — see #63 for the hardware-heavy follow-up.

Dependencies: #52 (storage), #53 (exposure), #59 (contract), #66 (shared contract).
"""

from __future__ import annotations

import json
import os

import pytest

from tests.service_catalog.shared.kube import (
    NAMESPACE,
    TEST_LANE,
    require_kubectl,
    run_kubectl,
    write_artifact,
)


DEPLOYMENT_NAME = "media-service"
SERVICE_NAME = "media-service"
APP_LABEL = "app.kubernetes.io/name=media-service"
LANE_LABEL = "bluefin.io/lane=svc-media"
CONFIG_PVC = "media-config"
DATA_PVC = "media-data"
CONFIG_MOUNT = "/config"
DATA_MOUNT = "/data/media"
SERVICE_PORT = 8096
CONTAINER_NAME = "jellyfin"


def _first_pod_name() -> str:
    raw = require_kubectl(
        "get", "pods", "-n", NAMESPACE, "-l", APP_LABEL, "-o", "json",
    )
    data = json.loads(raw)
    items = data.get("items", [])
    assert items, f"No pods found with label {APP_LABEL} in {NAMESPACE}"
    running = [
        p for p in items
        if p.get("status", {}).get("phase") == "Running"
    ]
    assert running, (
        f"No Running pods for {APP_LABEL}; "
        f"phases: {[p['status'].get('phase') for p in items]}"
    )
    return running[0]["metadata"]["name"]


class TestDeployment:
    """Workload deploys and reaches ready state."""

    def test_deployment_ready(self):
        raw = require_kubectl(
            "get", "deployment", DEPLOYMENT_NAME, "-n", NAMESPACE, "-o", "json",
        )
        write_artifact(f"{TEST_LANE}-deployment.json", raw)
        data = json.loads(raw)
        available = data.get("status", {}).get("availableReplicas", 0)
        assert available >= 1, (
            f"{DEPLOYMENT_NAME} has {available} available replicas, expected >= 1"
        )

    def test_pod_running(self):
        raw = require_kubectl(
            "get", "pods", "-n", NAMESPACE, "-l", APP_LABEL, "-o", "json",
        )
        write_artifact(f"{TEST_LANE}-pods.json", raw)
        data = json.loads(raw)
        items = data.get("items", [])
        assert items, f"No pods with label {APP_LABEL}"
        running = [
            p for p in items
            if p.get("status", {}).get("phase") == "Running"
        ]
        assert running, (
            f"No Running pods; phases: {[p['status'].get('phase') for p in items]}"
        )

    def test_service_endpoints(self):
        raw = require_kubectl(
            "get", "endpoints", SERVICE_NAME, "-n", NAMESPACE, "-o", "json",
        )
        write_artifact(f"{TEST_LANE}-endpoints.json", raw)
        data = json.loads(raw)
        subsets = data.get("subsets") or []
        addresses = [a for s in subsets for a in s.get("addresses", [])]
        assert addresses, f"Service {SERVICE_NAME} has no endpoint addresses"

    def test_lane_labels(self):
        raw = require_kubectl(
            "get", "deployment", DEPLOYMENT_NAME,
            "-n", NAMESPACE, "-l", LANE_LABEL, "-o", "json",
        )
        data = json.loads(raw)
        items = data.get("items", [])
        assert items, f"Deployment {DEPLOYMENT_NAME} missing label {LANE_LABEL}"


class TestConfigPVC:
    """Config volume is bound and usable."""

    def test_pvc_bound(self):
        raw = require_kubectl(
            "get", "pvc", CONFIG_PVC, "-n", NAMESPACE, "-o", "json",
        )
        write_artifact(f"{TEST_LANE}-config-pvc.json", raw)
        data = json.loads(raw)
        phase = data.get("status", {}).get("phase", "")
        assert phase == "Bound", f"PVC {CONFIG_PVC} phase is {phase}, expected Bound"

    def test_config_writable(self):
        pod = _first_pod_name()
        result = run_kubectl(
            "exec", pod, "-n", NAMESPACE, "--",
            "sh", "-c", f'touch "{CONFIG_MOUNT}/.write-test" && rm -f "{CONFIG_MOUNT}/.write-test"',
        )
        assert result.returncode == 0, (
            f"Config mount not writable: {result.stderr}"
        )


class TestDataPVC:
    """Data volume is bound and usable."""

    def test_pvc_bound(self):
        raw = require_kubectl(
            "get", "pvc", DATA_PVC, "-n", NAMESPACE, "-o", "json",
        )
        write_artifact(f"{TEST_LANE}-data-pvc.json", raw)
        data = json.loads(raw)
        phase = data.get("status", {}).get("phase", "")
        assert phase == "Bound", f"PVC {DATA_PVC} phase is {phase}, expected Bound"

    def test_data_writable(self):
        pod = _first_pod_name()
        result = run_kubectl(
            "exec", pod, "-n", NAMESPACE, "--",
            "sh", "-c", f'touch "{DATA_MOUNT}/.write-test" && rm -f "{DATA_MOUNT}/.write-test"',
        )
        assert result.returncode == 0, (
            f"Data mount not writable: {result.stderr}"
        )


class TestReachability:
    """Service port is reachable within the cluster."""

    def test_dns_resolves(self):
        fqdn = f"{SERVICE_NAME}.{NAMESPACE}.svc.cluster.local"
        result = run_kubectl(
            "exec", _first_pod_name(), "-n", NAMESPACE, "--",
            "getent", "hosts", fqdn,
        )
        write_artifact(f"{TEST_LANE}-dns.txt", result.stdout + result.stderr)
        assert result.returncode == 0, f"DNS resolution failed for {fqdn}: {result.stderr}"

    def test_http_port_reachable(self):
        pod = _first_pod_name()
        fqdn = f"{SERVICE_NAME}.{NAMESPACE}.svc.cluster.local"
        result = run_kubectl(
            "exec", pod, "-n", NAMESPACE, "--",
            "sh", "-c",
            f'curl -sf --max-time 15 "http://{fqdn}:{SERVICE_PORT}/health" '
            f'|| curl -sf --max-time 15 -o /dev/null -w "%{{http_code}}" '
            f'"http://{fqdn}:{SERVICE_PORT}/"',
        )
        write_artifact(f"{TEST_LANE}-http.txt", result.stdout + result.stderr)
        assert result.returncode == 0, (
            f"HTTP request to {fqdn}:{SERVICE_PORT} failed: {result.stderr}"
        )


class TestEnvInjection:
    """PUID/PGID/TZ environment variables are present."""

    def test_puid(self):
        pod = _first_pod_name()
        result = run_kubectl(
            "exec", pod, "-n", NAMESPACE, "--",
            "printenv", "PUID",
        )
        assert result.returncode == 0 and result.stdout.strip() == "1000", (
            f"PUID not set to 1000: {result.stdout.strip()}"
        )

    def test_pgid(self):
        pod = _first_pod_name()
        result = run_kubectl(
            "exec", pod, "-n", NAMESPACE, "--",
            "printenv", "PGID",
        )
        assert result.returncode == 0 and result.stdout.strip() == "1000", (
            f"PGID not set to 1000: {result.stdout.strip()}"
        )

    def test_tz(self):
        pod = _first_pod_name()
        result = run_kubectl(
            "exec", pod, "-n", NAMESPACE, "--",
            "printenv", "TZ",
        )
        assert result.returncode == 0 and result.stdout.strip() == "Etc/UTC", (
            f"TZ not set to Etc/UTC: {result.stdout.strip()}"
        )


class TestPersistence:
    """Config and data survive a rollout restart."""

    def test_config_survives_restart(self):
        import uuid

        pod_before = _first_pod_name()
        sentinel = f"sentinel-{uuid.uuid4().hex[:12]}"
        sentinel_path = f"{CONFIG_MOUNT}/.sentinel"

        write_result = run_kubectl(
            "exec", pod_before, "-n", NAMESPACE, "--",
            "sh", "-c", f'echo "{sentinel}" > "{sentinel_path}"',
        )
        assert write_result.returncode == 0, (
            f"Failed to write sentinel: {write_result.stderr}"
        )
        write_artifact(f"{TEST_LANE}-config-sentinel-write.txt", sentinel)

        restart = run_kubectl(
            "rollout", "restart", f"deployment/{DEPLOYMENT_NAME}", "-n", NAMESPACE,
        )
        assert restart.returncode == 0, f"Restart failed: {restart.stderr}"

        status = run_kubectl(
            "rollout", "status", f"deployment/{DEPLOYMENT_NAME}",
            "-n", NAMESPACE, "--timeout=300s",
        )
        assert status.returncode == 0, f"Rollout failed: {status.stderr}"

        pod_after = _first_pod_name()
        read_result = run_kubectl(
            "exec", pod_after, "-n", NAMESPACE, "--",
            "cat", sentinel_path,
        )
        assert read_result.returncode == 0, (
            f"Failed to read sentinel after restart: {read_result.stderr}"
        )
        assert read_result.stdout.strip() == sentinel, (
            f"Sentinel mismatch: wrote {sentinel}, read {read_result.stdout.strip()}"
        )
        write_artifact(f"{TEST_LANE}-config-sentinel-read.txt", read_result.stdout.strip())

    def test_data_survives_restart(self):
        import uuid

        pod_before = _first_pod_name()
        sentinel = f"sentinel-{uuid.uuid4().hex[:12]}"
        sentinel_path = f"{DATA_MOUNT}/.sentinel"

        write_result = run_kubectl(
            "exec", pod_before, "-n", NAMESPACE, "--",
            "sh", "-c", f'echo "{sentinel}" > "{sentinel_path}"',
        )
        assert write_result.returncode == 0, (
            f"Failed to write data sentinel: {write_result.stderr}"
        )
        write_artifact(f"{TEST_LANE}-data-sentinel-write.txt", sentinel)

        restart = run_kubectl(
            "rollout", "restart", f"deployment/{DEPLOYMENT_NAME}", "-n", NAMESPACE,
        )
        assert restart.returncode == 0, f"Restart failed: {restart.stderr}"

        status = run_kubectl(
            "rollout", "status", f"deployment/{DEPLOYMENT_NAME}",
            "-n", NAMESPACE, "--timeout=300s",
        )
        assert status.returncode == 0, f"Rollout failed: {status.stderr}"

        pod_after = _first_pod_name()
        read_result = run_kubectl(
            "exec", pod_after, "-n", NAMESPACE, "--",
            "cat", sentinel_path,
        )
        assert read_result.returncode == 0, (
            f"Failed to read data sentinel after restart: {read_result.stderr}"
        )
        assert read_result.stdout.strip() == sentinel, (
            f"Data sentinel mismatch: wrote {sentinel}, read {read_result.stdout.strip()}"
        )
        write_artifact(f"{TEST_LANE}-data-sentinel-read.txt", read_result.stdout.strip())


class TestTeardown:
    """Namespace and resources exist for cleanup verification."""

    def test_namespace_exists(self):
        result = run_kubectl("get", "namespace", NAMESPACE, "-o", "json")
        assert result.returncode == 0, (
            f"Namespace {NAMESPACE} does not exist: {result.stderr}"
        )
        write_artifact(f"{TEST_LANE}-namespace.json", result.stdout)

    def test_no_cluster_scoped_leaks(self):
        for kind in ("clusterrole", "clusterrolebinding"):
            result = run_kubectl("get", kind, "-l", LANE_LABEL, "-o", "json")
            if result.returncode != 0:
                continue
            data = json.loads(result.stdout)
            items = data.get("items", [])
            names = [item["metadata"]["name"] for item in items]
            write_artifact(f"{TEST_LANE}-{kind}-leak.json", result.stdout)
            assert not names, (
                f"Cluster-scoped {kind} leak with label {LANE_LABEL}: {names}"
            )


class TestObservability:
    """Capture mount and storage state for operator evidence."""

    def test_capture_mount_info(self):
        pod = _first_pod_name()
        for mount, label in [(CONFIG_MOUNT, "config"), (DATA_MOUNT, "data")]:
            df = run_kubectl(
                "exec", pod, "-n", NAMESPACE, "--",
                "df", "-h", mount,
            )
            write_artifact(f"{TEST_LANE}-df-{label}.txt", df.stdout + df.stderr)
            assert df.returncode == 0, f"df failed for {mount}: {df.stderr}"

    def test_capture_events(self):
        result = run_kubectl(
            "get", "events", "-n", NAMESPACE, "--sort-by=.lastTimestamp",
        )
        write_artifact(f"{TEST_LANE}-events.txt", result.stdout + result.stderr)


class TestGPUExclusion:
    """GPU transcoding is explicitly deferred to #63."""

    @pytest.mark.skip(reason="GPU transcoding deferred to #63")
    def test_gpu_transcoding(self):
        pass

    @pytest.mark.skip(reason="Device passthrough deferred to #63")
    def test_device_passthrough(self):
        pass
