"""A thin, binding-local seam for a pre-validated MCP caller principal.

Scope note (COMMONS-MCP-DISTRIBUTION0 / DAGR-MCP-PRINCIPAL0): this module lets
an MCP binding/service hand DAGR a caller principal/scopes context that has
*already* been authenticated upstream (e.g. by an ARCS Forum ingress or any
other operator-owned auth boundary). DAGR does not authenticate credentials,
does not run OAuth, does not issue API keys, does not store credentials, does
not become an RBAC database, and does not become a gateway/proxy. This module
carries none of that machinery: it is a thin projection over the canonical
SDK caller-identity contract plus two lossless projections onto surfaces
DAGR already has.

Seam-1 closure (2026-09-02): ``dagr_sdk`` now owns the canonical caller-
identity wire contract, :class:`dagr_sdk.caller_auth_context.CallerAuthContext`
(``dagr-sdk`` main @ ``f11fbf817ea3b4af150e15effae9448c470e247d``, commit-pinned
in ``pyproject.toml``). That module's own docstring records that it was built
*specifically* to resolve the gap this module previously declared: "there is
no canonical actor/session/principal-with-scopes contract anywhere in
dagr_sdk today." That gap is now closed, so ``CallerPrincipal`` no longer
owns a competing three-field shape -- it is reduced to a thin adapter whose
constructor *consumes* a ``CallerAuthContext`` and adds only the DAGR-MCP-
local projections that ``CallerAuthContext`` itself deliberately does not
own (see that module's "Why connection_ref is OMITTED"):

* :meth:`CallerPrincipal.to_caller_context` -- projects onto the existing
  duck-typed ``caller_context.actor_ref`` / ``.session_ref`` / ``.request_ref``
  triple already consumed by ``dagr_mcp.enforcement_harness._build_context``.
  ``session_ref`` / ``request_ref`` remain call-site parameters here, exactly
  as before -- they are not, and per the SDK contract's own design should
  not become, fields on the caller-identity value itself.
* :meth:`CallerPrincipal.for_policy_resolver` -- a safe, minimal view for an
  operator-owned policy resolver.

``CallerPrincipal`` carries no state of its own beyond the wrapped
``CallerAuthContext``: it does not re-validate, re-derive, or shadow any of
``state`` / ``principal_ref`` / ``scope_refs``. Those properties simply
delegate to the wrapped contract, so there is exactly one place credential-
shape validation happens (``dagr_sdk.caller_auth_context.CallerAuthContext``),
not two.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from dagr_sdk.caller_auth_context import (
    ANONYMOUS_CALLER_AUTH_CONTEXT,
    CALLER_AUTH_STATES,
    CallerAuthContext,
    CallerAuthContextError,
    CallerAuthState,
)

# Re-exported so existing dagr-mcp call sites that imported the state
# vocabulary / error type from this module keep working, sourced from the
# single canonical definition rather than a re-declared local copy.
CallerPrincipalState = CallerAuthState
CALLER_PRINCIPAL_STATES: tuple[str, ...] = tuple(sorted(CALLER_AUTH_STATES))
CallerPrincipalError = CallerAuthContextError


@dataclass(frozen=True, slots=True)
class CallerPrincipal:
    """A thin DAGR-MCP-local adapter over the SDK's ``CallerAuthContext``.

    Construct this from an already-built ``CallerAuthContext`` (the canonical
    wire shape, owned by ``dagr_sdk``); do not construct a
    ``CallerAuthContext`` inline here as a convenience, because this type
    exists only to add the two DAGR-MCP-local projections below, not to
    re-mint an independent caller-identity shape.
    """

    auth: CallerAuthContext

    def __post_init__(self) -> None:
        if not isinstance(self.auth, CallerAuthContext):
            raise CallerPrincipalError(
                "CallerPrincipal.auth must be a dagr_sdk.caller_auth_context."
                f"CallerAuthContext, got {type(self.auth).__name__}"
            )

    @property
    def state(self) -> CallerPrincipalState:
        return self.auth.state

    @property
    def principal_ref(self) -> str | None:
        return self.auth.principal_ref

    @property
    def scopes(self) -> frozenset[str]:
        return self.auth.scope_refs

    @property
    def is_authenticated(self) -> bool:
        return self.auth.is_authenticated

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
            "actor_ref": self.auth.principal_ref if self.auth.is_authenticated else None,
            "session_ref": session_ref,
            "request_ref": request_ref,
        }

    def for_policy_resolver(self) -> Mapping[str, Any]:
        """A safe, minimal view for an operator-owned policy resolver.

        Carries only ``principal_state``, ``principal_ref`` (opaque, never a
        raw credential -- see :class:`dagr_sdk.caller_auth_context.CallerAuthContext`),
        and ``scopes`` (sorted for determinism). DAGR itself performs no
        scope check: an operator's own policy function reads this view and
        decides, producing an ``"admitted"``/``"refused"`` outcome that flows
        into
        :func:`dagr_mcp.operator_admission_resolver.resolve_operator_admission`
        exactly as any other operator decision would.
        """
        wire = self.auth.as_wire_dict()
        return {
            "principal_state": wire["state"],
            "principal_ref": wire["principal_ref"],
            "scopes": wire["scope_refs"],
        }

    @classmethod
    def from_auth_context(cls, auth: CallerAuthContext) -> "CallerPrincipal":
        """Explicit, named constructor mirroring the SDK contract's own name."""
        return cls(auth=auth)


ANONYMOUS_CALLER_PRINCIPAL = CallerPrincipal(auth=ANONYMOUS_CALLER_AUTH_CONTEXT)


__all__ = [
    "CALLER_PRINCIPAL_STATES",
    "ANONYMOUS_CALLER_PRINCIPAL",
    "CallerPrincipal",
    "CallerPrincipalError",
    "CallerPrincipalState",
]
