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

## Go-day substitution locations

The package is deliberately kept locally buildable *before* substitution: the
current values below are byte-grounded facts, not the final published names, and
the package builds and installs from them today. At go-day a single substitution
commit rewrites only the following locations to the operator-cleared published
distribution name; nothing else needs to change.

| Location | Current byte-grounded value | Substituted at go-day? |
|---|---|---|
| `pyproject.toml` → `[project].name` | `dagr-mcp` | **Yes** — this is the exact metadata field the go-day commit may change to the resolved published distribution name. |
| README / quickstart package-index install command | Not present; the documented install path is the source-clone `pip install -e .` (the `@@RUNTIME_DISTRIBUTION@@` token above stands in for the eventual `pip install <name>` line). | Only when the index-install line is added at/after go-day. |
| Package-index URL field (e.g. a future `[project.urls]` "PyPI"/index entry) | Not present. | Only when such a field is added at go-day. |
| Import root | `dagr_mcp` | **No** — the import root is stable and is not a distribution name. |
| Console entry points | `dagr-mcp`, `dagr-mcp-demo` | **No** — command names are not the distribution name and are not substituted here. |
| Repository clone URL | `https://github.com/thelaplage/dagr-mcp` | **No** — retained unless G1 explicitly changes the repository slug. |

The `[project.urls]` entries currently declared (`Repository`, `Issues`) point at
the existing canonical GitHub repository and are not package-index URLs; they are
not substitution locations. The binding identifier `fastmcp.middleware.v0.1` and
the SRS envelope/profile identifiers are protocol identifiers, not distribution
names, and are never rewritten by the naming substitution.

## Rules

- No candidate final distribution name, package-index name, or domain appears
  anywhere in this repository outside this file. The public-release checker
  (`tools/check_public_release.py`) enforces this against the tokens declared in
  `tools/brand_denylist.txt`.
- The quickstart and README install path must remain the concrete source-clone
  path (`pip install -e .`) and must not require substitution to run.
