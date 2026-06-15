"""
Redeploy / upgrade assertion helpers for service-catalog lanes.

Validates that a workload can be upgraded by changing image tag or
config and re-applying manifests. Corresponds to §5 of the
service-catalog contract (#66).
"""

from __future__ import annotations

import json

from tests.service_catalog.shared.kube import (
    NAMESPACE,
    TEST_LANE,
    require_kubectl,
    run_kubectl,
    write_artifact,
)


def capture_deployment_state(deployment_name: str, suffix: str) -> dict:
    raw = require_kubectl(
        "get", "deployment", deployment_name, "-n", NAMESPACE, "-o", "json",
    )
    write_artifact(f"{TEST_LANE}-upgrade-{suffix}.json", raw)
    return json.loads(raw)


def set_image(deployment_name: str, container_name: str, new_image: str) -> None:
    result = run_kubectl(
        "set", "image",
        f"deployment/{deployment_name}",
        f"{container_name}={new_image}",
        "-n", NAMESPACE,
    )
    assert result.returncode == 0, (
        f"set image failed: {result.stdout}{result.stderr}"
    )
    write_artifact(f"{TEST_LANE}-upgrade-apply.txt", result.stdout + result.stderr)


def wait_for_rollout(deployment_name: str) -> None:
    result = run_kubectl(
        "rollout", "status", f"deployment/{deployment_name}",
        "-n", NAMESPACE, "--timeout=300s",
    )
    assert result.returncode == 0, (
        f"rollout status failed: {result.stdout}{result.stderr}"
    )
    write_artifact(f"{TEST_LANE}-upgrade-rollout.txt", result.stdout + result.stderr)


def get_running_image(deployment_name: str, app_label: str) -> str:
    raw = require_kubectl(
        "get", "pods", "-n", NAMESPACE, "-l", app_label,
        "-o", "jsonpath={.items[0].spec.containers[0].image}",
    )
    write_artifact(f"{TEST_LANE}-upgrade-image.txt", raw)
    return raw.strip()


def assert_image_upgrade(
    deployment_name: str,
    container_name: str,
    new_image: str,
    app_label: str,
) -> None:
    capture_deployment_state(deployment_name, "before")
    set_image(deployment_name, container_name, new_image)
    wait_for_rollout(deployment_name)
    capture_deployment_state(deployment_name, "after")
    running = get_running_image(deployment_name, app_label)
    assert running == new_image, (
        f"Running image {running} does not match expected {new_image}"
    )
