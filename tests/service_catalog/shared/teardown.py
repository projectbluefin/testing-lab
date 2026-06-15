"""
Teardown assertion helpers for service-catalog lanes.

Provides namespace cleanup verification. The actual teardown is
performed by the Argo Workflow onExit handler, not by test code.
These helpers allow tests to verify pre-conditions about namespace
state. Corresponds to §6 of the service-catalog contract (#66).
"""

from __future__ import annotations

import json

from tests.service_catalog.shared.kube import (
    NAMESPACE,
    TEST_LANE,
    run_kubectl,
    write_artifact,
)


def assert_namespace_exists() -> dict:
    result = run_kubectl("get", "namespace", NAMESPACE, "-o", "json")
    assert result.returncode == 0, (
        f"Namespace {NAMESPACE} does not exist: {result.stderr}"
    )
    data = json.loads(result.stdout)
    write_artifact(f"{TEST_LANE}-namespace.json", result.stdout)
    return data


def assert_no_cluster_scoped_leaks(label_selector: str) -> None:
    for kind in ("clusterrole", "clusterrolebinding"):
        result = run_kubectl("get", kind, "-l", label_selector, "-o", "json")
        if result.returncode != 0:
            continue
        data = json.loads(result.stdout)
        items = data.get("items", [])
        names = [item["metadata"]["name"] for item in items]
        write_artifact(f"{TEST_LANE}-{kind}-leak-check.json", result.stdout)
        assert not names, (
            f"Found cluster-scoped {kind} resources with label {label_selector}: {names}. "
            f"These must be cleaned up in the onExit handler."
        )
