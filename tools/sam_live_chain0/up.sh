#!/usr/bin/env bash
# Reconstructed clean-replay bring-up for SAM-LIVE-CHAIN0.
# This is NOT the lost historical up.sh. It is a reviewable reconstruction
# derived from the frozen run evidence plus google/sam alpha.7's exact CLI.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
RUNTIME="${SAM_LIVE_RUNTIME:-$ROOT/.sam-live-chain0}"
RELEASE="${SAM_RELEASE_ROOT:?set SAM_RELEASE_ROOT to a directory containing sam_Darwin_arm64.tar.gz and bin/}"
PYTHON="${PYTHON:-python3}"
BIN="$RELEASE/bin"
API_TOKEN="${SAM_LIVE_API_TOKEN:-secret-token}"
CP_URL="http://127.0.0.1:18081"
OIDC_URL="http://127.0.0.1:18080"

mkdir -p "$RUNTIME"/{logs,pids,state,tokens,evidence}

cleanup_on_error() {
  code=$?
  if [[ $code -ne 0 ]]; then
    echo "SAM-LIVE-CHAIN0 bring-up failed; tearing down" >&2
    SAM_LIVE_RUNTIME="$RUNTIME" "$HERE/down.sh" || true
  fi
  exit "$code"
}
trap cleanup_on_error EXIT

"$PYTHON" "$HERE/verify_pins.py" "$RELEASE"
for b in sam-control-plane sam-router sam-node mcp-client; do [[ -x "$BIN/$b" ]] || { echo "not executable: $BIN/$b" >&2; exit 2; }; done
command -v curl >/dev/null || { echo "curl required" >&2; exit 2; }

wait_tcp() {
  local port="$1" name="$2"
  "$PYTHON" - "$port" "$name" <<'PY'
import socket, sys, time
port=int(sys.argv[1]); name=sys.argv[2]; deadline=time.monotonic()+20
while time.monotonic() < deadline:
    s=socket.socket(); s.settimeout(.2)
    try:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            print(f"ready: {name} :{port}"); raise SystemExit(0)
    finally: s.close()
    time.sleep(.1)
raise SystemExit(f"timeout waiting for {name} :{port}")
PY
}

start_bg() {
  local name="$1"; shift
  "$@" >"$RUNTIME/logs/$name.log" 2>&1 &
  echo $! >"$RUNTIME/pids/$name.pid"
}

mint_token() {
  local client="$1" target="$2"
  curl -fsS -X POST -d "client_id=$client" "$OIDC_URL/token" \
    | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["id_token"])' >"$target"
  chmod 600 "$target"
}

SAM_LIVE_RUNTIME="$RUNTIME" "$HERE/down.sh" >/dev/null 2>&1 || true
mkdir -p "$RUNTIME"/{logs,pids,state,tokens,evidence}

OIDC_ISSUER="$OIDC_URL" start_bg mock-oidc "$PYTHON" "$HERE/mock_oidc.py"
wait_tcp 18080 mock-oidc

SAM_ADMIN_TOKEN="sam-live-chain0-admin" start_bg control-plane \
  "$BIN/sam-control-plane" \
  --bind-address 127.0.0.1:18081 \
  --db-driver sqlite \
  --db-dsn "$RUNTIME/state/control-plane.db" \
  --issuer "$OIDC_URL" \
  --allowed-audiences sam-mesh-audience \
  --insecure-skip-tls-verify \
  --auto-approve-enrollment \
  --key-rotation-interval 0
wait_tcp 18081 control-plane

# Seed mesh authorization policy BEFORE any enrollment. alpha.7's control-plane
# denies enrollment for a requested role unless a group->role binding authorizes
# the identity (clean-replay attempt 1 @3be3749 failed here: router got
# "403 requested role sam:role:router is not authorized for this identity").
# Identity separation: router-client carries group "routers" -> sam:role:router;
# ordinary nodes carry group "sam-live-chain0" -> sam:role:node. Distinct groups
# mean a node identity is never authorized for the router role (see the hostile
# node->router refusal check below). Node role is scoped to exactly the services
# this replay uses; router keeps alpha.7's "*".
curl -fsS -X POST "$CP_URL/policies" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer sam-live-chain0-admin" \
  -d '{"roles":[{"name":"sam:role:router","allowed_services":["*"],"allowed_targets":["*"]},{"name":"sam:role:node","allowed_services":["system://sam.catalog","mcp://greeter","mcp://market"],"allowed_targets":["*"]}],"bindings":[{"role":"sam:role:router","members":["group:routers"]},{"role":"sam:role:node","members":["group:sam-live-chain0"]}]}' >/dev/null
