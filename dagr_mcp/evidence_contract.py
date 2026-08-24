"""MCP evidence contract — MCP-EVIDENCE-CONTRACT0.

A portable, additive, transport- and vendor-neutral machine-readable
declaration that MAY be attached to an MCP tool description under the
``x-evidence-contract`` key, so discovery can express what a tool is
*capable of producing* without confusing capability metadata with truth,
admission, publication, or authority.

Schema (declarative authority for non-Python consumers):
    schemas/mcp-evidence-contract/v0.1/x-evidence-contract.v0.1.schema.json

This module is the Python model/validation support for that schema. It does
not depend on FastMCP, the official MCP SDK, any specific binding, or on
SRS receipt machinery — it operates purely on the plain-dict JSON shape of
an MCP tool descriptor, which is the transport- and vendor-neutral surface
the mission requires.

SAM is one motivating consumer of this contract. SAM is not referenced here
and this module encodes no SAM-specific or Counterpedia-specific record
identity — see ``output_kind`` in the schema docstring.

Core doctrine (do not weaken):

    tool_declares_capability != invocation_produced_artifact
    invocation_produced_artifact != artifact_verified
    artifact_verified != evidence_supported
    evidence_supported != admitted
    admitted != published

A tool declaration is a claim about the tool *contract*, not proof that any
particular invocation satisfied it. A discovery registry may filter on this
contract, but it must never upgrade the standing of returned content because
of it.

AUTHORITY_MOVEMENT = 0. This module makes no admission, publication, or
verification decision, and ``authority_effect`` is fixed to ``"none"`` for
every v0.1 instance — there is no code path that produces any other value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

import rfc8785

# --------------------------------------------------------------------------- #
# Contract identity                                                          #
# --------------------------------------------------------------------------- #

#: Fixed contract_version value for this schema generation. Never widened to
#: cover a second schema version — a future v0.2 gets its own constant and
#: its own schema file, per the single-global-identity-constant discipline
#: this repository applies to SRS profile identities.
EVIDENCE_CONTRACT_VERSION = "mcp.evidence_contract.v0.1"

#: The vendor-extension key this contract attaches under on an MCP tool
#: description. Chosen to match the common MCP/OpenAPI convention of
#: prefixing non-protocol vendor extensions with "x-".
EVIDENCE_CONTRACT_EXTENSION_KEY = "x-evidence-contract"

#: authority_effect is fixed to "none" in v0.1. There is no constructor path
#: in this module that can produce any other value.
AUTHORITY_EFFECT = "none"

#: Closed v0.1 vocabulary for eligible_uses. Deliberately does NOT include
#: "admission", "publication", or "factual_truth" — those cannot be asserted
#: as positive (eligible) guarantees in v0.1, structurally, not by convention.
ELIGIBLE_USES: tuple[str, ...] = ("discovery", "evidence_candidate", "citation_candidate")

#: Fixed v0.1 vocabulary for ineligible_uses. Every v0.1 declaration must
#: disclose exactly this set — no more, no fewer, none omitted.
REQUIRED_INELIGIBLE_USES: tuple[str, ...] = ("admission", "publication", "factual_truth")

#: Digest algorithms this v0.1 schema recognizes as a mechanically
#: interpretable claim. Anything else is a malformed algorithm token.
RECOGNIZED_DIGEST_ALGORITHMS: frozenset[str] = frozenset({"sha256", "sha512"})

# --------------------------------------------------------------------------- #
# Core doctrine chain and non-equivalences (NEQ-EVC-01..05)                  #
# --------------------------------------------------------------------------- #
#
# A tool declaration is a claim about the tool contract, not proof that any
# particular invocation satisfied it. These stages are ordered but each
# adjacent pair is a distinct, non-implying fact — satisfying one is never
# grounds to infer the next. Consumers (including discovery registries) MUST
# NOT collapse this chain.

#: Ordered stage names in the core doctrine chain. Order reflects a typical
#: lifecycle progression, not an implication relation — see NON_EQUIVALENCES.
CORE_DOCTRINE_CHAIN: tuple[str, ...] = (
    "tool_declares_capability",
    "invocation_produced_artifact",
    "artifact_verified",
    "evidence_supported",
    "admitted",
    "published",
)

#: Each entry is (lhs_label, rhs_label, narrative), documenting what must NOT
#: be inferred from the presence of an x-evidence-contract declaration or
#: from any single stage of CORE_DOCTRINE_CHAIN. Mirrors the NON_EQUIVALENCES
#: convention in dagr_mcp.coverage.
NON_EQUIVALENCES: dict[str, tuple[str, str, str]] = {
    "NEQ-EVC-01": (
        "tool_declares_capability",
        "invocation_produced_artifact",
        "A tool declaring an evidence contract (this schema) is a claim about "
        "the tool, not evidence that any particular invocation produced the "
        "declared artifact.",
    ),
    "NEQ-EVC-02": (
        "invocation_produced_artifact",
        "artifact_verified",
        "An artifact having been produced by an invocation does not mean the "
        "artifact's content or the claimed guarantees were independently "
        "verified. Emitter assertion != independently-recomputed finding.",
    ),
    "NEQ-EVC-03": (
        "artifact_verified",
        "evidence_supported",
        "Verifying an artifact's structure/digest does not by itself mean the "
        "artifact supports any particular evidentiary claim it is cited for.",
    ),
    "NEQ-EVC-04": (
        "evidence_supported",
        "admitted",
        "Evidence support is a discovery/citation-candidate signal, not an "
        "admission decision. authority_effect is fixed to 'none' in v0.1: "
        "this contract cannot admit anything.",
    ),
    "NEQ-EVC-05": (
        "admitted",
        "published",
        "Admission is a distinct authority boundary from publication; neither "
        "is asserted, implied, or upgraded by this contract in v0.1.",
    ),
}

_EVIDENCE_GUARANTEES_FIELDS: frozenset[str] = frozenset(
    {
        "exact_bytes_available",
        "stable_identity_available",
        "digest_available",
        "digest_algorithm",
        "retrieval_observation_available",
        "provenance_lineage_ref_available",
    }
)

_OUTPUT_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_CONTRACT_TOP_LEVEL_FIELDS: frozenset[str] = frozenset(
    {
        "contract_version",
        "output_kind",
        "evidence_guarantees",
        "eligible_uses",
        "ineligible_uses",
        "authority_effect",
    }
)


class EvidenceContractError(ValueError):
    """Raised when an x-evidence-contract declaration violates the v0.1 contract.

    Covers unknown-field rejection (fail closed), contradictory guarantees,
    malformed digest algorithms, and any attempt to assert a positive
    admission/publication/factual_truth/authority guarantee.
    """


# --------------------------------------------------------------------------- #
# EvidenceGuarantees                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EvidenceGuarantees:
    """The mechanically interpretable evidence-capability guarantees block.

    Every field is an explicit boolean (or, for ``digest_algorithm``, an enum
    string / None) — no prose. A guarantee that cannot be mechanically
    interpreted must not be claimed.

    Fields
    ------
    exact_bytes_available :
        Whether the tool's output is claimed to carry the exact bytes of the
        underlying artifact, as opposed to a paraphrase or rendering.
    stable_identity_available :
        Whether the output carries an identity reference stable enough to
        re-resolve the same artifact across invocations.
    digest_available :
        Whether the output carries a content digest of the artifact.
    digest_algorithm :
        The digest algorithm, when ``digest_available`` is True. Must be
        ``None`` when ``digest_available`` is False (CR-EVC-01).
    retrieval_observation_available :
        Whether the output carries an observation of the retrieval event
        itself, independent of the fetched content's truth.
    provenance_lineage_ref_available :
        Whether the output carries a *reference* to the artifact's
        provenance/lineage chain (never inline provenance content).
    """

    exact_bytes_available: bool
    stable_identity_available: bool
    digest_available: bool
    digest_algorithm: str | None
    retrieval_observation_available: bool
    provenance_lineage_ref_available: bool

    def __post_init__(self) -> None:
        for name in (
            "exact_bytes_available",
            "stable_identity_available",
            "digest_available",
            "retrieval_observation_available",
            "provenance_lineage_ref_available",
        ):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise EvidenceContractError(
                    f"evidence_guarantees.{name} must be a bool, got {value!r}"
                )

        # CR-EVC-01: digest_algorithm <-> digest_available must not contradict.
        if self.digest_available:
            if self.digest_algorithm not in RECOGNIZED_DIGEST_ALGORITHMS:
                raise EvidenceContractError(
                    "CR-EVC-01: evidence_guarantees.digest_algorithm must be one "
                    f"of {sorted(RECOGNIZED_DIGEST_ALGORITHMS)!r} when "
                    f"digest_available is true; got {self.digest_algorithm!r}"
                )
        else:
            if self.digest_algorithm is not None:
                raise EvidenceContractError(
                    "CR-EVC-01: evidence_guarantees.digest_algorithm must be null "
                    f"when digest_available is false; got {self.digest_algorithm!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "exact_bytes_available": self.exact_bytes_available,
            "stable_identity_available": self.stable_identity_available,
            "digest_available": self.digest_available,
            "digest_algorithm": self.digest_algorithm,
            "retrieval_observation_available": self.retrieval_observation_available,
            "provenance_lineage_ref_available": self.provenance_lineage_ref_available,
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "EvidenceGuarantees":
        if not isinstance(data, Mapping):
            raise EvidenceContractError("evidence_guarantees must be an object")
        unknown = set(data.keys()) - _EVIDENCE_GUARANTEES_FIELDS
        if unknown:
            raise EvidenceContractError(
                f"evidence_guarantees has unknown field(s): {sorted(unknown)!r} "
                "(unknown fields fail closed)"
            )
        missing = _EVIDENCE_GUARANTEES_FIELDS - set(data.keys())
        if missing:
            raise EvidenceContractError(
                f"evidence_guarantees is missing required field(s): {sorted(missing)!r}"
            )
        return EvidenceGuarantees(
            exact_bytes_available=data["exact_bytes_available"],
            stable_identity_available=data["stable_identity_available"],
            digest_available=data["digest_available"],
            digest_algorithm=data["digest_algorithm"],
            retrieval_observation_available=data["retrieval_observation_available"],
            provenance_lineage_ref_available=data["provenance_lineage_ref_available"],
        )


# --------------------------------------------------------------------------- #
# EvidenceContract                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EvidenceContract:
    """A validated ``x-evidence-contract`` v0.1 declaration.

    Construct via :func:`build_evidence_contract` (recommended) or the
    dataclass constructor directly; both apply the same conformance checks
    in ``__post_init__``. Use :meth:`from_dict` to parse and validate an
    untrusted dict (e.g. one read off an MCP tool descriptor over the wire).
    """

    contract_version: str
    output_kind: str
    evidence_guarantees: EvidenceGuarantees
    eligible_uses: tuple[str, ...]
    ineligible_uses: tuple[str, ...]
    authority_effect: str

    def __post_init__(self) -> None:
        if self.contract_version != EVIDENCE_CONTRACT_VERSION:
            raise EvidenceContractError(
                f"contract_version must be {EVIDENCE_CONTRACT_VERSION!r}; "
                f"got {self.contract_version!r}"
            )

        if not isinstance(self.output_kind, str) or not self.output_kind.strip():
            raise EvidenceContractError("output_kind must be a non-empty string")
        if not _OUTPUT_KIND_PATTERN.match(self.output_kind):
            raise EvidenceContractError(
                "output_kind must match ^[a-z][a-z0-9_]*$ (a generic, "
                f"vendor-neutral snake_case token); got {self.output_kind!r}"
            )

        if not isinstance(self.evidence_guarantees, EvidenceGuarantees):
            raise EvidenceContractError(
                "evidence_guarantees must be an EvidenceGuarantees instance"
            )

        eligible = tuple(self.eligible_uses)
        if not eligible:
            raise EvidenceContractError("eligible_uses must be non-empty")
        if len(set(eligible)) != len(eligible):
            raise EvidenceContractError("eligible_uses must not contain duplicates")
        invalid_eligible = set(eligible) - set(ELIGIBLE_USES)
        if invalid_eligible:
            # This is the structural enforcement of "publication and admission
            # cannot be asserted as positive guarantees": any token outside
            # the closed v0.1 eligible vocabulary is rejected here, including
            # (but not limited to) "admission", "publication", and
            # "factual_truth" themselves.
            raise EvidenceContractError(
                "eligible_uses contains value(s) outside the v0.1 eligible "
                f"vocabulary {ELIGIBLE_USES!r}: {sorted(invalid_eligible)!r}"
            )

        ineligible = tuple(self.ineligible_uses)
        if len(set(ineligible)) != len(ineligible):
            raise EvidenceContractError("ineligible_uses must not contain duplicates")
        invalid_ineligible = set(ineligible) - set(REQUIRED_INELIGIBLE_USES)
        if invalid_ineligible:
            raise EvidenceContractError(
                "ineligible_uses contains value(s) outside the v0.1 fixed "
                f"vocabulary {REQUIRED_INELIGIBLE_USES!r}: "
                f"{sorted(invalid_ineligible)!r}"
            )
        missing_ineligible = set(REQUIRED_INELIGIBLE_USES) - set(ineligible)
        if missing_ineligible:
            raise EvidenceContractError(
                "ineligible_uses must always disclose the full v0.1 fixed set "
                f"{REQUIRED_INELIGIBLE_USES!r}; missing "
                f"{sorted(missing_ineligible)!r}"
            )

        if self.authority_effect != AUTHORITY_EFFECT:
            raise EvidenceContractError(
                f"authority_effect must be {AUTHORITY_EFFECT!r} in v0.1; "
                f"got {self.authority_effect!r}"
            )

    # -- serialization -------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict projection, in stable field order, ready for JSON."""
        return {
            "contract_version": self.contract_version,
            "output_kind": self.output_kind,
            "evidence_guarantees": self.evidence_guarantees.to_dict(),
            "eligible_uses": list(self.eligible_uses),
            "ineligible_uses": list(self.ineligible_uses),
            "authority_effect": self.authority_effect,
        }

    def to_tool_extension(self) -> dict[str, Any]:
        """Wrap as the ``{"x-evidence-contract": {...}}`` sub-object.

        The returned mapping is suitable for merging into (not replacing) an
        existing MCP tool description dict — it introduces exactly one new
        top-level key and leaves every other field of the descriptor
        untouched, satisfying the additive-only constraint.
        """
        return {EVIDENCE_CONTRACT_EXTENSION_KEY: self.to_dict()}

    def canonical_bytes(self) -> bytes:
        """RFC 8785 (JCS) canonical serialization of :meth:`to_dict`.

        Deterministic: semantically identical contracts always produce byte-
        identical output regardless of construction order, matching the
        canonicalization convention this repository already uses for SRS
        receipt content (see ``dagr_mcp.srs_receipts``).
        """
        try:
            return rfc8785.dumps(self.to_dict())
        except Exception as exc:  # pragma: no cover - defensive
            raise EvidenceContractError(
                "evidence contract is not RFC 8785 canonicalizable"
            ) from exc

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "EvidenceContract":
        """Parse and validate an untrusted ``x-evidence-contract`` object.

        Unknown top-level fields fail closed (rejected), per this
        repository's existing compatibility conventions.
        """
        if not isinstance(data, Mapping):
            raise EvidenceContractError("x-evidence-contract must be an object")
        unknown = set(data.keys()) - _CONTRACT_TOP_LEVEL_FIELDS
        if unknown:
            raise EvidenceContractError(
                f"x-evidence-contract has unknown field(s): {sorted(unknown)!r} "
                "(unknown fields fail closed)"
            )
        missing = _CONTRACT_TOP_LEVEL_FIELDS - set(data.keys())
        if missing:
            raise EvidenceContractError(
                f"x-evidence-contract is missing required field(s): {sorted(missing)!r}"
            )

        eg_raw = data["evidence_guarantees"]
        evidence_guarantees = EvidenceGuarantees.from_dict(eg_raw)

        eligible_raw = data["eligible_uses"]
        if not isinstance(eligible_raw, (list, tuple)):
            raise EvidenceContractError("eligible_uses must be an array")

        ineligible_raw = data["ineligible_uses"]
        if not isinstance(ineligible_raw, (list, tuple)):
            raise EvidenceContractError("ineligible_uses must be an array")

        return EvidenceContract(
            contract_version=data["contract_version"],
            output_kind=data["output_kind"],
            evidence_guarantees=evidence_guarantees,
            eligible_uses=tuple(eligible_raw),
            ineligible_uses=tuple(ineligible_raw),
            authority_effect=data["authority_effect"],
        )


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #


