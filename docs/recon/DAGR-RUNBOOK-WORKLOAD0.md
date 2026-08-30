# DAGR-RUNBOOK-WORKLOAD0 — initial recon

## External workload studied

`espirado/runbook_generator` normalizes heterogeneous infrastructure observations into an `EnvironmentSnapshot`, deterministically renders runbook/agent/reporting artifacts, and keeps Jira/Confluence/Slack/wiki outputs as dry-run artifacts unless an explicit side-effecting path is enabled.

## Adoption decision

Do not import its operational schema into DAGR. Use the workload only if it provides a clean demonstration of the distinction:

`proposal artifact exists != external side effect executed`.

## Candidate governance seam

Reads and deterministic generation are ordinary observations/proposals. A later create/send/publish operation is the potential governed action. A refusal must preserve the generated proposal for review rather than erase or relabel it.

## Proof posture

Any proof must be offline by default, use fixture environment data and a fake publisher, keep credentials/content out of receipts, and demonstrate that transcript language cannot turn a refused publish into `sent=true`.

## Next gate

Inspect whether the external project already exposes MCP/tool entrypoints. If not, determine whether a tiny isolated wrapper can demonstrate the seam without invasive upstream changes. Otherwise return `NEEDS_UPSTREAM_SEAM` rather than constructing a framework inside DAGR.

**Current posture:** `READY_FOR_SEAM_RECON` / `AUTHORITY_MOVEMENT=0`.