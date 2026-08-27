# Clean-replay attempt 1 (@3be3749) — frozen failure record

Provenance, preserved intentionally: the first clean-checkout replay of the
harness landed at commit `3be3749` **failed**, exposing that the reconstructed
harness had been committed without ever being run end to end. This is useful
history — do not treat `3be3749` as a working reproduction.

## What passed at 3be3749

- `verify_pins.py` PASS (5/5) against a freshly downloaded pinned asset
- mock OIDC + control-plane came up on the fresh release
- (with the policy repair only) router + greeter + market + all 3 sam-nodes,
  `get_mesh_info` connected

## What failed at 3be3749

1. **Router enrollment `403 Forbidden: requested role "sam:role:router" is not
   authorized for this identity`** — `up.sh` never seeded `/policies`, so no
   `group → role` binding existed at enrollment time.
2. After the policy fix, the **semantic probe** raised
   `expected one greeter provider, got []` on every retry — not a mesh fault
   (direct `find_remote_tools` returned the greeter tools), but a result-shape
   parsing bug in `probe_semantic.py` (and the same bug in `live_market0.py`).

All three defects are fixed in the repair commit that supersedes this attempt;
the successful clean reproduction is recorded in `REPRODUCTION_REPORT.md`.
`3be3749` itself is left unmodified as the record of attempt 1.