def build_evidence_contract(
    *,
    output_kind: str,
    exact_bytes_available: bool,
    stable_identity_available: bool,
    digest_available: bool,
    digest_algorithm: str | None = None,
    retrieval_observation_available: bool,
    provenance_lineage_ref_available: bool,
    eligible_uses: tuple[str, ...] | list[str],
) -> EvidenceContract:
    """Build a validated v0.1 :class:`EvidenceContract`.

    ``contract_version``, ``ineligible_uses``, and ``authority_effect`` are
    not caller-supplied — they are fixed by the v0.1 contract and set here,
    so there is no call path that can produce a non-conformant value.

    Raises:
        EvidenceContractError: on any conformance violation (contradictory
            guarantees, malformed digest algorithm, an eligible_uses value
            outside the closed v0.1 vocabulary, etc).
    """
    guarantees = EvidenceGuarantees(
        exact_bytes_available=exact_bytes_available,
        stable_identity_available=stable_identity_available,
        digest_available=digest_available,
        digest_algorithm=digest_algorithm,
        retrieval_observation_available=retrieval_observation_available,
        provenance_lineage_ref_available=provenance_lineage_ref_available,
    )
    return EvidenceContract(
        contract_version=EVIDENCE_CONTRACT_VERSION,
        output_kind=output_kind,
        evidence_guarantees=guarantees,
        eligible_uses=tuple(eligible_uses),
        ineligible_uses=REQUIRED_INELIGIBLE_USES,
        authority_effect=AUTHORITY_EFFECT,
    )


