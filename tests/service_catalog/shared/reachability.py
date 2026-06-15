"""
Reachability assertion helpers for service-catalog lanes.

Validates cluster DNS resolution, endpoint presence, and HTTP(S)
responses. Corresponds to §4 of the service-catalog contract (#66).
"""

from __future__ import annotations

import subprocess
import urllib.request

from tests.service_catalog.shared.kube import (
    NAMESPACE,
    TEST_LANE,
    write_artifact,
)

TIMEOUT_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 15


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)


def service_fqdn(service_name: str) -> str:
    return f"{service_name}.{NAMESPACE}.svc.cluster.local"


def assert_dns_resolves(service_name: str) -> str:
    fqdn = service_fqdn(service_name)
    result = run("getent", "hosts", fqdn)
    write_artifact(f"{TEST_LANE}-dns.txt", result.stdout + result.stderr)
    assert result.returncode == 0, f"DNS resolution failed for {fqdn}: {result.stderr}"
    return result.stdout.strip()


def assert_http_reachable(service_name: str, port: int = 80, path: str = "/") -> str:
    fqdn = service_fqdn(service_name)
    url = f"http://{fqdn}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode()
        write_artifact(f"{TEST_LANE}-http.txt", body)
        return body
    except Exception as exc:
        write_artifact(f"{TEST_LANE}-http.txt", f"ERROR: {exc}")
        raise AssertionError(f"HTTP request to {url} failed: {exc}") from exc


def assert_https_reachable(
    service_name: str,
    hostname: str,
    port: int = 8443,
    path: str = "/healthz",
) -> str:
    fqdn = service_fqdn(service_name)
    result = run(
        "curl", "-sk",
        "-H", f"Host: {hostname}",
        f"https://{fqdn}:{port}{path}",
    )
    combined = result.stdout + result.stderr
    write_artifact(f"{TEST_LANE}-https.txt", combined)
    assert result.returncode == 0, f"HTTPS request failed: {result.stderr}"
    return result.stdout.strip()


def assert_tls_handshake(service_name: str, hostname: str, port: int = 8443) -> str:
    fqdn = service_fqdn(service_name)
    result = run(
        "openssl", "s_client",
        "-connect", f"{fqdn}:{port}",
        "-servername", hostname,
        "-brief",
    )
    combined = result.stdout + result.stderr
    write_artifact(f"{TEST_LANE}-tls-handshake.txt", combined)
    assert result.returncode == 0, f"TLS handshake failed: {combined}"
    assert "Protocol version" in combined, f"No protocol version in TLS output: {combined}"
    return combined
