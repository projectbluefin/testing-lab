"""
Persistence assertion helpers for service-catalog lanes.

Validates PVC lifecycle and data survival across rollout restarts.
Corresponds to §3 of the service-catalog contract (#66).
"""

from __future__ import annotations

import json
import uuid

from tests.service_catalog.shared.kube import (
    NAMESPACE,
    TEST_LANE,
    require_kubectl,
    run_kubectl,
    write_artifact,
)


def assert_pvc_bound(pvc_name: str) -> dict:
    raw = require_kubectl("get", "pvc", pvc_name, "-n", NAMESPACE, "-o", "json")
    write_artifact(f"{TEST_LANE}-pvc.json", raw)
    data = json.loads(raw)
    phase = data.get("status", {}).get("phase", "")
    assert phase == "Bound", f"PVC {pvc_name} phase is {phase}, expected Bound"
    return data


def write_sentinel(pod_name: str, mount_path: str) -> str:
    sentinel_value = f"sentinel-{uuid.uuid4().hex[:12]}"
    sentinel_path = f"{mount_path}/.sentinel"
    result = run_kubectl(
        "exec", pod_name, "-n", NAMESPACE, "--",
        "sh", "-c", f'echo "{sentinel_value}" > "{sentinel_path}"',
    )
    assert result.returncode == 0, (
        f"Failed to write sentinel to {pod_name}:{sentinel_path}: {result.stderr}"
    )
    write_artifact(f"{TEST_LANE}-sentinel-write.txt", f"{sentinel_value}\n")
    return sentinel_value


def read_sentinel(pod_name: str, mount_path: str) -> str:
    sentinel_path = f"{mount_path}/.sentinel"
    result = run_kubectl(
        "exec", pod_name, "-n", NAMESPACE, "--",
        "cat", sentinel_path,
    )
    assert result.returncode == 0, (
        f"Failed to read sentinel from {pod_name}:{sentinel_path}: {result.stderr}"
    )
    value = result.stdout.strip()
    write_artifact(f"{TEST_LANE}-sentinel-read.txt", f"{value}\n")
    return value


def get_pod_uids(app_label: str) -> set[str]:
    raw = require_kubectl("get", "pods", "-n", NAMESPACE, "-l", app_label, "-o", "json")
    data = json.loads(raw)
    return {item["metadata"]["uid"] for item in data.get("items", [])}


def rollout_restart(deployment_name: str) -> None:
    pods_before = require_kubectl(
        "get", "pods", "-n", NAMESPACE, "-o", "json",
    )
    write_artifact(f"{TEST_LANE}-pods-before.json", pods_before)

    restart = run_kubectl(
        "rollout", "restart", f"deployment/{deployment_name}", "-n", NAMESPACE,
    )
    assert restart.returncode == 0, (
        f"rollout restart failed: {restart.stdout}{restart.stderr}"
    )
    write_artifact(f"{TEST_LANE}-restart.txt", restart.stdout + restart.stderr)

    status = run_kubectl(
        "rollout", "status", f"deployment/{deployment_name}",
        "-n", NAMESPACE, "--timeout=300s",
    )
    assert status.returncode == 0, (
        f"rollout status failed: {status.stdout}{status.stderr}"
    )
    write_artifact(f"{TEST_LANE}-rollout-status.txt", status.stdout + status.stderr)

    pods_after = require_kubectl(
        "get", "pods", "-n", NAMESPACE, "-o", "json",
    )
    write_artifact(f"{TEST_LANE}-pods-after.json", pods_after)


def assert_restart_changes_pods(deployment_name: str, app_label: str) -> None:
    before_uids = get_pod_uids(app_label)
    assert before_uids, f"No pods found before restart for {app_label}"

    rollout_restart(deployment_name)

    after_uids = get_pod_uids(app_label)
    assert after_uids, f"No pods found after restart for {app_label}"
    assert before_uids != after_uids, (
        f"Pod UIDs did not change across restart: {sorted(before_uids)}"
    )
