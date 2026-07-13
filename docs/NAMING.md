# Naming substitution

This repository does not select a final published distribution / install name.
The name, the package index it is published to, and the resulting install
command are operator-gated and are resolved in a single substitution step at
launch, not in this documentation.

The current project name (`dagr-mcp`), import package (`dagr_mcp`), and
repository (`thelaplage/dagr-mcp`) are reported throughout the documentation as
current, byte-grounded facts. They are not the final published distribution
name. Every string that depends on the *final published* name references a
substitution token declared here; a one-commit substitution rewrites the tokens
below to their resolved values. Until then the documentation carries the tokens
and the working quickstart uses the concrete source-clone install path, which
needs no substitution.

## Tokens

| Token | Resolves to | Status |
|---|---|---|
| `@@RUNTIME_DISTRIBUTION@@` | The published distribution / install name for this emitter runtime (e.g. the argument to `pip install`). | Not selected. Operator-gated; the final index name and install command are pending G1 clearance. |

Only tokens actually referenced by the current documentation are declared here.
Additional tokens (for example a verifier distribution name, a public docs base,
or a badge base) are added when the documentation that needs them is added, and
not before. The verifier's own published name is resolved in the ARCS Verify
repository, not here.

## Rules

- No candidate final distribution name, package-index name, or domain appears
  anywhere in this repository outside this file. The public-release checker
  (`tools/check_public_release.py`) enforces this against the tokens declared in
  `tools/brand_denylist.txt`.
- The quickstart and README install path must remain the concrete source-clone
  path (`pip install -e .`) and must not require substitution to run.
