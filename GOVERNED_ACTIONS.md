# Governed Actions

## Vocabulary Boundaries

Current runtime policy values and receipt dispositions are separate vocabularies.

| Runtime policy value | Current meaning at policy/harness layer |
|---|---|
| `allow` | Permit execution after admission checks |
| `deny` | Refuse before execution |
| `gate` | Route to review/deferral behavior when review can be created |
| `defer` | Runtime policy value that does not itself become a receipt disposition |
| `fail_closed` | Refuse when the boundary cannot safely admit |

| Receipt disposition | Current meaning in admission receipts |
|---|---|
| `admitted` | Boundary admitted the call; execution may proceed |
| `refused` | Boundary refused the call; handler/delegate does not run |
| `deferred_for_review` | Boundary deferred to a review object; handler/delegate does not run |

Do not collapse these lists. Policy values belong to runtime decision inputs and
harness behavior. Receipt dispositions belong to serialized admission evidence.

## Mapping

| Policy-side situation | Receipt-side result |
|---|---|
| Allowed call with available required admission sink | `admitted` admission, then an outcome if execution is observed and outcome emission succeeds |
| Explicit deny | `refused` admission with `policy_refused` when emitted |
| Unknown tool under fail-closed policy | `refused` admission with `unknown_tool_fail_closed` when emitted |
| Gate with review object created | `deferred_for_review` admission with `retry_after_approval` |
| Gate with required review sink unavailable | `refused` admission with `required_sink_unavailable` when emitted |
| Review object creator raises | `refused` admission with `review_object_creation_failed` when emitted |
| Required admission sink unavailable | execution prevented according to fail-closed behavior; receipt is best effort |

## Governed Surfaces

DAGR MCP currently governs tool calls that pass through configured binding paths:
FastMCP middleware, official MCP SDK 1.x handler registration, official MCP SDK
2.x handler composition, and neutral service connector execution. Optional
Amnesiac operations are exposed as governed tools through the same boundary.

## Not Governed Here

DAGR MCP does not govern MCP traffic that bypasses the configured boundary. It
does not ratify durable memory admission, define organization-wide policy,
certify implementations, publish public evidence views, or verify its own
receipts.
