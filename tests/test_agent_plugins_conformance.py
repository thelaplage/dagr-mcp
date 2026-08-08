"""Agent Plugins Specification v1.0.0 conformance fixture tests.

Scope: representation/conformance fixture only.
Target: Agent Plugins Specification v1.0.0 Working Draft
        (https://agent-plugins.org/specification)

Claim: the canonical existing DAGR MCP configuration is representable by
Agent Plugins v1 ``mcp.json``, to the extent the evidence below supports it.

This module does NOT:
- prove a client conformant with Agent Plugins v1;
- alter DAGR MCP wire/runtime/admission semantics (governed by existing DAGR
  contracts);
- define or claim any Agent Plugins extension namespace;
- change receipt/schema authority (distributed across dagr-mcp, arcs-srs,
  arcs-verify as current owners);
- perform network access during tests.

Agent Plugins supplies portable package/configuration semantics only.
DAGR MCP semantics remain governed by existing DAGR contracts.

Legacy GARP literals encountered in the repository are compatibility debt; they
are not current naming and are not introduced here.

Representational gaps are documented below in ``TestRepresentationalGaps``.
"""

from __future__ import annotations

import io
import json
import re
import tokenize
from pathlib import Path
from urllib.parse import urlparse

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "agent_plugins" / "mcp.json"

CANONICAL_SCHEMA_URI = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

# Fields permitted at the server-entry level per each recognised type.
# Derived from the normative specification text (v1.0.0 Working Draft).
_KNOWN_FIELDS_BY_TYPE: dict[str, set[str]] = {
    "stdio": {"type", "command", "args", "env", "cwd"},
    "streamable-http": {"type", "url", "headers"},
    "sse": {"type", "url", "headers"},
}

# Loopback hosts that may use plain HTTP per rule 5.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Heuristic patterns that must not appear in fixture values — prevent accidental
# secret leakage.  These check the *serialised* fixture, not runtime config.
_SECRET_PATTERNS = [
    re.compile(r"(?i)(password|secret|token|api[_-]?key|bearer)\s*[=:]\s*\S"),
    re.compile(r"(?i)Authorization\s*[=:]"),
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),  # long base64 blobs (keys, tokens)
]


@pytest.fixture(scope="module")
def mcp_doc() -> dict:
    return json.loads(FIXTURE.read_text())


class TestFixtureCanonicalURI:
    """$schema must be exactly the canonical Agent Plugins 1.0.0 URI."""

    def test_schema_field_present(self, mcp_doc):
        assert "$schema" in mcp_doc, "mcp.json must have a top-level $schema field"

    def test_schema_uri_exact(self, mcp_doc):
        assert mcp_doc["$schema"] == CANONICAL_SCHEMA_URI, (
            f"$schema must be exactly {CANONICAL_SCHEMA_URI!r}; "
            f"got {mcp_doc['$schema']!r}"
        )


class TestTopLevelShape:
    """Top-level mcp.json must contain exactly $schema and mcpServers."""

    def test_mcp_servers_present(self, mcp_doc):
        assert "mcpServers" in mcp_doc

    def test_no_extra_top_level_keys(self, mcp_doc):
        allowed = {"$schema", "mcpServers"}
        extra = set(mcp_doc) - allowed
        assert not extra, (
            f"mcp.json must contain only {sorted(allowed)}; "
            f"unexpected top-level keys: {sorted(extra)}"
        )

    def test_mcp_servers_is_object(self, mcp_doc):
        assert isinstance(mcp_doc["mcpServers"], dict), (
            "mcpServers must be a JSON object"
        )

    def test_mcp_servers_non_empty(self, mcp_doc):
        assert mcp_doc["mcpServers"], "mcpServers must not be empty"


class TestServerTypeVariant:
    """Each server entry must declare a recognised, closed transport type."""

    def test_each_entry_has_type(self, mcp_doc):
        for key, entry in mcp_doc["mcpServers"].items():
            assert "type" in entry, f"server {key!r}: missing 'type' field"

    def test_each_entry_type_is_recognised(self, mcp_doc):
        recognised = set(_KNOWN_FIELDS_BY_TYPE)
        for key, entry in mcp_doc["mcpServers"].items():
            t = entry.get("type")
            assert t in recognised, (
                f"server {key!r}: type {t!r} is not a recognised Agent Plugins "
                f"v1 transport variant; expected one of {sorted(recognised)}"
            )

    def test_no_sse_unless_required(self, mcp_doc):
        """The deprecated 'sse' variant must not appear unless repo reality requires it."""
        for key, entry in mcp_doc["mcpServers"].items():
            assert entry.get("type") != "sse", (
                f"server {key!r}: 'sse' transport is legacy/deprecated; "
                "only include it if the existing DAGR MCP codebase requires that "
                "exact variant (it does not)"
            )


