"""
Representative non-media homelab workload lane — OpenPrinting/CUPS print service.

Proves the minimum in-cluster validation contract for a linuxserver.io-style
print service (OpenPrinting/CUPS class) running directly in Kubernetes:

  1. Deployment   — workload reaches Running state on the cluster node.
  2. Persistence  — config PVC binds on local-path, the config mount is
                    writable, and state survives a rollout restart.
  3. Reachability — IPP port (631) is reachable within the cluster namespace.
  4. Secret/env   — PUID, PGID, and TZ environment variables are injected
                    into the container and visible in the process environment.
  5. Teardown     — namespace cleanup is handled by the workflow onExit handler;
                    this lane verifies the pod and PVC are present before any
                    cleanup runs.

Lane dependencies:
  - #52 (homelab storage epic)   — local-path PVC contract proven first
  - #53 (homelab access epic)    — in-cluster DNS and TLS contracts proven first
  - #54 (homelab substrate epic) — in-cluster workload scheduling proven first

Out-of-scope for this base lane (split explicitly):
  - USB printer device access and attachment → issue #67
  - LAN mDNS / self-discovery (avahi) → issue #67
  - NodePort or LoadBalancer exposure for LAN printing → issue #67
  - Auth-gated administration UI → deferred beyond #67

Source idea: projectbluefin/bluespeed#11 (OpenPrinting-class homelab path)
Child of: #64, #51
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

DEPLOYMENT_NAME = "homelab-print-service"
APP_LABEL = os.environ.get("TEST_APP_LABEL", f"app={DEPLOYMENT_NAME}")
SERVICE_NAME = os.environ.get("TEST_SERVICE_NAME", DEPLOYMENT_NAME)

CONFIG_PVC_NAME = "homelab-print-config"
CONFIG_MOUNT_PATH = "/config"

PRINT_SERVICE_PORT = 631  # IPP (Internet Printing Protocol) standard port

EXPECTED_ENV_VARS = {"PUID": "1000", "PGID": "1000", "TZ": "UTC"}

EXPECTED_STORAGE_CLASS = "local-path"
EXPECTED_CONFIG_CAPACITY = "1Gi"
EXPECTED_ACCESS_MODES = ["ReadWriteOnce"]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _exec_in_pod(*command: str) -> subprocess.CompletedProcess[str]:
    return run_kubectl("exec", "-n", TEST_NAMESPACE, first_pod_name(), "--", *command)


def _get_pvc(pvc_name: str) -> dict:
    result = run_kubectl("get", "pvc", pvc_name, "-n", TEST_NAMESPACE, "-o", "json")
    assert result.returncode == 0, result.stdout + result.stderr
    write_artifact(f"print-pvc-{pvc_name}.json", result.stdout)
    return json.loads(result.stdout)


def _pvc_debug(data: dict) -> str:
    return json.dumps(data, indent=2)


# ── Test class ────────────────────────────────────────────────────────────────


class TestPrintServiceLane:
    """
    Base non-media homelab workload lane (OpenPrinting/CUPS class).

    Validates deployment, single-PVC persistence, IPP port reachability, env
    injection, and rollout-restart survival.  USB device access and LAN
    discovery paths are skipped with explicit references to #67.
    """

    # ── 1. Deployment ─────────────────────────────────────────────────────────

    def test_deployment_becomes_ready(self):
        """Workload reaches availableReplicas >= 1 on the cluster node."""
        result = run_kubectl(
            "get", "deployment", DEPLOYMENT_NAME, "-n", TEST_NAMESPACE, "-o", "json"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        write_artifact("print-deployment.json", result.stdout)
        data = json.loads(result.stdout)
        status = data.get("status", {})
        assert status.get("availableReplicas", 0) >= 1, json.dumps(status, indent=2)
        assert status.get("readyReplicas", 0) >= 1, json.dumps(status, indent=2)

    def test_pod_reaches_running_state(self):
        """At least one pod is Running and its containers are all Ready."""
        pods = get_pods_json()
        write_artifact("print-pods.json", json.dumps(pods, indent=2))
        items = pods.get("items", [])
        assert items, "No print-service pod found"
        pod = items[0]
        phase = pod.get("status", {}).get("phase")
        assert phase == "Running", json.dumps(pod.get("status", {}), indent=2)
        container_statuses = pod.get("status", {}).get("containerStatuses", [])
        assert container_statuses, "No containerStatuses found"
        for cs in container_statuses:
            assert cs.get("ready"), f"Container {cs.get('name')} not ready: {cs}"

    def test_service_has_endpoints(self):
        """ClusterIP service exposes at least one endpoint on PRINT_SERVICE_PORT."""
        svc = run_kubectl("get", "service", SERVICE_NAME, "-n", TEST_NAMESPACE, "-o", "json")
        eps = run_kubectl("get", "endpoints", SERVICE_NAME, "-n", TEST_NAMESPACE, "-o", "json")
        assert svc.returncode == 0, svc.stdout + svc.stderr
        assert eps.returncode == 0, eps.stdout + eps.stderr
        write_artifact("print-service.json", svc.stdout)
        write_artifact("print-endpoints.json", eps.stdout)
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
        """Config PVC reports the expected storage capacity and access modes."""
        data = _get_pvc(CONFIG_PVC_NAME)
        assert (
            data.get("status", {}).get("capacity", {}).get("storage")
            == EXPECTED_CONFIG_CAPACITY
        ), _pvc_debug(data)
        assert (
            data.get("spec", {}).get("accessModes") == EXPECTED_ACCESS_MODES
        ), _pvc_debug(data)

    def test_config_pvc_storage_class(self):
        """Config PVC is provisioned by the expected storage class."""
        data = _get_pvc(CONFIG_PVC_NAME)
        assert (
            data.get("spec", {}).get("storageClassName") == EXPECTED_STORAGE_CLASS
        ), _pvc_debug(data)

    def test_config_mount_is_writable(self):
        """Container can write to /config — required for CUPS printer state."""
        result = _exec_in_pod(
            "sh", "-c",
            f"test -d {CONFIG_MOUNT_PATH}"
            f" && touch {CONFIG_MOUNT_PATH}/.writetest"
            f" && rm -f {CONFIG_MOUNT_PATH}/.writetest",
        )
        assert result.returncode == 0, result.stdout + result.stderr

    # ── 3. Reachability ───────────────────────────────────────────────────────

    def test_ipp_port_is_reachable_in_cluster(self):
        """
        HTTP GET to the print service on port 631 (IPP) succeeds in-cluster.

        Uses wget from inside the workload pod.  A non-200 response that is
        not a connection error (e.g. 426 Upgrade Required, which CUPS returns
        for plain-HTTP requests to an IPP-only socket) still proves the port
        is open and the service is running.
        """
        fqdn = f"{SERVICE_NAME}.{TEST_NAMESPACE}.svc.cluster.local"
        result = _exec_in_pod(
            "sh", "-c",
            f"wget -q -S -O /dev/null http://{fqdn}:{PRINT_SERVICE_PORT}/ 2>&1 || true",
        )
        output = result.stdout + result.stderr
        write_artifact("print-reachability.txt", output)
        # A TCP connection refusal or DNS failure means the service is down.
        assert "Connection refused" not in output, output
        assert "Name or service not known" not in output, output

    def test_cluster_dns_resolves_print_service(self):
        """Cluster DNS resolves the print service FQDN."""
        fqdn = f"{SERVICE_NAME}.{TEST_NAMESPACE}.svc.cluster.local"
        result = run_kubectl(
            "exec", "-n", TEST_NAMESPACE, first_pod_name(),
            "--", "getent", "hosts", fqdn,
        )
        write_artifact("print-dns.txt", result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr

    # ── 4. Secret / env injection ─────────────────────────────────────────────

    def test_puid_pgid_tz_env_vars_are_present(self):
        """
        PUID, PGID, and TZ env vars are visible in the container environment.

        linuxserver.io containers rely on these to set file ownership and
        timezone at startup.  This check proves the env values are injected
        by the Deployment spec and not silently dropped.
        """
        result = _exec_in_pod("env")
        assert result.returncode == 0, result.stdout + result.stderr
        write_artifact("print-env.txt", result.stdout)
        env = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        for var, expected in EXPECTED_ENV_VARS.items():
            assert var in env, f"{var} not found in container env:\n{result.stdout}"
            assert env[var] == expected, (
                f"{var}={env[var]!r} but expected {expected!r}"
            )

    # ── 5. Rollout-restart persistence ────────────────────────────────────────

    def test_config_state_survives_rollout_restart(self):
        """
        A sentinel file written to /config survives a rollout restart, proving
        the config PVC persists through pod replacement.
        """
        before = get_pods_json()
        write_artifact("print-pods-before-restart.json", json.dumps(before, indent=2))

        seed = _exec_in_pod(
            "sh", "-c",
            f"echo print-sentinel >{CONFIG_MOUNT_PATH}/print-sentinel.txt",
        )
        assert seed.returncode == 0, seed.stdout + seed.stderr

        restart = run_kubectl(
            "rollout", "restart", f"deployment/{DEPLOYMENT_NAME}", "-n", TEST_NAMESPACE
        )
        assert restart.returncode == 0, restart.stdout + restart.stderr
        write_artifact("print-restart.txt", restart.stdout + restart.stderr)

        status = run_kubectl(
            "rollout", "status", f"deployment/{DEPLOYMENT_NAME}",
            "-n", TEST_NAMESPACE, "--timeout=300s",
        )
        assert status.returncode == 0, status.stdout + status.stderr
        write_artifact("print-rollout-status.txt", status.stdout + status.stderr)

        after = get_pods_json()
        write_artifact("print-pods-after-restart.json", json.dumps(after, indent=2))

        verify = _exec_in_pod("cat", f"{CONFIG_MOUNT_PATH}/print-sentinel.txt")
        assert verify.returncode == 0, verify.stdout + verify.stderr
        assert verify.stdout.strip() == "print-sentinel", (
            f"Sentinel missing from {CONFIG_MOUNT_PATH} after restart: {verify.stdout!r}"
        )

    # ── 6. Storage observability artifacts ────────────────────────────────────

    def test_collects_storage_observability_artifacts(self):
        """Capture disk/mount evidence for the config PVC mount path."""
        commands = {
            "print-config-df.txt": ["df", "-h", CONFIG_MOUNT_PATH],
            "print-config-findmnt.txt": ["findmnt", CONFIG_MOUNT_PATH],
            "print-config-stat.txt": ["stat", CONFIG_MOUNT_PATH],
        }
        for artifact, cmd in commands.items():
            result = _exec_in_pod(*cmd)
            assert result.returncode == 0, (
                f"{' '.join(cmd)} failed: {result.stdout}{result.stderr}"
            )
            write_artifact(artifact, result.stdout + result.stderr)

    # ── 7. Explicitly deferred paths ─────────────────────────────────────────

    def test_usb_printer_device_access_is_out_of_scope_for_base_lane(self):
        """
        USB printer device access and attachment to the CUPS container are
        out of scope for this base lane.  Requires host device passthrough
        (hostPath /dev/usb/lp0 or similar) which depends on substrate work
        in #54.  Tracked explicitly in issue #67.
        """
        pytest.skip(
            "USB printer device access deferred to #67; "
            "requires host device passthrough — depends on #54 substrate work"
        )

    def test_lan_mdns_discovery_is_out_of_scope_for_base_lane(self):
        """
        LAN mDNS / avahi-based self-discovery is out of scope for this base
        lane.  The in-cluster validation contract covers IPP reachability and
        DNS resolution within the cluster namespace only.  LAN discovery
        exposure (NodePort or LoadBalancer + avahi) is tracked in issue #67.
        """
        pytest.skip(
            "LAN mDNS autodiscovery deferred to #67; "
            "requires avahi sidecar and NodePort/LoadBalancer exposure — "
            "out of scope for base in-cluster validation"
        )
