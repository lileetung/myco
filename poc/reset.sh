#!/usr/bin/env bash
# Tear the PoC down and restore a clean slate.
#
#   - stops the host auto-healer (if running) and the docker stack
#   - reverts workspace/scraper.py to the seed (v1-only selectors + non-null validation)
#   - clears workspace/failure.json, workspace/agent.log
#
# Run `make up` again to start fresh.

set -e
cd "$(dirname "$0")"

echo "==> stopping auto-healer (if running)"
PID=$(cat .agent.lock 2>/dev/null || true)
if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
fi
rm -f .agent.lock

echo "==> stopping stack"
docker compose down >/dev/null

echo "==> restoring workspace/scraper.py from seed/"
cp seed/scraper.py workspace/scraper.py

echo "==> clearing failure.json, agent.log"
rm -f workspace/failure.json workspace/agent.log

cat <<EOF

reset complete.

  scraper.py             -> seed (only v1 selectors)
  failure.json, agent.log -> cleared
  stack                  -> stopped
  auto-healer            -> stopped

Run \`make up\` to start fresh.
EOF
