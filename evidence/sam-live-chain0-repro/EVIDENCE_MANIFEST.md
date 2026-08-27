# SAM-LIVE-CHAIN0 clean-checkout reproduction — evidence manifest

Generation: identity-separated clean-checkout reproduction (2026-08-27).
**Tested executable state (exact): `6d783574d018794d28393754bed61d264b697132`** (branch feat/sam-live-chain0-repro).
The gen-3 chain was executed against that tree; this evidence bundle is frozen
on top of it by an evidence-only commit that changes no executable/authz/parser
code. Supersedes the dd98b4e intermediate (shared-group binding), preserved in
git history. All digests sha256. Runtime processes torn down (see teardown.log).

## Pin + release (official prebuilt, verify_pins 5/5 PASS)
```
6c97d964e118bded0d25133e1f8a20d723648ea7415108788ce058006b061a81  sam_Darwin_arm64.tar.gz
b1e8457409012bde0f9f0fde02517d3aff4e48b0a0c02ea129b843f2c509ad49  bin/sam-control-plane
0299d54df4c69c1189d7f37b19c8a915a6224c7b9fe4767ad96bf28961ccb6ce  bin/sam-router
4f5775af9fd679a1fc4e9de5f3338c2ddd05c095407223cac8df67bcc006dfd8  bin/sam-node
01330bad86b999e371a7abf5ef08ddac2a3d63db00d9216437b8708cf4fa8e23  bin/mcp-client
```

## Retained artifacts (sha256)
```
090636b1309a0b2c8dac0e2f61072ce1694b86f6709901bb242b802ea1b6ee59  ATTEMPT1_DIAGNOSTIC.md
81c6b5072533e5f08860b9f376dbae7aeac94fec8a085b4261d58e4dd3b735d3  REPRODUCTION_REPORT.md
c72f4c9fd284fe85a9dc24c9ff8fc452b4f1835624a68f3a88f1f7c4bd4e0f2f  market-audit-packet/issuer-keys.json
ab971aff492237fb1ad2a756c6d4eeec75854523bcfef11dc67154822cbd11c6  market-audit-packet/urn_srs_receipt_admission_eee897c6-5fcf-4b73-b293-6558a97a0003.json
8e412136e6d51ac23c13d3806610fde59f8245b16e43516a071240828237fde8  market-audit-packet/urn_srs_receipt_outcome_433d7b69-535d-4dd8-b79c-9b5847bc6e11.json
6ac0bce589ba8148f52f154dd4b914c3d86944b8880621ac04eab3d3231b4787  run-logs/arcs_verify_exit_code.txt
6586a5929231919353460c63b75cbd8ca51c27a6494f831170a75171b1112253  run-logs/arcs_verify_output.txt
e18b4eecb69d00a1f656baf8a80700969f103570bcf9baa8c4c544c287b6883b  run-logs/get_mesh_info-18101.log
e18b4eecb69d00a1f656baf8a80700969f103570bcf9baa8c4c544c287b6883b  run-logs/get_mesh_info-18102.log
e18b4eecb69d00a1f656baf8a80700969f103570bcf9baa8c4c544c287b6883b  run-logs/get_mesh_info-18103.log
e4da8f5d71a9b4f16a41905efa5859a13fa02d934cc111f2f6767925904177a1  run-logs/governed-call.stdout.log
8ad206519375d36690a6524f55b0baba6555a2878a5ba11008f26f8442845227  run-logs/hostile-node-as-router.log
26fbeab7ccff6016c0eb186fed2d6c5c8bb7ebf0eba5f3ea48ddc8a7ecbe5314  run-logs/pytest_static_gate.log
d65da150c69140bd15b29b8a2e8c35d23e535c97729b811972db1bf5a8a38358  run-logs/semantic-probe.log
8e30b8b894ad77105dc5127eb65149b82f88ca0e3400c16f1c840f1a2f2c5303  run-logs/teardown.log
fc86cd361794bef8ec96153cbe8191b3b7e2177f3e92657a45e327da1bbef3a8  run-logs/up.stdout.log
4b78e0433696b250f80f79bd1208a08b1343df610fc762802ad552f2673ce80e  run-logs/verify_pins.log
```

## Gate results (this generation) — every gate has a retained artifact
| gate | result | evidence |
|---|---|---|
| static pytest gate | 15 passed | run-logs/pytest_static_gate.log |
| release verify_pins | 5/5 PASS | run-logs/verify_pins.log |
| policy seed + identity separation | group:routers→router; group:sam-live-chain0→node | run-logs/up.stdout.log |
| hostile node→router refusal | fail-closed PASS | run-logs/hostile-node-as-router.log |
| 3-node mesh + get_mesh_info×3 | PASS | run-logs/get_mesh_info-181{01,02,03}.log |
| semantic parity (Hello, SAM!) | PASS | run-logs/semantic-probe.log + up.stdout.log |
| governed settle | admitted/result | run-logs/governed-call.stdout.log |
| same-call receipts | req:live-market0:1 admission+outcome | market-audit-packet/ |
| independent ARCS | aggregate exit 0 | run-logs/arcs_verify_output.txt + arcs_verify_exit_code.txt |
| teardown / ports free | PASS (0 procs, 9 ports free) | run-logs/teardown.log |

## Constitutional boundary
- route-success != authorization != semantic truth; fixture `settle` != real financial event.
- ARCS recomputes the receipt, not the external event. loopback-only, no cloud, no spend.
- AUTHORITY_MOVEMENT=0; DRAFT; no ready-flip, no merge.
