# DAGR-RUNBOOK-WORKLOAD0 — result

## Terminal

`NEEDS_UPSTREAM_SEAM`

`AUTHORITY_MOVEMENT=0`

## External workload finding

`espirado/runbook_generator` has a useful architecture for this governance story:

- collectors normalize infrastructure observations into `EnvironmentSnapshot`;
- deterministic rendering produces `runbook.md`, `snapshot.json`, incident/agent context, and dry-run Jira/Confluence/Slack/wiki payloads;
- external publication is deliberately not the default side effect;
- Slack sending exists only behind explicit `RUNBOOK_SLACK_SEND=true` / `--send-slack`;
- Jira/Confluence/wiki publisher implementations are still listed as future work;
- MCP collectors are also listed as future work.

The repository therefore already preserves the key semantic distinction `proposal artifact exists != external publish executed`, but it does **not** currently expose the MCP/tool boundary needed for a DAGR-MCP interoperability proof.

## Why DAGR does not add the wrapper here

Creating an MCP server inside `dagr-mcp` that knows how to invoke the runbook CLI, map its proposal files, and publish Slack/Jira/Confluence would make DAGR own application-specific orchestration and side-effect semantics. That is the inversion this recon was meant to avoid.

The correct upstream seam would be a small workload-owned tool/MCP surface, for example:

- `generate_snapshot` / `generate_ops_package` as observation/proposal operations;
- one explicit `publish_*` / `send_*` operation for the external side effect;
- proposal digest/reference carried into that side-effect request;
- dry-run/fake publisher available for hermetic tests.

Once such a workload-owned seam exists, DAGR can govern it without importing the runbook schema.

## Non-claims

- no AWS/Kubernetes/runbook semantics are copied into DAGR;
- no dry-run artifact is relabeled a receipt;
- no real Slack/Jira/Confluence call is made;
- no model statement can establish that an external publish occurred.

## Result

The workload is conceptually good, but current implementation lacks the owner-side MCP/action seam. Stop here rather than build application infrastructure in DAGR.