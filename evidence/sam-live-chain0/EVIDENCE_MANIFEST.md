# SAM-LIVE-CHAIN0 — frozen evidence manifest

Frozen 2026-08-26 from the live run. Read-only proof substrate; the mesh
processes are torn down separately. All digests sha256.

## SAM pin
- google/sam tag `v0.1.0-alpha.7`, commit `a5f2c4e` (canonical, owner Gate-0a).
- Release asset `sam_Darwin_arm64.tar.gz` (official prebuilt, no source build).

## Binary / archive pins (sha256)
```
6c97d964e118bded0d25133e1f8a20d723648ea7415108788ce058006b061a81  sam_Darwin_arm64.tar.gz
b1e8457409012bde0f9f0fde02517d3aff4e48b0a0c02ea129b843f2c509ad49  bin/sam-control-plane
0299d54df4c69c1189d7f37b19c8a915a6224c7b9fe4767ad96bf28961ccb6ce  bin/sam-router
4f5775af9fd679a1fc4e9de5f3338c2ddd05c095407223cac8df67bcc006dfd8  bin/sam-node
01330bad86b999e371a7abf5ef08ddac2a3d63db00d9216437b8708cf4fa8e23  bin/mcp-client
011388f39ef28a8e6922f6c5b8d78af5636045f6b72e46295ecfa20c9a2fa595  bin/sam-box
7fd99e6e1ccef5b2f06849dff90325ef5a8f9231496ca3d2bc9b887c53bc9bb7  bin/nano-init
```

## Frozen artifacts (sha256)
```
af7b3c73b5b26b8cece3bb6aeda9a4630f912b8fbbb265c11cd175434140633b  CHAIN_REPORT.md
6ac0bce589ba8148f52f154dd4b914c3d86944b8880621ac04eab3d3231b4787  arcs_verify_exit_code.txt
3fb225187787d45e2d06debccb48cce8a86c844fc21e6d3639dd2beee6b3310f  arcs_verify_output.txt
8c54763ad3a0057e5601b06e1d465c0102d8c41e281f181ee7011444f345a192  config/provider-node-config.yaml
d2f61a524ed63465364380f0f905e9c46fee6bd84d80741e31f405509855fe99  harness/down.sh
54cd04a2edb50575c84fb89b8eb0f9a6ffd4b3b99f96ead2ccbe8078b978d5fd  harness/lib.sh
dbac3ba921c14115b9fb4ac4eb36e5556ca909a66488cde3ebf69971598be9b3  harness/live_market0.py
0715a271a5be8ef60a278faa57cb3de8f13a1d196e42a24e13a8f783817442ea  harness/market_server.py
65ca069f09c078ecca832abbf072cf6a621058d351b2e8572758c8fd9a98dedf  harness/reseed_and_restart_nodes.sh
b8d33106e312330eedb5b6289118d332808d9d0fd4dbb57121ff581c863a4e2a  harness/restart_provider.sh
0048ade760bcb984c324d169dbe74a6a8abe93307b6b489e6df708d4c01e0030  logs/control-plane.log
7d25181cc6a5352d959667d4d084f35dcf2e871fc1fe9651ebbafeaa6280cb5b  logs/greeter.log
04698e761bcc500e5c8f5cbf9ba8a800407656ee278d57079a1494fef91224df  logs/market.log
8f577767fcedef46f50a676cebc543dbd020dde5d7e62e98648bf702c78507da  logs/mock-oidc.log
c1c23bb375340fa604820a488fa80204bbd453dd31e1a4ebc61acfd5c467d4fd  logs/node-orchestrator.log
c082a73587a242352fdff25cf2ce55846a87a5af26dd4d2564c9b4fb176dfe0e  logs/node-provider.log
2e073b646b26fd5536d30b241b3fcc2f0ca6ed8197b38ba26514de60b80c94e3  logs/node-witness.log
1f65c07efd85adf55d07319ea2642fb602cf63882e9c88be5fcf0c85c30f9898  logs/router.log
3705220c9f023269e16cafeea0e75fee80d7de0b14ac0fe908949dd4eb9bd2b3  market-audit-packet/issuer-keys.json
89f9b578d1bab8290c5c29cc6da6ac713e046538a4d8743c1ff8fc4416e0525f  market-audit-packet/urn_srs_receipt_admission_c92a89d5-0fda-426f-a5a8-3f1e5254eaa4.json
336ab6699d69527a916523fc82726f3066d1ccedada48439525d4a7c424923ea  market-audit-packet/urn_srs_receipt_outcome_5f2f24b8-c49c-466f-ad4f-e3d35308a2d6.json
6a8fda002dc132dce4e7b0f00769ac8938492fbb1c358cbcbb065aa7c1bde7be  vendor/greeter_server.py
5cbe6ca660341079f810080760d4a282c32566e934577bb1881b7d2e673d5447  vendor/mock_oidc.py
```

## ARCS verifier verdict
- aggregate exit code: **0** (all receipts passed).
- per-check (both receipts): schema_digest, envelope, profile, raw_content_exclusion,
  signature_valid, issuer_key_resolved, issuer_key_trusted, attestation_limits_present = PASS;
  chain_status = not_applicable. Full report: `arcs_verify_output.txt`.
- verifier run from arcs-verify OWN venv — imports no producer code.

## Governed call binding
- admission + outcome share `logical_call_id: req:live-market0:1`.
- admission disposition=admitted; outcome=result_returned.
- profile `srs.mcp.sdk_enforcement v0.1`, Ed25519 / RFC8785-JCS, metadata-only.

## Constitutional boundary (recorded)
- Fixture settlement proves the routing/governance chain, NOT a real financial event.
- ARCS verifies the receipt bytes, NOT external-world truth (emitter assertion ≠ recomputed finding).
- Posture: loopback-local, no cloud, no spend, AUTHORITY_MOVEMENT=0, nothing merged/pushed/ratified.
