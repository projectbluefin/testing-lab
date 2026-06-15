"""
Auth-gating lane checks for exposed homelab service UIs (#61).

Validates that an auth-gated homelab service correctly enforces
credentials over HTTPS: rejects unauthenticated requests, rejects
bad credentials, accepts valid credentials, and returns the expected
WWW-Authenticate challenge header.

Depends on the HTTPS exposure lane (#58) for transport security.
Identity-provider / SSO integration is out of scope — see follow-ups.
"""

from __future__ import annotations

import os
import subprocess

from tests.service_catalog.shared.kube import RESULTS_DIR, write_artifact


NAMESPACE = os.environ["TEST_NAMESPACE"]
SERVICE_NAME = os.environ.get("TEST_SERVICE_NAME", "homelab-access")
HOSTNAME = "homelab-access.local"
SERVICE_FQDN = f"{SERVICE_NAME}.{NAMESPACE}.svc.cluster.local"
HTTPS_PORT = 8443

TIMEOUT_SECONDS = 30

VALID_USER = "homelab"
VALID_PASS = "controlnode"

EXPECTED_REALM = "homelab"
EXPECTED_AUTH_SCHEME = "Basic"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)


def curl_auth(user: str | None = None, password: str | None = None, extra_flags: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [
        "curl", "-sk",
        "-H", f"Host: {HOSTNAME}",
    ]
    if extra_flags:
        cmd.extend(extra_flags)
    if user is not None and password is not None:
        cmd.extend(["-u", f"{user}:{password}"])
    cmd.append(f"https://{SERVICE_FQDN}:{HTTPS_PORT}/healthz")
    return run(*cmd)


class TestAuthGating:
    """Evidence suite for the auth-gating lane (#61)."""

    def test_unauthenticated_request_returns_401(self):
        result = curl_auth(extra_flags=["-o", "/dev/null", "-w", "%{http_code}"])
        write_artifact("auth-unauth-status.txt", result.stdout + result.stderr)
        assert result.returncode == 0, f"curl failed: {result.stderr}"
        assert result.stdout.strip() == "401", (
            f"Expected HTTP 401 for unauthenticated request, got: {result.stdout.strip()}"
        )

    def test_unauthenticated_response_contains_challenge(self):
        result = curl_auth(extra_flags=["-i"])
        combined = result.stdout + result.stderr
        write_artifact("auth-challenge-headers.txt", combined)
        assert result.returncode == 0, f"curl failed: {result.stderr}"
        assert "WWW-Authenticate" in result.stdout, (
            f"Missing WWW-Authenticate header in 401 response: {result.stdout}"
        )
        assert EXPECTED_AUTH_SCHEME in result.stdout, (
            f"Expected {EXPECTED_AUTH_SCHEME} auth scheme in challenge: {result.stdout}"
        )
        assert EXPECTED_REALM in result.stdout, (
            f"Expected realm '{EXPECTED_REALM}' in challenge: {result.stdout}"
        )

    def test_wrong_credentials_returns_401(self):
        result = curl_auth(
            user="wrong-user",
            password="wrong-pass",
            extra_flags=["-o", "/dev/null", "-w", "%{http_code}"],
        )
        write_artifact("auth-bad-creds-status.txt", result.stdout + result.stderr)
        assert result.returncode == 0, f"curl failed: {result.stderr}"
        assert result.stdout.strip() == "401", (
            f"Expected HTTP 401 for bad credentials, got: {result.stdout.strip()}"
        )

    def test_valid_credentials_returns_200(self):
        result = curl_auth(user=VALID_USER, password=VALID_PASS)
        write_artifact("auth-valid-creds.txt", result.stdout + result.stderr)
        assert result.returncode == 0, f"curl failed: {result.stderr}"
        assert result.stdout.strip() == "access-ok", (
            f"Expected 'access-ok' with valid credentials, got: {result.stdout.strip()}"
        )

    def test_valid_credentials_over_tls(self):
        result = curl_auth(
            user=VALID_USER,
            password=VALID_PASS,
            extra_flags=["-w", "\n%{ssl_verify_result}\n%{scheme}"],
        )
        combined = result.stdout + result.stderr
        write_artifact("auth-tls-evidence.txt", combined)
        assert result.returncode == 0, f"curl failed: {result.stderr}"
        assert "HTTPS" in combined, (
            f"Expected HTTPS scheme for auth request: {combined}"
        )

    def test_auth_failure_body_is_not_sensitive(self):
        result = curl_auth()
        write_artifact("auth-failure-body.txt", result.stdout + result.stderr)
        assert result.returncode == 0, f"curl failed: {result.stderr}"
        body = result.stdout.strip()
        assert body == "auth-required", (
            f"Expected 'auth-required' body on 401, got: {body}"
        )
        assert VALID_PASS not in body, "401 response body must not leak credentials"
        assert VALID_USER not in body, "401 response body must not leak usernames"
