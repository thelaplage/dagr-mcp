"""Tests for dagr_mcp.cg_extension — CG execution packet ref extension builder.

EXECUTION-BINDING0 L07 — dagr-mcp producer-side helper.

REF-ONLY discipline: only digest + packet_id in the extension. No
authority-shaped field is present — NE-11 structural absence, per the #149
CGResearchInput ruling (no EXECUTION-BINDING carve-out). Vocabulary
(EXECUTION-BINDING-VOCAB0): ref != replay != truth.

Tests cover:
  - build_cg_extension: valid construction, format validation, digest/id cross-check
  - validate_cg_extension: None/empty pass-through, valid shape, malformed shape
  - vocabulary discipline: no authority-shaped field is ever present (structural
    absence, not a pinned-to-none value)
  - closed shape: an injected authority-shaped (or any other unexpected) field
    is rejected
  - integration: extension produced by build_cg_extension passes validate_cg_extension
  - no raw content keys survive (REF-ONLY)
"""

from __future__ import annotations

import pytest

from dagr_mcp.cg_extension import (
    CGExtensionError,
    build_cg_extension,
    validate_cg_extension,
)

# ── shared constants ──────────────────────────────────────────────────────────

_DIGEST_A = "sha256:" + "a" * 64
_PACKET_ID_A = "cg:execution-packet:sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_PACKET_ID_B = "cg:execution-packet:sha256:" + "b" * 64


# ── build_cg_extension: valid cases ──────────────────────────────────────────

class TestBuildCGExtensionValid:
    def test_returns_nested_dict(self):
        ext = build_cg_extension(_DIGEST_A, _PACKET_ID_A)
        assert isinstance(ext, dict)
        assert "cg" in ext
        assert "execution_packet_ref" in ext["cg"]

    def test_fields_present(self):
        ext = build_cg_extension(_DIGEST_A, _PACKET_ID_A)
        ref = ext["cg"]["execution_packet_ref"]
        assert ref["execution_packet_digest"] == _DIGEST_A
        assert ref["packet_id"] == _PACKET_ID_A

    def test_no_authority_shaped_field_present(self):
        """NE-11 structural absence: non-authority is expressed by the absence
        of an authority-shaped field, never by pinning one to "none"/0/a
        frozen const (#149 ruling: no EXECUTION-BINDING carve-out)."""
        ext = build_cg_extension(_DIGEST_A, _PACKET_ID_A)
        ref = ext["cg"]["execution_packet_ref"]
        authority_shaped = {
            "authority_effect", "authority_movement", "admission_effect",
            "standing_effect", "trust_effect",
        }
        assert not (set(ref.keys()) & authority_shaped)

    def test_exactly_two_ref_fields(self):
        ext = build_cg_extension(_DIGEST_A, _PACKET_ID_A)
        ref = ext["cg"]["execution_packet_ref"]
        assert set(ref.keys()) == {"execution_packet_digest", "packet_id"}

    def test_different_digest_accepted(self):
        ext = build_cg_extension(_DIGEST_B, _PACKET_ID_B)
        ref = ext["cg"]["execution_packet_ref"]
        assert ref["execution_packet_digest"] == _DIGEST_B
        assert ref["packet_id"] == _PACKET_ID_B

    def test_extension_key_is_cg(self):
        ext = build_cg_extension(_DIGEST_A, _PACKET_ID_A)
        assert list(ext.keys()) == ["cg"]


# ── build_cg_extension: invalid cases ────────────────────────────────────────

class TestBuildCGExtensionInvalid:
    def test_malformed_digest_rejected(self):
        with pytest.raises(CGExtensionError, match="execution_packet_digest"):
            build_cg_extension("not-a-sha256", _PACKET_ID_A)

    def test_wrong_digest_prefix_rejected(self):
        with pytest.raises(CGExtensionError, match="execution_packet_digest"):
            build_cg_extension("md5:" + "a" * 32, _PACKET_ID_A)

    def test_uppercase_hex_in_digest_rejected(self):
        with pytest.raises(CGExtensionError, match="execution_packet_digest"):
            build_cg_extension("sha256:" + "A" * 64, _PACKET_ID_A)

    def test_malformed_packet_id_rejected(self):
        with pytest.raises(CGExtensionError, match="packet_id"):
            build_cg_extension(_DIGEST_A, "bad-id")

    def test_wrong_packet_id_prefix_rejected(self):
        with pytest.raises(CGExtensionError, match="packet_id"):
            build_cg_extension(_DIGEST_A, "sha256:" + "a" * 64)

    def test_packet_id_not_encoding_digest_rejected(self):
        with pytest.raises(CGExtensionError, match="packet_id"):
            build_cg_extension(_DIGEST_A, _PACKET_ID_B)  # B encodes different hex

    def test_empty_string_digest_rejected(self):
        with pytest.raises(CGExtensionError):
            build_cg_extension("", _PACKET_ID_A)

    def test_empty_string_packet_id_rejected(self):
        with pytest.raises(CGExtensionError):
            build_cg_extension(_DIGEST_A, "")


# ── validate_cg_extension ────────────────────────────────────────────────────

