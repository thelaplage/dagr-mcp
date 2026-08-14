"""Operator admission resolver: a neutral decision -> ToolPolicy translation.

This module is the entire surface an external operator's own policy
authority needs to drive :func:`dagr_mcp.enforcement_harness.wrap_handler`.
It carries no vocabulary specific to any tool-calling domain, and no
knowledge of any particular calling application or the reasoning behind its
decisions. It does not evaluate tool arguments, does not inspect call
context, and applies no policy of its own -- it is a pure, total function
from a two-value neutral decision to the harness's own ``ToolPolicy`` shape.

An operator with its own domain-specific rule runs that rule entirely in its
own repository and calls in here only with the outcome, already reduced to
``"admitted"`` or ``"refused"``. This module does not, and must not, grow a
parameter that lets a caller's domain vocabulary leak into it -- the
boundary this module draws is exactly: below this line, DAGR; above this
line, the operator.
"""

from __future__ import annotations

from typing import Literal

from .enforcement_harness import ToolClass, ToolPolicy

OperatorAdmissionDecision = Literal["admitted", "refused"]

DEFAULT_REFUSAL_REASON = "policy_refused"

_DECISION_TO_POLICY_DECISION: dict[OperatorAdmissionDecision, str] = {
    "admitted": "allow",
    "refused": "deny",
}


class OperatorAdmissionResolverError(ValueError):
    """Raised for malformed operator admission resolver inputs."""


def resolve_operator_admission(
    *,
    tool_name: str,
    tool_class: ToolClass,
    decision: OperatorAdmissionDecision,
    reason: str | None = None,
    gate_timeout_seconds: int | None = None,
) -> ToolPolicy:
    """Translate one already-decided operator admission outcome into a policy.

    ``decision`` is exactly one of ``"admitted"`` or ``"refused"`` -- a
    closed, neutral vocabulary. There is no default-admit fallback: any
    other value fails closed with :exc:`OperatorAdmissionResolverError`
    rather than being coerced toward either outcome.

    ``reason`` is an operator-supplied free-text code (e.g.
    ``"policy_refused"``) carried onto the resulting :class:`ToolPolicy` and,
    downstream, onto the admission receipt's ``reason_code``. This module
    does not inspect or validate its contents beyond requiring a string --
    the operator's own vocabulary lives entirely in that string, never in a
    parameter name or branch here.
    """

    if not isinstance(tool_name, str) or not tool_name.strip():
        raise OperatorAdmissionResolverError("tool_name must be a non-empty string")

    if decision not in _DECISION_TO_POLICY_DECISION:
        raise OperatorAdmissionResolverError(
            f"unrecognized operator admission decision: {decision!r} "
            f"(expected one of {sorted(_DECISION_TO_POLICY_DECISION)})"
        )

    if reason is not None and not isinstance(reason, str):
        raise OperatorAdmissionResolverError("reason must be a string when supplied")

    resolved_reason = reason
    if resolved_reason is None:
        resolved_reason = (
            DEFAULT_REFUSAL_REASON if decision == "refused" else f"operator_{decision}"
        )

    return ToolPolicy(
        tool_name=tool_name,
        tool_class=tool_class,
        decision=_DECISION_TO_POLICY_DECISION[decision],
        reason=resolved_reason,
        gate_timeout_seconds=gate_timeout_seconds,
    )


__all__ = [
    "DEFAULT_REFUSAL_REASON",
    "OperatorAdmissionDecision",
    "OperatorAdmissionResolverError",
    "resolve_operator_admission",
]
