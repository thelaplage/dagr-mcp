# Governed Action Membrane v0.1

This record describes the product-neutral governed-action membrane introduced in
this lane.

## Intent

This is deterministic agent/tool governance, not a security scanner.

Security is one application of the membrane, not the contract itself.

DAGR decides whether a bounded action may proceed under policy.

SRS records bounded decisions, actions, and outcomes.

ARCS Verify independently checks receipt and evidence claims.

Counterpedia may later project history.

None of these operations decide truth.

## Invariant

NO AGENT ACTION CROSSES A GOVERNED BOUNDARY
WITHOUT A DETERMINISTIC DECISION,
AND THE DECISION/ACTION CAN LEAVE
A PORTABLE, INDEPENDENTLY VERIFIABLE RECEIPT.

## Notes

- The request snapshot is deep-frozen before any identity digest is derived.
- Allow, refuse, and defer are mapped onto the existing neutral lifecycle
  vocabulary.
- Refusal and defer emit bounded admission evidence; allow emits admission and
  outcome evidence.
- Receipt persistence failure is tracked separately from execution fact.
- No truth, confidence, standing, or source-record semantics are introduced.
