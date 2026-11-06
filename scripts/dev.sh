#!/usr/bin/env bash
# Run the API (8020), worker, and web (3020) natively in one terminal. Ctrl-C stops all three.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
api_port="${RELAYOPS_API_PORT:-8020}"
web_port="${RELAYOPS_WEB_PORT:-3020}"
for port in "$api_port" "$web_port"; do
  if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use. Set RELAYOPS_API_PORT/RELAYOPS_WEB_PORT (and RELAYOPS_*_ORIGIN) to free ports." >&2
    exit 1
  fi
done
mkdir -p "$root/data/runtime"
pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
(cd "$root/backend" && exec uv run uvicorn relayops.api.main:app --host 127.0.0.1 --port "$api_port") &
pids+=($!)
(cd "$root/backend" && exec uv run python -m relayops.workers.worker) &
pids+=($!)
(cd "$root/frontend" && RELAYOPS_API_INTERNAL_URL="http://127.0.0.1:$api_port" NEXT_TELEMETRY_DISABLED=1 exec npx next dev -p "$web_port" -H 127.0.0.1) &
pids+=($!)
echo "RelayOps: web http://localhost:$web_port  api http://localhost:$api_port/api/docs"
wait