# --------------------------------------------------------------------------- #
# Tool descriptor helpers                                                    #
# --------------------------------------------------------------------------- #


def validate_tool_descriptor_extension(descriptor: Mapping[str, Any] | None) -> None:
    """Validate ``descriptor["x-evidence-contract"]`` if present.

    Mirrors ``dagr_mcp.cg_extension.validate_cg_extension``: a missing
    descriptor, or a descriptor without the extension key, passes silently
    — this is the mechanism by which existing MCP tool descriptors remain
    valid without ``x-evidence-contract``. Only raises when the key is
    present but malformed.

    This function is transport- and vendor-neutral: it operates on a plain
    ``Mapping`` (the wire/JSON shape of a tool descriptor), never on a
    binding-specific Tool object, so it makes no claim about and no change
    to the MCP protocol itself.

    Raises:
        EvidenceContractError: if the extension is present but violates the
            v0.1 contract.
    """
    if not descriptor:
        return
    if EVIDENCE_CONTRACT_EXTENSION_KEY not in descriptor:
        return
    ext = descriptor[EVIDENCE_CONTRACT_EXTENSION_KEY]
    if not isinstance(ext, Mapping):
        raise EvidenceContractError(
            f"{EVIDENCE_CONTRACT_EXTENSION_KEY} must be an object, got {type(ext)!r}"
        )
    EvidenceContract.from_dict(ext)


def attach_evidence_contract(
    descriptor: Mapping[str, Any], contract: EvidenceContract
) -> dict[str, Any]:
    """Return a new descriptor dict with ``x-evidence-contract`` merged in.

    Additive only: every existing key of ``descriptor`` is preserved
    unchanged; a pre-existing ``x-evidence-contract`` key (if any) is
    replaced by ``contract``'s projection. The input mapping is never
    mutated in place.
    """
    merged = dict(descriptor)
    merged.update(contract.to_tool_extension())
    return merged


__all__ = [
    "AUTHORITY_EFFECT",
    "CORE_DOCTRINE_CHAIN",
    "ELIGIBLE_USES",
    "EVIDENCE_CONTRACT_EXTENSION_KEY",
    "EVIDENCE_CONTRACT_VERSION",
    "NON_EQUIVALENCES",
    "RECOGNIZED_DIGEST_ALGORITHMS",
    "REQUIRED_INELIGIBLE_USES",
    "EvidenceContract",
    "EvidenceContractError",
    "EvidenceGuarantees",
    "attach_evidence_contract",
    "build_evidence_contract",
    "validate_tool_descriptor_extension",
]
