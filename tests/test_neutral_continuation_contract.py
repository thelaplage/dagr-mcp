"""Neutral MCP continuation contract v0.1 — focused test matrix.

Authority: DAGR MCP 2026-07-28 Decision Ratification Record v0.1, merged at
``33099657b5beb41e2388018183aaf2a1e8f31659``. These tests pin
:mod:`dagr_mcp_continuation`: identity validation, the ratified
three-condition admission gate, the ``continuable``-only outcome boundary,
builder behavior, source-level neutrality (no wire/binding/ID-minting import
or field), and that the frozen v0.1 lifecycle vocabulary this package depends
on is unchanged.

``dagr_mcp_continuation`` is a new top-level sibling package, not a submodule
of ``dagr_mcp_lifecycle`` — it stays outside every existing frozen
package-surface snapshot in the repository (``dagr_mcp``, ``dagr_mcp_lifecycle``,
``dagr_mcp_sdk_binding``), so none of those goldens change.

Nothing here touches the FastMCP binding, the official SDK binding, receipts,
or any existing golden.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from dagr_mcp_lifecycle import contract
from dagr_mcp_continuation import (
    ContinuationContractError,
    ContinuationIdentity,
    NeutralContinuation,
    build_neutral_continuation,
    require_continuation_admission,
)

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "dagr_mcp_continuation" / "__init__.py"


def _identity(**overrides: object) -> ContinuationIdentity:
    fields = {
        "interaction_id": "interaction-1",
        "request_id": "request-2",
        "parent_request_id": "request-1",
        "round_number": 2,
    }
    fields.update(overrides)
    return ContinuationIdentity(**fields)


# --------------------------------------------------------------------------- #
# Identity validation                                                          #
# --------------------------------------------------------------------------- #


def test_valid_identity_preserves_every_supplied_value_exactly():
    identity = _identity(
        interaction_id=" interaction-1 stays whole ",
        request_id="request-2",
        parent_request_id="request-1",
        round_number=7,
    )
    assert identity.interaction_id == " interaction-1 stays whole "
    assert identity.request_id == "request-2"
    assert identity.parent_request_id == "request-1"
    assert identity.round_number == 7


def test_identity_dataclass_is_immutable():
    identity = _identity()
    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.request_id = "request-3"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field_name", ["interaction_id", "request_id", "parent_request_id"]
)
@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
def test_empty_or_whitespace_only_ids_rejected(field_name, bad_value):
    with pytest.raises(ContinuationContractError):
        _identity(**{field_name: bad_value})


def test_identical_interaction_and_request_ids_rejected():
    with pytest.raises(ContinuationContractError):
        _identity(interaction_id="same-value", request_id="same-value")


def test_identical_request_and_parent_ids_rejected():
    with pytest.raises(ContinuationContractError):
        _identity(request_id="same-value", parent_request_id="same-value")


def test_round_zero_rejected():
    with pytest.raises(ContinuationContractError):
        _identity(round_number=0)


def test_negative_round_rejected():
    with pytest.raises(ContinuationContractError):
        _identity(round_number=-1)


def test_boolean_round_rejected():
    with pytest.raises(ContinuationContractError):
        _identity(round_number=True)
    with pytest.raises(ContinuationContractError):
        _identity(round_number=False)


@pytest.mark.parametrize("bad_round", [1.5, "1", None, [1]])
def test_non_integer_round_rejected(bad_round):
    with pytest.raises(ContinuationContractError):
        _identity(round_number=bad_round)


# --------------------------------------------------------------------------- #
# Admission truth table                                                        #
# --------------------------------------------------------------------------- #


class _TruthyNonBoolean:
    def __bool__(self) -> bool:
        return True


_TRUTHY_NON_BOOLEANS = (1, "true", _TruthyNonBoolean())
_BOOLEANS = (True, False)
_RECORDS = (object(), None)


@pytest.mark.parametrize("execution_proceeds", _BOOLEANS)
@pytest.mark.parametrize("admission_recorded", _BOOLEANS)
@pytest.mark.parametrize("admission_record", _RECORDS)
def test_admission_truth_table_exactly_one_combination_passes(
    execution_proceeds, admission_recorded, admission_record
):
    should_pass = (
        execution_proceeds is True
        and admission_recorded is True
        and admission_record is not None
    )
    if should_pass:
        require_continuation_admission(
            execution_proceeds=execution_proceeds,
            admission_recorded=admission_recorded,
            admission_record=admission_record,
        )
    else:
        with pytest.raises(ContinuationContractError, match=(
            "Refused, deferred, or unrecorded-admission paths cannot continue."
        )):
            require_continuation_admission(
                execution_proceeds=execution_proceeds,
                admission_recorded=admission_recorded,
                admission_record=admission_record,
            )


@pytest.mark.parametrize("truthy_value", _TRUTHY_NON_BOOLEANS)
def test_truthy_non_booleans_do_not_satisfy_execution_proceeds(truthy_value):
    with pytest.raises(ContinuationContractError):
        require_continuation_admission(
            execution_proceeds=truthy_value,
            admission_recorded=True,
            admission_record=object(),
        )


@pytest.mark.parametrize("truthy_value", _TRUTHY_NON_BOOLEANS)
def test_truthy_non_booleans_do_not_satisfy_admission_recorded(truthy_value):
    with pytest.raises(ContinuationContractError):
        require_continuation_admission(
            execution_proceeds=True,
            admission_recorded=truthy_value,
            admission_record=object(),
        )


# --------------------------------------------------------------------------- #
# Outcome boundary                                                             #
# --------------------------------------------------------------------------- #


def test_canonical_continuable_passes():
    nc = NeutralContinuation(identity=_identity(), outcome="continuable")
    assert nc.outcome == "continuable"


def test_canonical_interrupted_is_rejected():
    with pytest.raises(ContinuationContractError):
        NeutralContinuation(identity=_identity(), outcome="interrupted")


@pytest.mark.parametrize("outcome", contract.NEUTRAL_OUTCOMES)
def test_every_other_current_canonical_lifecycle_outcome_is_rejected(outcome):
    with pytest.raises(ContinuationContractError):
        NeutralContinuation(identity=_identity(), outcome=outcome)


def test_no_input_required_value_is_treated_as_neutral_continuation():
    with pytest.raises(ContinuationContractError):
        NeutralContinuation(identity=_identity(), outcome="input_required")


@pytest.mark.parametrize(
    "arbitrary", ["Continuable", "CONTINUABLE", "continuable ", "resumed", ""]
)
def test_arbitrary_strings_are_rejected_rather_than_normalized(arbitrary):
    with pytest.raises(ContinuationContractError):
        NeutralContinuation(identity=_identity(), outcome=arbitrary)


# --------------------------------------------------------------------------- #
# Builder behavior                                                             #
# --------------------------------------------------------------------------- #


def test_valid_builder_result_contains_only_identity_and_outcome():
    identity = _identity()
    admission_record = object()
    nc = build_neutral_continuation(
        outcome="continuable",
        identity=identity,
        execution_proceeds=True,
        admission_recorded=True,
        admission_record=admission_record,
    )
    assert dataclasses.fields(nc)
    field_names = {f.name for f in dataclasses.fields(nc)}
    assert field_names == {"identity", "outcome"}
    assert nc.identity is identity
    assert nc.outcome == "continuable"


def test_builder_applies_admission_before_constructing_result():
    # Admission failure raised even though the outcome is also invalid — proves
    # the admission gate is checked first, not just eventually.
    with pytest.raises(ContinuationContractError, match=(
        "Refused, deferred, or unrecorded-admission paths cannot continue."
    )):
        build_neutral_continuation(
            outcome="interrupted",
            identity=_identity(),
            execution_proceeds=False,
            admission_recorded=False,
            admission_record=None,
        )


def test_builder_rejects_bad_outcome_when_admission_passes():
    with pytest.raises(ContinuationContractError):
        build_neutral_continuation(
            outcome="interrupted",
            identity=_identity(),
            execution_proceeds=True,
            admission_recorded=True,
            admission_record=object(),
        )


def test_builder_does_not_preserve_or_expose_the_admission_record():
    admission_record = {"opaque": "state"}
    nc = build_neutral_continuation(
        outcome="continuable",
        identity=_identity(),
        execution_proceeds=True,
        admission_recorded=True,
        admission_record=admission_record,
    )
    field_names = {f.name for f in dataclasses.fields(nc)}
    assert "admission_record" not in field_names
    stored_values = [getattr(nc, f.name) for f in dataclasses.fields(nc)]
    assert admission_record not in stored_values
    assert not hasattr(nc, "admission_record")


def test_builder_does_not_accept_unexpected_wire_or_raw_state_kwargs():
    with pytest.raises(TypeError):
        build_neutral_continuation(
            outcome="continuable",
            identity=_identity(),
            execution_proceeds=True,
            admission_recorded=True,
            admission_record=object(),
            requestState={"opaque": "blob"},  # type: ignore[call-arg]
        )


def test_repeated_valid_constructions_preserve_supplied_request_ids():
    identity_a = _identity(request_id="request-round-1")
    identity_b = _identity(request_id="request-round-2")

    nc_a = build_neutral_continuation(
        outcome="continuable",
        identity=identity_a,
        execution_proceeds=True,
        admission_recorded=True,
        admission_record=object(),
    )
    nc_b = build_neutral_continuation(
        outcome="continuable",
        identity=identity_b,
        execution_proceeds=True,
        admission_recorded=True,
        admission_record=object(),
    )

    assert nc_a.identity.request_id == "request-round-1"
    assert nc_b.identity.request_id == "request-round-2"
    assert nc_a.identity.request_id != nc_b.identity.request_id


# --------------------------------------------------------------------------- #
# Neutrality inspection                                                       #
# --------------------------------------------------------------------------- #

_PROHIBITED_IMPORT_ROOTS = frozenset(
    {
        "mcp",
        "fastmcp",
        "dagr_mcp_sdk_binding",
        "dagr_mcp",
        "uuid",
        "datetime",
        "time",
        "secrets",
        "random",
        "hashlib",
    }
)

_PROHIBITED_FIELD_NAMES = frozenset(
    {
        "requestState",
        "inputRequests",
        "inputResponses",
        "headers",
        "Authorization",
        "cookies",
        "clientInfo",
        "protocol_version",
        "timestamp",
        "digest",
    }
)


def _module_ast() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))


def test_module_imports_no_prohibited_binding_wire_or_minting_package():
    tree = _module_ast()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    offending = roots & _PROHIBITED_IMPORT_ROOTS
    assert offending == set(), offending


def test_module_only_imports_stdlib_typing_and_the_neutral_contract():
    tree = _module_ast()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)
    allowed = {"__future__", "dataclasses", "dagr_mcp_lifecycle.contract"}
    assert imported_modules <= allowed, imported_modules


def test_dataclass_fields_carry_no_prohibited_names():
    for cls in (ContinuationIdentity, NeutralContinuation):
        field_names = {f.name for f in dataclasses.fields(cls)}
        assert field_names.isdisjoint(_PROHIBITED_FIELD_NAMES), (cls, field_names)


def test_function_signatures_carry_no_prohibited_parameter_names():
    for fn in (require_continuation_admission, build_neutral_continuation):
        params = set(inspect.signature(fn).parameters)
        assert params.isdisjoint(_PROHIBITED_FIELD_NAMES), (fn, params)


def test_no_prohibited_raw_or_minted_field_substring_in_source():
    text = MODULE_PATH.read_text(encoding="utf-8")
    needles = (
        "requestState",
        "inputRequests",
        "inputResponses",
        "Authorization",
        "cookies",
        "clientInfo",
        "Mcp-Param-",
        "protocol_version",
        "timestamp",
        "digest",
    )
    offenders = [needle for needle in needles if needle in text]
    assert offenders == [], offenders


# --------------------------------------------------------------------------- #
# Frozen v0.1 regression                                                       #
# --------------------------------------------------------------------------- #


def test_frozen_input_required_modes_unchanged():
    assert contract.INPUT_REQUIRED_MODES == ("continuable", "interrupted")


def test_frozen_neutral_outcomes_unchanged():
    assert contract.NEUTRAL_OUTCOMES == (
        "result",
        "error",
        "exception",
        "task_submitted",
        "timeout",
        "cancellation",
        "input_required",
    )


def test_frozen_contract_identifiers_unchanged():
    assert contract.CONTRACT_ID == "dagr.mcp.lifecycle_contract"
    assert contract.CONTRACT_VERSION == "v0.1"
