"""
Representative media-service workload lane.

Proves the minimum in-cluster validation contract for a linuxserver.io-style
media service (Plex/Jellyfin class) running directly in Kubernetes:

  1. Deployment   — workload reaches Running state on the cluster node.
  2. Persistence  — config PVC and media-data PVC bind on local-path and
                    survive a rollout restart.
  3. Reachability — web UI port (8096) is reachable within the cluster
                    namespace.
  4. Secret/env   — PUID, PGID, and TZ environment variables are injected
                    into the container and visible in the process environment.
  5. Teardown     — namespace cleanup is handled by the workflow onExit handler;
                    this lane verifies the pod and PVCs are present before any
                    cleanup runs.

Lane dependencies:
  - #52 (homelab storage epic)  — local-path PVC contract proven first
  - #53 (homelab access epic)   — in-cluster DNS and TLS contracts proven first
  - #54 (homelab substrate epic) — in-cluster workload scheduling proven first

Out-of-scope for this base lane (tracked separately):
  - GPU transcoding and hardware passthrough → issue #63
  - ReadWriteMany / shared-media mount → blocked by #62
  - Auth-gated service UI (Authelia / OAuth proxy) → issue #61
  - External / LAN hostname routing → bluespeed repo
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from tests.service_catalog.shared.kube import (
    TEST_NAMESPACE,
    first_pod_name,
    get_pods_json,
    run_kubectl,
    write_artifact,
)


# ── Lane constants ────────────────────────────────────────────────────────────

DEPLOYMENT_NAME = "homelab-media-service"
APP_LABEL = os.environ.get("TEST_APP_LABEL", f"app={DEPLOYMENT_NAME}")
SERVICE_NAME = os.environ.get("TEST_SERVICE_NAME", DEPLOYMENT_NAME)

CONFIG_PVC_NAME = "homelab-media-config"
DATA_PVC_NAME = "homelab-media-data"
CONFIG_MOUNT_PATH = "/config"
DATA_MOUNT_PATH = "/data"

MEDIA_SERVICE_PORT = 8096  # Jellyfin/linuxserver.io standard HTTP port

EXPECTED_ENV_VARS = {"PUID": "1000", "PGID": "1000", "TZ": "UTC"}

EXPECTED_STORAGE_CLASS = "local-path"
EXPECTED_CONFIG_CAPACITY = "1Gi"
EXPECTED_DATA_CAPACITY = "10Gi"
EXPECTED_ACCESS_MODES = ["ReadWriteOnce"]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _exec_in_pod(*command: str) -> subprocess.CompletedProcess[str]:
    return run_kubectl("exec", "-n", TEST_NAMESPACE, first_pod_name(), "--", *command)


def _get_pvc(pvc_name: str) -> dict:
    result = run_kubectl("get", "pvc", pvc_name, "-n", TEST_NAMESPACE, "-o", "json")
    assert result.returncode == 0, result.stdout + result.stderr
    write_artifact(f"media-pvc-{pvc_name}.json", result.stdout)
    return json.loads(result.stdout)


def _pvc_debug(data: dict) -> str:
    return json.dumps(data, indent=2)


# ── Test class ────────────────────────────────────────────────────────────────


class TestMediaServiceLane:
    """
    Base media-service workload lane.

    Validates deployment, dual-PVC persistence, port reachability, env
    injection, and rollout-restart survival.  GPU transcoding and RWX/
    shared-storage paths are skipped with explicit issue references.
    """

    # ── 1. Deployment ─────────────────────────────────────────────────────────

    def test_deployment_becomes_ready(self):
        """Workload reaches availableReplicas >= 1 on the cluster node."""
        result = run_kubectl(
            "get", "deployment", DEPLOYMENT_NAME, "-n", TEST_NAMESPACE, "-o", "json"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        write_artifact("media-deployment.json", result.stdout)
        data = json.loads(result.stdout)
        status = data.get("status", {})
        assert status.get("availableReplicas", 0) >= 1, json.dumps(status, indent=2)
        assert status.get("readyReplicas", 0) >= 1, json.dumps(status, indent=2)

    def test_pod_reaches_running_state(self):
        """At least one pod is Running and its containers are all Ready."""
        pods = get_pods_json()
        write_artifact("media-pods.json", json.dumps(pods, indent=2))
        items = pods.get("items", [])
        assert items, "No media-service pod found"
        pod = items[0]
        phase = pod.get("status", {}).get("phase")
        assert phase == "Running", json.dumps(pod.get("status", {}), indent=2)
        container_statuses = pod.get("status", {}).get("containerStatuses", [])
        assert container_statuses, "No containerStatuses found"
        for cs in container_statuses:
            assert cs.get("ready"), f"Container {cs.get('name')} not ready: {cs}"

    def test_service_has_endpoints(self):
        """ClusterIP service exposes at least one endpoint on MEDIA_SERVICE_PORT."""
        svc = run_kubectl("get", "service", SERVICE_NAME, "-n", TEST_NAMESPACE, "-o", "json")
        eps = run_kubectl("get", "endpoints", SERVICE_NAME, "-n", TEST_NAMESPACE, "-o", "json")
        assert svc.returncode == 0, svc.stdout + svc.stderr
        assert eps.returncode == 0, eps.stdout + eps.stderr
        write_artifact("media-service.json", svc.stdout)
        write_artifact("media-endpoints.json", eps.stdout)
        eps_data = json.loads(eps.stdout)
        subsets = eps_data.get("subsets", [])
        assert subsets, "No endpoint subsets found"
        all_addresses = [addr for s in subsets for addr in s.get("addresses", [])]
        assert all_addresses, "No endpoint addresses found"

    # ── 2. Persistence — config PVC ───────────────────────────────────────────

    def test_config_pvc_is_bound(self):
        """Config PVC (1Gi ReadWriteOnce local-path) binds within the namespace."""
        data = _get_pvc(CONFIG_PVC_NAME)
        assert data.get("status", {}).get("phase") == "Bound", _pvc_debug(data)

    def test_config_pvc_capacity_and_access_modes(self):
        data = _get_pvc(CONFIG_PVC_NAME)
        assert (
            data.get("status", {}).get("capacity", {}).get("storage")
            == EXPECTED_CONFIG_CAPACITY
        ), _pvc_debug(data)
        assert data.get("spec", {}).get("accessModes") == EXPECTED_ACCESS_MODES, _pvc_debug(data)

    def test_config_pvc_storage_class(self):
        data = _get_pvc(CONFIG_PVC_NAME)
        assert (
            data.get("spec", {}).get("storageClassName") == EXPECTED_STORAGE_CLASS
        ), _pvc_debug(data)

    def test_config_mount_is_writable(self):
        """Container can write to /config — required for service configuration state."""
        result = _exec_in_pod(
            "sh", "-c",
            f"test -d {CONFIG_MOUNT_PATH} && touch {CONFIG_MOUNT_PATH}/.writetest"
            f" && rm -f {CONFIG_MOUNT_PATH}/.writetest",
        )
        assert result.returncode == 0, result.stdout + result.stderr

    # ── 3. Persistence — media data PVC ──────────────────────────────────────

    def test_data_pvc_is_bound(self):
        """Media-data PVC (10Gi ReadWriteOnce local-path) binds within the namespace."""
        data = _get_pvc(DATA_PVC_NAME)
        assert data.get("status", {}).get("phase") == "Bound", _pvc_debug(data)

    def test_data_pvc_capacity_and_access_modes(self):
        data = _get_pvc(DATA_PVC_NAME)
        assert (
            data.get("status", {}).get("capacity", {}).get("storage")
            == EXPECTED_DATA_CAPACITY
        ), _pvc_debug(data)
        assert data.get("spec", {}).get("accessModes") == EXPECTED_ACCESS_MODES, _pvc_debug(data)

    def test_data_mount_is_writable(self):
        """Container can write to /data — required for media library state."""
        result = _exec_in_pod(
            "sh", "-c",
            f"test -d {DATA_MOUNT_PATH} && touch {DATA_MOUNT_PATH}/.writetest"
            f" && rm -f {DATA_MOUNT_PATH}/.writetest",
        )
        assert result.returncode == 0, result.stdout + result.stderr

    # ── 4. Reachability ───────────────────────────────────────────────────────

    def test_media_port_is_reachable_in_cluster(self):
        """
        HTTP GET to the media service on port 8096 succeeds within the cluster.

        Uses wget from inside the workload pod because the test runner pod may
        not be on the same node or network segment.  A non-200 response that
        is not a connection error (e.g. 401 Unauthorized) still proves the
        port is open and the service is running.
        """
        fqdn = f"{SERVICE_NAME}.{TEST_NAMESPACE}.svc.cluster.local"
        result = _exec_in_pod(
            "sh", "-c",
            f"wget -q -S -O /dev/null http://{fqdn}:{MEDIA_SERVICE_PORT}/ 2>&1 || true",
        )
        # We tolerate any HTTP response code; a TCP connection refusal is the only failure.
        output = result.stdout + result.stderr
        write_artifact("media-reachability.txt", output)
        # "Connection refused" or "Name or service not known" = service is down
        assert "Connection refused" not in output, output
        assert "Name or service not known" not in output, output

    def test_cluster_dns_resolves_media_service(self):
        """Cluster DNS resolves the media service FQDN."""
        fqdn = f"{SERVICE_NAME}.{TEST_NAMESPACE}.svc.cluster.local"
        result = run_kubectl(
            "exec", "-n", TEST_NAMESPACE, first_pod_name(),
            "--", "getent", "hosts", fqdn,
        )
        write_artifact("media-dns.txt", result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr

    # ── 5. Secret / env injection ─────────────────────────────────────────────

    def test_puid_pgid_tz_env_vars_are_present(self):
        """
        PUID, PGID, and TZ env vars are visible in the container environment.

        linuxserver.io containers rely on these to set file ownership and
        timezone at startup.  This check proves the env values are injected
        by the Deployment spec and not silently dropped.
        """
        result = _exec_in_pod("env")
        assert result.returncode == 0, result.stdout + result.stderr
        write_artifact("media-env.txt", result.stdout)
        env = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        for var, expected in EXPECTED_ENV_VARS.items():
            assert var in env, f"{var} not found in container env:\n{result.stdout}"
            assert env[var] == expected, (
                f"{var}={env[var]!r} but expected {expected!r}"
            )

    # ── 6. Rollout-restart persistence ────────────────────────────────────────

    def test_config_and_data_state_survive_rollout_restart(self):
        """
        A sentinel file written to both /config and /data survives a
        rollout restart, proving both PVCs persist through pod replacement.
        """
        before = get_pods_json()
        write_artifact("media-pods-before-restart.json", json.dumps(before, indent=2))

        for mount, label in [(CONFIG_MOUNT_PATH, "config"), (DATA_MOUNT_PATH, "data")]:
            seed = _exec_in_pod(
                "sh", "-c", f"echo media-sentinel-{label} >{mount}/media-sentinel-{label}.txt",
            )
            assert seed.returncode == 0, seed.stdout + seed.stderr

        restart = run_kubectl(
            "rollout", "restart", f"deployment/{DEPLOYMENT_NAME}", "-n", TEST_NAMESPACE
        )
        assert restart.returncode == 0, restart.stdout + restart.stderr
        write_artifact("media-restart.txt", restart.stdout + restart.stderr)

        status = run_kubectl(
            "rollout", "status", f"deployment/{DEPLOYMENT_NAME}",
            "-n", TEST_NAMESPACE, "--timeout=300s",
        )
        assert status.returncode == 0, status.stdout + status.stderr
        write_artifact("media-rollout-status.txt", status.stdout + status.stderr)

        after = get_pods_json()
        write_artifact("media-pods-after-restart.json", json.dumps(after, indent=2))

        for mount, label in [(CONFIG_MOUNT_PATH, "config"), (DATA_MOUNT_PATH, "data")]:
            verify = _exec_in_pod("cat", f"{mount}/media-sentinel-{label}.txt")
            assert verify.returncode == 0, verify.stdout + verify.stderr
            assert verify.stdout.strip() == f"media-sentinel-{label}", (
                f"Sentinel missing from {mount} after restart: {verify.stdout!r}"
            )

    # ── 7. Storage observability artifacts ────────────────────────────────────

    def test_collects_storage_observability_artifacts(self):
        """Capture disk/mount evidence for both PVC mount paths."""
        for mount, label in [(CONFIG_MOUNT_PATH, "config"), (DATA_MOUNT_PATH, "data")]:
            commands = {
                f"media-{label}-df.txt": ["df", "-h", mount],
                f"media-{label}-findmnt.txt": ["findmnt", mount],
                f"media-{label}-stat.txt": ["stat", mount],
            }
            for artifact, cmd in commands.items():
                result = _exec_in_pod(*cmd)
                assert result.returncode == 0, (
                    f"{' '.join(cmd)} failed: {result.stdout}{result.stderr}"
                )
                write_artifact(artifact, result.stdout + result.stderr)

    # ── 8. Explicitly deferred paths ─────────────────────────────────────────

    def test_gpu_transcoding_is_out_of_scope_for_base_lane(self):
        """
        GPU transcoding and hardware passthrough are out of scope for this
        base lane.  Filed as follow-up in issue #63.
        """
        pytest.skip(
            "GPU transcoding and KubeVirt device passthrough deferred to #63; "
            "requires GPU feature gate and device-plugin configuration"
        )

    def test_rwx_shared_media_mount_is_blocked(self):
        """
        ReadWriteMany / shared-media mount between multiple pods is blocked
        until a RWX-capable storage class (NFS CSI, Longhorn, etc.) is
        available on the cluster.  Tracked in #62.
        """
        pytest.skip(
            "RWX/shared-storage scenarios blocked by #62 until "
            "ReadWriteMany storage class is available"
        )
