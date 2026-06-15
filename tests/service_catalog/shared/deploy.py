"""
Deployment assertion helpers for service-catalog lanes.

Validates that a workload deployed into the test namespace reaches
a ready state and has the expected structure (Deployment, Service,
endpoints). Corresponds to §2 of the service-catalog contract (#66).
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


def get_deployment(name: str) -> dict:
    raw = require_kubectl("get", "deployment", name, "-n", NAMESPACE, "-o", "json")
    write_artifact(f"{TEST_LANE}-deployment.json", raw)
    return json.loads(raw)


def assert_deployment_ready(name: str) -> dict:
    data = get_deployment(name)
    status = data.get("status", {})
    available = status.get("availableReplicas", 0)
    ready = status.get("readyReplicas", 0)
    assert available >= 1, (
        f"Deployment {name} has {available} available replicas, expected >= 1"
    )
    assert ready >= 1, (
        f"Deployment {name} has {ready} ready replicas, expected >= 1"
    )
    return data


def get_pods(app_label: str) -> dict:
    raw = require_kubectl("get", "pods", "-n", NAMESPACE, "-l", app_label, "-o", "json")
    write_artifact(f"{TEST_LANE}-pods.json", raw)
    return json.loads(raw)


def assert_pod_running(app_label: str) -> dict:
    data = get_pods(app_label)
    items = data.get("items", [])
    assert items, f"No pods found with label {app_label} in {NAMESPACE}"
    running = [
        p for p in items
        if p.get("status", {}).get("phase") == "Running"
    ]
    assert running, (
        f"No pods in Running phase for {app_label}; "
        f"phases: {[p.get('status', {}).get('phase') for p in items]}"
    )
    return data


def get_endpoints(service_name: str) -> dict:
    raw = require_kubectl("get", "endpoints", service_name, "-n", NAMESPACE, "-o", "json")
    write_artifact(f"{TEST_LANE}-endpoints.json", raw)
    return json.loads(raw)


def assert_service_has_endpoints(service_name: str) -> dict:
    data = get_endpoints(service_name)
    subsets = data.get("subsets") or []
    addresses = [addr for s in subsets for addr in s.get("addresses", [])]
    assert addresses, (
        f"Service {service_name} has no endpoint addresses in {NAMESPACE}"
    )
    return data


def capture_events() -> str:
    result = run_kubectl(
        "get", "events", "-n", NAMESPACE,
        "--sort-by=.lastTimestamp",
    )
    output = result.stdout + result.stderr
    write_artifact(f"{TEST_LANE}-events.txt", output)
    return output