echo "policy seeded: group:routers -> sam:role:router; group:sam-live-chain0 -> sam:role:node"

# Hostile check: a node identity (group sam-live-chain0) must NOT be able to
# enroll as a router. Mint a node-role token, attempt router enrollment with it
# on a throwaway port, and require a fail-closed refusal. This proves the
# group->role separation actually denies cross-role assumption, rather than
# merely asserting it in config.
mint_token node-hostile "$RUNTIME/tokens/node-hostile.jwt"
set +e
"$BIN/sam-router" \
  --control-plane "$CP_URL" \
  --listen /ip4/127.0.0.1/tcp/18089 \
  --external-addr /ip4/127.0.0.1/tcp/18089 \
  --oidc-token "$(cat "$RUNTIME/tokens/node-hostile.jwt")" \
  --keys-path "$RUNTIME/state/hostile-router.key" \
  --allow-loopback --low-watermark 1 --high-watermark 32 \
  >"$RUNTIME/logs/hostile-node-as-router.log" 2>&1
hostile_rc=$?
set -e
if [[ $hostile_rc -eq 0 ]] || ! grep -qi 'not authorized\|forbidden\|403' "$RUNTIME/logs/hostile-node-as-router.log"; then
  echo "HOSTILE REFUSAL FAILED: a node identity was able to enroll as router (rc=$hostile_rc)" >&2
  exit 4
fi
echo "hostile node->router enrollment refused (fail-closed): PASS"

mint_token router-client "$RUNTIME/tokens/router.jwt"
ROUTER_TOKEN="$(cat "$RUNTIME/tokens/router.jwt")"
start_bg router \
  "$BIN/sam-router" \
  --control-plane "$CP_URL" \
  --listen /ip4/127.0.0.1/tcp/18082 \
  --external-addr /ip4/127.0.0.1/tcp/18082 \
  --oidc-token "$ROUTER_TOKEN" \
  --keys-path "$RUNTIME/state/router.key" \
  --allow-loopback \
  --low-watermark 1 --high-watermark 32
wait_tcp 18082 router

start_bg greeter "$PYTHON" "$HERE/greeter_server.py"
start_bg market "$PYTHON" "$HERE/market_server.py"
wait_tcp 7778 greeter
wait_tcp 7779 market

start_node() {
  local name="$1" api_port="$2" p2p_port="$3" config="$4"
  local token="$RUNTIME/tokens/$name.jwt"
  mint_token "$name" "$token"
  mkdir -p "$RUNTIME/state/$name"
  SAM_API_TOKEN="$API_TOKEN" start_bg "$name" \
    "$BIN/sam-node" run \
    --control-plane "$CP_URL" \
    --jwt-path "$token" \
    --join \
    --data-dir "$RUNTIME/state/$name" \
    --bind-addr "127.0.0.1:$api_port" \
    --socket-path "" \
    --listen "/ip4/127.0.0.1/tcp/$p2p_port" \
    --allow-loopback \
    --announce-private \
    --router-connect-timeout 10s \
    --discovery-interval 1s \
    --monitor-bootstrap 1s \
    --config "$config"
  wait_tcp "$api_port" "$name MCP"
}

start_node node-orchestrator 18101 18111 "$HERE/empty-node-config.yaml"
start_node node-provider     18102 18112 "$HERE/provider-node-config.yaml"
start_node node-witness      18103 18113 "$HERE/empty-node-config.yaml"

for p in 18101 18102 18103; do
  "$BIN/mcp-client" -url "http://127.0.0.1:$p/mcp" -tool get_mesh_info -args '{}' -token "$API_TOKEN" -timeout 15 \
    >"$RUNTIME/logs/get_mesh_info-$p.log" 2>&1
done

for _ in {1..30}; do
  if "$PYTHON" "$HERE/probe_semantic.py" --sam-endpoint http://127.0.0.1:18101/mcp --api-token "$API_TOKEN" \
      >"$RUNTIME/logs/semantic-probe.log" 2>&1; then
    cat "$RUNTIME/logs/semantic-probe.log"
    printf '%s\n' "SAM-LIVE-CHAIN0 mesh bring-up: PASS"
    printf '%s\n' "next: $PYTHON $HERE/live_market0.py --output $RUNTIME/evidence/market-audit-packet"
    trap - EXIT
    exit 0
  fi
  sleep 1
done
cat "$RUNTIME/logs/semantic-probe.log" >&2 || true
exit 3