class TestNoUnknownFields:
    """Server entries must not contain fields outside the v1 closed variant shape."""

    def test_no_unknown_fields_per_type(self, mcp_doc):
        for key, entry in mcp_doc["mcpServers"].items():
            t = entry.get("type")
            if t not in _KNOWN_FIELDS_BY_TYPE:
                continue  # covered by test_each_entry_type_is_recognised
            allowed = _KNOWN_FIELDS_BY_TYPE[t]
            extra = set(entry) - allowed
            assert not extra, (
                f"server {key!r} (type={t!r}): unknown field(s) {sorted(extra)}; "
                f"permitted fields for {t!r}: {sorted(allowed)}"
            )


class TestStreamableHttpURLRules:
    """URL rules for streamable-http server entries (normative spec rule 5)."""

    @pytest.fixture
    def http_entries(self, mcp_doc) -> list[tuple[str, dict]]:
        return [
            (k, v)
            for k, v in mcp_doc["mcpServers"].items()
            if v.get("type") in ("streamable-http", "sse")
        ]

    def test_url_present(self, http_entries):
        for key, entry in http_entries:
            assert "url" in entry, f"server {key!r}: streamable-http entry missing 'url'"

    def test_url_is_string(self, http_entries):
        for key, entry in http_entries:
            assert isinstance(entry.get("url"), str), (
                f"server {key!r}: 'url' must be a string"
            )

    def test_url_is_absolute(self, http_entries):
        for key, entry in http_entries:
            url = entry.get("url", "")
            parsed = urlparse(url)
            assert parsed.scheme in ("http", "https"), (
                f"server {key!r}: url {url!r} must be absolute HTTP or HTTPS"
            )
            assert parsed.netloc, (
                f"server {key!r}: url {url!r} must have a host (netloc)"
            )

    def test_non_loopback_requires_https(self, http_entries):
        for key, entry in http_entries:
            url = entry.get("url", "")
            parsed = urlparse(url)
            host = parsed.hostname or ""
            if host not in _LOOPBACK_HOSTS and parsed.scheme == "http":
                pytest.fail(
                    f"server {key!r}: non-loopback url {url!r} must use HTTPS"
                )

    def test_no_userinfo_in_url(self, http_entries):
        for key, entry in http_entries:
            url = entry.get("url", "")
            parsed = urlparse(url)
            assert not parsed.username, (
                f"server {key!r}: url {url!r} must not contain userinfo"
            )

    def test_no_fragment_in_url(self, http_entries):
        for key, entry in http_entries:
            url = entry.get("url", "")
            parsed = urlparse(url)
            assert not parsed.fragment, (
                f"server {key!r}: url {url!r} must not contain a fragment"
            )

    def test_no_secrets_in_headers(self, http_entries):
        for key, entry in http_entries:
            headers = entry.get("headers", {})
            for h_name, h_val in headers.items():
                low = h_name.lower()
                assert low != "authorization", (
                    f"server {key!r}: 'Authorization' header must not appear in "
                    "the fixture — secrets must not be stored in mcp.json"
                )
                assert "secret" not in low and "token" not in low, (
                    f"server {key!r}: header name {h_name!r} looks like a secret"
                )


class TestNoSecretsInFixture:
    """No secret-looking content must appear anywhere in the serialised fixture."""

    def test_fixture_contains_no_secret_patterns(self):
        raw = FIXTURE.read_text()
        # Exclude the base64 pattern for short legitimate values (URLs, names).
        # Only flag very long unbroken base64 strings that look like key material.
        for pattern in _SECRET_PATTERNS[:-1]:
            assert not pattern.search(raw), (
                f"Fixture contains a pattern matching {pattern.pattern!r}; "
                "remove credentials from mcp.json"
            )
        # Long base64 check: only flag strings ≥ 60 chars to avoid false positives
        # on URL path segments.
        long_b64 = re.compile(r"[A-Za-z0-9+/]{60,}={0,2}")
        assert not long_b64.search(raw), (
            "Fixture contains a long base64-like string that may be key material"
        )


