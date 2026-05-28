"""
PVC/local-path restore drill.

Proves the full backup→wipe→restore cycle for a stateful in-cluster workload:

  1. Seed  — write a deterministic sentinel and its checksum to /data.
  2. Backup — tar the /data directory and copy the archive to the test runner.
  3. Wipe   — delete the workload deployment and PVC to simulate data loss.
  4. Reset  — redeploy the workload with a fresh empty PVC.
  5. Restore — transfer the backup archive into the new pod and extract.
  6. Verify — assert the sentinel file survives with its original checksum.

Artifact inventory:
  restore-pre-backup-pods.json  — pod state before backup
  restore-backup.tar.gz.sha256  — SHA-256 of the backup archive
  restore-backup-size.txt       — byte count of the backup archive
  restore-wipe-log.txt          — kubectl delete/create output during wipe
  restore-rollout-status.txt    — rollout convergence after reset
  restore-post-restore-pods.json — pod state after restore
  restore-verify.txt            — cat sentinel.txt + sha256sum output

Storage model: local-path ReadWriteOnce (single-pod).  RWX/shared-storage
scenarios are skipped until #62 is resolved.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import pytest

from tests.service_catalog.shared.kube import (
    TEST_NAMESPACE,
    get_pods_json,
    run_kubectl,
    write_artifact,
)


DEPLOYMENT_NAME = "homelab-restore"
PVC_NAME = "homelab-restore-data"
DATA_MOUNT = "/data"
SENTINEL = "restore-drill-sentinel-v1"
SENTINEL_PATH = f"{DATA_MOUNT}/sentinel.txt"

RESTORE_MANIFEST = f"""apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {PVC_NAME}
  labels:
    app: {DEPLOYMENT_NAME}
    app.kubernetes.io/part-of: bluefin-test-suite
    bluefin.io/lane: homelab-restore
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {DEPLOYMENT_NAME}
  labels:
    app: {DEPLOYMENT_NAME}
    app.kubernetes.io/part-of: bluefin-test-suite
    bluefin.io/lane: homelab-restore
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {DEPLOYMENT_NAME}
  template:
    metadata:
      labels:
        app: {DEPLOYMENT_NAME}
        app.kubernetes.io/part-of: bluefin-test-suite
        bluefin.io/lane: homelab-restore
    spec:
      nodeSelector:
        kubernetes.io/hostname: ghost
      containers:
        - name: fedora
          image: quay.io/fedora/fedora:latest
          command:
            - bash
            - -lc
            - |
              mkdir -p /data
              sleep infinity
          volumeMounts:
            - name: data
              mountPath: /data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: {PVC_NAME}
