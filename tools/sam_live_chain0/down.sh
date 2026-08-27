#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
RUNTIME="${SAM_LIVE_RUNTIME:-$ROOT/.sam-live-chain0}"

if [[ -d "$RUNTIME/pids" ]]; then
  for pf in "$RUNTIME"/pids/*.pid; do
    [[ -e "$pf" ]] || continue
    pid="$(cat "$pf" 2>/dev/null || true)"
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    if kill -0 "$pid" 2>/dev/null; then kill -TERM "$pid" 2>/dev/null || true; fi
  done
  for _ in {1..50}; do
    alive=0
    for pf in "$RUNTIME"/pids/*.pid; do
      [[ -e "$pf" ]] || continue
      pid="$(cat "$pf" 2>/dev/null || true)"
      if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then alive=1; fi
    done
    [[ "$alive" -eq 0 ]] && break
    sleep 0.1
  done
  for pf in "$RUNTIME"/pids/*.pid; do
    [[ -e "$pf" ]] || continue
    pid="$(cat "$pf" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid" 2>/dev/null || true; fi
  done
fi
rm -rf "$RUNTIME/pids"

python3 - <<'PY'
import socket
ports = [7778, 7779, 18080, 18081, 18082, 18101, 18102, 18103, 18111, 18112, 18113]
open_ports=[]
for p in ports:
    s=socket.socket(); s.settimeout(.08)
    try:
        if s.connect_ex(("127.0.0.1", p)) == 0: open_ports.append(p)
    finally: s.close()
if open_ports:
    raise SystemExit(f"SAM-LIVE-CHAIN0 teardown incomplete; ports still open: {open_ports}")
print("SAM-LIVE-CHAIN0 teardown: PASS — tracked processes stopped; known TCP ports free")
PY
