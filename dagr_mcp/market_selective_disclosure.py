"""Audience-scoped selective disclosure of market metadata — MARKET-SELECTIVE-DISCLOSURE0 (L07).

Projects a bounded, audience-scoped subset of a governed market record's
*metadata* fields for disclosure, identified only by a sha256 reference to
the underlying record — never the record's raw bytes.

REF-ONLY / metadata-only discipline: this module never carries raw
args/results/creds. It reuses ``dagr_mcp.srs_receipts.RAW_KEYS`` — the same
raw-content exclusion vocabulary the receipt emitter enforces — so a caller
cannot smuggle a transcript, tool argument, or credential through a
disclosure rule any more than they could through a receipt. On top of that
shared vocabulary, this module hard-blocks a second, market-specific field
family: authority, trust, standing, and secret. These are blocked by
``"_"``-delimited segment match (e.g. ``authority_level``, ``is_trusted``,
``standing_tier``, ``secret_key`` are all blocked), not by loose substring
match, so an unrelated field like ``outstanding_balance`` is not
accidentally swept in.

Vocabulary (MARKET-SELECTIVE-DISCLOSURE-VOCAB0):
  disclosure != verdict
  disclosed_field != admitted_field
  a hard-blocked field is refused from disclosure, never leaked as a value
  a ``SelectiveDisclosureEnvelope`` carries no authority-shaped field at
  all (no ``authority_effect``, ``admission_effect``, ``trust_effect``,
  or similar) — it expresses "grants no authority" by the *absence* of
  any such field from its definition, not by serializing one pinned to
  "none". Even a caller-supplied ``authority_effect`` value is unrepresentable:
  the envelope's constructor has no such parameter, so any attempt to set
  one fails closed with a ``TypeError``.

Non-goals: this module does not admit, gate, or emit an SRS receipt, and it
makes no claim about authority, trust, or standing — it has no field capable
of asserting one. It performs no policy evaluation beyond the fixed
hard-block field families below, and it does not resolve or authenticate
the audience it is scoped to — audience is an opaque caller-supplied label.
Emitting the governed record's own admission/outcome receipt remains the
job of ``dagr_mcp.srs_receipts``; this module only ever produces a
``SelectiveDisclosureEnvelope``, never a receipt.

Usage::

    from dagr_mcp.market_selective_disclosure import DisclosureRule, disclose

    envelope = disclose(
        object_id="offer:o1",
        object_digest="sha256:<64 hex>",
        payload={"offer_id": "o1", "price": 20, "trusted": True},
        rule=DisclosureRule(audience="buyer", fields=("offer_id", "price", "trusted")),
    )
    # envelope.disclosed == {"offer_id": "o1", "price": 20}
    # "trusted" was hard-blocked, not disclosed as some none-value
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from dagr_mcp.srs_receipts import RAW_KEYS

DISCLOSURE_KIND = "market_selective_disclosure.v0.1"

_DIGEST_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")

# Hard-blocked market field family (Goal: "hard-blocked authority/trust/
# standing/secret fields"). Matched by exact "_"-delimited segment, so
# variants like "authorized"/"authorization"/"trusted"/"secrets" are caught
# without over-blocking unrelated fields that merely contain one of these
# words as a substring (e.g. "outstanding_balance").
MARKET_FORBIDDEN_SEGMENTS = frozenset({
    "authority",
    "authorized",
    "authorization",
    "admitted",
    "admit",
    "trust",
    "trusted",
    "standing",
    "secret",
    "secrets",
})


class MarketSelectiveDisclosureError(ValueError):
    """Raised when a selective disclosure request or rule is malformed."""


@dataclass(frozen=True, slots=True)
class DisclosureRule:
    """A single audience's requested field allowlist.

    ``fields`` is the caller's *request*, not a guarantee: any field that is
    hard-blocked (``MARKET_FORBIDDEN_SEGMENTS``) or raw-content-excluded
    (``dagr_mcp.srs_receipts.RAW_KEYS``) is dropped by ``disclose`` even if
    named here.
    """

    audience: str
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SelectiveDisclosureEnvelope:
    """The result of projecting a payload through a ``DisclosureRule``.

    Deliberately carries no ``receipt_kind``, ``disposition``, or
    ``receipt_version`` field: a ``SelectiveDisclosureEnvelope`` is not an
    SRS receipt and must never be mistaken for one. It also carries no
    ``authority_effect`` (or any other authority-shaped) field at all —
    disclosing a field grants no authority and does not admit, and that
    fact is expressed by the field's *absence* from this dataclass, not by
    a value pinned to ``"none"``. Constructing an envelope with an
    ``authority_effect`` keyword argument fails closed with ``TypeError``,
    since no such field is defined.
    """

    disclosure_kind: str
    object_id: str
    object_digest: str
    audience: str
    disclosed: dict[str, Any]
    redacted_fields: tuple[str, ...]
    blocked_fields: tuple[str, ...]


def is_market_forbidden_field(field_name: str) -> bool:
    """True if ``field_name`` belongs to the hard-blocked market field family.

    Matches by exact ``"_"``-delimited segment against
    ``MARKET_FORBIDDEN_SEGMENTS`` — not substring — so ``authority_level``
    and ``is_trusted`` are blocked while ``outstanding_balance`` is not.
    """
    if not isinstance(field_name, str):
        return False
    segments = field_name.lower().split("_")
    return any(segment in MARKET_FORBIDDEN_SEGMENTS for segment in segments)


def _is_raw_content_field(field_name: str) -> bool:
    return field_name in RAW_KEYS


def disclose(
    *,
    object_id: str,
    object_digest: str,
    payload: Mapping[str, Any],
    rule: DisclosureRule,
) -> SelectiveDisclosureEnvelope:
    """Project ``payload`` through ``rule`` into an audience-scoped envelope.

    Only fields the audience *requested* (``rule.fields``) and that are
    *present* in ``payload`` are disclosed, minus anything hard-blocked
    (``MARKET_FORBIDDEN_SEGMENTS``) or raw-content-excluded (``RAW_KEYS``).
    ``authority_effect`` itself is a forbidden segment (``"authority"``), so
    a hostile ``rule.fields`` naming it is blocked like any other
    authority-shaped field — it can never appear in ``disclosed``. Disclosure
    is a projection, not a verdict: this function never admits and never
    emits a receipt; the returned envelope has no field capable of claiming
    otherwise.

    Raises:
        MarketSelectiveDisclosureError: if ``object_id``/``object_digest`` are
            malformed, ``payload`` is not a mapping, or ``rule`` is not a
            ``DisclosureRule``.
    """
    if not isinstance(object_id, str) or not object_id:
        raise MarketSelectiveDisclosureError(
            f"object_id must be a non-empty string; got {object_id!r}"
        )
    if not isinstance(object_digest, str) or not _DIGEST_PATTERN.match(object_digest):
        raise MarketSelectiveDisclosureError(
            "object_digest must be a sha256 reference: "
            f"'sha256:<64 lowercase hex>' or '<64 lowercase hex>'; got {object_digest!r}"
        )
    if not isinstance(payload, Mapping):
        raise MarketSelectiveDisclosureError("payload must be a mapping")
    if not isinstance(rule, DisclosureRule):
        raise MarketSelectiveDisclosureError("rule must be a DisclosureRule")
    if not isinstance(rule.audience, str) or not rule.audience:
        raise MarketSelectiveDisclosureError(
            f"rule.audience must be a non-empty string; got {rule.audience!r}"
        )

    requested = set(rule.fields)
    blocked = {
        f for f in requested if is_market_forbidden_field(f) or _is_raw_content_field(f)
    }
    allowed = requested - blocked

    disclosed = {k: payload[k] for k in sorted(allowed) if k in payload}
    redacted_fields = tuple(sorted(k for k in payload if k not in disclosed))
    blocked_fields = tuple(sorted(blocked))

    return SelectiveDisclosureEnvelope(
        disclosure_kind=DISCLOSURE_KIND,
        object_id=object_id,
        object_digest=object_digest,
        audience=rule.audience,
        disclosed=disclosed,
        redacted_fields=redacted_fields,
        blocked_fields=blocked_fields,
    )


__all__ = [
    "DISCLOSURE_KIND",
    "MARKET_FORBIDDEN_SEGMENTS",
    "DisclosureRule",
    "MarketSelectiveDisclosureError",
    "SelectiveDisclosureEnvelope",
    "disclose",
    "is_market_forbidden_field",
]
