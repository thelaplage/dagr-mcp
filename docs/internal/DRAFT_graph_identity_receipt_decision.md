# DRAFT: Future Graph Identity Receipt Decision

Status: draft, not merged, and not implementation-authorized.

This note freezes one future-compatible invariant only:

When a governed MCP invocation acts on or queries a named graph, graph identity
must be capable of appearing as a stable semantic receipt fact and must not be
reconstructed later from deployment topology.

This is not a federation design and not a graph-query feature. It does not add
list/describe graph operations, cross-graph query semantics, SPARQL/Cypher,
identifier bridges, or countergraph dependencies.

## Current surface inventory

The existing receipt surface already distinguishes:

* `subject_ref` as the semantic subject identity.
* `subject_ref_origin` as the optional trusted-boundary disclosure of how that
  subject reference was obtained.
* `extensions.mcp.binding_version` as the single binding-owned stamp emitted by
  the shared SRS receipt constructor.

The current schema is permissive at the top level, but the implementation
authority is not present:

* there is no graph-scoped field in `ReceiptContext`;
* there is no graph identity resolver in the current receipt emitter;
* there is no graph origin vocabulary;
* there is no verifier contract that treats graph identity as a governed fact.

That means the current extension seam is only an opaque carrier, not a governed
graph identity authority.

## Recommended future field semantics

Recommended future field name: `graph_ref`.

Semantics:

* Optional.
* Present only when the call is graph-scoped.
* Names the graph identity, not graph contents.
* Must be stable across deployment hostname changes.
* Must be stable across storage-engine migrations.
* Must not be inferred from database, path, socket, or host labels.
* Must remain opaque to contents and topology.

If a later reviewed authority authorizes a second provenance field, the
corresponding trusted-origin disclosure should be a separate, closed vocabulary
field rather than an inferred convention.

## Trusted origin rule

Graph identity may enter a receipt only when supplied or resolved by a trusted
boundary that has explicit governance authority to do so.

That trusted boundary may be:

* a binding-side resolver configured by the operator;
* a server-side trusted context that already carries an authorized graph
  identity;
* a governed service boundary that resolves a request into a graph identity
  before receipt emission.

What is not sufficient:

* ordinary tool arguments;
* deployment hostname strings;
* storage-engine names;
* filesystem paths;
* socket addresses;
* content-derived hashes of the graph body.

If the binding has no explicitly governed resolution rule, graph identity must
remain absent.

## Hostile cases

Treat these as hostile and non-authoritative:

* `graph_ref` embedded in untrusted tool arguments.
* `graph_ref` reconstructed from `runtime_instance_id`, `boundary_id`, pod
  names, container names, or service DNS names.
* `graph_ref` reconstructed from DB names, file paths, UNIX sockets, TCP ports,
  or object-store bucket names.
* `graph_ref` derived from graph contents, membership, or query results.
* any attempt to use `subject_ref` as a substitute for graph identity.

## Implementation authorization assessment

Assessment: no implementation authority is present in the current repository
surface.

Reasons:

* the public SRS envelope has not been revised for graph identity;
* the current emitter owns only the existing receipt fields and the current
  extension conventions;
* the current documented extension convention is binding-owned state, not a
  graph identity contract;
* the current SRS receipt code has no trusted resolution rule for graph
  identity.

Conclusion: do not add a graph identity field to the live receipt surface yet.

## NOW vs LATER

NOW:

* keep the public SRS envelope unchanged;
* do not infer graph identity from deployment topology;
* do not add graph federation features;
* keep graph identity out of ordinary tool arguments.

LATER:

* if a separate review authorizes it, add a narrowly-scoped graph identity
  field and a governed trusted-origin rule;
* add verifier coverage that treats the graph fact as a stable semantic receipt
  fact;
* add hostile-case tests that prove topology cannot recreate the identity.

The current code path is therefore proposal-only. It is suitable for review, not
for merge.
