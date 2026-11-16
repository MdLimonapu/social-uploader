#!/usr/bin/env bash
# Always-on start for a Linux VM: cloudflared quick tunnel -> write PUBLIC_BASE_URL/BASE_URL to .env -> run app.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
getenv(){ grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//;s/[[:space:]]*$//'; }
PORT="$(getenv PORT)"; PORT="${PORT:-8000}"
HOST="$(getenv HOST)"; HOST="${HOST:-127.0.0.1}"
[ -n "$(getenv APP_PASSWORD)" ] || echo "WARNING: APP_PASSWORD is empty – anyone with the tunnel URL can use the app!" >&2

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

command -v cloudflared >/dev/null || { echo "cloudflared not installed (see README)"; exit 1; }
mkdir -p logs
TLOG=logs/cloudflared.log; : > "$TLOG"
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}" >"$TLOG" 2>&1 &
TPID=$!
URL=""
for _ in $(seq 1 60); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TLOG" | head -1 || true)"
  [ -n "$URL" ] && break
  kill -0 "$TPID" 2>/dev/null || { echo "cloudflared exited:"; cat "$TLOG"; exit 1; }
  sleep 1
done
[ -n "$URL" ] || { echo "No tunnel URL after 60s"; cat "$TLOG"; exit 1; }
echo "Public URL: $URL"

# portable in-place edit (works with both GNU sed on Linux and BSD sed on macOS)
setenv(){ if grep -qE "^$1=" .env; then sed -i.bak "s#^$1=.*#$1=$2#" .env && rm -f .env.bak; else echo "$1=$2" >> .env; fi; }
setenv PUBLIC_BASE_URL "$URL"
setenv BASE_URL "$URL"
export HOST PORT
# cloudflared keeps running as a sibling in the same systemd cgroup; it is stopped with the service.
exec .venv/bin/python -m app
