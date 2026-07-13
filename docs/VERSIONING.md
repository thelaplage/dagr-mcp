# Versioning policy

## Semantic Versioning

This project follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).
A release version is `MAJOR.MINOR.PATCH`:

- `MAJOR` increments on incompatible public-surface changes;
- `MINOR` increments on backward-compatible additions;
- `PATCH` increments on backward-compatible fixes.

## Source of truth

`[project].version` in `pyproject.toml` is the single source of truth for the
package version. The current value is `0.1.0`. The package does not expose a
separate runtime `__version__`, so there is no duplicate version to keep in
sync; the installed version is read from package metadata
(`importlib.metadata.version("dagr-mcp")`).

## Tags and releases

- A release is published by creating an annotated Git tag of the form `vX.Y.Z`
  (for example `v0.1.0`) at the go-day tagging commit.
- **A tag or release does not exist merely because a version appears in source.**
  The presence of `0.1.0` in `pyproject.toml`, in this document, or in the
  changelog is not itself a tag, a release, or a claim of public availability.
- Until that tag is created, the changelog entry for the current version stays
  marked `Unreleased` with no assigned date.

## Protocol and binding identifiers are independent

Package versions and protocol/binding identifiers are separate namespaces and do
not track each other:

- `fastmcp.middleware.v0.1` is the **binding identifier** the middleware records
  in receipts. It is **not** the FastMCP package version and it is not the
  `dagr-mcp` package version. The supported FastMCP package range is declared
  separately as `fastmcp>=3.4.4,<4`.
- The SRS **envelope** schema version (for example `srs-envelope-v0.2.0`) and the
  named **profile** version (`srs.mcp.sdk_enforcement.v0.1`), together with the
  reserved receipt/envelope identifiers, are independent protocol identifiers.
- Bumping the `dagr-mcp` package version does not bump the binding identifier,
  the FastMCP range, or any envelope/profile identifier, and vice versa. Those
  change only through their own governed processes.

## Distribution-name substitution

The final published distribution name is operator-gated (see
[NAMING.md](NAMING.md)). Substituting that name at launch changes only the
declared distribution/install string; it does **not** change the import root
(`dagr_mcp`), the repository clone URL, the binding identifier, or any envelope
or profile identifier, unless such a change is separately reviewed.

## Pre-1.0 discipline

While the version is below `1.0.0`, the public surface may still change between
minor versions. Compatibility is offered on a best-effort basis and breaking
changes are called out in the changelog. Stronger compatibility guarantees begin
at `1.0.0`.

## Release ordering for P4 / go-day

The go-day sequence is, in order:

1. finalize the changelog entry for the version and record its release date;
2. apply any operator-gated distribution-name substitution;
3. create the `vX.Y.Z` tag on that commit;

so that the changelog date and the tag are assigned together and no earlier than
the tag exists. Building or installing the package from source before that point
does not constitute a release.
