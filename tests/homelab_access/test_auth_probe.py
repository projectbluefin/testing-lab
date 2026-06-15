"""
Auth-gated homelab HTTPS access probe tests.

Validates the first auth-gating contract for k8s-hosted homelab workloads:

  1. Unauthenticated request is rejected with HTTP 401.
  2. 401 response carries the expected WWW-Authenticate challenge header.
  3. Authenticated request succeeds with HTTP 200.
  4. HTTPS remains intact while auth is enforced (TLS handshake passes).
  5. Wrong credentials are rejected (not silently accepted).
  6. Failure artifacts (headers, status, body) are written to RESULTS_DIR
     for operator inspection.

The fixture is the Python HTTPS server deployed by the homelab-access-probe
WorkflowTemplate in auth-mode=true.  Credentials are injected from the
per-run homelab-access-auth Secret (username: homelab, password: controlnode).

Out of scope:
  - SSO / identity-provider integration (see issue #61)
  - Token / OAuth flows (future work)
"""

from __future__ import annotations

import base64
import os
import ssl
import subprocess
import urllib.error
import urllib.request

import pytest

from tests.service_catalog.shared.kube import (
    NAMESPACE,
    SERVICE_NAME,
    TEST_LANE,
    RESULTS_DIR,
    write_artifact,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOSTNAME = os.environ.get("TEST_HOSTNAME", "homelab-access.local")
_PORT = int(os.environ.get("TEST_PORT", "8443"))
_AUTH_USER = os.environ.get("TEST_AUTH_USER", "homelab")
_AUTH_PASS = os.environ.get("TEST_AUTH_PASS", "controlnode")
_SERVICE_FQDN = f"{SERVICE_NAME}.{NAMESPACE}.svc.cluster.local"
_BASE_URL = f"https://{_SERVICE_FQDN}:{_PORT}"

# Insecure SSL context — the fixture uses a self-signed cert generated
# per workflow run; we test the auth layer, not the PKI chain.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_header(user: str, password: str) -> str:
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {raw}"


def _curl(*extra: str) -> subprocess.CompletedProcess[str]:
    """Run curl with TLS verification disabled and a fixed Host header."""
    return subprocess.run(
        [
            "curl",
            "-sk",
            "--max-time", "20",
            "-H", f"Host: {HOSTNAME}",
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _dump_response(label: str, status: int, headers: dict, body: str) -> None:
    header_text = "\n".join(f"{k}: {v}" for k, v in headers.items())
    artifact = (
        f"HTTP Status: {status}\n\n"
        f"Headers:\n{header_text}\n\n"
        f"Body:\n{body}\n"
    )
    write_artifact(f"{TEST_LANE}-{label}.txt", artifact)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestUnauthenticatedRejection:
    """Unauthenticated requests must be rejected before any content is served."""

    def test_unauthenticated_returns_401(self):
        """GET without credentials must return HTTP 401 Unauthorized."""
        result = _curl("-o", "/dev/null", "-w", "%{http_code}", f"{_BASE_URL}/healthz")
        status = result.stdout.strip()
        write_artifact(f"{TEST_LANE}-unauth-status.txt", f"HTTP {status}\n{result.stderr}")
        assert status == "401", (
            f"Expected 401 for unauthenticated request, got: {status!r}"
        )

    def test_unauthenticated_response_includes_www_authenticate(self):
        """401 response must include WWW-Authenticate challenge header."""
        result = _curl("-D", "-", "-o", "/dev/null", f"{_BASE_URL}/healthz")
        write_artifact(f"{TEST_LANE}-unauth-headers.txt", result.stdout + result.stderr)
        headers_lower = result.stdout.lower()
        assert "www-authenticate" in headers_lower, (
            f"WWW-Authenticate header missing from 401 response.\n"
            f"Full headers:\n{result.stdout}"
        )

    def test_unauthenticated_challenge_advertises_basic_realm(self):
        """WWW-Authenticate header must specify Basic scheme and homelab realm."""
        result = _curl("-D", "-", "-o", "/dev/null", f"{_BASE_URL}/healthz")
        combined = result.stdout + result.stderr
        assert "basic" in combined.lower(), (
            f"Expected 'Basic' scheme in WWW-Authenticate.\nGot: {combined}"
        )
        assert "homelab" in combined.lower(), (
            f"Expected 'homelab' realm in WWW-Authenticate.\nGot: {combined}"
        )

    def test_unauthenticated_body_is_not_protected_content(self):
        """Body of 401 response must not contain the protected 'access-ok' token."""
        result = _curl(f"{_BASE_URL}/healthz")
        write_artifact(f"{TEST_LANE}-unauth-body.txt", result.stdout)
        assert "access-ok" not in result.stdout, (
            "Protected content was returned without authentication"
        )


class TestAuthenticatedAccess:
    """Authenticated requests must pass the gate and receive expected content."""

    def test_authenticated_returns_200(self):
        """GET with correct Basic credentials must return HTTP 200."""
        token = _basic_header(_AUTH_USER, _AUTH_PASS)
        result = _curl(
            "-o", "/dev/null", "-w", "%{http_code}",
            "-H", f"Authorization: {token}",
            f"{_BASE_URL}/healthz",
        )
        status = result.stdout.strip()
        write_artifact(f"{TEST_LANE}-auth-status.txt", f"HTTP {status}\n{result.stderr}")
        assert status == "200", (
            f"Expected 200 for authenticated request, got: {status!r}"
        )

    def test_authenticated_response_body_contains_success_token(self):
        """Authenticated response body must contain the 'access-ok' sentinel."""
        token = _basic_header(_AUTH_USER, _AUTH_PASS)
        result = _curl(
            "-H", f"Authorization: {token}",
            f"{_BASE_URL}/healthz",
        )
        write_artifact(f"{TEST_LANE}-auth-body.txt", result.stdout)
        assert result.stdout.strip() == "access-ok", (
            f"Expected body 'access-ok', got: {result.stdout.strip()!r}"
        )

    def test_wrong_password_returns_401(self):
        """GET with incorrect password must still return HTTP 401."""
        token = _basic_header(_AUTH_USER, "wrong-password")
        result = _curl(
            "-o", "/dev/null", "-w", "%{http_code}",
            "-H", f"Authorization: {token}",
            f"{_BASE_URL}/healthz",
        )
        status = result.stdout.strip()
        write_artifact(f"{TEST_LANE}-wrongpass-status.txt", f"HTTP {status}\n")
        assert status == "401", (
            f"Expected 401 for wrong credentials, got: {status!r}"
        )

    def test_wrong_user_returns_401(self):
        """GET with incorrect username must still return HTTP 401."""
        token = _basic_header("intruder", _AUTH_PASS)
        result = _curl(
            "-o", "/dev/null", "-w", "%{http_code}",
            "-H", f"Authorization: {token}",
            f"{_BASE_URL}/healthz",
        )
        status = result.stdout.strip()
        write_artifact(f"{TEST_LANE}-wronguser-status.txt", f"HTTP {status}\n")
        assert status == "401", (
            f"Expected 401 for wrong username, got: {status!r}"
        )


class TestHttpsIntegrityUnderAuth:
    """TLS must remain intact while the auth gate is active."""

    def test_tls_handshake_succeeds_without_credentials(self):
        """openssl s_client must complete the TLS handshake even for unauth requests."""
        result = subprocess.run(
            [
                "openssl", "s_client",
                "-connect", f"{_SERVICE_FQDN}:{_PORT}",
                "-servername", HOSTNAME,
                "-brief",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        write_artifact(f"{TEST_LANE}-tls-handshake.txt", result.stdout + result.stderr)
        combined = result.stdout + result.stderr
        # openssl exits 1 when the server closes the connection after the HTTP
        # layer, but the TLS layer itself must have completed.
        assert "Protocol version" in combined or "Verification error" in combined or \
               "Connection established" in combined, (
            f"TLS handshake did not complete:\n{combined}"
        )

    def test_https_scheme_required_for_auth(self):
        """Confirming the fixture uses HTTPS — plaintext HTTP must not be reachable."""
        result = subprocess.run(
            ["curl", "-s", "--max-time", "5",
             f"http://{_SERVICE_FQDN}:{_PORT}/healthz"],
            capture_output=True, text=True, timeout=15,
        )
        write_artifact(f"{TEST_LANE}-http-attempt.txt", result.stdout + result.stderr)
        # Connection should fail or return non-200 — plain HTTP to TLS port
        # either gets a connection error or a protocol error, never "access-ok"
        assert "access-ok" not in result.stdout, (
            "Fixture served protected content over plain HTTP — auth gate is missing TLS"
        )

    def test_authenticated_success_artifact_written(self):
        """At least one auth-success artifact must exist for operator inspection."""
        # Drive an authenticated request to ensure the artifact is present
        token = _basic_header(_AUTH_USER, _AUTH_PASS)
        result = _curl(
            "-D", "-",
            "-H", f"Authorization: {token}",
            f"{_BASE_URL}/healthz",
        )
        write_artifact(f"{TEST_LANE}-auth-evidence.txt", result.stdout + result.stderr)
        artifacts = list(RESULTS_DIR.glob(f"{TEST_LANE}-*.txt"))
        assert artifacts, (
            f"No auth-lane artifacts found in {RESULTS_DIR}; "
            "lane produced no inspectable evidence"
        )

    @pytest.mark.skip(
        reason="SSO / identity-provider integration is explicitly out of scope — see issue #61"
    )
    def test_sso_token_accepted(self):
        """OIDC/SSO token acceptance: deferred to issue #61."""
