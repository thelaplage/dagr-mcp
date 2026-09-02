"""A thin, binding-local seam for a pre-validated MCP caller principal.

Scope note (COMMONS-MCP-DISTRIBUTION0 / DAGR-MCP-PRINCIPAL0): this module lets
an MCP binding/service hand DAGR a caller principal/scopes context that has
*already* been authenticated upstream (e.g. by an ARCS Forum ingress or any
other operator-owned auth boundary). DAGR does not authenticate credentials,
does not run OAuth, does not issue API keys, does not store credentials, does
not become an RBAC database, and does not become a gateway/proxy. This module
carries none of that machinery: it is a closed-shape value object plus two
lossless projections onto surfaces DAGR already has.

Contract-ownership note: :mod:`dagr_sdk` (the canonical DAGR SDK) was
inspected before adding this type. Its only existing caller-identity surface
is the duck-typed ``caller_context.actor_ref`` / ``.session_ref`` /
``.request_ref`` triple consumed by
``dagr_mcp.enforcement_harness._build_context`` (ported byte-for-byte from
``dagr_sdk.enforcement_harness``) — three bare, optional strings, with no
notion of caller state (anonymous vs. authenticated user vs. authenticated
machine) and no notion of scopes. That existing surface is reused exactly,
unchanged: :meth:`CallerPrincipal.to_caller_context` projects losslessly onto
it. There is no canonical actor/session/principal-with-scopes contract
anywhere in ``dagr_sdk`` today, so :class:`CallerPrincipal` is declared here,
explicitly, as a **non-canonical, binding-local adapter type** — not a new
DAGR-MCP-local canonical identity. A canonical principal+scopes wire contract,
if one is wanted across bindings, remains a gap to be filled in ``dagr_sdk``
itself, not minted here.

Receipt-discipline note: the existing MCP admission/outcome envelope already
carries an ``actor_ref`` field (``dagr_mcp.srs_receipts.ReceiptContext.actor_ref``
-> envelope ``actor_ref``), sourced from ``HarnessContext.actor_ref``. This
module supplies that existing field with the principal's opaque ref and
introduces no new receipt field, no email, no display name, and no raw
credential.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

CallerPrincipalState = Literal[
    "anonymous",
    "authenticated_user",
    "authenticated_machine",
]

CALLER_PRINCIPAL_STATES: tuple[CallerPrincipalState, ...] = (
    "anonymous",
    "authenticated_user",
    "authenticated_machine",
)

_AUTHENTICATED_STATES: frozenset[str] = frozenset(
    {"authenticated_user", "authenticated_machine"}
)

# Case-insensitive prefixes/markers that indicate a *raw* credential value
# (an Authorization header, a bearer token, a literal "Bearer " prefix) was
# passed where an already-validated opaque reference belongs. This is a
# format-shape guard, not authentication: it does not verify the reference,
# it only refuses to carry something that is structurally a live credential.
_RAW_CREDENTIAL_MARKERS: tuple[str, ...] = (
    "bearer ",
    "basic ",
    "authorization:",
)


class CallerPrincipalError(ValueError):
    """Raised when a :class:`CallerPrincipal` is malformed."""


@dataclass(frozen=True, slots=True)
class CallerPrincipal:
    """A pre-validated caller principal, opaque and credential-free.

    ``state`` distinguishes the three caller postures DAGR must be able to
    carry: an anonymous call, a call from an authenticated human/user
    principal, and a call from an authenticated machine/service principal.

    ``principal_ref`` is an opaque, upstream-minted reference to the caller
    (e.g. a stable user id or service-account id) -- never a bearer token,
    API key, email address, or display name. It is required for the two
    authenticated states and forbidden for ``anonymous``.

    ``scopes`` is a closed set of operator-defined scope tokens the upstream
    auth boundary has already granted this principal. DAGR does not
    interpret them; it only carries them to wherever an operator's own
    policy resolver can read them via :meth:`for_policy_resolver`.

    There is deliberately no field on this type capable of holding a raw
    credential (bearer token, API key, refresh token, password, cookie,
    header value, ...): the dataclass shape is closed to exactly
    ``state`` / ``principal_ref`` / ``scopes``, so a raw credential cannot be
    constructed onto, or serialized through, this type.
    """

    state: CallerPrincipalState
    principal_ref: str | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.state not in CALLER_PRINCIPAL_STATES:
            raise CallerPrincipalError(
                f"state outside the closed vocabulary: {self.state!r} "
                f"(expected one of {CALLER_PRINCIPAL_STATES})"
            )

        if self.state == "anonymous":
            if self.principal_ref is not None:
                raise CallerPrincipalError(
                    "anonymous principal must not carry principal_ref"
                )
            if self.scopes:
                raise CallerPrincipalError(
                    "anonymous principal must not carry scopes"
                )
            return

        # authenticated_user / authenticated_machine
        if not isinstance(self.principal_ref, str) or not self.principal_ref.strip():
            raise CallerPrincipalError(
                f"{self.state} principal requires a non-empty principal_ref"
            )
        ref = self.principal_ref.strip()
        object.__setattr__(self, "principal_ref", ref)
        lowered = ref.lower()
        if any(marker in lowered for marker in _RAW_CREDENTIAL_MARKERS):
            raise CallerPrincipalError(
                "principal_ref must be an opaque, pre-validated reference, "
                "not a raw credential/header value"
            )
        if any(ch.isspace() for ch in ref):
            raise CallerPrincipalError(
                "principal_ref must not contain whitespace"
            )

        normalized_scopes = frozenset(self.scopes)
        for scope in normalized_scopes:
            if not isinstance(scope, str) or not scope.strip():
                raise CallerPrincipalError("scopes must be non-empty strings")
        object.__setattr__(self, "scopes", normalized_scopes)

    @property
    def is_authenticated(self) -> bool:
        """``True`` for either authenticated state, ``False`` for anonymous."""
        return self.state in _AUTHENTICATED_STATES

    def to_caller_context(
        self,
        *,
        session_ref: str | None = None,
        request_ref: str | None = None,
    ) -> dict[str, str | None]:
        """Project this principal onto the existing duck-typed caller context.

        The returned mapping is exactly the shape
        ``dagr_mcp.enforcement_harness._build_context`` already reads via
        ``_context_value`` (``actor_ref`` / ``session_ref`` / ``request_ref``):
        no new keys, no wire change. ``actor_ref`` is the principal's opaque
        ref for an authenticated principal and is genuinely absent (``None``)
        for an anonymous one, matching today's default (no-context) behavior.
        """
        return {
            "actor_ref": self.principal_ref if self.is_authenticated else None,
            "session_ref": session_ref,
            "request_ref": request_ref,
        }

    def for_policy_resolver(self) -> Mapping[str, Any]:
        """A safe, minimal view for an operator-owned policy resolver.

        Carries only ``principal_state``, ``principal_ref`` (opaque, never a
        raw credential -- see :class:`CallerPrincipal`), and ``scopes``
        (sorted for determinism). DAGR itself performs no scope check: an
        operator's own policy function reads this view and decides,
        producing an ``"admitted"``/``"refused"`` outcome that flows into
        :func:`dagr_mcp.operator_admission_resolver.resolve_operator_admission`
        exactly as any other operator decision would.
        """
        return {
            "principal_state": self.state,
            "principal_ref": self.principal_ref,
            "scopes": tuple(sorted(self.scopes)),
        }


ANONYMOUS_CALLER_PRINCIPAL = CallerPrincipal(state="anonymous")


__all__ = [
    "CALLER_PRINCIPAL_STATES",
    "ANONYMOUS_CALLER_PRINCIPAL",
    "CallerPrincipal",
    "CallerPrincipalError",
    "CallerPrincipalState",
]