"""


def _require_kubectl(*args: str) -> str:
    result = run_kubectl(*args)
    assert result.returncode == 0, (
        f"kubectl {' '.join(args)} failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result.stdout


def _first_running_pod(app_label: str = f"app={DEPLOYMENT_NAME}") -> str:
    data = json.loads(
        _require_kubectl("get", "pods", "-n", TEST_NAMESPACE, "-l", app_label, "-o", "json")
    )
    items = [
        p for p in data.get("items", [])
        if p.get("status", {}).get("phase") == "Running"
    ]
    assert items, f"No Running pod found for {app_label} in {TEST_NAMESPACE}"
    return items[0]["metadata"]["name"]


def _exec_pod(pod: str, *cmd: str) -> subprocess.CompletedProcess[str]:
    return run_kubectl("exec", "-n", TEST_NAMESPACE, pod, "--", *cmd)


def _wait_for_rollout(timeout: int = 300) -> None:
    result = run_kubectl(
        "rollout", "status",
        f"deployment/{DEPLOYMENT_NAME}",
        "-n", TEST_NAMESPACE,
        f"--timeout={timeout}s",
    )
    write_artifact("restore-rollout-status.txt", result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr


class TestRestoreDrill:

    def test_seed_sentinel(self) -> None:
        """Write a deterministic sentinel and its checksum into the PVC."""
        write_artifact(
            "restore-pre-backup-pods.json",
            json.dumps(get_pods_json(), indent=2),
        )
        pod = _first_running_pod()

        result = _exec_pod(
            pod,
            "bash", "-lc",
            f"printf '%s\\n' '{SENTINEL}' > {SENTINEL_PATH}"
            f" && sha256sum {SENTINEL_PATH}",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        # Store checksum for later comparison
        write_artifact("restore-seed-checksum.txt", result.stdout.strip())

    def test_backup_captured(self) -> None:
        """Tar /data inside the pod and copy the archive to the test runner."""
        pod = _first_running_pod()

        # Create tarball inside the pod
        tar = _exec_pod(pod, "tar", "czf", "/tmp/backup.tar.gz", DATA_MOUNT)
        assert tar.returncode == 0, tar.stdout + tar.stderr

        # Copy archive from pod to runner filesystem
        cp = run_kubectl(
            "cp",
            f"{TEST_NAMESPACE}/{pod}:/tmp/backup.tar.gz",
            "/tmp/restore-backup.tar.gz",
        )
        assert cp.returncode == 0, cp.stdout + cp.stderr

        archive = Path("/tmp/restore-backup.tar.gz")
        assert archive.exists() and archive.stat().st_size > 0, "backup archive is empty"

        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        write_artifact("restore-backup.tar.gz.sha256", f"{digest}  restore-backup.tar.gz\n")
        write_artifact("restore-backup-size.txt", f"{archive.stat().st_size}\n")

    def test_wipe_workload(self) -> None:
        """Delete the deployment and PVC to simulate data loss."""
        log_parts: list[str] = []

        del_dep = run_kubectl(
            "delete", "deployment", DEPLOYMENT_NAME,
            "-n", TEST_NAMESPACE, "--ignore-not-found=True",
        )
        log_parts.append(del_dep.stdout + del_dep.stderr)

        del_pvc = run_kubectl(
            "delete", "pvc", PVC_NAME,
            "-n", TEST_NAMESPACE, "--ignore-not-found=True",
        )
        log_parts.append(del_pvc.stdout + del_pvc.stderr)

        # Wait briefly for PVC deletion to complete (may be finalised)
        deadline = time.time() + 60
        while time.time() < deadline:
            check = run_kubectl("get", "pvc", PVC_NAME, "-n", TEST_NAMESPACE)
            if check.returncode != 0:
                break
            time.sleep(3)

        write_artifact("restore-wipe-log.txt", "\n".join(log_parts))
        assert del_dep.returncode == 0, del_dep.stdout + del_dep.stderr
        assert del_pvc.returncode == 0, del_pvc.stdout + del_pvc.stderr

    def test_redeploy_after_wipe(self) -> None:
        """Recreate the workload with a fresh empty PVC."""
        apply = subprocess.run(
            ["kubectl", "apply", "-n", TEST_NAMESPACE, "-f", "-"],
            input=RESTORE_MANIFEST,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert apply.returncode == 0, apply.stdout + apply.stderr
        _wait_for_rollout()

    def test_restore_from_backup(self) -> None:
        """Copy the backup archive into the new pod and extract."""
        pod = _first_running_pod()
        archive = Path("/tmp/restore-backup.tar.gz")
        assert archive.exists(), "backup archive missing from runner filesystem"

        cp = run_kubectl(
            "cp",
            "/tmp/restore-backup.tar.gz",
            f"{TEST_NAMESPACE}/{pod}:/tmp/restore-backup.tar.gz",
        )
        assert cp.returncode == 0, cp.stdout + cp.stderr

        # Extract into / (archive contains data/sentinel.txt path)
        extract = _exec_pod(
            pod, "tar", "xzf", "/tmp/restore-backup.tar.gz", "-C", "/",
        )
        assert extract.returncode == 0, extract.stdout + extract.stderr

    def test_verify_restored_state(self) -> None:
        """Assert the sentinel and its checksum match the seeded values."""
        pod = _first_running_pod()

        result = _exec_pod(
            pod,
            "bash", "-lc",
            f"cat {SENTINEL_PATH} && sha256sum {SENTINEL_PATH}",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        write_artifact("restore-verify.txt", result.stdout + result.stderr)

        post_restore_pods = get_pods_json()
        write_artifact(
            "restore-post-restore-pods.json",
            json.dumps(post_restore_pods, indent=2),
        )

        assert SENTINEL in result.stdout, (
            f"Sentinel '{SENTINEL}' not found in restored data:\n{result.stdout}"
        )

        # Compare checksum with the seed snapshot
        seed_file = Path("/tmp/results/restore-seed-checksum.txt")
        if seed_file.exists():
            seed_line = seed_file.read_text().strip()
            seed_hash = seed_line.split()[0] if seed_line else ""
            restore_output = result.stdout.strip()
            for line in restore_output.splitlines():
                if SENTINEL_PATH in line:
                    restore_hash = line.split()[0]
                    assert restore_hash == seed_hash, (
                        f"Checksum mismatch after restore:\n"
                        f"  seed:    {seed_hash}\n"
                        f"  restore: {restore_hash}"
                    )
                    break

    def test_rwx_restore_blocked_by_design(self) -> None:
        """Cross-pod / shared-storage restore is blocked until #62 is resolved."""
        pytest.skip(
            "RWX/shared-storage restore scenarios blocked by #62 "
            "until ReadWriteMany storage class is available"
        )
