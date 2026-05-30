from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path


NAMESPACE = os.environ["TEST_NAMESPACE"]
APP_LABEL = os.environ.get("TEST_APP_LABEL", "app=service-catalog-workload")
SERVICE_NAME = os.environ.get("TEST_SERVICE_NAME", "service-catalog")
TEST_NAMESPACE = NAMESPACE
TEST_SERVICE_NAME = SERVICE_NAME
TEST_LANE = os.environ.get("TEST_LANE", "")
RESULTS_DIR = Path(os.environ.get("TEST_RESULTS_DIR", "/tmp/results"))
RESULTS_DIR.mkdir(parents=True, exist_ok=True)



def run_kubectl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def require_kubectl(*args: str) -> str:
    result = run_kubectl(*args)
    assert result.returncode == 0, (
        f"kubectl {' '.join(args)} failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stdout


def write_artifact(name: str, content: str) -> None:
    (RESULTS_DIR / name).write_text(content)


def get_pods_json() -> dict:
    return json.loads(require_kubectl("get", "pods", "-n", NAMESPACE, "-l", APP_LABEL, "-o", "json"))


def restart_workload() -> None:
    restart = run_kubectl("rollout", "restart", "deployment/service-catalog-workload", "-n", NAMESPACE)
    assert restart.returncode == 0, restart.stdout + restart.stderr
    write_artifact(f"{TEST_LANE}-restart.txt", restart.stdout + restart.stderr)
    status = run_kubectl(
        "rollout",
        "status",
        "deployment/service-catalog-workload",
        "-n",
        NAMESPACE,
        "--timeout=300s",
    )
    assert status.returncode == 0, status.stdout + status.stderr
    write_artifact(f"{TEST_LANE}-rollout-status.txt", status.stdout + status.stderr)


def first_pod_name() -> str:
    data = get_pods_json()
    items = data.get("items", [])
    assert items, "No service-catalog pod found"
    return items[0]["metadata"]["name"]


def http_get() -> str:
    url = f"http://{SERVICE_NAME}.{NAMESPACE}.svc.cluster.local:8080/"
    with urllib.request.urlopen(url, timeout=15) as response:
        body = response.read().decode()
    write_artifact(f"{TEST_LANE}-http-body.txt", body)
    return body