class TestValidateCGExtension:
    def test_none_passes(self):
        validate_cg_extension(None)  # no raise

    def test_empty_dict_passes(self):
        validate_cg_extension({})  # no raise

    def test_extensions_without_cg_key_passes(self):
        validate_cg_extension({"mcp": {"binding_version": "fastmcp@3.x"}})

    def test_valid_extension_passes(self):
        ext = build_cg_extension(_DIGEST_A, _PACKET_ID_A)
        validate_cg_extension(ext)  # no raise

    def test_malformed_digest_in_extension_rejected(self):
        ext = {
            "cg": {
                "execution_packet_ref": {
                    "execution_packet_digest": "bad-digest",
                    "packet_id": _PACKET_ID_A,
                }
            }
        }
        with pytest.raises(CGExtensionError, match="execution_packet_digest"):
            validate_cg_extension(ext)

    def test_digest_packet_id_mismatch_rejected(self):
        ext = {
            "cg": {
                "execution_packet_ref": {
                    "execution_packet_digest": _DIGEST_A,
                    "packet_id": _PACKET_ID_B,  # encodes different hex
                }
            }
        }
        with pytest.raises(CGExtensionError, match="packet_id"):
            validate_cg_extension(ext)

    def test_cg_not_dict_rejected(self):
        with pytest.raises(CGExtensionError, match="must be a dict"):
            validate_cg_extension({"cg": "not-a-dict"})

    def test_exec_packet_ref_not_dict_rejected(self):
        with pytest.raises(CGExtensionError, match="must be a dict"):
            validate_cg_extension({"cg": {"execution_packet_ref": "bad"}})

    def test_valid_shape_without_authority_field_passes(self):
        """The closed two-key shape (no authority-shaped field) is valid on
        its own — structural absence is the passing case, not an error."""
        ext = {
            "cg": {
                "execution_packet_ref": {
                    "execution_packet_digest": _DIGEST_A,
                    "packet_id": _PACKET_ID_A,
                }
            }
        }
        validate_cg_extension(ext)  # no raise


# ── hostile: injected authority-shaped field must be rejected ────────────────

class TestHostileAuthorityFieldInjection:
    """NE-11 closed-shape enforcement: an attacker/producer that injects an
    authority-shaped field onto this non-authority object must be rejected
    outright, not silently tolerated or accepted if pinned to "none"."""

    @pytest.mark.parametrize(
        "field_name",
        [
            "authority_effect",
            "authority_movement",
            "admission_effect",
            "standing_effect",
            "trust_effect",
        ],
    )
    def test_injected_authority_field_rejected(self, field_name):
        ext = {
            "cg": {
                "execution_packet_ref": {
                    "execution_packet_digest": _DIGEST_A,
                    "packet_id": _PACKET_ID_A,
                    field_name: "none",
                }
            }
        }
        with pytest.raises(CGExtensionError, match="closed shape"):
            validate_cg_extension(ext)

    def test_injected_authority_field_with_elevated_value_also_rejected(self):
        ext = {
            "cg": {
                "execution_packet_ref": {
                    "execution_packet_digest": _DIGEST_A,
                    "packet_id": _PACKET_ID_A,
                    "authority_effect": "full",
                }
            }
        }
        with pytest.raises(CGExtensionError, match="closed shape"):
            validate_cg_extension(ext)

    def test_injected_unrelated_extra_key_also_rejected(self):
        """Closed shape rejects ANY unexpected key, not just authority-shaped
        ones — the shape itself, not a field-by-field denylist, is the
        control."""
        ext = {
            "cg": {
                "execution_packet_ref": {
                    "execution_packet_digest": _DIGEST_A,
                    "packet_id": _PACKET_ID_A,
                    "unexpected_field": "value",
                }
            }
        }
        with pytest.raises(CGExtensionError, match="closed shape"):
            validate_cg_extension(ext)


# ── round-trip: build → validate ─────────────────────────────────────────────

class TestRoundTrip:
    def test_built_extension_passes_validation(self):
        ext = build_cg_extension(_DIGEST_A, _PACKET_ID_A)
        validate_cg_extension(ext)  # must not raise

    def test_built_merged_with_other_extensions_passes(self):
        cg_ext = build_cg_extension(_DIGEST_A, _PACKET_ID_A)
        merged = {"mcp": {"binding_version": "fastmcp@3.x"}, **cg_ext}
        validate_cg_extension(merged)  # no raise


# ── vocabulary discipline ─────────────────────────────────────────────────────

class TestVocabularyDiscipline:
    """EXECUTION-BINDING-VOCAB0: ref != replay != truth != authority.

    NE-11 structural absence: non-authority is expressed by the absence of
    an authority-shaped field on this object, never by pinning one to
    "none" (#149 ruling — no EXECUTION-BINDING carve-out)."""

    def test_no_authority_shaped_constant_exported(self):
        import dagr_mcp.cg_extension as cg_ext_module
        assert "AUTHORITY_EFFECT" not in dir(cg_ext_module)
        assert "AUTHORITY_EFFECT" not in cg_ext_module.__all__

    def test_no_raw_content_keys_in_extension(self):
        ext = build_cg_extension(_DIGEST_A, _PACKET_ID_A)
        ref = ext["cg"]["execution_packet_ref"]
        forbidden = {
            "raw_content", "result", "result_bytes", "tool_result",
            "response_body", "request_body", "prompt", "verified",
            "proof", "evidence", "admitted",
        }
        assert not (set(ref.keys()) & forbidden), (
            f"forbidden keys in extension ref: {set(ref.keys()) & forbidden}"
        )
