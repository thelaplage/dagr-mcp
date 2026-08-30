# DAGR-RUNBOOK-WORKLOAD0

**Status:** DRAFT recon lane / DO NOT MERGE  
**Authority:** `AUTHORITY_MOVEMENT=0`

## Mission

Evaluate `espirado/runbook_generator` as an external workload for demonstrating the governed crossing from deterministic observation/proposal artifacts to a real external side effect.

The useful boundary is:

`EnvironmentSnapshot / runbook / jira_issue.json / slack_message.json = observation or proposal`

versus

`actual create/send/publish = governed action`.

Do not import its platform-neutral model into DAGR and do not make DAGR own AWS, Kubernetes, runbook, Jira, Confluence, Slack, or wiki semantics.

## Recon

Determine whether an MCP/tool seam already exists. If not, assess whether a tiny isolated example could expose read/proposal operations separately from one side-effecting publish/send operation without invasive upstream changes.

Questions:
- can read/generate remain ordinary while publish/send receives stronger admission policy?;
- can a refusal leave the proposal artifact intact for human review?;
- can SRS artifacts remain metadata/hash/reference-only?;
- can replay demonstrate `proposal created != external publish executed`?;
- can the proof run entirely offline using fixture data and a fake publisher?

## Hostile invariants, if buildable

- proposal exists + publish refused => proposal retained, no publish;
- model says `sent` + boundary refused => `sent=false`;
- read/generate permission != publish permission;
- tampered proposal digest != admitted action snapshot;
- replay cannot fabricate a second external-execution observation;
- receipts contain digest/ref only, never webhook/token/content body.

No real AWS, Slack, Jira, Confluence, wiki, or destructive call in CI.

## Terminal

`GOOD_EXTERNAL_WORKLOAD | NEEDS_UPSTREAM_SEAM | NOT_USEFUL | NOT_EVALUATED`.

## Deliverables

`docs/recon/DAGR-RUNBOOK-WORKLOAD0.md` plus an isolated interop example only if the recon proves it belongs here.