class TestNamingGate:
    """No new legacy-brand naming must be introduced in the fixture or this module.

    "garp" is the retired brand; "dagr" is canonical.  Legacy bytes elsewhere in
    the repository are migration debt and must not be replicated in new files.
    """

    def test_fixture_clean_of_legacy_brand(self):
        raw = FIXTURE.read_text().lower()
        # Exact substring match — none of the legacy brand bytes must appear in
        # the new fixture.
        assert "garp" not in raw, (
            "mcp.json fixture must not introduce the legacy brand token; "
            "DAGR is the canonical name"
        )

    def test_module_identifier_tokens_clean_of_legacy_brand(self):
        # Use tokenize so that the legacy brand in docstrings/comments (legacy
        # debt discussion) is permitted; only Python NAME tokens (identifiers)
        # are checked, because those would constitute new naming.
        raw = Path(__file__).read_text()
        reader = io.StringIO(raw).readline
        _legacy = "garp"
        for tok_type, tok_string, tok_start, _, _ in tokenize.generate_tokens(reader):
            if tok_type == tokenize.NAME and _legacy in tok_string.lower():
                pytest.fail(
                    f"Line {tok_start[0]}: legacy brand identifier token "
                    f"{tok_string!r} in test module; DAGR is the canonical name"
                )


class TestRepresentationalGaps:
    """Document and protect the known representational gaps.

    Neither gap invalidates the fixture.  They are recorded here as executable
    evidence for adjudication per the lane brief.

    Gap 1 — No registered stdio server entry point
    -----------------------------------------------
    The ``dagr-mcp`` / ``dagr-mcp-demo`` CLI entry points (``dagr_mcp.demo:main``)
    run a one-shot demo workflow that emits receipts and exits.  They do NOT start
    a persistent stdio MCP server (no ``mcp.run()`` or equivalent).  Therefore,
    the ``stdio`` variant cannot be truthfully represented in ``mcp.json`` without
    a production-code change.  The fixture deliberately omits the ``stdio`` entry;
    this test encodes that absence as an explicit assertion.

    Gap 2 — HTTP server is an example, not an installed CLI entry point
    --------------------------------------------------------------------
    The Streamable HTTP DAGR server lives in ``examples/http_proof_v2/server.py``
    and is launched via ``uvicorn examples.http_proof_v2.server:app``.  It is not
    a packaged CLI entry point in the base ``dagr-mcp`` distribution, and it
    requires the separate ``dagr-mcp-core`` + ``dagr-mcp-sdk-v2`` packages.
    The ``streamable-http`` entry in ``mcp.json`` truthfully describes the running
    server's URL; no launch command is encoded (correct for the HTTP variant).
    """

    def test_no_stdio_entry_in_fixture(self, mcp_doc):
        """Asserts the stdio gap: no stdio entry must appear until a real stdio
        server entry point is registered in the dagr-mcp package."""
        stdio_keys = [
            k for k, v in mcp_doc["mcpServers"].items() if v.get("type") == "stdio"
        ]
        assert not stdio_keys, (
            f"Unexpected stdio entries {stdio_keys}: the dagr-mcp CLI entry points "
            "do not expose a persistent stdio MCP server.  Add a stdio entry only "
            "if a new production server entry point is registered."
        )

    def test_streamable_http_server_key_matches_repo_reality(self, mcp_doc):
        """The server key must match the server name registered in
        examples/http_proof_v2/server.py (``build_governed_server`` call)."""
        expected_key = "dagr-mcp-http-proof-v2"
        assert expected_key in mcp_doc["mcpServers"], (
            f"Expected server key {expected_key!r} derived from "
            "``build_governed_server('dagr-mcp-http-proof-v2', ...)`` in "
            "examples/http_proof_v2/server.py; update the fixture if the "
            "server name changes"
        )

    def test_http_proof_v2_url_matches_server_source(self, mcp_doc):
        """The URL must match the address the http_proof_v2 server binds to:
        host=127.0.0.1, port=8765, path=/mcp (per server.py __main__ block
        and client_proof.py connection)."""
        entry = mcp_doc["mcpServers"].get("dagr-mcp-http-proof-v2", {})
        url = entry.get("url", "")
        parsed = urlparse(url)
        assert parsed.hostname == "127.0.0.1", (
            f"Expected host 127.0.0.1; got {parsed.hostname!r}"
        )
        assert parsed.port == 8765, (
            f"Expected port 8765; got {parsed.port!r}"
        )
        assert parsed.path == "/mcp", (
            f"Expected path /mcp; got {parsed.path!r}"
        )
